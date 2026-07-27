from __future__ import annotations

import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
MAKEFILE = ROOT / "Makefile"
INSTALLER = ROOT / "install.sh"


class MakefilePythonRuntimeTests(unittest.TestCase):
    def run_make(self, *args: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["make", "--no-print-directory", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def test_supported_explicit_interpreter_passes(self) -> None:
        result = self.run_make("python-check", f"PYTHON={sys.executable}")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(sys.executable, result.stdout)

    def test_installed_unsupported_interpreter_is_rejected(self) -> None:
        candidate = Path("/usr/bin/python3")
        if not candidate.is_file():
            self.skipTest("/usr/bin/python3 is unavailable")
        version = subprocess.run(
            [str(candidate), "-c", "import sys; print(str(sys.version_info.major) + chr(46) + str(sys.version_info.minor))"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        major, minor = (int(part) for part in version.split(".", 1))
        if (major, minor) >= (3, 11):
            self.skipTest(f"{candidate} is supported ({version})")
        result = self.run_make("python-check", f"PYTHON={candidate}")
        self.assertEqual(result.returncode, 2)
        self.assertIn("Python 3.11+ is required", result.stderr)
        self.assertIn(str(candidate), result.stderr)

    def test_all_makefile_python_recipes_are_overridable_and_gated(self) -> None:
        text = MAKEFILE.read_text(encoding="utf-8")
        lines = text.splitlines()
        target = ""
        python_targets: set[str] = set()
        bare_python_lines: list[int] = []
        for line_number, line in enumerate(lines, start=1):
            match = re.match(r"^([A-Za-z0-9_-]+):", line)
            if match:
                target = match.group(1)
            if not line.startswith("\t"):
                continue
            if re.search(r"(?<![A-Za-z0-9_$()])python3(?=\s|$)", line):
                bare_python_lines.append(line_number)
            if "$(PYTHON)" in line and target != "python-check":
                python_targets.add(target)

        declared_match = re.search(r"^PYTHON_TARGETS := (.+)$", text, re.MULTILINE)
        self.assertIsNotNone(declared_match)
        declared = set(declared_match.group(1).split()) if declared_match else set()
        self.assertEqual(bare_python_lines, [])
        self.assertEqual(python_targets - declared, set())
        self.assertIn("PYTHON ?= python3", text)
        self.assertIn("PYTHON_MIN_VERSION := 3.11", text)

    def test_validate_dry_run_uses_explicit_interpreter(self) -> None:
        result = self.run_make("-n", "validate", f"PYTHON={sys.executable}")
        self.assertEqual(result.returncode, 0, result.stderr)
        command_lines = [line for line in result.stdout.splitlines() if line.strip()]
        self.assertTrue(command_lines)
        self.assertTrue(all(not line.lstrip().startswith("python3 ") for line in command_lines))
        self.assertGreater(sum(str(sys.executable) in line for line in command_lines), 5)

    def test_installer_rejects_unsupported_runtime_before_mutation(self) -> None:
        with tempfile.TemporaryDirectory(prefix="python-runtime-contract-") as raw_tmp:
            tmp = Path(raw_tmp)
            bin_dir = tmp / "bin"
            home = tmp / "home"
            bin_dir.mkdir()
            home.mkdir()
            (bin_dir / "git").write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            (bin_dir / "python3").write_text(
                textwrap.dedent(
                    """\
                    #!/bin/sh
                    if [ "${1:-}" = "--version" ]; then
                        printf "Python 3.9.0\n"
                        exit 0
                    fi
                    exit 2
                    """
                ),
                encoding="utf-8",
            )
            os.chmod(bin_dir / "git", 0o700)
            os.chmod(bin_dir / "python3", 0o700)
            env = {
                "HOME": str(home),
                "PATH": f"{bin_dir}:/bin:/usr/bin",
                "CI": "true",
            }
            result = subprocess.run(
                ["/bin/bash", str(INSTALLER), "--non-interactive", "--skip-self-check"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Python 3.11+ is required", result.stderr)
            self.assertIn("Python 3.9.0", result.stderr)
            self.assertFalse((home / ".config").exists())


if __name__ == "__main__":
    unittest.main()
