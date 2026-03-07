#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib
import json
import sys
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


_service_mod = importlib.import_module("demo.news_search.backend.search_service")
connect_db = _service_mod.connect_db
fetch_topics = _service_mod.fetch_topics
search_news = _service_mod.search_news


class NewsSearchHandler(BaseHTTPRequestHandler):
    db_path: str = "demo/news_search/runtime/news.db"
    allow_origin: str = "*"

    def _send_json(self, payload: dict, status: int = HTTPStatus.OK) -> None:
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Access-Control-Allow-Origin", self.allow_origin)
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.end_headers()
        self.wfile.write(data)

    def do_OPTIONS(self) -> None:  # noqa: N802
        self._send_json({"ok": True}, HTTPStatus.NO_CONTENT)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/health":
            self._send_json({"status": "ok", "service": "news-search-api"})
            return

        if parsed.path == "/api/topics":
            with connect_db(self.db_path) as conn:
                topics = fetch_topics(conn)
            self._send_json({"topics": topics})
            return

        if parsed.path == "/api/search":
            params = parse_qs(parsed.query)
            query = params.get("q", [""])[0].strip()
            topic = params.get("topic", [""])[0].strip() or None
            try:
                limit = int(params.get("limit", ["12"])[0])
            except ValueError:
                limit = 12

            with connect_db(self.db_path) as conn:
                results = search_news(conn, query=query, topic=topic, limit=limit)
                topics = fetch_topics(conn)

            self._send_json(
                {
                    "query": query,
                    "topic": topic,
                    "count": len(results),
                    "results": results,
                    "topics": topics,
                }
            )
            return

        self._send_json(
            {
                "error": "not_found",
                "message": f"Route '{parsed.path}' is not available",
            },
            status=HTTPStatus.NOT_FOUND,
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run local API for fake news search demo"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind")
    parser.add_argument("--port", type=int, default=8000, help="Port to bind")
    parser.add_argument(
        "--db-path",
        default="demo/news_search/runtime/news.db",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--allow-origin",
        default="*",
        help="Access-Control-Allow-Origin response header",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    db_path = Path(args.db_path)
    if not db_path.exists():
        print(f"error: db path not found: {db_path}")
        print(
            "hint: run python3 demo/news_search/ingestor/ingest.py "
            "--output demo/news_search/runtime/news.db"
        )
        return 2

    NewsSearchHandler.db_path = str(db_path)
    NewsSearchHandler.allow_origin = args.allow_origin
    server = ThreadingHTTPServer((args.host, args.port), NewsSearchHandler)
    print(f"news-search-api listening on http://{args.host}:{args.port}")
    print(f"db: {db_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
