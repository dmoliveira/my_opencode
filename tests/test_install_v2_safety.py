from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstallV2SafetyTest(unittest.TestCase):
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
