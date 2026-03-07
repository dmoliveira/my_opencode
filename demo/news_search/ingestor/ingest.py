#!/usr/bin/env python3

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_service_mod = importlib.import_module("demo.news_search.backend.search_service")
connect_db = _service_mod.connect_db
replace_all_news = _service_mod.replace_all_news


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load fake news docs into demo SQLite search index"
    )
    parser.add_argument(
        "--input",
        default="demo/news_search/data/news_seed.json",
        help="Path to seed JSON list",
    )
    parser.add_argument(
        "--output",
        default="demo/news_search/runtime/news.db",
        help="Destination SQLite file",
    )
    return parser.parse_args()


def load_docs(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as handle:
        docs = json.load(handle)
    if not isinstance(docs, list):
        raise ValueError("input must be a JSON list")
    required = {"id", "title", "body", "topic", "source", "published_at", "url"}
    for index, item in enumerate(docs):
        if not isinstance(item, dict):
            raise ValueError(f"item {index} is not an object")
        missing = required - set(item)
        if missing:
            raise ValueError(
                f"item {index} missing fields: {', '.join(sorted(missing))}"
            )
    return docs


def main() -> int:
    args = parse_args()
    input_path = Path(args.input)
    output_path = Path(args.output)
    if not input_path.exists():
        print(f"error: input file not found: {input_path}")
        return 2

    output_path.parent.mkdir(parents=True, exist_ok=True)
    docs = load_docs(input_path)
    with connect_db(str(output_path)) as conn:
        count = replace_all_news(conn, docs)

    print(f"ingested_docs: {count}")
    print(f"db: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
