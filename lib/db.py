"""SQLite への接続と初期化をまとめたヘルパー。"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = BASE_DIR / "data"
DB_PATH = DATA_DIR / "dashboard.db"
SCHEMA_PATH = BASE_DIR / "db" / "schema.sql"


def get_connection() -> sqlite3.Connection:
    """DB に接続する。data フォルダが無ければ作る。"""
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    """schema.sql を流してテーブルを用意する（何度実行してもOK）。"""
    conn = get_connection()
    try:
        conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        conn.commit()
    finally:
        conn.close()


def log_sync(source: str, status: str, rows: int, message: str = "",
             started_at: str | None = None) -> None:
    """同期結果を sync_log に1行残す。"""
    now = datetime.now(timezone.utc).isoformat()
    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO sync_log (source, started_at, finished_at, status, "
            "rows_upserted, message) VALUES (?, ?, ?, ?, ?, ?)",
            (source, started_at or now, now, status, rows, message),
        )
        conn.commit()
    finally:
        conn.close()
