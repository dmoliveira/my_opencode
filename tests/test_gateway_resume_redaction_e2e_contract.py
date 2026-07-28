from __future__ import annotations

import re
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gateway_resume_redaction_e2e.py"
MAKEFILE = ROOT / "Makefile"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SPEC = ROOT / "docs" / "specs" / "provider-boundary-secret-redaction.md"


class GatewayResumeRedactionE2EContractTests(unittest.TestCase):
    def test_runtime_and_ci_use_one_exact_opencode_version(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        match = re.search(
            r'^EXPECTED_OPENCODE_VERSION = "([^"]+)"$', script, re.MULTILINE
        )
        self.assertIsNotNone(match)
        version = match.group(1) if match else ""
        self.assertEqual(version, "1.18.5")
        self.assertIn('"autoupdate": False', script)
        self.assertIn('"postflight_opencode_version"', script)

        makefile = MAKEFILE.read_text(encoding="utf-8")
        workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn(f"OPENCODE_RESUME_E2E_VERSION := {version}", makefile)
        install_specs = re.findall(r"opencode-ai@([^\s\"']+)", workflow)
        self.assertEqual(install_specs, [version])
        install_lines = [
            line.strip() for line in workflow.splitlines() if "opencode-ai@" in line
        ]
        self.assertEqual(
            install_lines,
            [f"npm install --global opencode-ai@{version} --no-audit --no-fund"],
        )

    def test_ci_requires_the_live_resume_transport_gate(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")
        workflow = CI_WORKFLOW.read_text(encoding="utf-8")
        target_match = re.search(
            r"^gateway-resume-redaction-e2e:.*\n(?P<body>(?:\t.*\n)+)",
            makefile,
            re.MULTILINE,
        )
        self.assertIsNotNone(target_match)
        target_body = target_match.group("body") if target_match else ""
        self.assertIn("scripts/gateway_resume_redaction_e2e.py", target_body)
        self.assertNotRegex(target_body, r"(?m)^\t-")
        self.assertNotRegex(target_body, r"\|\|\s*true|;\s*true")

        gate_match = re.search(
            r"^      - name: Gate provider-boundary session resume regressions\n"
            r"(?P<body>(?:(?!^      - name:).*(?:\n|\Z))+)",
            workflow,
            re.MULTILINE,
        )
        self.assertIsNotNone(gate_match)
        gate_body = gate_match.group("body") if gate_match else ""
        self.assertNotIn("continue-on-error", gate_body)
        self.assertNotRegex(gate_body, r"(?m)^\s+if:")
        self.assertNotRegex(gate_body, r"\|\|\s*true|;\s*true")
        self.assertRegex(
            gate_body,
            r"run: \|\n          make gateway-resume-redaction-e2e "
            r'OPENCODE_BIN="\$\(command -v opencode\)"',
        )
        self.assertNotRegex(gate_body, r"(?m)^\s*-\s*make gateway-resume-redaction-e2e")
        self.assertNotIn("continue-on-error", workflow)
        help_result = subprocess.run(
            ["make", "--no-print-directory", "help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn("gateway-resume-redaction-e2e", help_result.stdout)

    def test_security_spec_pins_reviewed_converter_and_future_gate(self) -> None:
        spec = SPEC.read_text(encoding="utf-8")
        self.assertIn("OpenCode `1.18.5` conversion contract", spec)
        self.assertIn("e5cc278dec9294a627a7b05f47ce6a564408c1a2", spec)
        self.assertIn("1bea9f52c3ec6afec280e176a930c747c72091b7", spec)
        self.assertIn("eb116f6b960f6da4115ffb262695af6162ac2045", spec)
        self.assertIn("credential-free resume gate is mandatory CI", spec)


if __name__ == "__main__":
    unittest.main()
