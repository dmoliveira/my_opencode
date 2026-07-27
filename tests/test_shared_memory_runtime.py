from __future__ import annotations

import importlib
import sys
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


class SharedMemoryTimestampTest(unittest.TestCase):
    def _module(self):
        return importlib.reload(importlib.import_module("shared_memory_runtime"))

    def test_naive_timestamp_is_utc_aware_and_scoreable(self) -> None:
        module = self._module()
        naive = datetime.now(UTC).replace(tzinfo=None, microsecond=0).isoformat()
        parsed = module._parse_iso(naive)
        self.assertIsNotNone(parsed)
        self.assertEqual(UTC, parsed.tzinfo)

        record = module.MemoryRecord(
            memory_id="memory-naive-time",
            kind="note",
            scope="repo",
            namespace="repo",
            title="timestamp compatibility",
            content="legacy timestamp",
            summary="legacy",
            tags=[],
            links=[],
            source_type=None,
            source_ref=None,
            session_id=None,
            cwd="/repo",
            pinned=False,
            archived=False,
            confidence=60,
            created_at=naive,
            updated_at=naive,
        )
        score, reasons = module._score_record(record, lexical_score=None)
        self.assertGreater(score, 0)
        self.assertTrue(any(reason.startswith("recency=") for reason in reasons))

    def test_queries_order_mixed_offsets_chronologically_before_limit(self) -> None:
        module = self._module()
        with tempfile.TemporaryDirectory() as tmp:
            connection = module.connect(Path(tmp) / "shared-memory.db")
            try:
                rows = [
                    (
                        "earlier-offset",
                        "2026-07-27T01:00:00+02:00",
                    ),
                    (
                        "later-utc",
                        "2026-07-26T23:30:00+00:00",
                    ),
                ]
                for memory_id, timestamp in rows:
                    connection.execute(
                        """
                        INSERT INTO memories(
                            id, kind, scope, namespace, title, content, summary,
                            tags_json, tags_text, links_json, source_type, source_ref,
                            session_id, cwd, pinned, archived, confidence, created_at, updated_at
                        ) VALUES (?, 'note', 'repo', 'repo', 'shared query', 'shared query',
                                  'shared query', '[]', '', '[]', NULL, NULL, NULL, '/repo',
                                  0, 0, 60, ?, ?)
                        """,
                        (memory_id, timestamp, timestamp),
                    )
                connection.commit()

                self.assertEqual(
                    "later-utc",
                    module.active_memory_records(connection)[0].memory_id,
                )
                self.assertEqual(
                    "later-utc",
                    module.recall_memories(connection, limit=1)[0].memory_id,
                )
                self.assertEqual(
                    "later-utc",
                    module._find_memories_like(
                        connection,
                        query="shared query",
                        limit=1,
                        scope=None,
                        namespace=None,
                    )[0].memory_id,
                )
                if module.fts_enabled(connection):
                    module._rebuild_fts(connection)
                    connection.commit()
                    self.assertEqual(
                        "later-utc",
                        module.find_memories(
                            connection,
                            query="shared query",
                            limit=1,
                        )[0].memory_id,
                    )
            finally:
                connection.close()

    def test_aware_timestamp_preserves_its_offset(self) -> None:
        module = self._module()
        value = "2026-07-27T10:00:00+10:00"
        parsed = module._parse_iso(value)
        self.assertIsNotNone(parsed)
        self.assertEqual(datetime.fromisoformat(value).utcoffset(), parsed.utcoffset())


if __name__ == "__main__":
    unittest.main()
