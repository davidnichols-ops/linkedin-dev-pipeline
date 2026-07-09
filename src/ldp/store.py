"""SQLite state store: event dedup + draft history."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .models import Draft, Event

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    source TEXT NOT NULL,
    repo TEXT NOT NULL,
    number INTEGER,
    actor TEXT,
    title TEXT,
    url TEXT,
    body TEXT,
    payload_json TEXT,
    created_at TEXT,
    seen_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_events_seen ON events(seen_at);
CREATE INDEX IF NOT EXISTS idx_events_kind ON events(kind);

CREATE TABLE IF NOT EXISTS drafts (
    id TEXT PRIMARY KEY,
    event_ids_json TEXT NOT NULL,
    category TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'draft'
);
CREATE INDEX IF NOT EXISTS idx_drafts_status ON drafts(status);

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""


class Store:
    def __init__(self, db_path: str | Path):
        self.path = Path(db_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> Store:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ---- events ----
    def upsert_event(self, ev: Event) -> bool:
        """Insert event if new. Returns True if it was newly inserted."""
        now = datetime.now(timezone.utc).isoformat()
        cur = self._conn.execute(
            "INSERT OR IGNORE INTO events "
            "(id, kind, source, repo, number, actor, title, url, body, payload_json, created_at, seen_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (*ev.to_db()[:11], now),
        )
        self._conn.commit()
        return cur.rowcount > 0

    def has_event(self, event_id: str) -> bool:
        cur = self._conn.execute("SELECT 1 FROM events WHERE id=?", (event_id,))
        return cur.fetchone() is not None

    def recent_events(self, limit: int = 50, kind: str | None = None) -> list[Event]:
        if kind:
            cur = self._conn.execute(
                "SELECT id, kind, source, repo, number, actor, title, url, body, payload_json, created_at, seen_at "
                "FROM events WHERE kind=? ORDER BY seen_at DESC LIMIT ?",
                (kind, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT id, kind, source, repo, number, actor, title, url, body, payload_json, created_at, seen_at "
                "FROM events ORDER BY seen_at DESC LIMIT ?",
                (limit,),
            )
        rows = cur.fetchall()
        return [self._row_to_event(r) for r in rows]

    def draftable_events(self, limit: int = 30) -> list[Event]:
        """Recent substantive events, excluding noise (push/starred/forked)."""
        noise = ("push", "starred", "forked")
        placeholders = ",".join("?" * len(noise))
        cur = self._conn.execute(
            "SELECT id, kind, source, repo, number, actor, title, url, body, payload_json, created_at, seen_at "
            f"FROM events WHERE kind NOT IN ({placeholders}) "
            "ORDER BY seen_at DESC LIMIT ?",
            (*noise, limit),
        )
        return [self._row_to_event(r) for r in cur.fetchall()]

    def _row_to_event(self, row: tuple) -> Event:
        import json

        (
            id_,
            kind,
            source,
            repo,
            number,
            actor,
            title,
            url,
            body,
            payload_json,
            created_at,
            seen_at,
        ) = row
        return Event(
            id=id_,
            kind=kind,
            source=source,
            repo=repo,
            number=number,
            actor=actor,
            title=title,
            url=url,
            body=body,
            payload=json.loads(payload_json) if payload_json else {},
            created_at=datetime.fromisoformat(created_at) if created_at else None,
            seen_at=datetime.fromisoformat(seen_at) if seen_at else None,
        )

    # ---- drafts ----
    def save_draft(self, d: Draft) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO drafts (id, event_ids_json, category, body, created_at, status) "
            "VALUES (?,?,?,?,?,?)",
            d.to_db(),
        )
        self._conn.commit()

    def list_drafts(self, status: str | None = None, limit: int = 50) -> list[Draft]:
        if status:
            cur = self._conn.execute(
                "SELECT id, event_ids_json, category, body, created_at, status "
                "FROM drafts WHERE status=? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        else:
            cur = self._conn.execute(
                "SELECT id, event_ids_json, category, body, created_at, status "
                "FROM drafts ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        return [Draft.from_db(r) for r in cur.fetchall()]

    def update_draft_status(self, draft_id: str, status: str) -> None:
        self._conn.execute("UPDATE drafts SET status=? WHERE id=?", (status, draft_id))
        self._conn.commit()

    # ---- meta ----
    def get_meta(self, key: str, default: str | None = None) -> str | None:
        cur = self._conn.execute("SELECT value FROM meta WHERE key=?", (key,))
        row = cur.fetchone()
        return row[0] if row else default

    def set_meta(self, key: str, value: str) -> None:
        self._conn.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?,?)", (key, value))
        self._conn.commit()
