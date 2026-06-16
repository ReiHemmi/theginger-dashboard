"""GA4（Google Analytics Data API）から日次×チャネルの流入データを取得する。

使い方:
    python -m collectors.ga4_collector --days 90

必要な環境変数(.env):
    GOOGLE_APPLICATION_CREDENTIALS  サービスアカウントJSONのフルパス
    GA4_PROPERTY_ID                 GA4のプロパティID（数字。測定IDのG-xxxとは別物）

何度実行しても (source, date_jst, channel) で上書きするので重複しない。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

from dotenv import load_dotenv
from google.oauth2 import service_account
from google.analytics.data_v1beta import BetaAnalyticsDataClient
from google.analytics.data_v1beta.types import (
    DateRange, Dimension, Metric, RunReportRequest,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.db import get_connection, init_db, log_sync  # noqa: E402

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


def _int(v: str) -> int:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return 0


def _float(v: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def fetch_ga4(days: int = 90) -> int:
    load_dotenv()
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    prop = os.getenv("GA4_PROPERTY_ID")
    if not cred_path or not prop:
        raise RuntimeError(
            "GOOGLE_APPLICATION_CREDENTIALS / GA4_PROPERTY_ID が未設定です。"
            "dashboard/.env を確認してください。"
        )
    if not os.path.exists(cred_path):
        raise RuntimeError(f"サービスアカウントJSONが見つかりません: {cred_path}")

    creds = service_account.Credentials.from_service_account_file(
        cred_path, scopes=SCOPES)
    client = BetaAnalyticsDataClient(credentials=creds)

    request = RunReportRequest(
        property=f"properties/{prop}",
        dimensions=[Dimension(name="date"),
                    Dimension(name="sessionDefaultChannelGroup"),
                    Dimension(name="hostName")],
        metrics=[Metric(name="sessions"), Metric(name="totalUsers"),
                 Metric(name="newUsers"), Metric(name="engagedSessions"),
                 Metric(name="conversions")],
        date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="today")],
        limit=100000,
    )
    resp = client.run_report(request)

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []
    for r in resp.rows:
        d = r.dimension_values[0].value           # YYYYMMDD
        channel = r.dimension_values[1].value
        host = r.dimension_values[2].value
        date_jst = f"{d[0:4]}-{d[4:6]}-{d[6:8]}"
        m = [v.value for v in r.metric_values]
        rows.append((
            "ga4", date_jst, channel, host,
            _int(m[0]), _int(m[1]), _int(m[2]), _int(m[3]), _float(m[4]),
            json.dumps({"channel": channel, "host": host, "metrics": m},
                       ensure_ascii=False),
            fetched_at,
        ))

    if rows:
        conn = get_connection()
        try:
            conn.executemany(
                """
                INSERT INTO traffic (
                    source, date_jst, channel, hostname, sessions, users,
                    new_users, engaged_sessions, conversions, raw_json, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(source, date_jst, channel, hostname) DO UPDATE SET
                    sessions         = excluded.sessions,
                    users            = excluded.users,
                    new_users        = excluded.new_users,
                    engaged_sessions = excluded.engaged_sessions,
                    conversions      = excluded.conversions,
                    raw_json         = excluded.raw_json,
                    fetched_at       = excluded.fetched_at
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    return len(rows)


def fetch_ga4_events(days: int = 90) -> int:
    """イベント別（scroll等）×日次の発生数を ga4_events へ保存する。"""
    load_dotenv()
    cred_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    prop = os.getenv("GA4_PROPERTY_ID")
    if not cred_path or not prop:
        raise RuntimeError("GOOGLE_APPLICATION_CREDENTIALS / GA4_PROPERTY_ID 未設定")
    creds = service_account.Credentials.from_service_account_file(
        cred_path, scopes=SCOPES)
    client = BetaAnalyticsDataClient(credentials=creds)

    request = RunReportRequest(
        property=f"properties/{prop}",
        dimensions=[Dimension(name="date"), Dimension(name="eventName"),
                    Dimension(name="hostName")],
        metrics=[Metric(name="eventCount")],
        date_ranges=[DateRange(start_date=f"{days}daysAgo", end_date="today")],
        limit=100000,
    )
    resp = client.run_report(request)
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows = []
    for r in resp.rows:
        d = r.dimension_values[0].value
        rows.append((f"{d[0:4]}-{d[4:6]}-{d[6:8]}", r.dimension_values[1].value,
                     r.dimension_values[2].value,
                     _int(r.metric_values[0].value), fetched_at))
    if rows:
        conn = get_connection()
        try:
            conn.executemany(
                """INSERT INTO ga4_events (date_jst, event_name, hostname, event_count, fetched_at)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(date_jst, event_name, hostname) DO UPDATE SET
                       event_count = excluded.event_count,
                       fetched_at  = excluded.fetched_at""",
                rows,
            )
            conn.commit()
        finally:
            conn.close()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="GA4 流入データ取得")
    parser.add_argument("--days", type=int, default=90, help="直近N日（既定90）")
    args = parser.parse_args()

    init_db()
    started = datetime.now(timezone.utc).isoformat()
    try:
        n = fetch_ga4(days=args.days)
        e = fetch_ga4_events(days=args.days)
        log_sync("ga4", "ok", n + e, started_at=started)
        print(f"[ga4] 流入 {n} 行 / イベント {e} 行を取り込みました。")
    except Exception as e:  # noqa: BLE001
        log_sync("ga4", "error", 0, message=str(e), started_at=started)
        print(f"[ga4] エラー: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
