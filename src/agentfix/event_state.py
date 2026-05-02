from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class EventStateStore:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def claim(self, event_key: str) -> bool:
        now = self._now()
        with self._connect() as connection:
            try:
                connection.execute(
                    """
                    INSERT INTO events(event_key, status, result_json, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (event_key, "processing", "{}", now, now),
                )
                return True
            except sqlite3.IntegrityError:
                return False

    def complete(self, event_key: str, status: str, result: dict[str, Any]) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE events
                SET status = ?, result_json = ?, updated_at = ?
                WHERE event_key = ?
                """,
                (status, json.dumps(result, ensure_ascii=False), self._now(), event_key),
            )

    def get(self, event_key: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT event_key, status, result_json, created_at, updated_at FROM events WHERE event_key = ?",
                (event_key,),
            ).fetchone()
        if row is None:
            return None
        result = json.loads(row[2] or "{}")
        return {
            "event_key": row[0],
            "status": row[1],
            "result": result,
            "created_at": row[3],
            "updated_at": row[4],
        }

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS events (
                    event_key TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    result_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
