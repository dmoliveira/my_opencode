from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallV2SafetyTest(unittest.TestCase):
    def test_version_probe_is_isolated_when_installer_is_streamed_or_on_disk(self) -> None:
        for streamed in (False, True):
            with self.subTest(streamed=streamed), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                home = root / "home"
                config_dir = home / ".config" / "opencode"
                config_dir.mkdir(parents=True)
                config = config_dir / "opencode.json"
                config.write_text('{"user_setting": true}\n', encoding="utf-8")
                database = home / "runtime.sqlite"
                database.write_text("user runtime\n", encoding="utf-8")
                binary_dir = root / "bin"
                binary_dir.mkdir()
                binary = binary_dir / "opencode"
                binary.write_text(
                    '#!/bin/sh\n'
                    '[ "${CI:-}" = "true" ] || exit 47\n'
                    'printf touched > "$HOME/version-probe-marker"\n'
                    'printf touched > "$PWD/version-probe-cwd"\n'
                    'if [ -n "${OPENCODE_DB:-}" ]; then printf changed > "$OPENCODE_DB"; fi\n'
                    'printf "opencode v2.2.5\\n"\n',
                    encoding="utf-8",
                )
                binary.chmod(0o700)
                env = os.environ.copy()
                env.update(
                    HOME=str(home),
                    PATH=f"{binary_dir}{os.pathsep}{env['PATH']}",
                    OPENCODE_DB=str(database),
                    XDG_CONFIG_HOME=str(home / "custom-config"),
                )
                env.pop("INSTALL_DIR", None)
                script = ROOT / "install.sh"
                command = (
                    ["/bin/bash", "-s", "--", "--skip-self-check"]
                    if streamed
                    else ["/bin/bash", str(script), "--skip-self-check"]
                )
                result = subprocess.run(
                    command,
                    input=script.read_text(encoding="utf-8") if streamed else None,
                    cwd=root,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("not yet compatible with OpenCode V2", result.stderr)
                self.assertFalse((home / "version-probe-marker").exists())
                self.assertFalse((root / "version-probe-cwd").exists())
                self.assertFalse((home / "custom-config").exists())
                self.assertEqual(database.read_text(encoding="utf-8"), "user runtime\n")
                self.assertEqual(config.read_text(encoding="utf-8"), '{"user_setting": true}\n')

    def test_hung_installer_version_probe_refuses_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text("#!/bin/sh\n/bin/sleep 30 & wait\n", encoding="utf-8")
            binary.chmod(0o700)
            env = os.environ.copy()
            env.update(HOME=str(home), PATH=f"{binary_dir}{os.pathsep}{env['PATH']}")
            env.pop("INSTALL_DIR", None)
            result = subprocess.run(
                ["/bin/bash", str(ROOT / "install.sh"), "--skip-self-check"],
                env=env, capture_output=True, text=True, check=False, timeout=9,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unable to determine OpenCode compatibility", result.stderr)
            self.assertEqual(list(home.iterdir()), [])

    def test_zero_major_is_not_treated_as_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            home.mkdir()
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text('#!/bin/sh\nprintf "0.9.0\\n"\n', encoding="utf-8")
            binary.chmod(0o700)
            env = os.environ.copy()
            env.update(HOME=str(home), PATH=f"{binary_dir}{os.pathsep}{env['PATH']}")
            env.pop("INSTALL_DIR", None)
            result = subprocess.run(
                ["/bin/bash", str(ROOT / "install.sh"), "--skip-self-check"],
                env=env, capture_output=True, text=True, check=False, timeout=15,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("only OpenCode V1", result.stderr)
            self.assertEqual(list(home.iterdir()), [])

    def test_failed_invalid_and_oversized_version_probes_do_not_write(self) -> None:
        cases = (
            'printf "1.18.18\\n"; exit 1',
            "printf '\\377'",
            "printf '" + ("x" * 513) + "'",
        )
        for script in cases:
            with self.subTest(script=script), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                home = root / "home"
                home.mkdir()
                binary_dir = root / "bin"
                binary_dir.mkdir()
                binary = binary_dir / "opencode"
                binary.write_text("#!/bin/sh\n" + script + "\n", encoding="utf-8")
                binary.chmod(0o700)
                env = os.environ.copy()
                env.update(HOME=str(home), PATH=f"{binary_dir}{os.pathsep}{env['PATH']}")
                env.pop("INSTALL_DIR", None)
                result = subprocess.run(
                    ["/bin/bash", str(ROOT / "install.sh"), "--skip-self-check"],
                    env=env, capture_output=True, text=True, check=False, timeout=15,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("unable to determine OpenCode compatibility", result.stderr)
                self.assertEqual(list(home.iterdir()), [])

    def test_v2_installer_fails_before_modifying_existing_configuration(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            config_dir = home / ".config" / "opencode"
            config_dir.mkdir(parents=True)
            config = config_dir / "opencode.json"
            config.write_text('{"user_setting": true}\n', encoding="utf-8")
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text(
                '#!/bin/sh\nprintf "opencode v2.2.5\\n"\n', encoding="utf-8"
            )
            binary.chmod(0o700)
            env = os.environ.copy()
            env.update(
                {"HOME": str(home), "PATH": f"{binary_dir}{os.pathsep}{env['PATH']}"}
            )
            env.pop("INSTALL_DIR", None)
            result = subprocess.run(
                ["bash", str(ROOT / "install.sh"), "--skip-self-check"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("not yet compatible with OpenCode V2", result.stderr)
            self.assertFalse(config.is_symlink())
            self.assertEqual(
                config.read_text(encoding="utf-8"), '{"user_setting": true}\n'
            )
            self.assertFalse((config_dir / "my_opencode").exists())

    def test_unrecognized_runtime_version_fails_without_creating_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            binary = binary_dir / "opencode"
            binary.write_text('#!/bin/sh\necho "unknown-runtime"\n', encoding="utf-8")
            binary.chmod(0o700)
            home = root / "home"
            env = os.environ.copy()
            env.update(
                {"HOME": str(home), "PATH": f"{binary_dir}{os.pathsep}{env['PATH']}"}
            )
            env.pop("INSTALL_DIR", None)
            result = subprocess.run(
                ["bash", str(ROOT / "install.sh"), "--skip-self-check"],
                env=env,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("unrecognized OpenCode version", result.stderr)
            self.assertFalse((home / ".config" / "opencode").exists())

    def test_missing_runtime_fails_without_creating_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary_dir = root / "bin"
            binary_dir.mkdir()
            (binary_dir / "python3").symlink_to(sys.executable)
            git = binary_dir / "git"
            git.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            git.chmod(0o700)
            home = root / "home"
            env = os.environ.copy()
            env.update({"HOME": str(home), "PATH": str(binary_dir)})
            env.pop("INSTALL_DIR", None)
            result = subprocess.run(
                ["/bin/bash", str(ROOT / "install.sh"), "--skip-self-check"],
                env=env, capture_output=True, text=True, check=False, timeout=30,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("OpenCode is not installed or not on PATH", result.stderr)
            self.assertFalse((home / ".config" / "opencode").exists())


if __name__ == "__main__":
    unittest.main()
