from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from checkpoint_snapshot_manager import (
    list_snapshots,
    runtime_run_id,
    show_snapshot,
    write_snapshot,
)


class CheckpointSnapshotSelectionTest(unittest.TestCase):
    def test_active_run_selection_is_independent_of_same_second_ties(self) -> None:
        with tempfile.TemporaryDirectory() as raw_tmp:
            config = Path(raw_tmp) / "opencode.json"
            previous = {
                "status": "failed",
                "started_at": "2026-11-03T00:00:00Z",
                "plan": {"metadata": {"id": "previous"}},
            }
            active = {
                "status": "completed",
                "started_at": "2026-11-03T00:00:00Z",
                "plan": {"metadata": {"id": "active"}},
            }
            with patch(
                "checkpoint_snapshot_manager.now_iso",
                return_value="2026-11-03T00:00:01Z",
            ):
                self.assertEqual(
                    "PASS", write_snapshot(config, previous, source="test")["result"]
                )
                self.assertEqual(
                    "PASS", write_snapshot(config, active, source="test")["result"]
                )
            self.assertEqual(2, len(list_snapshots(config)))
            run_id = runtime_run_id(active)
            selected = list_snapshots(config, run_id)
            self.assertEqual([run_id], [item["run_id"] for item in selected])
            self.assertEqual(
                "completed",
                show_snapshot(config, run_id, "latest")["snapshot"]["status"],
            )


if __name__ == "__main__":
    unittest.main()
