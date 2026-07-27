from __future__ import annotations

import json
import multiprocessing
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from gateway_state_protocol import (  # noqa: E402
    LOCK_DIRECTORY_NAME,
    LOCK_RECOVERY_GUIDANCE,
    MAX_SAFE_INTEGER,
    MAX_STATE_BYTES,
    OWNER_TOKEN_NAME,
    PRIVATE_DIRECTORY_MODE,
    PRIVATE_FILE_MODE,
    STAGE_PREFIX,
    STATE_FILE_NAME,
    DomainMutation,
    GatewayStateProtocolError,
    gateway_state_lock_path,
    gateway_state_lock_status,
    gateway_state_path,
    load_gateway_state,
    mutate_gateway_state_domain,
    update_gateway_state_domain,
)
from concise_mode_runtime import set_active_mode  # noqa: E402
from gateway_plugin_bridge import (  # noqa: E402
    bridge_start_loop,
    bridge_stop_loop,
    cleanup_orphan_loop,
)


def _concurrent_writer(
    root: str,
    domain: str,
    count: int,
    output: object,
    ready_path: str | None = None,
    go_path: str | None = None,
) -> None:
    try:
        cwd = Path(root)
        if ready_path or go_path:
            if not ready_path or not go_path:
                raise RuntimeError("start barrier requires ready and go paths")
            Path(ready_path).write_text("ready\n", encoding="utf-8")
            deadline = time.monotonic() + 10
            while not Path(go_path).exists():
                if time.monotonic() >= deadline:
                    raise TimeoutError("start barrier timed out")
                time.sleep(0.01)
        for index in range(count):
            if domain == "activeLoop":
                value = {
                    "active": True,
                    "sessionId": "node-like",
                    "objective": f"objective-{index}",
                    "completionMode": "promise",
                    "completionPromise": "DONE",
                    "iteration": index,
                    "maxIterations": count,
                    "startedAt": "2026-07-27T00:00:00Z",
                }
            else:
                value = {
                    "mode": "lite" if index % 2 else "full",
                    "source": "python-test",
                    "sessionId": "session",
                    "activatedAt": "2026-07-27T00:00:00Z",
                    "updatedAt": f"2026-07-27T00:00:{index:02d}Z",
                }
            update_gateway_state_domain(
                cwd,
                domain,  # type: ignore[arg-type]
                value,
                root_updates={"lastUpdatedAt": "2026-07-27T00:00:00Z"},
            )
        output.put((domain, "PASS"))
    except BaseException as error:  # pragma: no cover - surfaced in parent.
        output.put((domain, f"{type(error).__name__}:{error}"))


def _seed_state(root: Path) -> None:
    update_gateway_state_domain(
        root,
        "activeLoop",
        {
            "active": True,
            "sessionId": "seed",
            "objective": "seed",
            "completionMode": "promise",
            "completionPromise": "DONE",
            "iteration": 0,
            "maxIterations": 100,
            "startedAt": "2026-07-27T00:00:00Z",
            "unknownLoop": {"sentinel": "loop"},
        },
        root_updates={
            "lastUpdatedAt": "2026-07-27T00:00:00Z",
            "source": "seed",
        },
    )
    update_gateway_state_domain(
        root,
        "conciseMode",
        {
            "mode": "lite",
            "source": "seed",
            "sessionId": "seed",
            "activatedAt": "2026-07-27T00:00:00Z",
            "updatedAt": "2026-07-27T00:00:00Z",
            "unknownConcise": {"sentinel": "concise"},
        },
        root_updates={"lastUpdatedAt": "2026-07-27T00:00:00Z"},
    )
    payload = load_gateway_state(root)
    payload["unknownRoot"] = {"sentinel": "root"}
    path = gateway_state_path(root)
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    path.chmod(PRIVATE_FILE_MODE)


class GatewayStateProtocolTest(unittest.TestCase):
    def test_python_bridge_and_concise_writers_preserve_sibling_domains(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            _seed_state(root)
            bridge_start_loop(
                root,
                {
                    "run_id": "run-1",
                    "started_at": "2026-07-27T00:00:00Z",
                    "objective": {
                        "goal": "bridge objective",
                        "completion_mode": "promise",
                        "completion_promise": "DONE",
                    },
                },
                session_id="bridge-session",
            )
            after_bridge = load_gateway_state(root)
            self.assertEqual("bridge-session", after_bridge["activeLoop"]["sessionId"])
            self.assertEqual(
                "loop", after_bridge["activeLoop"]["unknownLoop"]["sentinel"]
            )
            self.assertEqual(
                "concise",
                after_bridge["conciseMode"]["unknownConcise"]["sentinel"],
            )
            self.assertEqual("root", after_bridge["unknownRoot"]["sentinel"])

            set_active_mode(
                root,
                "full",
                source="test",
                session_id="concise-session",
            )
            after_concise = load_gateway_state(root)
            self.assertEqual("bridge-session", after_concise["activeLoop"]["sessionId"])
            self.assertEqual("full", after_concise["conciseMode"]["mode"])
            self.assertEqual(
                "concise",
                after_concise["conciseMode"]["unknownConcise"]["sentinel"],
            )
            self.assertEqual("root", after_concise["unknownRoot"]["sentinel"])

            self.assertIsNotNone(bridge_stop_loop(root))
            self.assertFalse(load_gateway_state(root)["activeLoop"]["active"])

    def test_orphan_cleanup_rechecks_predicate_inside_transaction(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            _seed_state(root)
            path, changed, reason = cleanup_orphan_loop(root, max_age_hours=1)
            self.assertTrue(changed)
            self.assertEqual("stale_loop_deactivated", reason)
            self.assertEqual(gateway_state_path(root).resolve(), path.resolve())
            self.assertFalse(load_gateway_state(root)["activeLoop"]["active"])

    def test_python_and_node_protocol_constants_match(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable")
        script = """
import * as storage from './plugin/gateway-core/dist/state/storage.js';
process.stdout.write(JSON.stringify({
  lock: storage.LOCK_DIRECTORY_NAME,
  token: storage.OWNER_TOKEN_NAME,
  stage: storage.STAGE_PREFIX,
  lockTimeoutMs: storage.LOCK_TIMEOUT_MS,
  lockPollMs: storage.LOCK_POLL_MS,
  maxBytes: storage.MAX_STATE_BYTES,
  directoryMode: storage.PRIVATE_DIRECTORY_MODE,
  fileMode: storage.PRIVATE_FILE_MODE,
}));
"""
        completed = subprocess.run(
            [node, "--input-type=module", "--eval", script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
        payload = json.loads(completed.stdout)
        self.assertEqual(LOCK_DIRECTORY_NAME, payload["lock"])
        self.assertEqual(OWNER_TOKEN_NAME, payload["token"])
        self.assertEqual(STAGE_PREFIX, payload["stage"])
        self.assertEqual(2000, payload["lockTimeoutMs"])
        self.assertEqual(20, payload["lockPollMs"])
        self.assertEqual(MAX_STATE_BYTES, payload["maxBytes"])
        self.assertEqual(PRIVATE_DIRECTORY_MODE, payload["directoryMode"])
        self.assertEqual(PRIVATE_FILE_MODE, payload["fileMode"])

    def test_missing_read_is_non_mutating_and_first_write_is_private(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            self.assertEqual({}, load_gateway_state(root))
            self.assertFalse((root / ".opencode").exists())

            result = update_gateway_state_domain(
                root,
                "activeLoop",
                None,
                root_updates={"lastUpdatedAt": "2026-07-27T00:00:00Z"},
            )
            state_path = gateway_state_path(root)
            self.assertTrue(result.changed)
            self.assertTrue(result.commit and result.commit.lock_released)
            self.assertEqual(PRIVATE_FILE_MODE, stat.S_IMODE(state_path.stat().st_mode))
            self.assertEqual(
                PRIVATE_DIRECTORY_MODE,
                stat.S_IMODE((root / ".opencode").stat().st_mode),
            )
            self.assertFalse(gateway_state_lock_path(root).exists())
            self.assertFalse(
                any(path.name.startswith(STAGE_PREFIX) for path in state_path.parent.iterdir())
            )

    def test_open_reader_accepts_atomic_replacement_of_opened_inode(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            _seed_state(root)
            path = gateway_state_path(root)
            replacement_payload = load_gateway_state(root)
            replacement_payload["activeLoop"]["sessionId"] = "replacement"

            def replace_after_open(phase: str) -> None:
                if phase != "after_state_open":
                    return
                replacement = path.with_name("replacement.json")
                replacement.write_text(
                    json.dumps(replacement_payload, indent=2) + "\n", encoding="utf-8"
                )
                replacement.chmod(PRIVATE_FILE_MODE)
                os.replace(replacement, path)

            observed = load_gateway_state(root, _failure_injector=replace_after_open)
            self.assertEqual("seed", observed["activeLoop"]["sessionId"])
            self.assertEqual(
                "replacement", load_gateway_state(root)["activeLoop"]["sessionId"]
            )

    def test_unsafe_ancestor_namespace_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            unsafe_parent = Path(raw_tmp) / "unsafe-parent"
            unsafe_parent.mkdir()
            unsafe_parent.chmod(0o777)
            root = unsafe_parent / "project"
            root.mkdir(mode=0o700)
            with self.assertRaises(GatewayStateProtocolError) as raised:
                load_gateway_state(root)
            self.assertEqual(
                "gateway_state_unsafe_project_root", raised.exception.reason_code
            )
            self.assertFalse((root / ".opencode").exists())

    def test_nonfinite_lock_timeouts_are_rejected_before_mutation(self) -> None:
        for timeout in (float("nan"), float("inf"), float("-inf")):
            with self.subTest(timeout=timeout), tempfile.TemporaryDirectory() as raw_tmp:
                root = Path(raw_tmp)
                with self.assertRaises(GatewayStateProtocolError) as raised:
                    update_gateway_state_domain(
                        root, "activeLoop", None, timeout_ms=timeout  # type: ignore[arg-type]
                    )
                self.assertEqual(
                    "gateway_state_invalid_timeout", raised.exception.reason_code
                )
                self.assertFalse((root / ".opencode").exists())

    def test_domain_updates_preserve_sibling_and_unknown_sentinels(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            _seed_state(root)
            update_gateway_state_domain(
                root,
                "activeLoop",
                {
                    "active": False,
                    "sessionId": "updated",
                    "objective": "updated",
                    "completionMode": "promise",
                    "completionPromise": "DONE",
                    "iteration": 9,
                    "maxIterations": 10,
                    "startedAt": "2026-07-27T00:00:00Z",
                },
                root_updates={
                    "lastUpdatedAt": "2026-07-27T01:00:00Z",
                    "source": "active-writer",
                },
            )
            after_active = load_gateway_state(root)
            self.assertEqual("loop", after_active["activeLoop"]["unknownLoop"]["sentinel"])
            self.assertEqual(
                "concise",
                after_active["conciseMode"]["unknownConcise"]["sentinel"],
            )
            self.assertEqual("root", after_active["unknownRoot"]["sentinel"])

            update_gateway_state_domain(
                root,
                "conciseMode",
                {"mode": "full", "updatedAt": "2026-07-27T02:00:00Z"},
                mode="patch",
                root_updates={"lastUpdatedAt": "2026-07-27T02:00:00Z"},
            )
            final = load_gateway_state(root)
            self.assertEqual("updated", final["activeLoop"]["sessionId"])
            self.assertEqual("full", final["conciseMode"]["mode"])
            self.assertEqual("seed", final["conciseMode"]["sessionId"])
            self.assertEqual(
                "concise", final["conciseMode"]["unknownConcise"]["sentinel"]
            )
            self.assertEqual("root", final["unknownRoot"]["sentinel"])

    def test_malformed_nonobject_invalid_utf8_and_unsafe_numbers_fail_closed(self) -> None:
        cases: tuple[tuple[bytes, str], ...] = (
            (b"{not-json}\n", "gateway_state_malformed_json"),
            (b"[]\n", "gateway_state_root_not_object"),
            (b"{\"value\":\xff}\n", "gateway_state_invalid_utf8"),
            (
                json.dumps({"value": MAX_SAFE_INTEGER + 1}).encode() + b"\n",
                "gateway_state_number_unsupported",
            ),
            (b'{"value": NaN}\n', "gateway_state_number_unsupported"),
        )
        for content, reason in cases:
            with self.subTest(reason=reason), tempfile.TemporaryDirectory() as raw_tmp:
                root = Path(raw_tmp)
                directory = root / ".opencode"
                directory.mkdir(mode=PRIVATE_DIRECTORY_MODE)
                path = directory / STATE_FILE_NAME
                path.write_bytes(content)
                path.chmod(PRIVATE_FILE_MODE)
                before = path.read_bytes()
                with self.assertRaises(GatewayStateProtocolError) as raised:
                    update_gateway_state_domain(root, "activeLoop", None)
                self.assertEqual(reason, raised.exception.reason_code)
                self.assertEqual(before, path.read_bytes())
                self.assertFalse(gateway_state_lock_path(root).exists())

    def test_gateway_status_reports_malformed_state_without_crashing(self) -> None:
        from gateway_command import status_payload

        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            directory = root / ".opencode"
            directory.mkdir(mode=PRIVATE_DIRECTORY_MODE)
            path = directory / STATE_FILE_NAME
            path.write_text("{not-json}\n", encoding="utf-8")
            path.chmod(PRIVATE_FILE_MODE)
            payload = status_payload({}, root, root, cleanup_orphans=True)
            self.assertEqual("PASS", payload["result"])
            self.assertEqual(
                "gateway_state_malformed_json",
                payload["orphan_cleanup"]["reason"],
            )
            self.assertTrue(
                any(
                    item.get("reason_code") == "gateway_state_malformed_json"
                    for item in payload["state_protocol_errors"]
                )
            )
            self.assertTrue(payload["gateway_state_lock"]["safe"])
            self.assertEqual("missing", payload["gateway_state_lock"]["state"])
            self.assertEqual("{not-json}\n", path.read_text(encoding="utf-8"))

    def test_oversized_input_and_output_fail_without_replacing_state(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            directory = root / ".opencode"
            directory.mkdir(mode=PRIVATE_DIRECTORY_MODE)
            path = directory / STATE_FILE_NAME
            path.write_bytes(b"{" + b" " * MAX_STATE_BYTES + b"}")
            path.chmod(PRIVATE_FILE_MODE)
            before = path.read_bytes()
            with self.assertRaises(GatewayStateProtocolError) as raised:
                load_gateway_state(root)
            self.assertEqual("gateway_state_too_large", raised.exception.reason_code)
            self.assertEqual(before, path.read_bytes())

        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            _seed_state(root)
            path = gateway_state_path(root)
            before = path.read_bytes()
            with self.assertRaises(GatewayStateProtocolError) as raised:
                update_gateway_state_domain(
                    root, "activeLoop", {"blob": "x" * MAX_STATE_BYTES}
                )
            self.assertEqual("gateway_state_too_large", raised.exception.reason_code)
            self.assertEqual(before, path.read_bytes())
            self.assertFalse(gateway_state_lock_path(root).exists())

    def test_path_attacks_preserve_victims(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            victim = root / "victim.json"
            victim.write_text('{"victim": true}\n', encoding="utf-8")
            victim_before = victim.read_bytes()
            directory = root / ".opencode"
            directory.symlink_to(root, target_is_directory=True)
            with self.assertRaises(GatewayStateProtocolError) as raised:
                update_gateway_state_domain(root, "activeLoop", None)
            self.assertEqual("gateway_state_unsafe_directory", raised.exception.reason_code)
            self.assertEqual(victim_before, victim.read_bytes())

        for attack in ("symlink", "hardlink", "fifo"):
            with self.subTest(attack=attack), tempfile.TemporaryDirectory() as raw_tmp:
                root = Path(raw_tmp)
                directory = root / ".opencode"
                directory.mkdir(mode=PRIVATE_DIRECTORY_MODE)
                victim = root / "victim.json"
                victim.write_text('{"victim": true}\n', encoding="utf-8")
                target = directory / STATE_FILE_NAME
                if attack == "symlink":
                    target.symlink_to(victim)
                elif attack == "hardlink":
                    os.link(victim, target)
                else:
                    os.mkfifo(target)
                before = victim.read_bytes()
                with self.assertRaises(GatewayStateProtocolError) as raised:
                    update_gateway_state_domain(root, "activeLoop", None)
                self.assertEqual("gateway_state_unsafe_target", raised.exception.reason_code)
                self.assertEqual(before, victim.read_bytes())

        for target_name in ("root", "directory"):
            with self.subTest(target_name=target_name), tempfile.TemporaryDirectory() as raw_tmp:
                root = Path(raw_tmp)
                directory = root / ".opencode"
                directory.mkdir(mode=PRIVATE_DIRECTORY_MODE)
                unsafe = root if target_name == "root" else directory
                unsafe.chmod(0o777)
                with self.assertRaises(GatewayStateProtocolError) as raised:
                    update_gateway_state_domain(root, "activeLoop", None)
                expected = (
                    "gateway_state_unsafe_project_root"
                    if target_name == "root"
                    else "gateway_state_unsafe_directory"
                )
                self.assertEqual(expected, raised.exception.reason_code)

    def test_valid_and_incomplete_locks_timeout_without_reclamation(self) -> None:
        for token in (b"a" * 64 + b"\n", b"partial"):
            with self.subTest(token=token), tempfile.TemporaryDirectory() as raw_tmp:
                root = Path(raw_tmp)
                directory = root / ".opencode"
                lock = directory / LOCK_DIRECTORY_NAME
                lock.mkdir(parents=True, mode=PRIVATE_DIRECTORY_MODE)
                token_path = lock / OWNER_TOKEN_NAME
                token_path.write_bytes(token)
                token_path.chmod(PRIVATE_FILE_MODE)
                started = time.monotonic()
                with self.assertRaises(GatewayStateProtocolError) as raised:
                    update_gateway_state_domain(
                        root, "activeLoop", None, timeout_ms=60
                    )
                self.assertEqual("gateway_state_lock_timeout", raised.exception.reason_code)
                elapsed = time.monotonic() - started
                self.assertGreaterEqual(elapsed, 0.04)
                self.assertLess(elapsed, 0.5)
                self.assertEqual(token, token_path.read_bytes())
                status = gateway_state_lock_status(root)
                self.assertTrue(status["present"])
                self.assertEqual(LOCK_RECOVERY_GUIDANCE, status["recovery_guidance"])

    def test_unsafe_lock_metadata_fails_immediately(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            lock = root / ".opencode" / LOCK_DIRECTORY_NAME
            lock.mkdir(parents=True, mode=PRIVATE_DIRECTORY_MODE)
            token = lock / OWNER_TOKEN_NAME
            token.write_bytes(b"a" * 64 + b"\n")
            token.chmod(0o644)
            started = time.monotonic()
            with self.assertRaises(GatewayStateProtocolError) as raised:
                update_gateway_state_domain(root, "activeLoop", None, timeout_ms=500)
            self.assertEqual("gateway_state_lock_unsafe", raised.exception.reason_code)
            self.assertLess(time.monotonic() - started, 0.2)
            self.assertTrue(lock.exists())

    def test_nested_transaction_fails_reentrant_without_deadlock(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)

            def nested(_current: object, _state: dict[str, object]) -> DomainMutation:
                update_gateway_state_domain(root, "conciseMode", None)
                return DomainMutation(None)

            started = time.monotonic()
            with self.assertRaises(GatewayStateProtocolError) as raised:
                mutate_gateway_state_domain(root, "activeLoop", nested)
            self.assertEqual("gateway_state_lock_reentrant", raised.exception.reason_code)
            self.assertLess(time.monotonic() - started, 0.5)
            self.assertFalse(gateway_state_lock_path(root).exists())

    def test_failure_injection_distinguishes_pre_and_post_commit(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            _seed_state(root)
            path = gateway_state_path(root)
            before = path.read_bytes()

            def fail_before(phase: str) -> None:
                if phase == "after_stage_fsync":
                    raise RuntimeError("pre-commit")

            with self.assertRaises(GatewayStateProtocolError) as raised:
                update_gateway_state_domain(
                    root,
                    "activeLoop",
                    {"active": False},
                    mode="patch",
                    _failure_injector=fail_before,
                )
            self.assertEqual("gateway_state_io_failed", raised.exception.reason_code)
            self.assertFalse(raised.exception.committed)
            self.assertEqual(before, path.read_bytes())
            self.assertFalse(gateway_state_lock_path(root).exists())
            self.assertFalse(
                any(item.name.startswith(STAGE_PREFIX) for item in path.parent.iterdir())
            )

            def fail_after(phase: str) -> None:
                if phase == "after_replace":
                    raise RuntimeError("post-commit")

            with self.assertRaises(GatewayStateProtocolError) as raised:
                update_gateway_state_domain(
                    root,
                    "activeLoop",
                    {"active": False},
                    mode="patch",
                    _failure_injector=fail_after,
                )
            self.assertEqual(
                "committed_durability_uncertain", raised.exception.reason_code
            )
            self.assertTrue(raised.exception.committed)
            self.assertTrue(raised.exception.lock_released)
            self.assertFalse(load_gateway_state(root)["activeLoop"]["active"])
            self.assertFalse(gateway_state_lock_path(root).exists())

    def test_release_identity_change_is_never_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            _seed_state(root)
            lock_path = gateway_state_lock_path(root)
            displaced = lock_path.with_name(lock_path.name + ".owned")

            def replace_lock(phase: str) -> None:
                if phase != "before_lock_release":
                    return
                lock_path.rename(displaced)
                lock_path.mkdir(mode=PRIVATE_DIRECTORY_MODE)
                token = lock_path / OWNER_TOKEN_NAME
                token.write_bytes(b"b" * 64 + b"\n")
                token.chmod(PRIVATE_FILE_MODE)

            with self.assertRaises(GatewayStateProtocolError) as raised:
                update_gateway_state_domain(
                    root,
                    "activeLoop",
                    {"active": False},
                    mode="patch",
                    _failure_injector=replace_lock,
                )
            self.assertEqual(
                "committed_lock_release_failed", raised.exception.reason_code
            )
            self.assertTrue(raised.exception.committed)
            self.assertTrue(lock_path.exists())
            self.assertEqual(
                b"b" * 64 + b"\n", (lock_path / OWNER_TOKEN_NAME).read_bytes()
            )

    def test_lock_release_metadata_tracks_owned_lock_disposition(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            _seed_state(root)

            def fail_before_remove(phase: str) -> None:
                if phase == "before_lock_release":
                    raise RuntimeError("before remove")

            with self.assertRaises(GatewayStateProtocolError) as raised:
                update_gateway_state_domain(
                    root,
                    "activeLoop",
                    {"active": False},
                    mode="patch",
                    _failure_injector=fail_before_remove,
                )
            self.assertEqual(
                "committed_lock_release_failed", raised.exception.reason_code
            )
            self.assertFalse(raised.exception.lock_released)
            self.assertTrue(gateway_state_lock_path(root).exists())

        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            _seed_state(root)

            def fail_after_remove(phase: str) -> None:
                if phase == "after_lock_remove":
                    raise RuntimeError("after remove")

            with self.assertRaises(GatewayStateProtocolError) as raised:
                update_gateway_state_domain(
                    root,
                    "activeLoop",
                    {"active": False},
                    mode="patch",
                    _failure_injector=fail_after_remove,
                )
            self.assertEqual(
                "committed_lock_release_failed", raised.exception.reason_code
            )
            self.assertTrue(raised.exception.lock_released)
            self.assertFalse(gateway_state_lock_path(root).exists())

    def test_python_process_contention_preserves_both_domains_and_valid_json(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            _seed_state(root)
            path = gateway_state_path(root)
            context = multiprocessing.get_context("spawn")
            output = context.Queue()
            processes = [
                context.Process(
                    target=_concurrent_writer,
                    args=(str(root), domain, 30, output),
                )
                for domain in ("activeLoop", "conciseMode")
            ]
            for process in processes:
                process.start()
            deadline = time.monotonic() + 15
            observations = 0
            while any(process.is_alive() for process in processes):
                self.assertLess(time.monotonic(), deadline)
                payload = load_gateway_state(root)
                self.assertIsInstance(payload, dict)
                observations += 1
                time.sleep(0.002)
            for process in processes:
                process.join(timeout=1)
                self.assertEqual(0, process.exitcode)
            results = {output.get(timeout=1) for _ in processes}
            self.assertEqual(
                {("activeLoop", "PASS"), ("conciseMode", "PASS")}, results
            )
            self.assertGreater(observations, 0)
            final = load_gateway_state(root)
            self.assertEqual("loop", final["activeLoop"]["unknownLoop"]["sentinel"])
            self.assertEqual(
                "concise", final["conciseMode"]["unknownConcise"]["sentinel"]
            )
            self.assertEqual("root", final["unknownRoot"]["sentinel"])
            self.assertFalse(gateway_state_lock_path(root).exists())
            self.assertFalse(
                any(item.name.startswith(STAGE_PREFIX) for item in path.parent.iterdir())
            )

    def test_real_node_python_contention_preserves_disjoint_domains(self) -> None:
        node = shutil.which("node")
        if node is None:
            self.skipTest("node is unavailable")
        repo_root = Path(__file__).resolve().parents[1]
        fixture = (
            repo_root
            / "plugin"
            / "gateway-core"
            / "test"
            / "fixtures"
            / "gateway-state-writer.mjs"
        )
        if not (repo_root / "plugin" / "gateway-core" / "dist" / "state" / "protocol.js").is_file():
            self.skipTest("gateway-core dist protocol is not built")
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            _seed_state(root)
            path = gateway_state_path(root)
            context = multiprocessing.get_context("spawn")
            output = context.Queue()
            python_writer = context.Process(
                target=_concurrent_writer,
                args=(
                    str(root),
                    "conciseMode",
                    30,
                    output,
                    str(root / "python.ready"),
                    str(root / "writers.go"),
                ),
            )
            node_writer = subprocess.Popen(
                [
                    node,
                    str(fixture),
                    str(root),
                    "activeLoop",
                    "30",
                    str(root / "node.ready"),
                    str(root / "writers.go"),
                ],
                cwd=repo_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                start_new_session=True,
            )
            python_writer.start()
            deadline = time.monotonic() + 15
            while not (root / "python.ready").exists() or not (
                root / "node.ready"
            ).exists():
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.01)
            (root / "writers.go").write_text("go\n", encoding="utf-8")
            observations = 0
            while python_writer.is_alive() or node_writer.poll() is None:
                self.assertLess(time.monotonic(), deadline)
                payload = load_gateway_state(root)
                self.assertIsInstance(payload, dict)
                observations += 1
                time.sleep(0.002)
            python_writer.join(timeout=1)
            stdout, stderr = node_writer.communicate(timeout=1)
            self.assertEqual(0, python_writer.exitcode)
            self.assertEqual(("conciseMode", "PASS"), output.get(timeout=1))
            self.assertEqual(0, node_writer.returncode, stderr)
            self.assertEqual("PASS", json.loads(stdout)["result"])
            self.assertGreater(observations, 0)
            final = load_gateway_state(root)
            self.assertEqual("loop", final["activeLoop"]["unknownLoop"]["sentinel"])
            self.assertEqual(
                "concise", final["conciseMode"]["unknownConcise"]["sentinel"]
            )
            self.assertEqual("root", final["unknownRoot"]["sentinel"])
            self.assertFalse(gateway_state_lock_path(root).exists())
            self.assertFalse(
                any(item.name.startswith(STAGE_PREFIX) for item in path.parent.iterdir())
            )


if __name__ == "__main__":
    unittest.main()
