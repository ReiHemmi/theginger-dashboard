"""BASE（自社ショップ）から注文データを取得して orders テーブルへ保存する。

OAuth2。初回だけ認可コードからトークンを取得し、以降はリフレッシュトークンで
アクセストークンを自動更新する（リフレッシュトークンは回転するので都度保存）。

使い方:
    # 初回（認可コードからトークン取得）:
    python -m collectors.base_collector --auth-code "<code>"
    # 取り込み:
    python -m collectors.base_collector --all
    python -m collectors.base_collector --days 90

必要な環境変数(.env):
    BASE_CLIENT_ID / BASE_CLIENT_SECRET / BASE_REDIRECT_URI
リフレッシュトークンは secrets/base_token.json に保存・更新する。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone, timedelta

import requests
from dotenv import load_dotenv

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.db import get_connection, init_db, log_sync  # noqa: E402

JST = timezone(timedelta(hours=9))
API = "https://api.thebase.in/1"
TOKEN_URL = f"{API}/oauth/token"
TOKEN_STORE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "secrets", "base_token.json")


def _save_refresh_token(token: str) -> None:
    os.makedirs(os.path.dirname(TOKEN_STORE), exist_ok=True)
    with open(TOKEN_STORE, "w", encoding="utf-8") as f:
        json.dump({"refresh_token": token,
                   "updated_at": datetime.now(timezone.utc).isoformat()}, f)


def _load_refresh_token() -> str | None:
    if os.path.exists(TOKEN_STORE):
        with open(TOKEN_STORE, encoding="utf-8") as f:
            return json.load(f).get("refresh_token")
    return os.getenv("BASE_REFRESH_TOKEN") or None


def exchange_code(code: str) -> None:
    """認可コード → アクセス/リフレッシュトークン（初回のみ）。"""
    load_dotenv()
    data = {
        "grant_type": "authorization_code",
        "client_id": os.getenv("BASE_CLIENT_ID"),
        "client_secret": os.getenv("BASE_CLIENT_SECRET"),
        "code": code,
        "redirect_uri": os.getenv("BASE_REDIRECT_URI"),
    }
    r = requests.post(TOKEN_URL, data=data, timeout=60)
    j = r.json()
    if "error" in j:
        raise RuntimeError(f"BASE 認可エラー: {j}")
    _save_refresh_token(j["refresh_token"])
    print("BASE トークン取得・保存しました（refresh_token を secrets に保存）。")


def get_access_token() -> str:
    load_dotenv()
    refresh = _load_refresh_token()
    if not refresh:
        raise RuntimeError(
            "BASEのリフレッシュトークンがありません。先に --auth-code で認可してください。")
    data = {
        "grant_type": "refresh_token",
        "client_id": os.getenv("BASE_CLIENT_ID"),
        "client_secret": os.getenv("BASE_CLIENT_SECRET"),
        "refresh_token": refresh,
    }
    r = requests.post(TOKEN_URL, data=data, timeout=60)
    j = r.json()
    if "error" in j:
        raise RuntimeError(f"BASE トークン更新エラー: {j}")
    if j.get("refresh_token"):            # リフレッシュトークンは回転する→保存
        _save_refresh_token(j["refresh_token"])
    return j["access_token"]


def _to_utc_iso(ordered) -> tuple[str, str]:
    """BASEのorderedは Unixタイムスタンプ(数値) → (UTC iso, JST日付)。
    文字列 'YYYY-MM-DD HH:MM:SS'(JST) 形式にも一応対応。"""
    if isinstance(ordered, (int, float)) or (isinstance(ordered, str) and ordered.isdigit()):
        dt = datetime.fromtimestamp(int(ordered), tz=timezone.utc)
    else:
        dt = datetime.strptime(ordered, "%Y-%m-%d %H:%M:%S").replace(tzinfo=JST)
    return dt.astimezone(timezone.utc).isoformat(), dt.astimezone(JST).strftime("%Y-%m-%d")


def fetch_base(days: int | None = 90, fetch_all: bool = False) -> int:
    token = get_access_token()
    headers = {"Authorization": f"Bearer {token}"}
    params = {"limit": 100, "offset": 0, "order": "desc"}
    if not fetch_all and days:
        params["start_ordered"] = int(
            (datetime.now(timezone.utc) - timedelta(days=days)).timestamp())

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []
    while True:
        r = requests.get(f"{API}/orders", headers=headers, params=params, timeout=60)
        j = r.json()
        if "error" in j:
            raise RuntimeError(f"BASE 注文取得エラー: {j}")
        orders = j.get("orders", [])
        if not orders:
            break
        for o in orders:
            dt_utc, date_jst = _to_utc_iso(o["ordered"])
            cancelled = 1 if o.get("cancelled") else 0
            rows.append((
                "base", str(o["unique_key"]), dt_utc, date_jst,
                None, o.get("mail_address"),
                float(o.get("total") or 0), 0.0, float(o.get("total") or 0),
                "jpy", o.get("dispatch_status"), cancelled,
                o.get("payment"),
                json.dumps(o, ensure_ascii=False), fetched_at,
            ))
        if len(orders) < params["limit"]:
            break
        params["offset"] += params["limit"]

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
                    gross_amount = excluded.gross_amount,
                    net_amount   = excluded.net_amount,
                    status       = excluded.status,
                    is_refunded  = excluded.is_refunded,
                    raw_json     = excluded.raw_json,
                    fetched_at   = excluded.fetched_at
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="BASE 注文データ取得")
    parser.add_argument("--auth-code", type=str, help="初回: 認可コード")
    parser.add_argument("--days", type=int, default=90, help="直近N日（既定90）")
    parser.add_argument("--all", action="store_true", help="全期間")
    args = parser.parse_args()

    init_db()
    if args.auth_code:
        exchange_code(args.auth_code)
        return

    started = datetime.now(timezone.utc).isoformat()
    try:
        n = fetch_base(days=args.days, fetch_all=args.all)
        log_sync("base", "ok", n, started_at=started)
        print(f"[base] {n} 件を取り込みました。")
    except Exception as e:  # noqa: BLE001
        log_sync("base", "error", 0, message=str(e), started_at=started)
        print(f"[base] エラー: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
