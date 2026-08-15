from __future__ import annotations

import json
import sys
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import intent_coordinator_command as intent


def proposal() -> dict[str, Any]:
    return {
        "version": 1,
        "proposal_id": "request-1",
        "scope": "example/repo",
        "source": {
            "kind": "user",
            "id": "message-1",
            "summary": "Create a tracked implementation slice",
        },
        "records": [
            {
                "key": "epic:root",
                "entity_type": "epic",
                "title": "Deliver tracked objective",
                "kind": "feature",
                "priority": "P1",
            },
            {
                "key": "task:first",
                "entity_type": "task",
                "title": "Implement first tracked slice",
                "kind": "feature",
                "priority": "P1",
                "goal": "Deliver the first safe implementation slice.",
                "summary": "Build, validate, and record the bounded change.",
                "labels": ["agents", "codememory"],
            },
        ],
        "links": [{"from": "epic:root", "edge": "parent-of", "to": "task:first"}],
    }


def batch_result() -> dict[str, Any]:
    return {
        "type": "batch_plan_result",
        "scope_key": "example/repo",
        "count": 3,
        "records": [
            {
                "key": "epic:root",
                "id": "epic_1",
                "entity_type": "epic",
                "title": "Deliver tracked objective",
            },
            {
                "key": "task:first",
                "id": "task_1",
                "entity_type": "task",
                "title": "Implement first tracked slice",
            },
        ],
        "links": [
            {
                "id": "link_1",
                "edge_type": "parent-of",
                "from_id": "epic_1",
                "to_id": "task_1",
            }
        ],
    }


class FakeRunner:
    def __init__(
        self,
        *,
        collision: bool = False,
        saturated_find: bool = False,
        fail_apply: bool = False,
        apply_result: dict[str, Any] | None = None,
    ) -> None:
        self.collision = collision
        self.saturated_find = saturated_find
        self.fail_apply = fail_apply
        self.apply_result = apply_result
        self.calls: list[tuple[list[str], str]] = []
        self.manifests: list[str] = []

    def __call__(self, arguments: list[str], operation: str) -> dict[str, Any]:
        self.calls.append((list(arguments), operation))
        if operation == "intent_codememory_doctor":
            return {"status": "ok", "runtime_ready": True, "backend": "sqlite"}
        if operation == "intent_codememory_find":
            if self.saturated_find:
                return {
                    "items": [
                        {
                            "id": f"task_{index}",
                            "display": f"related result {index}",
                            "kind": "feature",
                        }
                        for index in range(intent.TITLE_LOOKUP_LIMIT)
                    ]
                }
            if self.collision:
                return {
                    "items": [
                        {
                            "id": "task_9",
                            "display": arguments[1],
                            "kind": "feature",
                        }
                    ]
                }
            return {"items": []}
        if operation == "intent_codememory_apply":
            manifest_path = Path(arguments[arguments.index("--file") + 1])
            self.manifests.append(manifest_path.read_text(encoding="utf-8"))
            if self.fail_apply:
                raise intent.CoordinatorError(
                    "intent_codememory_apply_timeout", "timeout"
                )
            return (
                self.apply_result if self.apply_result is not None else batch_result()
            )
        raise AssertionError((arguments, operation))


class BlockingRunner(FakeRunner):
    def __init__(self) -> None:
        super().__init__()
        self.apply_entered = threading.Event()
        self.release_apply = threading.Event()

    def __call__(self, arguments: list[str], operation: str) -> dict[str, Any]:
        if operation == "intent_codememory_apply":
            self.apply_entered.set()
            if not self.release_apply.wait(timeout=2):
                raise AssertionError("timed out waiting to release fake apply")
        return super().__call__(arguments, operation)


class IntentSchemaTest(unittest.TestCase):
    def test_manifest_and_fingerprint_are_deterministic(self) -> None:
        normalized = intent.normalize_proposal(proposal())

        self.assertEqual(
            intent.proposal_fingerprint(normalized),
            intent.proposal_fingerprint(intent.normalize_proposal(proposal())),
        )
        manifest = intent.build_manifest(normalized)
        self.assertIn('scope: "example/repo"', manifest)
        self.assertIn('key: "epic:root"', manifest)
        self.assertIn('edge: "parent-of"', manifest)

    def test_unknown_field_is_rejected(self) -> None:
        candidate = proposal()
        candidate["raw_prompt"] = "do not persist"

        with self.assertRaisesRegex(intent.CoordinatorError, "unknown fields"):
            intent.normalize_proposal(candidate)

    def test_change_limit_is_enforced(self) -> None:
        candidate = proposal()
        candidate["links"] = candidate["links"] * 9

        with self.assertRaisesRegex(intent.CoordinatorError, "exceed 10"):
            intent.normalize_proposal(candidate)

    def test_duplicate_keys_are_rejected(self) -> None:
        candidate = proposal()
        candidate["records"][1]["key"] = "epic:root"

        with self.assertRaisesRegex(intent.CoordinatorError, "keys must be unique"):
            intent.normalize_proposal(candidate)

    def test_unknown_reference_and_lifecycle_edge_are_rejected(self) -> None:
        unknown = proposal()
        unknown["links"][0]["to"] = "task:missing"
        with self.assertRaisesRegex(intent.CoordinatorError, "proposal record keys"):
            intent.normalize_proposal(unknown)

        lifecycle = proposal()
        lifecycle["links"][0]["edge"] = "active-task"
        with self.assertRaisesRegex(intent.CoordinatorError, "must be one of"):
            intent.normalize_proposal(lifecycle)

    def test_invalid_edge_endpoint_types_are_rejected(self) -> None:
        candidate = proposal()
        candidate["links"][0] = {
            "from": "task:first",
            "edge": "parent-of",
            "to": "epic:root",
        }

        with self.assertRaisesRegex(intent.CoordinatorError, "task -> epic"):
            intent.normalize_proposal(candidate)

    def test_load_rejects_malformed_and_oversized_json(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            malformed = Path(directory) / "malformed.json"
            malformed.write_text("{", encoding="utf-8")
            with self.assertRaises(intent.CoordinatorError) as malformed_error:
                intent.load_proposal(malformed)
            self.assertEqual(
                "intent_proposal_invalid_json", malformed_error.exception.reason_code
            )

            oversized = Path(directory) / "oversized.json"
            oversized.write_text(
                "x" * (intent.MAX_PROPOSAL_BYTES + 1), encoding="utf-8"
            )
            with self.assertRaises(intent.CoordinatorError) as oversized_error:
                intent.load_proposal(oversized)
            self.assertEqual(
                "intent_schema_limit_exceeded", oversized_error.exception.reason_code
            )

            with self.assertRaises(intent.CoordinatorError) as unsafe_error:
                intent.load_proposal(Path(directory))
            self.assertEqual(
                "intent_proposal_unsafe", unsafe_error.exception.reason_code
            )


class IntentCoordinatorTest(unittest.TestCase):
    def setUp(self) -> None:
        self.normalized = intent.normalize_proposal(proposal())
        self.temp = tempfile.TemporaryDirectory()
        self.state_dir = Path(self.temp.name) / "state"

    def tearDown(self) -> None:
        self.temp.cleanup()

    def test_preview_reports_collision_without_mutation(self) -> None:
        runner = FakeRunner(collision=True)

        report = intent.preview_proposal(self.normalized, runner)

        self.assertEqual("FAIL", report["result"])
        self.assertEqual("intent_title_collision", report["reason_code"])
        self.assertFalse(self.state_dir.exists())
        self.assertFalse(
            any(operation == "intent_codememory_apply" for _, operation in runner.calls)
        )

    def test_apply_persists_receipt_and_replay_is_noop(self) -> None:
        first_runner = FakeRunner()
        first = intent.apply_proposal(
            self.normalized,
            first_runner,
            state_dir=self.state_dir,
            actor="test",
        )

        self.assertEqual("PASS", first["result"])
        self.assertFalse(first["replayed"])
        self.assertEqual(2, first["record_count"])
        self.assertEqual(1, len(first_runner.manifests))
        receipt_path = next(self.state_dir.glob("receipts/*/*.json"))
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        self.assertEqual(self.normalized["source"], receipt["source"])
        self.assertEqual("test", receipt["actor"])

        replay_runner = FakeRunner(collision=True, fail_apply=True)
        replay = intent.apply_proposal(
            self.normalized,
            replay_runner,
            state_dir=self.state_dir,
            actor="test",
        )

        self.assertTrue(replay["replayed"])
        self.assertEqual([], replay_runner.calls)

    def test_changed_content_under_same_id_fails_closed(self) -> None:
        intent.apply_proposal(
            self.normalized,
            FakeRunner(),
            state_dir=self.state_dir,
            actor="test",
        )
        changed = proposal()
        changed["records"][1]["title"] = "Implement changed tracked slice"
        normalized_changed = intent.normalize_proposal(changed)

        with self.assertRaisesRegex(intent.CoordinatorError, "different content"):
            intent.apply_proposal(
                normalized_changed,
                FakeRunner(),
                state_dir=self.state_dir,
                actor="test",
            )

    def test_prepared_receipt_recovers_with_exact_manifest(self) -> None:
        first_runner = FakeRunner(fail_apply=True)
        with self.assertRaises(intent.CoordinatorError):
            intent.apply_proposal(
                self.normalized,
                first_runner,
                state_dir=self.state_dir,
                actor="first-actor",
            )
        self.assertEqual(1, len(first_runner.manifests))

        retry_runner = FakeRunner()
        recovered = intent.apply_proposal(
            self.normalized,
            retry_runner,
            state_dir=self.state_dir,
            actor="replacement-actor",
        )

        self.assertEqual("PASS", recovered["result"])
        self.assertFalse(recovered["replayed"])
        self.assertEqual(first_runner.manifests, retry_runner.manifests)
        self.assertFalse(
            any(
                operation == "intent_codememory_find"
                for _, operation in retry_runner.calls
            )
        )
        apply_args = next(
            arguments
            for arguments, operation in retry_runner.calls
            if operation == "intent_codememory_apply"
        )
        self.assertEqual("first-actor", apply_args[apply_args.index("--actor") + 1])

    def test_collision_aborts_without_receipt(self) -> None:
        with self.assertRaises(intent.CoordinatorError) as context:
            intent.apply_proposal(
                self.normalized,
                FakeRunner(collision=True),
                state_dir=self.state_dir,
                actor="test",
            )

        self.assertEqual("intent_title_collision", context.exception.reason_code)
        self.assertEqual([], list(self.state_dir.glob("receipts/*/*.json")))

    def test_saturated_title_lookup_aborts_without_receipt(self) -> None:
        runner = FakeRunner(saturated_find=True)

        with self.assertRaises(intent.CoordinatorError) as context:
            intent.apply_proposal(
                self.normalized,
                runner,
                state_dir=self.state_dir,
                actor="test",
            )

        self.assertEqual("intent_title_lookup_saturated", context.exception.reason_code)
        self.assertEqual([], list(self.state_dir.glob("receipts/*/*.json")))
        self.assertFalse(
            any(
                operation == "intent_codememory_apply"
                for _, operation in runner.calls
            )
        )
        find_arguments = next(
            arguments
            for arguments, operation in runner.calls
            if operation == "intent_codememory_find"
        )
        self.assertEqual(
            str(intent.TITLE_LOOKUP_LIMIT),
            find_arguments[find_arguments.index("--limit") + 1],
        )

    def test_invalid_apply_results_leave_prepared_receipt(self) -> None:
        wrong_scope = batch_result()
        wrong_scope["scope_key"] = "wrong/scope"

        missing_records = batch_result()
        del missing_records["records"]

        partial_records = batch_result()
        partial_records["records"] = partial_records["records"][:1]

        empty_record_id = batch_result()
        empty_record_id["records"][0]["id"] = ""

        wrong_link = batch_result()
        wrong_link["links"][0]["to_id"] = "task_wrong"

        for name, result in (
            ("wrong-scope", wrong_scope),
            ("missing-records", missing_records),
            ("partial-records", partial_records),
            ("empty-record-id", empty_record_id),
            ("wrong-link", wrong_link),
        ):
            with self.subTest(name=name):
                state_dir = Path(self.temp.name) / name
                with self.assertRaises(intent.CoordinatorError) as context:
                    intent.apply_proposal(
                        self.normalized,
                        FakeRunner(apply_result=result),
                        state_dir=state_dir,
                        actor="test",
                    )
                self.assertEqual(
                    "intent_codememory_apply_invalid", context.exception.reason_code
                )
                receipt_path = next(state_dir.glob("receipts/*/*.json"))
                receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
                self.assertEqual("prepared", receipt["status"])
                self.assertIsNone(receipt["result"])

    def test_state_subtree_symlinks_fail_closed(self) -> None:
        scope_digest = intent._scope_digest(str(self.normalized["scope"]))
        cases = {
            "locks": Path("locks"),
            "receipts": Path("receipts"),
            "receipt-scope": Path("receipts") / scope_digest,
            "tmp": Path("tmp"),
            "lock-file": Path("locks") / f"scope-{scope_digest}.json.lock",
        }
        for name, relative_path in cases.items():
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                state_dir = root / "state"
                outside = root / "outside"
                state_dir.mkdir()
                outside.mkdir()
                link = state_dir / relative_path
                link.parent.mkdir(parents=True, exist_ok=True)
                try:
                    link.symlink_to(outside, target_is_directory=True)
                except OSError as exc:
                    self.skipTest(f"symlinks are unavailable: {exc}")
                runner = FakeRunner()

                with self.assertRaises(intent.CoordinatorError) as context:
                    intent.apply_proposal(
                        self.normalized,
                        runner,
                        state_dir=state_dir,
                        actor="test",
                    )

                self.assertEqual(
                    "intent_state_path_unsafe", context.exception.reason_code
                )
                self.assertEqual([], runner.calls)

    def test_concurrent_apply_serializes_and_replays(self) -> None:
        runner = BlockingRunner()
        second_started = threading.Event()

        def apply() -> dict[str, Any]:
            return intent.apply_proposal(
                self.normalized,
                runner,
                state_dir=self.state_dir,
                actor="test",
            )

        def apply_second() -> dict[str, Any]:
            second_started.set()
            return apply()

        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(apply)
            self.assertTrue(runner.apply_entered.wait(timeout=1))
            second = pool.submit(apply_second)
            self.assertTrue(second_started.wait(timeout=1))
            time.sleep(0.05)
            self.assertFalse(second.done())
            runner.release_apply.set()
            first_result = first.result(timeout=2)
            second_result = second.result(timeout=2)

        self.assertFalse(first_result["replayed"])
        self.assertTrue(second_result["replayed"])
        self.assertEqual(
            1,
            sum(
                operation == "intent_codememory_apply" for _, operation in runner.calls
            ),
        )


if __name__ == "__main__":
    unittest.main()
