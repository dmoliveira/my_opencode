from __future__ import annotations

import hashlib
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from setup_safety import instruction_links, require_v1_runtime


def snapshot(root: Path) -> dict[str, tuple[object, ...]]:
    result = {}
    for path in [root, *sorted(root.rglob("*"))]:
        info = path.lstat()
        key = str(path.relative_to(root))
        metadata = (stat.S_IMODE(info.st_mode), info.st_mtime_ns)
        if path.is_symlink():
            result[key] = ("link", *metadata, os.readlink(path))
        elif path.is_file():
            result[key] = (
                "file",
                *metadata,
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        elif path.is_dir():
            result[key] = ("dir", *metadata)
        else:
            result[key] = ("other", *metadata)
    return result


class SetupFixture:
    def __init__(self, root: Path, *, existing_config: bool = True) -> None:
        self.root = root
        self.home = root / "home"
        self.repo = root / "repo"
        self.oldrepo = root / "oldrepo"
        self.config = self.home / ".config" / "opencode"
        self.source = root / "instructions.md"
        self.bin = root / "bin"
        for directory in (self.home, self.repo, self.oldrepo, self.bin):
            directory.mkdir()
        (self.repo / "opencode.json").write_text("{}\n", encoding="utf-8")
        (self.oldrepo / "opencode.json").write_text('{"old":true}\n', encoding="utf-8")
        (self.repo / "AGENTS.md").write_text("user instructions\n", encoding="utf-8")
        self.source.write_text("source instructions\n", encoding="utf-8")
        (self.oldrepo / "runtime").mkdir()
        state = self.oldrepo / "runtime" / "plan_execution.json"
        state.write_text('{"synthetic":"preserve"}\n', encoding="utf-8")
        state.chmod(0o600)
        if existing_config:
            self.config.mkdir(parents=True)
            (self.config / "my_opencode").symlink_to(self.oldrepo)
            (self.config / "opencode.json").symlink_to(self.oldrepo / "opencode.json")
            (self.config / "user.json").write_text(
                '{"custom":true}\n', encoding="utf-8"
            )
            (self.home / ".zshrc").write_text(
                "# user shell settings\n", encoding="utf-8"
            )
        (self.bin / "python3").symlink_to(sys.executable)
        for command in ("dirname", "basename", "git", "mkdir"):
            binary = shutil.which(command)
            if binary:
                (self.bin / command).symlink_to(binary)

    def runtime(self, script: str) -> None:
        binary = self.bin / "opencode"
        binary.write_text("#!/bin/sh\n" + script + "\n", encoding="utf-8")
        binary.chmod(0o700)

    def run(self, name: str, *, timeout: int = 12) -> subprocess.CompletedProcess[str]:
        env = os.environ.copy()
        env.update(
            HOME=str(self.home),
            PATH=str(self.bin),
            MY_OPENCODE_REPO=str(self.repo),
            OPENCODE_CONFIG_DIR=str(self.config),
            AGENTS_SOURCE_PATH=str(self.source),
            OHMY_CONFIG_HOME=str(self.home / ".config" / "opencode-ohmy"),
            ZSHRC_FILE=str(self.home / ".zshrc"),
            OPENCODE_DB=str(self.root / "user-runtime.sqlite"),
            PYTHONDONTWRITEBYTECODE="1",
        )
        return subprocess.run(
            ["/bin/bash", str(ROOT / "scripts" / name)],
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )


@unittest.skipUnless(os.name == "posix", "legacy setup scripts require POSIX")
class SetupV2SafetyTest(unittest.TestCase):
    scripts = ("setup_local_dev_symlinks.sh", "setup_dual_opencode.sh")

    def test_unverified_and_incompatible_runtimes_refuse_without_writes(self) -> None:
        cases = {
            "v2": 'printf "opencode v2.2.5\\n"',
            "future": 'printf "3.0.0\\n"',
            "old_major": 'printf "0.9.0\\n"',
            "unknown": 'printf "unknown-runtime\\n"',
            "empty": "exit 0",
            "failed": 'printf "1.18.18\\n"; exit 1',
            "too_long": "printf '" + ("1" * 513) + "'",
            "invalid_utf8": "printf '\\377'",
            "missing": None,
        }
        for name in self.scripts:
            for label, runtime in cases.items():
                with (
                    self.subTest(script=name, runtime=label),
                    tempfile.TemporaryDirectory() as raw,
                ):
                    fixture = SetupFixture(Path(raw))
                    if runtime is not None:
                        fixture.runtime(runtime)
                    before = snapshot(fixture.root)
                    result = fixture.run(name)
                    self.assertNotEqual(result.returncode, 0, result.stdout)
                    self.assertIn("setup cannot proceed", result.stderr)
                    self.assertEqual(snapshot(fixture.root), before)

    def test_unverified_runtime_does_not_create_config_directories(self) -> None:
        for name in self.scripts:
            with self.subTest(script=name), tempfile.TemporaryDirectory() as raw:
                fixture = SetupFixture(Path(raw), existing_config=False)
                fixture.runtime('printf "2.2.5\\n"')
                before = snapshot(fixture.root)
                result = fixture.run(name)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(fixture.config.exists())
                self.assertEqual(snapshot(fixture.root), before)

    def test_probe_side_effects_are_confined_to_disposable_home(self) -> None:
        for name in self.scripts:
            with self.subTest(script=name), tempfile.TemporaryDirectory() as raw:
                fixture = SetupFixture(Path(raw))
                database = fixture.root / "user-runtime.sqlite"
                database.write_text("user runtime record\n", encoding="utf-8")
                fixture.runtime(
                    'printf "probe cache" > "$HOME/probe-cache"\n'
                    'printf "probe cwd" > "$PWD/probe-cwd"\n'
                    'if [ -n "${OPENCODE_DB:-}" ]; then printf changed > "$OPENCODE_DB"; fi\n'
                    'printf "2.2.5\\n"'
                )
                before = snapshot(fixture.root)
                result = fixture.run(name)
                self.assertNotEqual(result.returncode, 0, result.stdout)
                self.assertIn("requires OpenCode V1", result.stderr)
                self.assertEqual(snapshot(fixture.root), before)

    def test_hung_probe_and_inherited_stdout_are_bounded_without_writes(self) -> None:
        for name in self.scripts:
            for runtime in ("exec /bin/sleep 30", "/bin/sleep 30 & wait"):
                with (
                    self.subTest(script=name, runtime=runtime),
                    tempfile.TemporaryDirectory() as raw,
                ):
                    fixture = SetupFixture(Path(raw))
                    fixture.runtime(runtime)
                    before = snapshot(fixture.root)
                    result = fixture.run(name, timeout=9)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("version probe timed out", result.stderr)
                    self.assertEqual(snapshot(fixture.root), before)

    def test_probe_timeout_also_covers_processes_that_close_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = SetupFixture(Path(raw))
            fixture.runtime("exec 1>&-; exec /bin/sleep 30")
            before = snapshot(fixture.root)
            with (
                patch.dict(os.environ, {"PATH": str(fixture.bin)}),
                patch("setup_safety.VERSION_TIMEOUT_SECONDS", 0.25),
                self.assertRaisesRegex(ValueError, "version probe timed out"),
            ):
                require_v1_runtime()
            self.assertEqual(snapshot(fixture.root), before)

    def test_local_v1_setup_is_idempotent_and_preserves_equivalent_links(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = SetupFixture(Path(raw), existing_config=False)
            fixture.runtime('printf "opencode v1.18.18\\n"')
            (fixture.repo / "AGENTS.md").unlink()
            (fixture.repo / "AGENTS.md").symlink_to("../instructions.md")
            (fixture.repo / "agent").mkdir()
            (fixture.repo / "agent" / "reviewer.md").write_text(
                "reviewer\n", encoding="utf-8"
            )
            (fixture.repo / "agent" / ".hidden.md").write_text(
                "hidden\n", encoding="utf-8"
            )
            first = fixture.run(self.scripts[0])
            self.assertEqual(first.returncode, 0, first.stderr)
            self.assertEqual(
                os.readlink(fixture.repo / "AGENTS.md"), "../instructions.md"
            )
            self.assertEqual(
                (fixture.config / "my_opencode").resolve(), fixture.repo.resolve()
            )
            self.assertEqual(
                (fixture.config / "opencode.json").resolve(),
                (fixture.repo / "opencode.json").resolve(),
            )
            self.assertEqual(
                (fixture.config / "agent" / "reviewer.md").resolve(),
                (fixture.repo / "agent" / "reviewer.md").resolve(),
            )
            self.assertFalse(os.path.lexists(fixture.config / "agent" / ".hidden.md"))
            before = snapshot(fixture.root)
            second = fixture.run(self.scripts[0])
            self.assertEqual(second.returncode, 0, second.stderr)
            self.assertEqual(snapshot(fixture.root), before)

    def test_local_v1_setup_creates_missing_instruction_link(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = SetupFixture(Path(raw), existing_config=False)
            fixture.runtime('printf "1.18.18\\n"')
            (fixture.repo / "AGENTS.md").unlink()
            result = fixture.run(self.scripts[0])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue((fixture.repo / "AGENTS.md").is_symlink())
            self.assertEqual(
                (fixture.repo / "AGENTS.md").resolve(), fixture.source.resolve()
            )

    def test_dual_v1_setup_moves_only_disposable_runtime_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            fixture = SetupFixture(Path(raw))
            fixture.runtime('printf "1.18.18\\n"')
            result = fixture.run(self.scripts[1])
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(
                (fixture.oldrepo / "runtime" / "plan_execution.json").exists()
            )
            self.assertEqual(
                (fixture.repo / "runtime" / "plan_execution.json").read_text(
                    encoding="utf-8"
                ),
                '{"synthetic":"preserve"}\n',
            )
            self.assertEqual(
                (fixture.config / "my_opencode").resolve(), fixture.repo.resolve()
            )
            self.assertEqual(
                (fixture.config / "user.json").read_text(encoding="utf-8"),
                '{"custom":true}\n',
            )
            self.assertIn(
                "# user shell settings",
                (fixture.home / ".zshrc").read_text(encoding="utf-8"),
            )

    def test_conflicting_instruction_and_agent_paths_refuse_before_writes(self) -> None:
        for role in ("instructions", "agent"):
            for kind in ("file", "directory", "symlink", "dangling"):
                with (
                    self.subTest(role=role, kind=kind),
                    tempfile.TemporaryDirectory() as raw,
                ):
                    fixture = SetupFixture(Path(raw))
                    fixture.runtime('printf "1.18.18\\n"')
                    instruction = fixture.repo / "AGENTS.md"
                    instruction.unlink()
                    (fixture.repo / "agent").mkdir()
                    (fixture.repo / "agent" / "reviewer.md").write_text(
                        "agent\n", encoding="utf-8"
                    )
                    (fixture.config / "agent").mkdir()
                    if role == "agent":
                        instruction.symlink_to(fixture.source)
                        conflict = fixture.config / "agent" / "reviewer.md"
                    else:
                        conflict = instruction
                    if kind == "file":
                        conflict.write_text("user-authored\n", encoding="utf-8")
                    elif kind == "directory":
                        conflict.mkdir()
                    elif kind == "symlink":
                        conflict.symlink_to(fixture.oldrepo / "opencode.json")
                    else:
                        conflict.symlink_to(fixture.root / "missing")
                    before = snapshot(fixture.root)
                    result = fixture.run(self.scripts[0])
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn("refusing to replace existing path", result.stderr)
                    self.assertEqual(snapshot(fixture.root), before)

    def test_link_creation_race_never_replaces_a_new_file(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            repo = root / "repo"
            repo.mkdir()
            source = root / "instructions.md"
            source.write_text("source\n", encoding="utf-8")
            destination = repo / "AGENTS.md"

            def racing_symlink(_target: str, link: Path) -> None:
                link.write_text("concurrent user data\n", encoding="utf-8")
                raise FileExistsError

            with (
                patch("setup_safety.os.symlink", side_effect=racing_symlink),
                self.assertRaisesRegex(ValueError, "refusing to replace"),
            ):
                instruction_links(repo, root / "config", str(source), create=True)
            self.assertFalse(destination.is_symlink())
            self.assertEqual(
                destination.read_text(encoding="utf-8"), "concurrent user data\n"
            )


if __name__ == "__main__":
    unittest.main()
