"""Stripe から決済データを取得して orders テーブルへ保存する。

使い方:
    python -m collectors.stripe_collector              # 直近90日
    python -m collectors.stripe_collector --days 365   # 直近1年
    python -m collectors.stripe_collector --since 2025-01-01
    python -m collectors.stripe_collector --all        # 全期間

同じデータを何度取り込んでも重複しない（external_id で上書き）ので、
毎日実行しても安全。返金などの後からの変化も拾えるよう、
日次実行では直近ぶんを取り直す想定。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import stripe
from stripe import StripeObject
from dotenv import load_dotenv

# プロジェクト直下を import パスに追加（単体実行できるように）
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.db import get_connection, init_db, log_sync  # noqa: E402

JST = timezone(timedelta(hours=9))

# 小数を持たない通貨（JPY など）。これらは amount がそのまま「円」。
ZERO_DECIMAL = {
    "jpy", "krw", "vnd", "clp", "bif", "djf", "gnf", "kmf",
    "mga", "pyg", "rwf", "ugx", "vuv", "xaf", "xof", "xpf",
}


def to_plain(obj):
    """Stripe オブジェクトを素のネスト dict へ再帰変換する（.get が使えるように）。"""
    if isinstance(obj, StripeObject):
        return {k: to_plain(v) for k, v in obj.to_dict().items()}
    if isinstance(obj, list):
        return [to_plain(v) for v in obj]
    return obj


def to_major(amount: int | None, currency: str) -> float:
    """Stripe の最小単位金額を主要単位(円/ドル)に直す。"""
    if amount is None:
        return 0.0
    if currency.lower() in ZERO_DECIMAL:
        return float(amount)
    return amount / 100.0


def _resolve_since(days: int, since: str | None, fetch_all: bool) -> int | None:
    """取得開始の unix 秒を決める。全期間なら None。"""
    if fetch_all:
        return None
    if since:
        dt = datetime.strptime(since, "%Y-%m-%d").replace(tzinfo=JST)
        return int(dt.timestamp())
    dt = datetime.now(timezone.utc) - timedelta(days=days)
    return int(dt.timestamp())


def fetch_stripe(days: int = 90, since: str | None = None,
                 fetch_all: bool = False) -> int:
    load_dotenv()
    api_key = os.getenv("STRIPE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "STRIPE_API_KEY が見つかりません。dashboard/.env に設定してください。"
        )
    stripe.api_key = api_key

    since_ts = _resolve_since(days, since, fetch_all)
    params: dict = {"limit": 100, "expand": ["data.balance_transaction"]}
    if since_ts is not None:
        params["created"] = {"gte": since_ts}

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []

    for ch_obj in stripe.Charge.list(**params).auto_paging_iter():
        ch = to_plain(ch_obj)
        currency = ch.get("currency", "jpy")
        created = datetime.fromtimestamp(ch["created"], tz=timezone.utc)
        bt = ch.get("balance_transaction")
        fee = to_major(bt["fee"], bt["currency"]) if isinstance(bt, dict) else 0.0
        net = to_major(bt["net"], bt["currency"]) if isinstance(bt, dict) else None

        billing = ch.get("billing_details") or {}
        email = billing.get("email") or ch.get("receipt_email")

        rows.append((
            "stripe",
            ch["id"],
            created.isoformat(),
            created.astimezone(JST).strftime("%Y-%m-%d"),
            ch.get("customer"),
            email,
            to_major(ch.get("amount"), currency),
            fee,
            net,
            currency,
            ch.get("status"),
            1 if ch.get("refunded") else 0,
            ch.get("description"),
            json.dumps(ch, default=str, ensure_ascii=False),
            fetched_at,
        ))

    if rows:
        conn = get_connection()
        try:
            conn.executemany(
                """
                INSERT INTO orders (
                    channel, external_id, order_datetime_utc, order_date_jst,
                    customer_id, customer_email, gross_amount, fee_amount,
                    net_amount, currency, status, is_refunded, description,
                    raw_json, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(channel, external_id) DO UPDATE SET
                    gross_amount   = excluded.gross_amount,
                    fee_amount     = excluded.fee_amount,
                    net_amount     = excluded.net_amount,
                    status         = excluded.status,
                    is_refunded    = excluded.is_refunded,
                    customer_email = excluded.customer_email,
                    raw_json       = excluded.raw_json,
                    fetched_at     = excluded.fetched_at
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Stripe 決済データ取得")
    parser.add_argument("--days", type=int, default=90, help="直近N日（既定90）")
    parser.add_argument("--since", type=str, help="YYYY-MM-DD 以降")
    parser.add_argument("--all", action="store_true", help="全期間")
    args = parser.parse_args()

    init_db()
    started = datetime.now(timezone.utc).isoformat()
    try:
        n = fetch_stripe(days=args.days, since=args.since, fetch_all=args.all)
        log_sync("stripe", "ok", n, started_at=started)
        print(f"[stripe] {n} 件を取り込みました。")
    except Exception as e:  # noqa: BLE001
        log_sync("stripe", "error", 0, message=str(e), started_at=started)
        print(f"[stripe] エラー: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
