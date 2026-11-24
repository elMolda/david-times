"""A tiny SQLite key-value cache for fetches, extractions and LLM outputs."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any


def hash_key(*parts: Any) -> str:
    raw = json.dumps(parts, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class Cache:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.execute(
            "CREATE TABLE IF NOT EXISTS kv (ns TEXT, key TEXT, value TEXT,"
            " created TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY (ns, key))"
        )

    def get(self, ns: str, key: str) -> Any | None:
        row = self.db.execute(
            "SELECT value FROM kv WHERE ns = ? AND key = ?", (ns, key)
        ).fetchone()
        return json.loads(row[0]) if row else None

    def set(self, ns: str, key: str, value: Any) -> None:
        self.db.execute(
            "INSERT OR REPLACE INTO kv (ns, key, value) VALUES (?, ?, ?)",
            (ns, key, json.dumps(value, ensure_ascii=False, default=str)),
        )
        self.db.commit()
