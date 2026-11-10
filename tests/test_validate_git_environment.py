from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / "scripts" / "isolated_unittest.py"


@unittest.skipUnless(shutil.which("git"), "git is required")
class ValidationGitEnvironmentTest(unittest.TestCase):
    def test_fixture_git_commands_cannot_modify_inherited_repository(self) -> None:
        with tempfile.TemporaryDirectory(prefix="validate-git-isolation-") as raw:
            root = Path(raw)
            victim = root / "victim"
            victim.mkdir()
            env = {
                key: value
                for key, value in os.environ.items()
                if not key.startswith("GIT_")
            }
            env.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)

            def git(*args: str) -> str:
                return subprocess.run(
                    ["git", *args],
                    cwd=victim,
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                ).stdout.strip()

            git("init", "-q")
            git("config", "user.name", "Victim")
            git("config", "user.email", "victim@example.invalid")
            (victim / "keep.txt").write_text("original\n", encoding="utf-8")
            git("add", "keep.txt")
            git("commit", "-qm", "original")
            head = git("rev-parse", "HEAD")
            config = (victim / ".git" / "config").read_bytes()
            index = (victim / ".git" / "index").read_bytes()

            fixtures = root / "fixtures"
            fixtures.mkdir()
            (fixtures / "test_fixture.py").write_text(
                textwrap.dedent(
                    """\
                    from pathlib import Path
                    import subprocess
                    import tempfile
                    import unittest

                    class Fixture(unittest.TestCase):
                        def test_git_fixture(self):
                            with tempfile.TemporaryDirectory() as raw:
                                repo = Path(raw)
                                def git(*args):
                                    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
                                git("init", "-q")
                                git("config", "user.name", "Fixture")
                                git("config", "user.email", "fixture@example.invalid")
                                (repo / "fixture.txt").write_text("fixture")
                                git("add", "fixture.txt")
                                git("commit", "-qm", "fixture")
                    """
                ),
                encoding="utf-8",
            )
            hostile = dict(env)
            hostile.update(
                GIT_DIR=str(victim / ".git"),
                GIT_WORK_TREE=str(victim),
                GIT_INDEX_FILE=str(victim / ".git" / "index"),
                GIT_CONFIG_COUNT="1",
                GIT_CONFIG_KEY_0="core.bare",
                GIT_CONFIG_VALUE_0="true",
            )
            result = subprocess.run(
                [
                    sys.executable,
                    str(RUNNER),
                    "discover",
                    "-s",
                    str(fixtures),
                    "-p",
                    "test_fixture.py",
                ],
                cwd=ROOT,
                env=hostile,
                capture_output=True,
                text=True,
                timeout=30,
                check=False,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(git("rev-parse", "HEAD"), head)
            self.assertEqual((victim / ".git" / "config").read_bytes(), config)
            self.assertEqual((victim / ".git" / "index").read_bytes(), index)
            self.assertEqual(git("status", "--porcelain"), "")


if __name__ == "__main__":
    unittest.main()
