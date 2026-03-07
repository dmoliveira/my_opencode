from __future__ import annotations

import tempfile
import unittest
import importlib
from pathlib import Path

_service_mod = importlib.import_module("demo.news_search.backend.search_service")
connect_db = _service_mod.connect_db
replace_all_news = _service_mod.replace_all_news
search_news = _service_mod.search_news


SAMPLE_DOCS = [
    {
        "id": "a",
        "title": "Electric bus launches downtown",
        "body": "Transit authority started electric bus service.",
        "topic": "Transit",
        "source": "Metro",
        "published_at": "2026-03-07T10:00:00Z",
        "url": "https://example.local/a",
    },
    {
        "id": "b",
        "title": "Solar co-op funding approved",
        "body": "Neighborhoods can apply for rooftop solar grants.",
        "topic": "Energy",
        "source": "Civic",
        "published_at": "2026-03-07T09:30:00Z",
        "url": "https://example.local/b",
    },
]


class SearchServiceTest(unittest.TestCase):
    def test_keyword_and_topic_filter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "test.db"
            with connect_db(str(db_path)) as conn:
                replace_all_news(conn, SAMPLE_DOCS)
                by_keyword = search_news(conn, query="electric", topic=None, limit=10)
                self.assertEqual(1, len(by_keyword))
                self.assertEqual("a", by_keyword[0]["id"])

                by_topic = search_news(conn, query="", topic="Energy", limit=10)
                self.assertEqual(1, len(by_topic))
                self.assertEqual("b", by_topic[0]["id"])


if __name__ == "__main__":
    unittest.main()
