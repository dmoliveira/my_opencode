#!/usr/bin/env python3

from __future__ import annotations

import sqlite3
from typing import Any


DEFAULT_DB_PATH = "demo/news_search/runtime/news.db"


def connect_db(db_path: str = DEFAULT_DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS news (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            topic TEXT NOT NULL,
            source TEXT NOT NULL,
            published_at TEXT NOT NULL,
            url TEXT NOT NULL
        );

        CREATE VIRTUAL TABLE IF NOT EXISTS news_fts USING fts5(
            id UNINDEXED,
            title,
            body,
            topic
        );
        """
    )
    conn.commit()


def replace_all_news(conn: sqlite3.Connection, docs: list[dict[str, Any]]) -> int:
    ensure_schema(conn)
    conn.execute("DELETE FROM news")
    conn.execute("DELETE FROM news_fts")

    for item in docs:
        conn.execute(
            """
            INSERT INTO news (id, title, body, topic, source, published_at, url)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                item["id"],
                item["title"],
                item["body"],
                item["topic"],
                item["source"],
                item["published_at"],
                item["url"],
            ),
        )
        conn.execute(
            "INSERT INTO news_fts (id, title, body, topic) VALUES (?, ?, ?, ?)",
            (item["id"], item["title"], item["body"], item["topic"]),
        )

    conn.commit()
    return len(docs)


def fetch_topics(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT topic FROM news GROUP BY topic ORDER BY topic"
    ).fetchall()
    return [str(row["topic"]) for row in rows]


def _match_query(raw_query: str) -> str:
    parts = [part.strip() for part in raw_query.split() if part.strip()]
    if not parts:
        return ""
    escaped = []
    for token in parts:
        cleaned = "".join(ch for ch in token if ch.isalnum() or ch in ("-", "_"))
        if cleaned:
            escaped.append(f'"{cleaned}"')
    return " AND ".join(escaped)


def search_news(
    conn: sqlite3.Connection,
    query: str,
    topic: str | None,
    limit: int,
) -> list[dict[str, Any]]:
    capped_limit = max(1, min(limit, 50))
    topic_clause = ""
    params: list[Any] = []
    if topic:
        topic_clause = " AND n.topic = ?"
        params.append(topic)

    match = _match_query(query)
    if not match:
        rows = conn.execute(
            f"""
            SELECT n.id, n.title, n.body, n.topic, n.source, n.published_at, n.url
            FROM news AS n
            WHERE 1=1 {topic_clause}
            ORDER BY n.published_at DESC
            LIMIT ?
            """,
            [*params, capped_limit],
        ).fetchall()
    else:
        rows = conn.execute(
            f"""
            SELECT
                n.id,
                n.title,
                n.body,
                n.topic,
                n.source,
                n.published_at,
                n.url,
                bm25(news_fts) AS score
            FROM news_fts
            JOIN news AS n ON n.id = news_fts.id
            WHERE news_fts MATCH ? {topic_clause}
            ORDER BY score, n.published_at DESC
            LIMIT ?
            """,
            [match, *params, capped_limit],
        ).fetchall()

    return [
        {
            "id": row["id"],
            "title": row["title"],
            "body": row["body"],
            "topic": row["topic"],
            "source": row["source"],
            "published_at": row["published_at"],
            "url": row["url"],
            "preview": str(row["body"])[:180]
            + ("..." if len(str(row["body"])) > 180 else ""),
        }
        for row in rows
    ]
