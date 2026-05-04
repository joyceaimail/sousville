"""SousVille — Supabase → local SQLite 同步引擎。

核心：
- ``pull_table(table)`` 把該表所有「比上次 cursor 還新」的列拉回本機
- ``pull_all()`` 跑全部要同步的表，回 (status, total_rows, errors)
- ``write_through_*`` 給 admin.py 用的雙寫包裝（先打 Supabase 再寫本機）

設計原則：
- Source of truth = Supabase。本機 SQLite 是只讀鏡像（admin 寫入也透過
  Supabase 雙寫，避免 split-brain）
- Incremental cursor：用 ``updated_at >= last_cursor``（PostgREST 不支援 ``>``，
  所以用 ``>=`` + 重新 upsert，靠 ``id`` PK 自然 dedupe）
- Pagination：PostgREST 預設 1000 筆 limit，用 ``Range`` header 翻頁
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests

from scripts import local_db

logger = logging.getLogger(__name__)


# ─── Supabase config ──────────────────────────────────────


def _env(key: str, default: str = "") -> str:
    val = os.environ.get(key, default)
    if not val:
        try:
            from dotenv import load_dotenv  # type: ignore
            load_dotenv(local_db.PROJECT_ROOT / ".env")
            val = os.environ.get(key, default)
        except Exception:
            pass
    return val


def _config() -> tuple[str, str]:
    url = _env("SUPABASE_URL", "").rstrip("/")
    key = _env("SUPABASE_SERVICE_KEY") or _env("SUPABASE_KEY")
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL 或 SUPABASE_SERVICE_KEY 沒設。"
            "請在 ~/SousVille/.env 或 shell 環境設好再跑同步。"
        )
    return url, key


def _headers(key: str, range_header: str | None = None) -> dict[str, str]:
    h = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Accept": "application/json",
    }
    if range_header:
        h["Range"] = range_header
        h["Range-Unit"] = "items"
    return h


PAGE_SIZE = 1000
HTTP_TIMEOUT = 30.0
HTTP_MAX_RETRY = 3


def _http_get_with_retry(url: str, headers: dict[str, str]) -> requests.Response:
    last_exc: Exception | None = None
    for attempt in range(HTTP_MAX_RETRY):
        try:
            resp = requests.get(url, headers=headers, timeout=HTTP_TIMEOUT)
            if resp.status_code in (429, 502, 503, 504):
                last_exc = RuntimeError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                time.sleep(1.5 ** attempt)
                continue
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            time.sleep(1.5 ** attempt)
    raise last_exc or RuntimeError("Unknown HTTP failure")


# ─── Pull single table ────────────────────────────────────


def _max_cursor(rows: list[dict[str, Any]], cursor_col: str) -> str | None:
    cursors = [r.get(cursor_col) for r in rows if r.get(cursor_col)]
    return max(cursors) if cursors else None


def pull_table(table: str) -> tuple[int, str | None]:
    """拉一張表，回 (寫入筆數, 新 cursor)。

    使用 ``updated_at >= last_cursor`` 增量；首次 pull（cursor=None）拉全部。
    """
    url_base, key = _config()
    cursor_col = local_db.CURSOR_COLUMN.get(table, "created_at")
    last_cursor = local_db.get_cursor(table)

    qs_parts = [f"select=*", f"order={cursor_col}.asc"]
    if last_cursor:
        qs_parts.append(f"{cursor_col}=gte.{last_cursor}")

    base_url = f"{url_base}/rest/v1/{table}?" + "&".join(qs_parts)

    total_written = 0
    new_cursor = last_cursor
    offset = 0

    while True:
        range_hdr = f"{offset}-{offset + PAGE_SIZE - 1}"
        try:
            resp = _http_get_with_retry(base_url, _headers(key, range_hdr))
        except Exception as exc:
            logger.error("pull %s failed at offset %s: %s", table, offset, exc)
            local_db.mark_table_error(table, f"offset={offset}: {exc}")
            raise

        try:
            rows = resp.json()
        except ValueError as exc:
            local_db.mark_table_error(table, f"json decode: {exc}")
            raise

        if not isinstance(rows, list):
            # PostgREST 錯誤通常回 dict
            local_db.mark_table_error(table, f"non-list response: {rows}")
            raise RuntimeError(f"pull {table}: unexpected response: {rows}")

        if not rows:
            break

        written = local_db.upsert_rows(table, rows)
        total_written += written

        page_cursor = _max_cursor(rows, cursor_col)
        if page_cursor and (new_cursor is None or page_cursor > new_cursor):
            new_cursor = page_cursor

        if len(rows) < PAGE_SIZE:
            break
        offset += PAGE_SIZE

    local_db.set_cursor(table, new_cursor, total_written)
    return total_written, new_cursor


# ─── Pull all ──────────────────────────────────────────────


def pull_all(tables: tuple[str, ...] | None = None) -> dict[str, Any]:
    """同步所有要鏡像的表。回 summary dict（每張表寫入幾筆 + 錯誤）。"""
    tables = tables or local_db.SYNCED_TABLES
    run_id = local_db.start_sync_run()

    results: dict[str, Any] = {"tables": {}, "errors": {}}
    total_rows = 0

    for table in tables:
        try:
            written, cursor = pull_table(table)
            results["tables"][table] = {"written": written, "cursor": cursor}
            total_rows += written
            logger.info("pull %s: %d rows; cursor=%s", table, written, cursor)
        except Exception as exc:
            results["errors"][table] = str(exc)
            logger.exception("pull %s failed", table)

    if results["errors"]:
        status = "partial" if results["tables"] else "error"
    else:
        status = "ok"

    local_db.finish_sync_run(
        run_id,
        status,
        total_rows,
        ("; ".join(f"{t}: {e}" for t, e in results["errors"].items()) or None),
    )

    results["status"] = status
    results["total_rows"] = total_rows
    results["run_id"] = run_id
    return results


# ─── Write-through helpers (admin.py 用) ──────────────────
#
# 重要：admin 寫入的真理是 Supabase。先打 cloud 成功了才回鏡到 local，
# 避免 admin 看到「假成功」結果其實沒同步上去。

def write_through_insert(table: str, payload: dict[str, Any]) -> dict[str, Any]:
    url_base, key = _config()
    headers = {
        **_headers(key),
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    resp = requests.post(
        f"{url_base}/rest/v1/{table}",
        headers=headers,
        json=payload,
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    rows = data if isinstance(data, list) else [data]
    if rows:
        local_db.upsert_rows(table, rows)
    return rows[0] if rows else {}


def write_through_update(table: str, row_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    url_base, key = _config()
    headers = {
        **_headers(key),
        "Content-Type": "application/json",
        "Prefer": "return=representation",
    }
    resp = requests.patch(
        f"{url_base}/rest/v1/{table}?id=eq.{row_id}",
        headers=headers,
        json=patch,
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    rows = data if isinstance(data, list) else [data]
    if rows:
        local_db.upsert_rows(table, rows)
    return rows[0] if rows else {}


def write_through_delete(table: str, row_id: str) -> None:
    url_base, key = _config()
    resp = requests.delete(
        f"{url_base}/rest/v1/{table}?id=eq.{row_id}",
        headers=_headers(key),
        timeout=HTTP_TIMEOUT,
    )
    resp.raise_for_status()
    local_db.delete_row(table, row_id)
