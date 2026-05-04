#!/usr/bin/env python3
"""SousVille — 把 Supabase 上所有資料拉回本機 SQLite。

用法：
    # 同步所有表（增量；用上次 cursor 之後）
    python scripts/sync_from_cloud.py

    # 強制全量重抓某幾張表
    python scripts/sync_from_cloud.py --tables users,daily_logs --full

    # 看本機目前 sync 狀態
    python scripts/sync_from_cloud.py --status

需要環境變數：``SUPABASE_URL``、``SUPABASE_SERVICE_KEY``（從 ~/SousVille/.env
自動讀）。launchd 排程裡記得 source 環境（plist 直接寫進 EnvironmentVariables）。
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

# 讓 `python scripts/sync_from_cloud.py` 直接 work（不用先 cd）
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts import local_db, sync_engine  # noqa: E402


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )


def _print_status() -> None:
    summary = local_db.sync_status_summary()
    print("\n=== 本機鏡像狀態 ===")
    print(f"DB 路徑：{local_db.get_db_path()}")
    last = summary.get("last_run")
    if last:
        print(
            f"上次 sync run #{last['id']}：{last['started_at']} → {last.get('finished_at') or '進行中'}"
            f"，狀態 {last.get('status')}，拉 {last.get('rows_pulled', 0)} 筆"
        )
        if last.get("error_message"):
            print(f"  錯誤：{last['error_message']}")
    else:
        print("（還沒 sync 過）")

    print("\n各表狀態：")
    if not summary["tables"]:
        print("  （尚未建立任何 cursor）")
        return
    for row in summary["tables"]:
        marker = "✅" if row["last_sync_status"] == "ok" else "⚠️ "
        print(
            f"  {marker} {row['table_name']:<22} cursor={row['cursor_value'] or '(none)':<32} "
            f"total={row['rows_total']:>6}  last={row['last_sync_at']}"
        )
        if row["last_error"]:
            print(f"      最後錯誤：{row['last_error']}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tables",
        type=str,
        default="",
        help="只同步指定表（用逗號分隔；不寫=全部）",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="忽略 cursor，從頭重抓（會 dedupe by id）",
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="只印同步狀態，不執行 sync",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="只印 ERROR 以上（給 launchd 用）",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="DEBUG level 詳細 log",
    )
    args = parser.parse_args(argv)

    if args.quiet:
        logging.basicConfig(level=logging.ERROR)
    else:
        _setup_logging(args.verbose)

    # 先確保 schema 存在
    local_db.get_conn()

    if args.status:
        _print_status()
        return 0

    if args.full:
        # 把指定表（或全部）的 cursor 清空，下面會重抓
        target = (
            tuple(t.strip() for t in args.tables.split(",") if t.strip())
            or local_db.SYNCED_TABLES
        )
        conn = local_db.get_conn()
        for t in target:
            conn.execute("DELETE FROM _sync_meta WHERE table_name = ?", (t,))
        logging.info("--full：已清掉 %s 的 cursor", ", ".join(target))

    tables = (
        tuple(t.strip() for t in args.tables.split(",") if t.strip())
        if args.tables
        else None
    )

    try:
        result = sync_engine.pull_all(tables)
    except Exception as exc:
        logging.exception("sync 失敗：%s", exc)
        return 2

    if not args.quiet:
        print(json.dumps(result, ensure_ascii=False, indent=2, default=str))

    return 0 if result["status"] == "ok" else 1


if __name__ == "__main__":
    raise SystemExit(main())
