"""Tiny storage layer: SQLite locally, Postgres when DATABASE_URL is set (Render)."""
from __future__ import annotations

import os
import sqlite3
import threading
from contextlib import contextmanager
from typing import Any, Iterator

DATABASE_URL = os.environ.get("DATABASE_URL", "").strip()
SQLITE_PATH = os.environ.get("SQLITE_PATH", os.path.join(os.path.dirname(os.path.dirname(__file__)), "var", "wizard.db"))
IS_PG = DATABASE_URL.startswith("postgres")

_lock = threading.Lock()

SCHEMA_SQLITE = """
CREATE TABLE IF NOT EXISTS invites (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  token TEXT UNIQUE NOT NULL,
  prospect_name TEXT, prospect_email TEXT, practice_name TEXT,
  rep_name TEXT, rep_email TEXT,
  created_at TEXT NOT NULL, expires_at TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'not_started',
  current_step INTEGER NOT NULL DEFAULT 0,
  answers_json TEXT NOT NULL DEFAULT '{}',
  tin_enc TEXT,
  opened_at TEXT, last_activity_at TEXT, submitted_at TEXT,
  revoked INTEGER NOT NULL DEFAULT 0,
  is_test INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  invite_id INTEGER, at TEXT NOT NULL, kind TEXT NOT NULL, detail TEXT
);
"""
SCHEMA_PG = SCHEMA_SQLITE.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "SERIAL PRIMARY KEY")


def _connect():
    if IS_PG:
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(DATABASE_URL, row_factory=dict_row, autocommit=False)
    os.makedirs(os.path.dirname(SQLITE_PATH), exist_ok=True)
    conn = sqlite3.connect(SQLITE_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


@contextmanager
def tx() -> Iterator[Any]:
    with _lock:
        conn = _connect()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()


def _q(sql: str) -> str:
    return sql.replace("?", "%s") if IS_PG else sql


def init() -> None:
    with tx() as conn:
        for stmt in (SCHEMA_PG if IS_PG else SCHEMA_SQLITE).split(";"):
            if stmt.strip():
                conn.execute(stmt)


def query(sql: str, params: tuple = ()) -> list[dict]:
    with tx() as conn:
        cur = conn.execute(_q(sql), params)
        rows = cur.fetchall() if cur.description else []
        return [dict(r) for r in rows]


def one(sql: str, params: tuple = ()) -> dict | None:
    rows = query(sql, params)
    return rows[0] if rows else None


def execute(sql: str, params: tuple = ()) -> int | None:
    with tx() as conn:
        if IS_PG and sql.lstrip().upper().startswith("INSERT"):
            cur = conn.execute(_q(sql) + " RETURNING id", params)
            return cur.fetchone()["id"]
        cur = conn.execute(_q(sql), params)
        return getattr(cur, "lastrowid", None)
