from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from gateway_execution_status_live_smoke import (  # noqa: E402
    SmokeError,
    resolve_opencode_binary,
)


class GatewayExecutionStatusLiveSmokeTests(unittest.TestCase):
    def test_resolves_bare_binary_before_isolated_path_removal(self) -> None:
        with tempfile.TemporaryDirectory(prefix="opencode-bin-") as raw_tmp:
            binary = Path(raw_tmp) / "opencode"
            binary.write_text("#!/bin/sh\n", encoding="utf-8")
            binary.chmod(0o700)

            with patch(
                "gateway_execution_status_live_smoke.shutil.which",
                return_value=str(binary),
            ):
                self.assertEqual(str(binary.resolve()), resolve_opencode_binary("opencode"))

    def test_rejects_missing_binary(self) -> None:
        with patch(
            "gateway_execution_status_live_smoke.shutil.which", return_value=None
        ):
            with self.assertRaisesRegex(SmokeError, "opencode_binary_not_found"):
                resolve_opencode_binary("opencode")


if __name__ == "__main__":
    unittest.main()
