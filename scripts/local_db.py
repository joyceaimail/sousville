"""SousVille — 本機 SQLite 鏡像層。

所有 admin 操作都先打 Supabase（cloud 為 source of truth），成功後同步寫進
本機 SQLite。背景排程每小時 pull 一次補齊使用者端寫的東西。

Schema 跟 Supabase migrations/0001 + 0002 一致；額外多一個 ``_sync_meta`` 表
記錄每張表的 incremental cursor。
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

logger = logging.getLogger(__name__)


# ─── 路徑 ──────────────────────────────────────────────────

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = PROJECT_ROOT / "data" / "sousville.db"


def get_db_path() -> Path:
    """允許 SOUSVILLE_LOCAL_DB 環境變數 override（測試 / CI 用）。"""
    override = os.environ.get("SOUSVILLE_LOCAL_DB")
    if override:
        return Path(override).expanduser().resolve()
    return DEFAULT_DB_PATH


# ─── Schema ────────────────────────────────────────────────

# 同步的 table 順序很重要：foreign-key 父表先建（users 在 daily_logs 之前等）
SYNCED_TABLES: tuple[str, ...] = (
    "users",
    "daily_logs",
    "meal_records",
    "exercise_records",
    "weight_history",
    "user_discount_codes",
)


# 每張表的 cursor 用哪一欄（PostgREST 那邊用 updated_at；沒有的退 created_at）
CURSOR_COLUMN: dict[str, str] = {
    "users":               "updated_at",
    "daily_logs":          "updated_at",
    "meal_records":        "created_at",   # immutable rows
    "exercise_records":    "created_at",
    "weight_history":      "created_at",
    "user_discount_codes": "created_at",
}


SCHEMA_SQL = """
-- 跟 Supabase 一致的鏡像。SQLite 沒有 UUID/JSONB/NUMERIC 真型別，
-- 一律用 TEXT；JSON 欄位存 JSON 字串，查詢用 json_extract。

CREATE TABLE IF NOT EXISTS users (
    id                   TEXT PRIMARY KEY,
    line_user_id         TEXT,
    email                TEXT,
    display_name         TEXT,
    picture_url          TEXT,
    tier                 TEXT NOT NULL DEFAULT '一般',
    encrypted_phone      TEXT,
    gender               TEXT,
    birth_date           TEXT,
    height_cm            REAL,
    weight_kg            REAL,
    target_weight_kg     REAL,
    activity_level       TEXT,
    goal                 TEXT,
    xp                   INTEGER NOT NULL DEFAULT 0,
    hearts               INTEGER NOT NULL DEFAULT 5,
    hearts_last_regen_at TEXT,
    current_streak       INTEGER NOT NULL DEFAULT 0,
    last_checkin_date    TEXT,
    game_progress        TEXT NOT NULL DEFAULT '{}',
    created_at           TEXT NOT NULL,
    updated_at           TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_users_email     ON users (email);
CREATE INDEX IF NOT EXISTS ix_users_line_uid  ON users (line_user_id);
CREATE INDEX IF NOT EXISTS ix_users_tier      ON users (tier);

CREATE TABLE IF NOT EXISTS daily_logs (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    log_date        TEXT NOT NULL,
    bmr_snapshot    REAL,
    tdee_snapshot   INTEGER,
    target_kcal     INTEGER,
    weight_kg       REAL,
    notes           TEXT,
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,
    UNIQUE (user_id, log_date)
);
CREATE INDEX IF NOT EXISTS ix_daily_logs_user_date ON daily_logs (user_id, log_date DESC);

CREATE TABLE IF NOT EXISTS meal_records (
    id              TEXT PRIMARY KEY,
    daily_log_id    TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    meal_type       TEXT NOT NULL,
    name            TEXT NOT NULL,
    calories        INTEGER NOT NULL DEFAULT 0,
    source          TEXT NOT NULL DEFAULT 'custom',
    bento_key       TEXT,
    portions        TEXT,           -- JSON
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_meal_records_daily_log    ON meal_records (daily_log_id);
CREATE INDEX IF NOT EXISTS ix_meal_records_user_created ON meal_records (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS exercise_records (
    id              TEXT PRIMARY KEY,
    daily_log_id    TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    name            TEXT NOT NULL,
    met             REAL NOT NULL,
    duration_min    INTEGER NOT NULL,
    intensity       TEXT NOT NULL,
    calories        INTEGER NOT NULL DEFAULT 0,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_exercise_records_daily_log    ON exercise_records (daily_log_id);
CREATE INDEX IF NOT EXISTS ix_exercise_records_user_created ON exercise_records (user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS weight_history (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    weight_kg       REAL NOT NULL,
    recorded_date   TEXT NOT NULL,
    note            TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_weight_history_user_date ON weight_history (user_id, recorded_date DESC);

CREATE TABLE IF NOT EXISTS user_discount_codes (
    id              TEXT PRIMARY KEY,
    user_id         TEXT NOT NULL,
    code            TEXT NOT NULL,
    chapter_id      INTEGER,
    discount_type   TEXT,
    value           INTEGER,
    issued_at       TEXT,
    expires_at      TEXT,
    used_at         TEXT,
    created_at      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_user_discount_codes_user ON user_discount_codes (user_id);

-- 同步 metadata：每張表 last cursor + 上次 sync 時間 + 上次錯誤訊息
CREATE TABLE IF NOT EXISTS _sync_meta (
    table_name        TEXT PRIMARY KEY,
    cursor_value      TEXT,           -- updated_at 或 created_at 的最大值
    rows_total        INTEGER NOT NULL DEFAULT 0,
    last_sync_at      TEXT,
    last_sync_status  TEXT,           -- 'ok' / 'error'
    last_error        TEXT
);

CREATE TABLE IF NOT EXISTS _sync_runs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at        TEXT NOT NULL,
    finished_at       TEXT,
    status            TEXT,           -- 'ok' / 'partial' / 'error'
    rows_pulled       INTEGER NOT NULL DEFAULT 0,
    error_message     TEXT
);
"""


# ─── Connection pool ───────────────────────────────────────

_local = threading.local()


def get_conn(db_path: Path | None = None) -> sqlite3.Connection:
    """每個 thread 拿自己的 connection；自動建好 schema。"""
    path = db_path or get_db_path()
    existing = getattr(_local, "conn", None)
    if existing is not None and getattr(_local, "path", None) == str(path):
        return existing

    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), isolation_level=None, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    conn.executescript(SCHEMA_SQL)
    _local.conn = conn
    _local.path = str(path)
    return conn


def close_conn() -> None:
    conn = getattr(_local, "conn", None)
    if conn is not None:
        conn.close()
        _local.conn = None
        _local.path = None


# ─── Helpers ───────────────────────────────────────────────

def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_value(value: Any) -> Any:
    """把 dict/list 轉 JSON 字串，其他原樣（datetime 留給 caller 轉 ISO）。"""
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return value


def upsert_row(table: str, row: dict[str, Any]) -> None:
    """以 ``id`` 為 key 做 INSERT OR REPLACE；只寫該表已知欄位，未知欄位直接 drop。"""
    conn = get_conn()
    cols = _table_columns(conn, table)
    payload = {k: _serialize_value(v) for k, v in row.items() if k in cols}
    if not payload or "id" not in payload:
        return
    placeholders = ", ".join(["?"] * len(payload))
    columns = ", ".join(payload.keys())
    sql = f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})"
    conn.execute(sql, tuple(payload.values()))


def upsert_rows(table: str, rows: Iterable[dict[str, Any]]) -> int:
    """批次 upsert。回實際寫入筆數。"""
    rows_list = list(rows)
    if not rows_list:
        return 0
    conn = get_conn()
    cols = _table_columns(conn, table)
    written = 0
    with conn:  # 一個交易包整批
        for row in rows_list:
            payload = {k: _serialize_value(v) for k, v in row.items() if k in cols}
            if not payload or "id" not in payload:
                continue
            placeholders = ", ".join(["?"] * len(payload))
            columns = ", ".join(payload.keys())
            sql = f"INSERT OR REPLACE INTO {table} ({columns}) VALUES ({placeholders})"
            conn.execute(sql, tuple(payload.values()))
            written += 1
    return written


def delete_row(table: str, row_id: str) -> None:
    conn = get_conn()
    conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    cur = conn.execute(f"PRAGMA table_info({table})")
    return {row["name"] for row in cur.fetchall()}


# ─── Sync metadata ────────────────────────────────────────

def get_cursor(table: str) -> str | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT cursor_value FROM _sync_meta WHERE table_name = ?",
        (table,),
    ).fetchone()
    return row["cursor_value"] if row else None


def set_cursor(table: str, cursor_value: str | None, rows_total: int) -> None:
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO _sync_meta (table_name, cursor_value, rows_total, last_sync_at, last_sync_status)
        VALUES (?, ?, ?, ?, 'ok')
        ON CONFLICT(table_name) DO UPDATE SET
            cursor_value     = excluded.cursor_value,
            rows_total       = rows_total + excluded.rows_total,
            last_sync_at     = excluded.last_sync_at,
            last_sync_status = 'ok',
            last_error       = NULL
        """,
        (table, cursor_value, rows_total, utcnow_iso()),
    )


def mark_table_error(table: str, message: str) -> None:
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO _sync_meta (table_name, cursor_value, last_sync_at,
                                last_sync_status, last_error)
        VALUES (?, NULL, ?, 'error', ?)
        ON CONFLICT(table_name) DO UPDATE SET
            last_sync_at     = excluded.last_sync_at,
            last_sync_status = 'error',
            last_error       = excluded.last_error
        """,
        (table, utcnow_iso(), message),
    )


def start_sync_run() -> int:
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO _sync_runs (started_at) VALUES (?)",
        (utcnow_iso(),),
    )
    return int(cur.lastrowid)


def finish_sync_run(run_id: int, status: str, rows_pulled: int, error: str | None) -> None:
    conn = get_conn()
    conn.execute(
        """
        UPDATE _sync_runs SET finished_at = ?, status = ?, rows_pulled = ?, error_message = ?
        WHERE id = ?
        """,
        (utcnow_iso(), status, rows_pulled, error, run_id),
    )


def sync_status_summary() -> dict[str, Any]:
    """admin.py header 顯示用：每張表 last_sync / cursor / 錯誤。"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT table_name, cursor_value, rows_total, last_sync_at, "
        "last_sync_status, last_error FROM _sync_meta"
    ).fetchall()
    last_run = conn.execute(
        "SELECT id, started_at, finished_at, status, rows_pulled, error_message "
        "FROM _sync_runs ORDER BY id DESC LIMIT 1"
    ).fetchone()
    return {
        "tables": [dict(r) for r in rows],
        "last_run": dict(last_run) if last_run else None,
    }


# ─── Convenience query helpers (for admin.py) ─────────────

def query_all(sql: str, params: tuple = ()) -> list[dict[str, Any]]:
    conn = get_conn()
    rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def query_one(sql: str, params: tuple = ()) -> dict[str, Any] | None:
    conn = get_conn()
    row = conn.execute(sql, params).fetchone()
    return dict(row) if row else None
