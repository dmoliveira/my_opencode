from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from lsp_rpc_client import LspClient, STDERR_TAIL_BYTES


FAKE_SERVER = ROOT / "tests" / "fixtures" / "fake_lsp_server.py"


class LspClientTransportTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="lsp-client-test-")
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def command(self, scenario: str) -> list[str]:
        return [sys.executable, str(FAKE_SERVER), scenario]

    def assert_transport_closed(self, client: LspClient) -> None:
        self.assertEqual(client.transport_threads_alive(), [])
        self.assertIsNotNone(client._proc)
        if client._proc is not None:
            self.assertIsNotNone(client._proc.poll())
            for stream in (client._proc.stdin, client._proc.stdout, client._proc.stderr):
                if stream is not None:
                    self.assertTrue(stream.closed)

    def test_normal_fragmented_and_wrong_id_responses(self) -> None:
        for scenario in ("normal", "fragmented", "wrong-id"):
            with self.subTest(scenario=scenario):
                client = LspClient(self.command(scenario), self.root, timeout_seconds=1.5)
                with client:
                    self.assertEqual(client.workspace_symbols("needle"), [])
                self.assert_transport_closed(client)

    def test_server_request_gets_method_not_found_reply(self) -> None:
        marker = self.root / "server-request-reply.json"
        previous = os.environ.get("FAKE_LSP_RESULT_PATH")
        os.environ["FAKE_LSP_RESULT_PATH"] = str(marker)
        try:
            client = LspClient(self.command("server-request"), self.root, timeout_seconds=1.5)
            with client:
                self.assertEqual(client.workspace_symbols("needle"), [])
            reply = json.loads(marker.read_text(encoding="utf-8"))
            self.assertEqual(reply.get("id"), 900)
            self.assertEqual((reply.get("error") or {}).get("code"), -32601)
            self.assert_transport_closed(client)
        finally:
            if previous is None:
                os.environ.pop("FAKE_LSP_RESULT_PATH", None)
            else:
                os.environ["FAKE_LSP_RESULT_PATH"] = previous

    def test_stderr_flood_does_not_block_and_tail_is_bounded(self) -> None:
        client = LspClient(self.command("stderr-flood"), self.root, timeout_seconds=2.0)
        with client:
            self.assertEqual(client.workspace_symbols("needle"), [])
            self.assertLessEqual(len(client.stderr_tail().encode("utf-8")), STDERR_TAIL_BYTES)
        self.assert_transport_closed(client)

    def test_partial_frames_time_out_and_cleanup(self) -> None:
        for scenario in ("stall-header", "stall-body"):
            with self.subTest(scenario=scenario):
                client = LspClient(self.command(scenario), self.root, timeout_seconds=0.2)
                started = time.monotonic()
                with self.assertRaises(TimeoutError):
                    client.__enter__()
                self.assertLess(time.monotonic() - started, 0.8)
                self.assert_transport_closed(client)

    def test_malformed_frames_fail_and_cleanup(self) -> None:
        scenarios = (
            "malformed-length",
            "conflicting-length",
            "oversized-length",
            "truncated-body",
            "abrupt-exit",
        )
        for scenario in scenarios:
            with self.subTest(scenario=scenario):
                client = LspClient(self.command(scenario), self.root, timeout_seconds=0.5)
                with self.assertRaises(RuntimeError):
                    client.__enter__()
                self.assert_transport_closed(client)

    def test_stalled_stdin_write_uses_same_deadline_and_cleanup(self) -> None:
        source = self.root / "large.py"
        source.write_text("value = 1\n" + ("# payload\n" * 300000), encoding="utf-8")
        client = LspClient(
            self.command("stop-reading-after-initialize"),
            self.root,
            timeout_seconds=0.2,
        )
        client.__enter__()
        started = time.monotonic()
        try:
            with self.assertRaises(TimeoutError):
                client.ensure_open(source)
            self.assertLess(time.monotonic() - started, 0.8)
        finally:
            client.__exit__(None, None, None)
        self.assert_transport_closed(client)

    def test_shutdown_timeout_escalates_and_reaps(self) -> None:
        client = LspClient(self.command("ignore-shutdown"), self.root, timeout_seconds=0.2)
        client.__enter__()
        started = time.monotonic()
        client.__exit__(None, None, None)
        self.assertLess(time.monotonic() - started, 0.8)
        self.assert_transport_closed(client)


class RealClangdSmokeTest(unittest.TestCase):
    def test_real_clangd_lifecycle_when_required(self) -> None:
        if os.environ.get("REQUIRE_REAL_CLANGD") != "1":
            return
        clangd = os.environ.get("CLANGD_BIN") or shutil.which("clangd")
        self.assertTrue(clangd, "CLANGD_BIN or clangd on PATH is required")
        with tempfile.TemporaryDirectory(prefix="lsp-clangd-smoke-") as raw_tmp:
            root = Path(raw_tmp)
            source = root / "main.c"
            source.write_text("int main(void) { return 0; }\n", encoding="utf-8")
            client = LspClient(
                [str(clangd), "--background-index=0", "--clang-tidy=0"],
                root,
                timeout_seconds=5.0,
            )
            with client:
                client.ensure_open(source)
                symbols = client.document_symbols(source)
                self.assertTrue(any(item.get("name") == "main" for item in symbols))
            self.assertEqual(client.transport_threads_alive(), [])
            self.assertIsNotNone(client._proc)
            if client._proc is not None:
                self.assertIsNotNone(client._proc.poll())


if __name__ == "__main__":
    unittest.main()
