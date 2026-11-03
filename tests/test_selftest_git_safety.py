from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SelftestGitSafetyTest(unittest.TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory(prefix="selftest-git-safety-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.victim = self.root / "synthetic-existing-repo"
        self.victim.mkdir()
        self.env = {
            "HOME": str(self.home),
            "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTHONPATH": str(ROOT / "scripts"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_TERMINAL_PROMPT": "0",
        }
        self.git("init", "-q", "-b", "main")
        self.git("config", "user.name", "Synthetic Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        (self.victim / "fixture.txt").write_text("synthetic original\n", encoding="utf-8")
        self.git("add", "fixture.txt")
        self.git("commit", "-qm", "initial synthetic commit")
        self.git("tag", "selftest-since-tag", "HEAD")
        self.git("commit", "--allow-empty", "-qm", "later synthetic commit")

    def git(self, *args: str) -> str:
        result = subprocess.run(
            ["git", *args],
            cwd=self.victim,
            env=self.env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return result.stdout

    def hostile_env(self) -> dict[str, str]:
        return {
            **self.env,
            "GIT_DIR": str(self.victim / ".git"),
            "GIT_WORK_TREE": str(self.victim),
            "GIT_COMMON_DIR": str(self.victim / ".git"),
            "GIT_INDEX_FILE": str(self.victim / ".git" / "index"),
            "GIT_OBJECT_DIRECTORY": str(self.victim / ".git" / "objects"),
            "GIT_TEMPLATE_DIR": str(self.victim),
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "core.worktree",
            "GIT_CONFIG_VALUE_0": str(self.victim),
        }

    def run_python(self, program: str, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-c", program, *args],
            cwd=self.root,
            env=self.hostile_env(),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )

    def test_since_fixture_preserves_existing_tag_and_repo_with_git_overrides(self) -> None:
        before_refs = self.git("show-ref")
        before_head = self.git("rev-parse", "HEAD")
        before_tag = self.git("rev-parse", "selftest-since-tag")
        before_index = (self.victim / ".git" / "index").read_bytes()
        program = (
            "import os, sys\n"
            "from pathlib import Path\n"
            "import selftest\n"
            "selftest.check_changes_since_fixture(Path(sys.argv[1]), dict(os.environ))\n"
            "print('fixture passed')\n"
        )
        result = self.run_python(program, str(self.root))
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("fixture passed", result.stdout)
        self.assertEqual(before_refs, self.git("show-ref"))
        self.assertEqual(before_head, self.git("rev-parse", "HEAD"))
        self.assertEqual(before_tag, self.git("rev-parse", "selftest-since-tag"))
        self.assertEqual(before_index, (self.victim / ".git" / "index").read_bytes())
        self.assertEqual("", self.git("status", "--porcelain"))
        self.assertEqual("synthetic original\n", (self.victim / "fixture.txt").read_text())

    def test_main_sanitizes_git_before_creating_any_fixture(self) -> None:
        program = (
            "import json, os\n"
            "import selftest\n"
            "class StopBeforeFixture(Exception): pass\n"
            "def stop(*args, **kwargs):\n"
            " print(json.dumps({k: v for k, v in os.environ.items() if k.startswith('GIT_')}))\n"
            " raise StopBeforeFixture()\n"
            "selftest.tempfile.TemporaryDirectory = stop\n"
            "try: selftest.main()\n"
            "except StopBeforeFixture: pass\n"
        )
        before_refs = self.git("show-ref")
        result = self.run_python(program)
        self.assertEqual(result.returncode, 0, result.stderr)
        git_env = json.loads(result.stdout)
        self.assertNotIn("GIT_DIR", git_env)
        self.assertNotIn("GIT_WORK_TREE", git_env)
        self.assertNotIn("GIT_COMMON_DIR", git_env)
        self.assertNotIn("GIT_INDEX_FILE", git_env)
        self.assertNotIn("GIT_OBJECT_DIRECTORY", git_env)
        self.assertNotIn("GIT_TEMPLATE_DIR", git_env)
        self.assertNotIn("GIT_CONFIG_COUNT", git_env)
        self.assertEqual("1", git_env["GIT_CONFIG_NOSYSTEM"])
        self.assertEqual(os.devnull, git_env["GIT_CONFIG_GLOBAL"])
        self.assertEqual("0", git_env["GIT_TERMINAL_PROMPT"])
        self.assertEqual(before_refs, self.git("show-ref"))

    def test_image_fixtures_do_not_reuse_fixed_checkout_names(self) -> None:
        tree = ast.parse((ROOT / "scripts" / "selftest.py").read_text(encoding="utf-8"))
        literals = {
            node.value for node in ast.walk(tree)
            if isinstance(node, ast.Constant) and isinstance(node.value, str)
        }
        self.assertNotIn(".tmp-selftest-image-provider.txt", literals)
        self.assertNotIn(".tmp-selftest-image-output-location.txt", literals)


if __name__ == "__main__":
    unittest.main()
