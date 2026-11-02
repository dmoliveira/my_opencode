from __future__ import annotations

import copy
import hashlib
import io
import json
import os
import signal
import sys
import tempfile
import threading
import time
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import intent_coordinator_command as coordinator
import intent_planner as planner


class IntentPlannerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "design.md").write_text(
            "Build bounded intake.\nCoordinator owns graph writes.\n"
        )
        self.request = {
            "version": 1,
            "proposal_id": "request-1",
            "scope": "example/repo",
            "source": {
                "kind": "user",
                "id": "msg-1",
                "summary": "Build safe intake",
                "session_id": "ses-1",
                "content_sha256": hashlib.sha256(b"user intent").hexdigest(),
            },
            "research": [
                {"id": "design", "path": "design.md", "start_line": 1, "end_line": 2}
            ],
        }

    def research(self, request=None, ingress=None):
        return planner.research(
            request or self.request, self.root, planner.Budget(), ingress
        )

    def draft(self, ingress=None):
        proposal = {
            key: copy.deepcopy(self.request[key])
            for key in ("version", "proposal_id", "scope", "source")
        }
        proposal.update(
            records=[
                {
                    "key": "task:intake",
                    "entity_type": "task",
                    "title": "Implement safe intake",
                    "goal": "Research without graph authority",
                    "summary": "Collect evidence and return typed proposals",
                }
            ],
            links=[],
        )
        return {
            "version": 1,
            "research": self.research(ingress=ingress),
            "proposal": proposal,
            "assessments": [
                {
                    "target": "record:task:intake",
                    "evidence": ["design", "source"],
                    "rationale": "The user requested bounded intake",
                    "acceptance": "Rejected inputs cause no writes",
                }
            ],
            "unresolved": [],
        }

    def plan(self, draft=None, ingress=None):
        return planner.plan(
            draft or self.draft(ingress), self.root, planner.Budget(), ingress
        )

    def envelope(self):
        project = planner.ingress_digest(["intent-ingress-project-v1", str(self.root)])[
            :32
        ]
        identity = planner.ingress_digest(
            ["intent-ingress-envelope-v1", project, "ses-1", "msg-1"]
        )[:32]
        return {
            "version": 1,
            "envelope_id": "intent_ingress_" + identity,
            "project_digest": project,
            "observed_at": "2026-11-03T00:00:00.000Z",
            "source": {"kind": "user", "session_id": "ses-1", "message_id": "msg-1"},
            "content": {
                "mode": "metadata",
                "char_count": 11,
                "sha256": self.request["source"]["content_sha256"],
            },
        }

    def test_research_synthesized_plan_is_deterministic_and_coordinator_compatible(
        self,
    ):
        draft = self.draft()
        first = self.plan(draft)
        self.assertEqual(first, self.plan(draft))
        self.assertEqual(first["authority"], "proposal-only")
        self.assertEqual(
            first["proposal"], coordinator.normalize_proposal(first["proposal"])
        )
        self.assertEqual(
            first["proposal_sha256"],
            coordinator.proposal_fingerprint(first["proposal"]),
        )
        self.assertNotIn("excerpt", first["evidence"][0])
        self.assertEqual(
            self.research()["evidence"][0]["file_sha256"],
            hashlib.sha256((self.root / "design.md").read_bytes()).hexdigest(),
        )

    def test_no_coordinator_runner_or_state_store_is_reached(self):
        draft = self.draft()
        with (
            patch.object(
                coordinator,
                "make_oc_runner",
                side_effect=AssertionError("runner reached"),
            ),
            patch.object(
                coordinator,
                "apply_proposal",
                side_effect=AssertionError("write reached"),
            ),
        ):
            path = self.root / "draft.json"
            path.write_text(json.dumps(draft))
            with redirect_stdout(io.StringIO()) as output:
                self.assertEqual(
                    coordinator.main(
                        ["plan", "--file", str(path), "--root", str(self.root)]
                    ),
                    0,
                )
            report = json.loads(output.getvalue())
            self.assertEqual(report["artifact"]["type"], "intent_plan")
        self.assertEqual(
            {p.name for p in self.root.iterdir()}, {"design.md", "draft.json"}
        )

    def test_stale_or_forged_research_fails(self):
        for field, value in (
            ("excerpt", "forged"),
            ("file_sha256", "0" * 64),
            ("byte_count", 1),
        ):
            with self.subTest(field=field):
                draft = self.draft()
                draft["research"]["evidence"][0][field] = value
                with self.assertRaisesRegex(
                    coordinator.CoordinatorError, "research packet changed"
                ):
                    self.plan(draft)
        draft = self.draft()
        (self.root / "design.md").write_text("changed\nsecond line\n")
        with self.assertRaisesRegex(
            coordinator.CoordinatorError, "research packet changed"
        ):
            self.plan(draft)

    def test_source_scope_and_proposal_identity_are_bound(self):
        for key, value in (
            ("source", {"kind": "agent", "id": "other", "summary": "Other"}),
            ("scope", "other/repo"),
            ("proposal_id", "other"),
        ):
            draft = self.draft()
            draft["proposal"][key] = value
            with self.assertRaisesRegex(
                coordinator.CoordinatorError, "preserve research"
            ):
                self.plan(draft)

    def test_ingress_binding_is_read_only_and_discards_preview(self):
        envelope = self.envelope()
        envelope["content"].update(
            mode="redacted_preview",
            preview="PRIVATE PREVIEW",
            truncated=False,
            redacted_fields=0,
        )
        result = self.plan(ingress=envelope)
        self.assertEqual(result["ingress"]["envelope_id"], envelope["envelope_id"])
        self.assertNotIn("PRIVATE PREVIEW", json.dumps(result))
        self.assertEqual(envelope["content"]["preview"], "PRIVATE PREVIEW")
        draft = self.draft(envelope)
        with self.assertRaisesRegex(
            coordinator.CoordinatorError, "research packet changed"
        ):
            self.plan(draft)  # bound ingress cannot silently be omitted

    def test_ingress_conflicts_and_malformed_envelopes_fail(self):
        for key, value in (
            ("envelope_id", "wrong"),
            ("project_digest", "0" * 32),
            ("observed_at", "invalid"),
            ("observed_at", "2026-11-03T00:00:00.000"),
            ("observed_at", "2026-11-03T00:00:00.000+11:00"),
            ("observed_at", "2026-11-03T00:00:00.000+00:00"),
            ("observed_at", "2026-11-03T00:00:00.000000000000000Z"),
            ("observed_at", "2026-02-30T00:00:00.000Z"),
        ):
            envelope = self.envelope()
            envelope[key] = value
            with self.assertRaises(coordinator.CoordinatorError):
                self.research(ingress=envelope)
        for key, value in (
            ("message_id", "other"),
            ("session_id", "other"),
            ("kind", "agent"),
        ):
            envelope = self.envelope()
            envelope["source"][key] = value
            with self.assertRaises(coordinator.CoordinatorError):
                self.research(ingress=envelope)
        for key, value in (
            ("char_count", True),
            ("sha256", "0" * 64),
            ("mode", "raw"),
            ("preview", "forbidden metadata"),
        ):
            envelope = self.envelope()
            envelope["content"][key] = value
            with self.assertRaises(coordinator.CoordinatorError):
                self.research(ingress=envelope)

    def test_unsafe_paths_and_ranges_fail_before_collection(self):
        for path in (
            "../outside",
            "/etc/passwd",
            "a/../b",
            "a//b",
            "./design.md",
            "~/.env",
            "a*",
            "a\\b",
            "https://example.com",
        ):
            request = copy.deepcopy(self.request)
            request["research"][0]["path"] = path
            with (
                self.subTest(path=path),
                patch.object(
                    planner,
                    "collect_citation",
                    side_effect=AssertionError("read reached"),
                ),
                self.assertRaises(coordinator.CoordinatorError),
            ):
                self.research(request)
        for start, end in ((0, 1), (2, 1), (True, 1), (1, 101)):
            request = copy.deepcopy(self.request)
            request["research"][0].update(start_line=start, end_line=end)
            with self.assertRaises(coordinator.CoordinatorError):
                self.research(request)

    def test_symlinks_ancestors_directories_and_fifo_are_rejected(self):
        (self.root / "alias").symlink_to(self.root, target_is_directory=True)
        (self.root / "link.md").symlink_to(self.root / "design.md")
        os.mkfifo(self.root / "fifo")
        for path in ("alias/design.md", "link.md", "fifo", "alias"):
            request = copy.deepcopy(self.request)
            request["research"][0]["path"] = path
            with (
                self.subTest(path=path),
                self.assertRaises((coordinator.CoordinatorError, OSError)),
            ):
                self.research(request)

    def test_sparse_oversized_binary_and_out_of_range_files_fail(self):
        with (self.root / "large").open("wb") as handle:
            handle.truncate(planner.MAX_FILE_BYTES + 1)
        (self.root / "binary").write_bytes(b"\xff\xfe")
        (self.root / "long").write_text("x" * (planner.MAX_EXCERPT_BYTES + 1) + "\n")
        for path, end in (("large", 1), ("binary", 1), ("long", 1), ("design.md", 3)):
            request = copy.deepcopy(self.request)
            request["research"][0].update(path=path, end_line=end)
            with (
                self.subTest(path=path),
                self.assertRaises(coordinator.CoordinatorError),
            ):
                self.research(request)

    def test_file_replacement_and_in_place_changes_are_detected(self):
        original_read = os.read
        for replace in (True, False):
            (self.root / "design.md").write_text("original\nline two\n")
            changed = False

            def mutate(fd, size, replace=replace):
                nonlocal changed
                result = original_read(fd, size)
                if not changed:
                    changed = True
                    if replace:
                        (self.root / "next").write_text("replacement\n")
                        (self.root / "next").replace(self.root / "design.md")
                    else:
                        (self.root / "design.md").write_text("mutated\n")
                return result

            with (
                patch.object(planner.os, "read", side_effect=mutate),
                self.assertRaisesRegex(
                    coordinator.CoordinatorError, "changed during research"
                ),
            ):
                self.research()

    def test_fanout_is_bounded_and_completion_order_does_not_change_output(self):
        request = copy.deepcopy(self.request)
        request["research"] = [
            {**request["research"][0], "id": f"item-{i}"} for i in reversed(range(8))
        ]
        active = maximum = 0
        lock = threading.Lock()
        original = planner.collect_citation

        def collect(*args):
            nonlocal active, maximum
            with lock:
                active += 1
                maximum = max(maximum, active)
            try:
                time.sleep(0.005 if args[1]["id"] == "item-0" else 0.001)
                return original(*args)
            finally:
                with lock:
                    active -= 1

        with patch.object(planner, "collect_citation", side_effect=collect):
            result = self.research(request)
        self.assertEqual(maximum, 2)
        self.assertEqual(
            [item["id"] for item in result["evidence"]],
            sorted(item["id"] for item in request["research"]),
        )
        self.assertEqual(result, self.research(request))

    def test_cancel_deadline_and_real_signals_produce_no_partial_artifact(self):
        budget = planner.Budget(0)
        with self.assertRaisesRegex(coordinator.CoordinatorError, "deadline"):
            planner.research(self.request, self.root, budget)
        budget = planner.Budget()
        budget.cancelled.set()
        with self.assertRaisesRegex(coordinator.CoordinatorError, "cancelled"):
            planner.research(self.request, self.root, budget)
        for signum in (signal.SIGINT, signal.SIGTERM):
            budget = planner.Budget()
            previous = signal.getsignal(signum)
            with planner.cancellation(budget):
                os.kill(os.getpid(), signum)
                with self.assertRaisesRegex(coordinator.CoordinatorError, "cancelled"):
                    planner.research(self.request, self.root, budget)
            self.assertEqual(signal.getsignal(signum), previous)

    def test_missing_duplicate_and_orphan_assessments_fail(self):
        for mutate in (
            lambda d: d.update(assessments=[]),
            lambda d: d.update(unresolved=["unknown requirements"]),
            lambda d: d["assessments"][0].update(evidence=["missing"]),
            lambda d: d["assessments"][0].update(evidence=["source"]),
            lambda d: d["assessments"][0].update(evidence=["design", "design"]),
            lambda d: d["assessments"][0].update(acceptance=" "),
            lambda d: d["assessments"][0].update(target="record:task:unknown"),
            lambda d: d["proposal"]["records"][0].pop("goal"),
        ):
            draft = self.draft()
            mutate(draft)
            with self.assertRaises(coordinator.CoordinatorError):
                self.plan(draft)

    def test_links_require_assessments_and_cycles_fail(self):
        draft = self.draft()
        other = {
            **draft["proposal"]["records"][0],
            "key": "task:other",
            "title": "Other task",
        }
        draft["proposal"]["records"].append(other)
        link = {"from": "task:intake", "edge": "depends-on", "to": "task:other"}
        draft["proposal"]["links"].append(link)
        draft["assessments"].append(
            {**draft["assessments"][0], "target": "record:task:other"}
        )
        with self.assertRaisesRegex(
            coordinator.CoordinatorError, "every record and link"
        ):
            self.plan(draft)
        draft["assessments"].append(
            {
                **draft["assessments"][0],
                "target": "link:task:intake|depends-on|task:other",
            }
        )
        self.assertTrue(self.plan(draft)["gates"]["coverage"])
        draft["proposal"]["links"].append(
            {"from": "task:other", "edge": "depends-on", "to": "task:intake"}
        )
        with self.assertRaisesRegex(coordinator.CoordinatorError, "cycle"):
            self.plan(draft)

    def test_duplicate_unknown_oversized_and_deep_json_fail(self):
        path = self.root / "input.json"
        for text in (
            '{"version":1,"version":1}',
            '{"a":NaN}',
            '{"a":"\\ud800"}',
            "[" * 2000 + "0" + "]" * 2000,
        ):
            path.write_text(text)
            with self.assertRaises(coordinator.CoordinatorError):
                planner.load_json(path, planner.Budget())
        path.write_bytes(b"x" * (coordinator.MAX_PROPOSAL_BYTES + 1))
        with self.assertRaises(coordinator.CoordinatorError):
            planner.load_json(path, planner.Budget())
        request = copy.deepcopy(self.request)
        request["raw_prompt"] = "not allowed"
        with self.assertRaises(coordinator.CoordinatorError):
            self.research(request)
        request = copy.deepcopy(self.request)
        request["research"] *= 2
        with self.assertRaises(coordinator.CoordinatorError):
            self.research(request)
        request["research"] *= 8
        with self.assertRaises(coordinator.CoordinatorError):
            self.research(request)

    def test_cli_failure_emits_single_safe_json_without_partial_research(self):
        path = self.root / "request.json"
        request = copy.deepcopy(self.request)
        request["research"][0]["path"] = "missing"
        path.write_text(json.dumps(request))
        args = SimpleNamespace(
            command="research", file=path, root=self.root, ingress_file=None
        )
        report = planner.command_report(args)
        self.assertEqual(report["result"], "FAIL")
        self.assertNotIn("artifact", report)
        self.assertNotIn(str(self.root), json.dumps(report))


if __name__ == "__main__":
    unittest.main()
