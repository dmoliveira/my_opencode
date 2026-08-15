from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
import unittest
from pathlib import Path
from typing import Any
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "gateway_resume_redaction_e2e.py"
MAKEFILE = ROOT / "Makefile"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
SPEC = ROOT / "docs" / "specs" / "provider-boundary-secret-redaction.md"


def load_resume_module():
    spec = importlib.util.spec_from_file_location("gateway_resume_e2e_contract", SCRIPT)
    if spec is None or spec.loader is None:
        raise AssertionError("unable to load resume E2E module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(spec.name, None)
    return module


def native_wire_payload(module) -> dict[str, Any]:
    expected_history = (
        f"{module.HISTORY_CONTROL}\n"
        f"{'Z' * module.LARGE_HISTORY_CHARS}\n"
        f"{module.REDACTION_TOKEN}"
    )
    return {
        "model": "gpt-4o",
        "input": [
            {
                "type": "reasoning",
                "encrypted_content": module.CIPHERTEXT,
                "summary": [
                    {"type": "summary_text", "text": module.REASONING_CONTROL}
                ],
            },
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": expected_history},
                    {"type": "input_image", "image_url": module.PNG_ATTACHMENT_DATA_URL},
                    {"type": "input_image", "image_url": module.JPEG_ATTACHMENT_DATA_URL},
                    {
                        "type": "input_file",
                        "filename": "direct.pdf",
                        "file_data": module.PDF_ATTACHMENT_DATA_URL,
                    },
                ],
            },
            {
                "type": "function_call",
                "call_id": "call_resume_e2e_0123456789",
                "name": "bash",
                "arguments": f'{{"command":"echo {module.TOOL_INPUT_CONTROL}"}}',
            },
            {
                "type": "function_call_output",
                "call_id": "call_resume_e2e_0123456789",
                "output": [
                    {"type": "input_text", "text": module.TOOL_OUTPUT_CONTROL},
                    {"type": "input_image", "image_url": module.PNG_ATTACHMENT_DATA_URL},
                    {"type": "input_image", "image_url": module.JPEG_ATTACHMENT_DATA_URL},
                    {
                        "type": "input_file",
                        "filename": "data",
                        "file_data": module.PDF_ATTACHMENT_DATA_URL,
                    },
                ],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": module.RESUME_CONTROL}],
            },
        ],
        "prompt_cache_key": f"ocpc-v1:{'a' * 24}:n1:s0",
    }


class GatewayResumeRedactionE2EContractTests(unittest.TestCase):
    def test_runtime_and_ci_use_one_exact_opencode_version(self) -> None:
        script = SCRIPT.read_text(encoding="utf-8")
        match = re.search(
            r'^EXPECTED_OPENCODE_VERSION = "([^"]+)"$', script, re.MULTILINE
        )
        self.assertIsNotNone(match)
        version = match.group(1) if match else ""
        self.assertEqual(version, "1.18.18")
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

    def test_opencode_binary_resolution_supports_basename_and_absolute_path(self) -> None:
        module = load_resume_module()

        with mock.patch.object(module.shutil, "which", return_value="/tmp/pinned-opencode"):
            self.assertEqual(
                module.resolve_opencode_binary(Path("opencode")),
                Path("/tmp/pinned-opencode").resolve(),
            )
        absolute = ROOT / "runtime" / "pinned-opencode"
        self.assertEqual(module.resolve_opencode_binary(absolute), absolute.resolve())

    def test_native_wire_validator_is_mutation_sensitive(self) -> None:
        module = load_resume_module()
        self.assertRegex(module.CIPHERTEXT, r"\bsk-[A-Za-z0-9_\-]{20,}")

        valid = module.validate_native_wire(
            native_wire_payload(module), {"ses_forbidden_runtime"}
        )
        for field in (
            "ciphertext_preserved_on_wire",
            "large_history_preserved_on_wire",
            "mutable_secret_absent_on_wire",
            "redaction_token_present_on_wire",
            "ui_only_metadata_absent_on_wire",
            "provider_controls_present",
            "png_attachment_preserved_on_wire",
            "jpeg_attachment_preserved_on_wire",
            "pdf_attachment_preserved_on_wire",
            "direct_user_png_attachment_preserved_on_wire",
            "direct_user_jpeg_attachment_preserved_on_wire",
            "direct_user_pdf_attachment_preserved_on_wire",
            "reasoning_without_item_id_on_wire",
            "prompt_cache_key_stable",
        ):
            self.assertIs(valid[field], True, field)

        def changed_ciphertext(payload: dict[str, Any]) -> None:
            payload["input"][0]["encrypted_content"] = "changed"

        def introduced_reasoning_id(payload: dict[str, Any]) -> None:
            payload["input"][0]["id"] = "rs_unexpected"

        def missing_image(payload: dict[str, Any]) -> None:
            payload["input"][3]["output"][2] = {"type": "future_attachment"}

        def remapped_image(payload: dict[str, Any]) -> None:
            payload["input"][3]["output"][2]["image_url"] = (
                module.PNG_ATTACHMENT_DATA_URL
            )

        def missing_direct_file(payload: dict[str, Any]) -> None:
            payload["input"][1]["content"][3] = {"type": "future_attachment"}

        for name, mutate, reason in (
            (
                "ciphertext",
                changed_ciphertext,
                "native_reasoning_ciphertext_invalid",
            ),
            (
                "reasoning-id",
                introduced_reasoning_id,
                "native_reasoning_shape_invalid",
            ),
            (
                "missing-image",
                missing_image,
                "native_function_output_image_count_invalid",
            ),
            (
                "remapped-image",
                remapped_image,
                "native_function_output_image_invalid",
            ),
            (
                "missing-direct-file",
                missing_direct_file,
                "native_direct_user_file_invalid",
            ),
        ):
            with self.subTest(name=name):
                payload = native_wire_payload(module)
                mutate(payload)
                with self.assertRaisesRegex(module.HarnessFailure, f"^{reason}$"):
                    module.validate_native_wire(payload, {"ses_forbidden_runtime"})

        leaked = native_wire_payload(module)
        leaked["leak"] = module.MUTABLE_SECRET
        leak_report = module.validate_native_wire(leaked, {"ses_forbidden_runtime"})
        self.assertIs(leak_report["mutable_secret_absent_on_wire"], False)

    def test_ci_requires_the_live_resume_transport_gate(self) -> None:
        makefile = MAKEFILE.read_text(encoding="utf-8")
        workflow = CI_WORKFLOW.read_text(encoding="utf-8")

        def target_body(name: str) -> str:
            match = re.search(
                rf"^{re.escape(name)}:.*\n(?P<body>(?:\t.*\n)+)",
                makefile,
                re.MULTILINE,
            )
            self.assertIsNotNone(match, name)
            return match.group("body") if match else ""

        full_target = "gateway-resume-redaction-e2e"
        prebuilt_target = "gateway-resume-redaction-e2e-prebuilt"
        phony_match = re.search(r"^\.PHONY:\s*(?P<targets>.+)$", makefile, re.MULTILINE)
        python_targets_match = re.search(
            r"^PYTHON_TARGETS\s*:=\s*(?P<targets>.+)$", makefile, re.MULTILINE
        )
        self.assertIsNotNone(phony_match)
        self.assertIsNotNone(python_targets_match)
        for target in (full_target, prebuilt_target):
            self.assertIn(target, phony_match.group("targets").split())
            self.assertIn(target, python_targets_match.group("targets").split())

        full_body = target_body(full_target)
        prebuilt_body = target_body(prebuilt_target)
        self.assertIn("npm --prefix plugin/gateway-core run build", full_body)
        self.assertIn(f"$(MAKE) --no-print-directory {prebuilt_target}", full_body)
        self.assertNotIn("scripts/gateway_resume_redaction_e2e.py", full_body)
        self.assertIn("scripts/gateway_resume_redaction_e2e.py", prebuilt_body)
        self.assertNotIn("npm ", prebuilt_body)
        self.assertNotIn("run build", prebuilt_body)
        for body in (full_body, prebuilt_body):
            self.assertNotRegex(body, r"(?m)^\t-")
            self.assertNotRegex(body, r"\|\|\s*true|;\s*true")

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
            rf"run: \|\n          make {prebuilt_target} "
            r'OPENCODE_BIN="\$\(command -v opencode\)"',
        )
        self.assertNotRegex(gate_body, rf"make {full_target}(?:\s|$)")
        self.assertLess(
            workflow.index("npm --prefix plugin/gateway-core run test"),
            workflow.index(f"make {prebuilt_target}"),
        )
        self.assertNotIn("continue-on-error", workflow)

        release_check_match = re.search(
            r"^release-check:\s*(?P<dependencies>[^#\n]+)",
            makefile,
            re.MULTILINE,
        )
        release_match = re.search(
            r"^release:\s*(?P<dependencies>[^#\n]+)",
            makefile,
            re.MULTILINE,
        )
        self.assertIsNotNone(release_check_match)
        self.assertIsNotNone(release_match)
        release_check_dependencies = (
            release_check_match.group("dependencies").split()
            if release_check_match
            else []
        )
        release_dependencies = (
            release_match.group("dependencies").split() if release_match else []
        )
        self.assertIn(full_target, release_check_dependencies)
        self.assertNotIn(prebuilt_target, release_check_dependencies)
        self.assertIn("release-check", release_dependencies)

        help_result = subprocess.run(
            ["make", "--no-print-directory", "help"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(help_result.returncode, 0, help_result.stderr)
        self.assertIn(full_target, help_result.stdout)
        self.assertIn(prebuilt_target, help_result.stdout)

    def test_security_spec_pins_reviewed_converter_and_future_gate(self) -> None:
        spec = SPEC.read_text(encoding="utf-8")
        self.assertIn("OpenCode `1.18.18` conversion contract", spec)
        self.assertIn("31406ccc51b4bd2a4e1e086b2bcaa5f7f804f26d", spec)
        self.assertIn("9b3f2c46f40578128001957004c67633a18da23a", spec)
        self.assertIn("22b1d7d99a2aa22211b5dae59385fa8a8a1d311d", spec)
        self.assertIn("@ai-sdk/openai` `3.0.84", spec)
        self.assertIn("da385f747e8277411d8b49c65e8a22c3bf158f4c", spec)
        self.assertIn("ai` `6.0.168", spec)
        self.assertIn("c38119a2e3df201a95a9979580f2c7a3c1b319ab", spec)
        self.assertIn("4fedd90b17f82c24cff7fd41b7f4872412a8a7d0", spec)
        self.assertIn("Canonical provider attachment envelope", spec)
        self.assertIn("`image/png`, `image/jpeg`, and", spec)
        self.assertIn("`application/pdf`", spec)
        self.assertIn("credential-free resume gate is mandatory CI", spec)


if __name__ == "__main__":
    unittest.main()
