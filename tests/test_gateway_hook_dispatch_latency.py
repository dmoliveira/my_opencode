from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import gateway_command  # noqa: E402


def _aggregate(hook: str = "continuation", **overrides: object) -> dict[str, object]:
    bucket_counts = [0] * len(gateway_command.HOOK_DISPATCH_LATENCY_BUCKETS_MS)
    bucket_counts[3] = 100
    record: dict[str, object] = {
        "hook": hook,
        "stage": "aggregate",
        "reason_code": "hook_dispatch_latency_window",
        "event_class": "session",
        "window_ms": 900_000,
        "minimum_samples": 100,
        "sample_count": 100,
        "success_count": 100,
        "failure_count": 0,
        "blocked_count": 0,
        "bucket_upper_bounds_ms": list(
            gateway_command.HOOK_DISPATCH_LATENCY_BUCKETS_MS
        ),
        "bucket_counts": bucket_counts,
        "overflow_count": 0,
        "elapsed_total_ms": 1000,
        "event_class_elapsed_total_ms": 20_000,
        "p50_upper_bound_ms": 10,
        "p50_overflow": False,
        "p95_upper_bound_ms": 10,
        "p95_overflow": False,
        "p99_upper_bound_ms": 10,
        "p99_overflow": False,
        "latency_share_pct": 5.0,
        "optimization_candidate": False,
        "candidate_gate_names": [],
        "window_series_total": 1,
        "window_series_enqueued": 1,
        "window_series_dropped": 0,
        "detached_windows_dropped": 0,
        "audit_batches_rejected": 0,
        "audit_batches_failed": 0,
        "series_samples_dropped": 0,
        "ts": "2026-08-05T00:00:00Z",
        "session_id": "status-session-canary",
        "prompt": "status-prompt-canary",
    }
    record.update(overrides)
    return record


class GatewayHookDispatchLatencyTest(unittest.TestCase):
    def _summary(self, records: list[dict[str, object]]) -> dict[str, object]:
        with tempfile.TemporaryDirectory() as raw_tmp:
            root = Path(raw_tmp)
            audit_path = root / "gateway-events.jsonl"
            audit_path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {
                    "MY_OPENCODE_GATEWAY_EVENT_AUDIT": "1",
                    "MY_OPENCODE_GATEWAY_EVENT_AUDIT_PATH": str(audit_path),
                },
                clear=False,
            ):
                return gateway_command.gateway_hook_dispatch_latency_summary(root)

    def test_status_returns_only_allowlisted_aggregate_fields(self) -> None:
        summary = self._summary([_aggregate()])
        self.assertEqual("active_audit_file", summary["source_scope"])
        self.assertTrue(summary["current_file_audit_enabled"])
        self.assertIsNone(summary["runtime_collector_active"])
        self.assertEqual(1, summary["valid_record_count"])
        self.assertEqual(0, summary["invalid_record_count"])
        self.assertFalse(summary["measurement_incomplete"])
        latest = summary["latest_aggregates"]
        self.assertIsInstance(latest, list)
        self.assertEqual(1, len(latest))
        serialized = json.dumps(latest)
        self.assertNotIn("status-session-canary", serialized)
        self.assertNotIn("status-prompt-canary", serialized)
        self.assertNotIn('"ts"', serialized)

    def test_status_rejects_unknown_hooks_and_broken_invariants(self) -> None:
        malformed = _aggregate()
        malformed["bucket_counts"] = [100]
        summary = self._summary(
            [
                _aggregate(hook="valid-looking-unknown-hook"),
                malformed,
                {"reason_code": "unrelated", "hook": "continuation"},
            ]
        )
        self.assertEqual(0, summary["valid_record_count"])
        self.assertEqual(2, summary["invalid_record_count"])
        self.assertEqual([], summary["latest_aggregates"])

    def test_status_recomputes_candidate_gate_contract(self) -> None:
        candidate_counts = [0] * len(
            gateway_command.HOOK_DISPATCH_LATENCY_BUCKETS_MS
        )
        candidate_counts[8] = 100
        valid_candidate = _aggregate(
            bucket_counts=candidate_counts,
            elapsed_total_ms=50_000,
            event_class_elapsed_total_ms=250_000,
            p50_upper_bound_ms=500,
            p95_upper_bound_ms=500,
            p99_upper_bound_ms=500,
            latency_share_pct=20.0,
            optimization_candidate=True,
            candidate_gate_names=["p50", "p95", "p99"],
        )
        invalid_candidate = dict(valid_candidate)
        invalid_candidate["optimization_candidate"] = False
        inconsistent_percentile = _aggregate(p99_upper_bound_ms=500)
        summary = self._summary(
            [valid_candidate, invalid_candidate, inconsistent_percentile]
        )
        self.assertEqual(1, summary["valid_record_count"])
        self.assertEqual(2, summary["invalid_record_count"])
        self.assertTrue(summary["latest_aggregates"][0]["optimization_candidate"])

    def test_status_marks_every_aggregate_loss_source_incomplete(self) -> None:
        records = [
            _aggregate(
                hook="continuation",
                window_series_total=2,
                window_series_dropped=1,
            ),
            _aggregate(hook="task-resume-info", detached_windows_dropped=1),
            _aggregate(hook="session-recovery", audit_batches_rejected=1),
            _aggregate(hook="notify-events", audit_batches_failed=1),
            _aggregate(hook="long-turn-watchdog", series_samples_dropped=1),
        ]
        summary = self._summary(records)
        self.assertEqual(5, summary["valid_record_count"])
        self.assertTrue(summary["measurement_incomplete"])

    def test_status_deduplicates_before_deterministic_cap(self) -> None:
        hook_ids = sorted(gateway_command.load_gateway_hook_ids())[:51]
        records = [_aggregate(hook=hook_id) for hook_id in hook_ids]
        records.append(
            _aggregate(hook=hook_ids[0], success_count=99, blocked_count=1)
        )
        summary = self._summary(records)
        self.assertEqual(52, summary["valid_record_count"])
        self.assertEqual(51, summary["series_total"])
        self.assertEqual(50, summary["series_returned"])
        self.assertTrue(summary["truncated"])
        latest = summary["latest_aggregates"]
        selected = next(item for item in latest if item["hook"] == hook_ids[0])
        self.assertEqual(1, selected["blocked_count"])

    def test_missing_manifest_fails_closed(self) -> None:
        with patch.object(
            gateway_command, "load_gateway_hook_ids", return_value=frozenset()
        ):
            summary = self._summary([_aggregate()])
        self.assertFalse(summary["hook_manifest_available"])
        self.assertEqual(1, summary["invalid_record_count"])
        self.assertEqual([], summary["latest_aggregates"])


if __name__ == "__main__":
    unittest.main()
