"""Search Console（Search Analytics API）から日次×検索キーワードを取得する。

使い方:
    python -m collectors.search_console_collector --days 90

必要な環境変数(.env):
    GOOGLE_APPLICATION_CREDENTIALS  サービスアカウントJSON（GA4と共用）
    SEARCH_CONSOLE_SITE_URL         例 https://reihemmi.github.io/theginger/
                                    （ドメインプロパティの場合 sc-domain:example.com）

何度実行しても (date_jst, query) で上書きするので重複しない。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.db import get_connection, init_db, log_sync  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


def fetch_search_console(days: int = 90) -> int:
    load_dotenv()
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    site = os.getenv("SEARCH_CONSOLE_SITE_URL")
    if not cred_path or not site:
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS / SEARCH_CONSOLE_SITE_URL が未設定です。"
        )
    if not os.path.exists(cred_path):
        raise RuntimeError(f"サービスアカウントJSONが見つかりません: {cred_path}")

    creds = service_account.Credentials.from_service_account_file(
        cred_path, scopes=SCOPES)
    service = build("searchconsole", "v1", credentials=creds,
                    cache_discovery=False)

    end = datetime.now(timezone.utc).date()
    start = end - timedelta(days=days)
    body = {
        "startDate": start.strftime("%Y-%m-%d"),
        "endDate": end.strftime("%Y-%m-%d"),
        "dimensions": ["date", "query"],
        "rowLimit": 25000,
    }
    resp = service.searchanalytics().query(siteUrl=site, body=body).execute()

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []
    for r in resp.get("rows", []):
        date_jst, query = r["keys"][0], r["keys"][1]
        rows.append((
            date_jst, query,
            int(r.get("clicks", 0)), int(r.get("impressions", 0)),
            float(r.get("ctr", 0)), float(r.get("position", 0)),
            json.dumps(r, ensure_ascii=False), fetched_at,
        ))

    if rows:
        conn = get_connection()
        try:
            conn.executemany(
                """
                INSERT INTO search_console (
                    date_jst, query, clicks, impressions, ctr, position,
                    raw_json, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(date_jst, query) DO UPDATE SET
                    clicks      = excluded.clicks,
                    impressions = excluded.impressions,
                    ctr         = excluded.ctr,
                    position    = excluded.position,
                    raw_json    = excluded.raw_json,
                    fetched_at  = excluded.fetched_at
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search Console データ取得")
    parser.add_argument("--days", type=int, default=90, help="直近N日（既定90）")
    args = parser.parse_args()

    init_db()
    started = datetime.now(timezone.utc).isoformat()
    try:
        n = fetch_search_console(days=args.days)
        log_sync("search_console", "ok", n, started_at=started)
        print(f"[search_console] {n} 行を取り込みました。")
    except Exception as e:  # noqa: BLE001
        log_sync("search_console", "error", 0, message=str(e), started_at=started)
        print(f"[search_console] エラー: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
