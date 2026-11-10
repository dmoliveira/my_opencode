from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

if os.name == "posix":
    sys.path.insert(
        0, str(Path(__file__).resolve().parents[1] / "plugin/gateway-core/test/v2")
    )
    import direct_shell_activation_live_smoke as probe


def complete_measurement() -> dict[str, object]:
    return {
        "host": "opencode v2.2.6",
        "first_response_created": True,
        "first_witness_before_plugin_ready": True,
        "configured_plugin_active": True,
        "second_response_created": True,
        "second_witness_after_plugin_ready": True,
        "post_activation_hook_seen": True,
        "post_activation_host_session_set": False,
        "post_activation_block_refused": True,
        "cleanup_complete": True,
    }


@unittest.skipUnless(os.name == "posix", "native shell probe is POSIX-only")
class DirectShellActivationTests(unittest.TestCase):
    def test_wait_keeps_runtime_leader_unreaped_until_group_cleanup(self) -> None:
        process = Mock()
        runtime = SimpleNamespace(process=process, deadline=time.monotonic() + 1)
        probe.wait_for(lambda: True, runtime, "not_observed")
        process.poll.assert_not_called()

    def test_direct_shell_requires_matching_successful_exit_not_timeout(self) -> None:
        command = "printf FIRST > first-witness"
        cwd = Path("/private-owned-fixture")
        created = {"data": {"id": "shell_owned"}}
        info = {
            "id": "shell_owned",
            "command": command,
            "cwd": str(cwd),
            "shell": "/bin/sh",
        }
        runtime = SimpleNamespace(
            request=Mock(return_value={"data": {**info, "status": "exited", "exit": 0}})
        )
        probe.wait_for_shell_exit(runtime, created, command, cwd)
        for update in (
            {"status": "timeout"},
            {"status": "exited", "exit": 1},
            {"status": "exited", "exit": 0, "id": "shell_other"},
            {"status": "exited", "exit": 0, "shell": "/other"},
        ):
            with self.subTest(update=update):
                runtime.request.return_value = {"data": {**info, **update}}
                with self.assertRaises(probe.ProbeFailure):
                    probe.wait_for_shell_exit(runtime, created, command, cwd)

    def test_measurement_requires_all_observations_and_successful_cleanup(self) -> None:
        evidence = complete_measurement()
        self.assertTrue(probe.measured(evidence))
        for name in evidence:
            with self.subTest(missing=name):
                incomplete = dict(evidence)
                del incomplete[name]
                self.assertFalse(probe.measured(incomplete))
        for change in (
            {"host": "opencode v2.2.7"},
            {"post_activation_host_session_set": True},
            {"cleanup_complete": False},
            {"reason": "probe_failed"},
        ):
            with self.subTest(change=change):
                self.assertFalse(probe.measured({**evidence, **change}))

    def test_observations_do_not_follow_links_or_accept_hardlinks(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            regular = root / "regular"
            regular.write_text("ready", encoding="utf-8")
            self.assertEqual(probe.read_owned(regular), "ready")
            self.assertIsNone(probe.read_owned(root / "absent"))
            symlink = root / "symlink"
            symlink.symlink_to(regular)
            with self.assertRaises(OSError):
                probe.read_owned(symlink)
            os.link(regular, root / "hardlink")
            with self.assertRaises(probe.ProbeFailure):
                probe.read_owned(regular)

    def test_failed_fixture_removal_cannot_report_a_successful_measurement(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            with (
                patch.object(probe, "preflight"),
                patch.object(
                    probe, "prepare", side_effect=probe.ProbeFailure("setup_failed")
                ),
                patch.object(
                    probe.shutil, "rmtree", side_effect=OSError("cleanup failed")
                ),
            ):
                report = probe.run_probe("unused", parent)
            self.assertFalse(report["cleanup_complete"])
            self.assertEqual(report["reason"], "cleanup_failed")
            self.assertEqual(report["result"], "FAIL")
            self.assertEqual(len(list(parent.iterdir())), 1)

    def test_unknown_shell_settlement_preserves_the_fixture(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            parent = Path(temporary)
            runtime = Mock()
            runtime.mutate.side_effect = probe.ProbeFailure("response_lost")
            with (
                patch.object(probe, "preflight"),
                patch.object(probe, "prepare"),
                patch.object(
                    probe, "run_child", return_value=(0, b"opencode v2.2.6", b"")
                ),
                patch.object(probe, "PrivateRuntime", return_value=runtime),
                patch.object(probe, "wait_for"),
            ):
                report = probe.run_probe("unused", parent)
            self.assertFalse(report["cleanup_complete"])
            self.assertEqual(report["reason"], "cleanup_failed")
            self.assertEqual(report["result"], "FAIL")
            self.assertEqual(len(list(parent.iterdir())), 1)


if __name__ == "__main__":
    unittest.main()
