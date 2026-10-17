"""SQLite schema for assets, media, events, findings, tasks, inspections, receipts and audit."""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from pathlib import Path

SCHEMA = """
PRAGMA journal_mode=WAL;
CREATE TABLE IF NOT EXISTS media(sha256 TEXT PRIMARY KEY, media_type TEXT NOT NULL, size INTEGER NOT NULL, dhash TEXT,
  captured_at TEXT, lat REAL, lon REAL, content BLOB NOT NULL, received_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, project TEXT NOT NULL, description TEXT NOT NULL, asset_id TEXT,
  asset_method TEXT, reported_risk TEXT NOT NULL, text_risk TEXT NOT NULL, vision_risk TEXT, final_risk TEXT NOT NULL,
  signals TEXT NOT NULL, stop_work INTEGER NOT NULL, status TEXT NOT NULL, reporter TEXT NOT NULL, lat REAL, lon REAL,
  response_due TEXT NOT NULL, close_due TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL, closed_at TEXT);
CREATE TABLE IF NOT EXISTS event_media(event_id TEXT NOT NULL, sha256 TEXT NOT NULL, role TEXT NOT NULL, added_by TEXT NOT NULL,
  added_at TEXT NOT NULL, PRIMARY KEY(event_id, sha256, role));
CREATE TABLE IF NOT EXISTS findings(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL, agent_id TEXT NOT NULL,
  status TEXT NOT NULL, claim TEXT NOT NULL, evidence_refs TEXT NOT NULL, confidence REAL NOT NULL, questions TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, event_id TEXT NOT NULL, title TEXT NOT NULL, owner_role TEXT NOT NULL,
  source TEXT NOT NULL, evidence_refs TEXT NOT NULL, status TEXT NOT NULL, due_at TEXT NOT NULL, done_by TEXT, done_at TEXT, note TEXT);
CREATE TABLE IF NOT EXISTS receipts(id TEXT PRIMARY KEY, event_id TEXT NOT NULL, kind TEXT NOT NULL, status TEXT NOT NULL,
  digest TEXT NOT NULL, payload TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS audit(id INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT, actor TEXT NOT NULL, action TEXT NOT NULL,
  detail TEXT NOT NULL, created_at TEXT NOT NULL);
"""


class Store:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path or os.getenv("INFRAPILOT_DB", "./data/infrapilot.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.tx() as c:
            c.executescript(SCHEMA)

    @contextmanager
    def tx(self):
        conn = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def rows(self, sql: str, args: tuple = ()) -> list[dict]:
        with self.tx() as c:
            return [dict(r) for r in c.execute(sql, args)]

    def one(self, sql: str, args: tuple = ()) -> dict | None:
        found = self.rows(sql, args)
        return found[0] if found else None
