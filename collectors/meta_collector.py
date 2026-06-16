"""Meta広告（Marketing API）から日次の広告実績を取得し ad_spend へ保存する。

使い方:
    python -m collectors.meta_collector              # 直近90日
    python -m collectors.meta_collector --days 365
    python -m collectors.meta_collector --since 2026-01-01

必要な環境変数(.env):
    META_ACCESS_TOKEN   システムユーザーの長期トークン（ads_read 権限）
    META_AD_ACCOUNT_ID  広告アカウントID（"act_123..." でも数字だけでも可）

何度実行しても (channel, date_jst, campaign) で上書きするので重複しない。
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
API_VERSION = "v21.0"

# 「購入」を表す action_type。重複計上を避けるため優先順に1つだけ採用する。
PURCHASE_TYPES = (
    "purchase",
    "omni_purchase",
    "offsite_conversion.fb_pixel_purchase",
    "onsite_web_purchase",
)


def _normalize_account(raw: str) -> str:
    raw = raw.strip()
    return raw if raw.startswith("act_") else f"act_{raw}"


def _date_range(days: int, since: str | None) -> tuple[str, str]:
    today = datetime.now(JST).date()
    if since:
        start = datetime.strptime(since, "%Y-%m-%d").date()
    else:
        start = today - timedelta(days=days)
    return start.strftime("%Y-%m-%d"), today.strftime("%Y-%m-%d")


def _extract_purchases(actions: list | None) -> float:
    if not actions:
        return 0.0
    by_type = {}
    for a in actions:
        try:
            by_type[a["action_type"]] = float(a["value"])
        except (KeyError, TypeError, ValueError):
            continue
    for t in PURCHASE_TYPES:
        if t in by_type:
            return by_type[t]
    return 0.0


def fetch_meta(days: int = 90, since: str | None = None) -> int:
    load_dotenv()
    token = os.getenv("META_ACCESS_TOKEN")
    account = os.getenv("META_AD_ACCOUNT_ID")
    if not token or not account:
        raise RuntimeError(
            "META_ACCESS_TOKEN / META_AD_ACCOUNT_ID が未設定です。"
            "dashboard/.env に設定してください。"
        )
    account = _normalize_account(account)
    since_str, until_str = _date_range(days, since)

    url = f"https://graph.facebook.com/{API_VERSION}/{account}/insights"
    params: dict | None = {
        "access_token": token,
        "level": "campaign",
        "time_increment": 1,
        "time_range": json.dumps({"since": since_str, "until": until_str}),
        "fields": "campaign_name,spend,impressions,clicks,actions",
        "limit": 200,
    }

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []

    while url:
        resp = requests.get(url, params=params, timeout=60)
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Meta APIエラー: {data['error'].get('message')}")
        for d in data.get("data", []):
            rows.append((
                "meta",
                d["date_start"],  # 広告アカウントのタイムゾーン基準(JP想定=JST)
                d.get("campaign_name"),
                float(d.get("spend") or 0),
                int(d.get("impressions") or 0),
                int(d.get("clicks") or 0),
                _extract_purchases(d.get("actions")),
                json.dumps(d, ensure_ascii=False),
                fetched_at,
            ))
        url = (data.get("paging") or {}).get("next")
        params = None  # next の URL に既にパラメータが含まれる

    if rows:
        conn = get_connection()
        try:
            conn.executemany(
                """
                INSERT INTO ad_spend (
                    channel, date_jst, campaign, spend, impressions,
                    clicks, conversions, raw_json, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(channel, date_jst, campaign) DO UPDATE SET
                    spend       = excluded.spend,
                    impressions = excluded.impressions,
                    clicks      = excluded.clicks,
                    conversions = excluded.conversions,
                    raw_json    = excluded.raw_json,
                    fetched_at  = excluded.fetched_at
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()

    return len(rows)


def fetch_meta_platform(days: int = 90, since: str | None = None) -> int:
    """配信面（Instagram/Facebook等）×日次の実績を ad_platform へ保存する。"""
    load_dotenv()
    token = os.getenv("META_ACCESS_TOKEN")
    account = os.getenv("META_AD_ACCOUNT_ID")
    if not token or not account:
        raise RuntimeError("META_ACCESS_TOKEN / META_AD_ACCOUNT_ID が未設定です。")
    account = _normalize_account(account)
    since_str, until_str = _date_range(days, since)

    url = f"https://graph.facebook.com/{API_VERSION}/{account}/insights"
    params: dict | None = {
        "access_token": token,
        "level": "account",
        "time_increment": 1,
        "breakdowns": "publisher_platform",
        "time_range": json.dumps({"since": since_str, "until": until_str}),
        "fields": "spend,impressions,clicks,actions",
        "limit": 500,
    }

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []
    while url:
        resp = requests.get(url, params=params, timeout=60)
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Meta APIエラー: {data['error'].get('message')}")
        for d in data.get("data", []):
            rows.append((
                "meta", d["date_start"], d.get("publisher_platform"),
                float(d.get("spend") or 0), int(d.get("impressions") or 0),
                int(d.get("clicks") or 0), _extract_purchases(d.get("actions")),
                json.dumps(d, ensure_ascii=False), fetched_at,
            ))
        url = (data.get("paging") or {}).get("next")
        params = None

    if rows:
        conn = get_connection()
        try:
            conn.executemany(
                """
                INSERT INTO ad_platform (
                    channel, date_jst, platform, spend, impressions,
                    clicks, conversions, raw_json, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?)
                ON CONFLICT(channel, date_jst, platform) DO UPDATE SET
                    spend       = excluded.spend,
                    impressions = excluded.impressions,
                    clicks      = excluded.clicks,
                    conversions = excluded.conversions,
                    raw_json    = excluded.raw_json,
                    fetched_at  = excluded.fetched_at
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()
    return len(rows)


def fetch_meta_placement(days: int = 90, since: str | None = None) -> int:
    """配信面×掲載位置（Instagram Stories/Feed/Reels 等）×日次の実績。"""
    load_dotenv()
    token = os.getenv("META_ACCESS_TOKEN")
    account = os.getenv("META_AD_ACCOUNT_ID")
    if not token or not account:
        raise RuntimeError("META_ACCESS_TOKEN / META_AD_ACCOUNT_ID が未設定です。")
    account = _normalize_account(account)
    since_str, until_str = _date_range(days, since)

    url = f"https://graph.facebook.com/{API_VERSION}/{account}/insights"
    params: dict | None = {
        "access_token": token,
        "level": "account",
        "time_increment": 1,
        "breakdowns": "publisher_platform,platform_position",
        "time_range": json.dumps({"since": since_str, "until": until_str}),
        "fields": "spend,impressions,clicks,actions",
        "limit": 500,
    }

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []
    while url:
        resp = requests.get(url, params=params, timeout=60)
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Meta APIエラー: {data['error'].get('message')}")
        for d in data.get("data", []):
            rows.append((
                "meta", d["date_start"], d.get("publisher_platform"),
                d.get("platform_position"),
                float(d.get("spend") or 0), int(d.get("impressions") or 0),
                int(d.get("clicks") or 0), _extract_purchases(d.get("actions")),
                json.dumps(d, ensure_ascii=False), fetched_at,
            ))
        url = (data.get("paging") or {}).get("next")
        params = None

    if rows:
        conn = get_connection()
        try:
            conn.executemany(
                """
                INSERT INTO ad_placement (
                    channel, date_jst, platform, position, spend, impressions,
                    clicks, conversions, raw_json, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(channel, date_jst, platform, position) DO UPDATE SET
                    spend       = excluded.spend,
                    impressions = excluded.impressions,
                    clicks      = excluded.clicks,
                    conversions = excluded.conversions,
                    raw_json    = excluded.raw_json,
                    fetched_at  = excluded.fetched_at
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()
    return len(rows)


def fetch_meta_detail(days: int = 90, since: str | None = None) -> int:
    """広告(クリエイティブ)×配信面×掲載位置×日次の明細を ad_detail へ保存。
    campaign_id 等の安定IDで管理（改名による二重計上を防ぐ）。"""
    load_dotenv()
    token = os.getenv("META_ACCESS_TOKEN")
    account = os.getenv("META_AD_ACCOUNT_ID")
    if not token or not account:
        raise RuntimeError("META_ACCESS_TOKEN / META_AD_ACCOUNT_ID が未設定です。")
    account = _normalize_account(account)
    since_str, until_str = _date_range(days, since)

    url = f"https://graph.facebook.com/{API_VERSION}/{account}/insights"
    params: dict | None = {
        "access_token": token,
        "level": "ad",
        "time_increment": 1,
        "breakdowns": "publisher_platform,platform_position",
        "time_range": json.dumps({"since": since_str, "until": until_str}),
        "fields": ("campaign_id,campaign_name,adset_id,adset_name,"
                   "ad_id,ad_name,spend,impressions,clicks,actions"),
        "limit": 500,
    }

    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []
    while url:
        resp = requests.get(url, params=params, timeout=60)
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"Meta APIエラー: {data['error'].get('message')}")
        for d in data.get("data", []):
            rows.append((
                d["date_start"],
                d.get("campaign_id"), d.get("campaign_name"),
                d.get("adset_id"), d.get("adset_name"),
                d.get("ad_id"), d.get("ad_name"),
                d.get("publisher_platform"), d.get("platform_position"),
                float(d.get("spend") or 0), int(d.get("impressions") or 0),
                int(d.get("clicks") or 0), _extract_purchases(d.get("actions")),
                json.dumps(d, ensure_ascii=False), fetched_at,
            ))
        url = (data.get("paging") or {}).get("next")
        params = None

    if rows:
        conn = get_connection()
        try:
            conn.executemany(
                """
                INSERT INTO ad_detail (
                    date_jst, campaign_id, campaign_name, adset_id, adset_name,
                    ad_id, ad_name, platform, position, spend, impressions,
                    clicks, conversions, raw_json, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(ad_id, date_jst, platform, position) DO UPDATE SET
                    campaign_id   = excluded.campaign_id,
                    campaign_name = excluded.campaign_name,
                    adset_name    = excluded.adset_name,
                    ad_name       = excluded.ad_name,
                    spend         = excluded.spend,
                    impressions   = excluded.impressions,
                    clicks        = excluded.clicks,
                    conversions   = excluded.conversions,
                    raw_json      = excluded.raw_json,
                    fetched_at    = excluded.fetched_at
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()
    return len(rows)


def _action_value(actions: list | None, name: str) -> float:
    for a in actions or []:
        if a.get("action_type") == name:
            try:
                return float(a.get("value", 0))
            except (TypeError, ValueError):
                return 0.0
    return 0.0


def fetch_meta_assets(days: int = 90, since: str | None = None) -> int:
    """広告内の画像/動画アセット別の実績を ad_asset へ保存する。
    どの画像・動画が流入/購入につながったかを見るため。"""
    load_dotenv()
    token = os.getenv("META_ACCESS_TOKEN")
    account = os.getenv("META_AD_ACCOUNT_ID")
    if not token or not account:
        raise RuntimeError("META_ACCESS_TOKEN / META_AD_ACCOUNT_ID が未設定です。")
    account = _normalize_account(account)
    since_str, until_str = _date_range(days, since)
    base = f"https://graph.facebook.com/{API_VERSION}/{account}/insights"
    fetched_at = datetime.now(timezone.utc).isoformat()
    rows: list[tuple] = []

    # 画像と動画は別ブレイクダウン（同時指定不可）なので2回取得
    for asset_type, breakdown in (("image", "image_asset"), ("video", "video_asset")):
        params: dict | None = {
            "access_token": token, "level": "ad", "breakdowns": breakdown,
            "time_increment": 1,
            "time_range": json.dumps({"since": since_str, "until": until_str}),
            "fields": "ad_id,ad_name,impressions,clicks,spend,actions",
            "limit": 500,
        }
        url = base
        while url:
            resp = requests.get(url, params=params, timeout=60)
            data = resp.json()
            if "error" in data:
                # アセット別非対応の広告のみの場合もあるので、エラーは握って継続
                break
            for d in data.get("data", []):
                asset = d.get(breakdown) or {}
                asset_id = (asset.get("id") or asset.get("video_id")
                            or asset.get("hash") or "")
                if not asset_id:
                    continue
                actions = d.get("actions")
                rows.append((
                    d["date_start"], d.get("ad_id"), d.get("ad_name"),
                    asset_type, asset_id, asset.get("name"), asset.get("url"),
                    int(d.get("impressions") or 0), int(d.get("clicks") or 0),
                    float(d.get("spend") or 0),
                    int(_action_value(actions, "link_click")),
                    int(_action_value(actions, "landing_page_view")),
                    _extract_purchases(actions),
                    json.dumps(d, ensure_ascii=False), fetched_at,
                ))
            url = (data.get("paging") or {}).get("next")
            params = None

    if rows:
        conn = get_connection()
        try:
            conn.executemany(
                """
                INSERT INTO ad_asset (
                    date_jst, ad_id, ad_name, asset_type, asset_id, asset_name,
                    asset_url, impressions, clicks, spend, link_clicks,
                    landing_views, purchases, raw_json, fetched_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(ad_id, date_jst, asset_type, asset_id) DO UPDATE SET
                    ad_name       = excluded.ad_name,
                    asset_name    = excluded.asset_name,
                    asset_url     = excluded.asset_url,
                    impressions   = excluded.impressions,
                    clicks        = excluded.clicks,
                    spend         = excluded.spend,
                    link_clicks   = excluded.link_clicks,
                    landing_views = excluded.landing_views,
                    purchases     = excluded.purchases,
                    raw_json      = excluded.raw_json,
                    fetched_at    = excluded.fetched_at
                """,
                rows,
            )
            conn.commit()
        finally:
            conn.close()
    return len(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Meta広告 実績取得")
    parser.add_argument("--days", type=int, default=90, help="直近N日（既定90）")
    parser.add_argument("--since", type=str, help="YYYY-MM-DD 以降")
    args = parser.parse_args()

    init_db()
    started = datetime.now(timezone.utc).isoformat()
    try:
        n = fetch_meta_detail(days=args.days, since=args.since)
        a = fetch_meta_assets(days=args.days, since=args.since)
        log_sync("meta", "ok", n + a, started_at=started)
        print(f"[meta] 広告明細 {n} 行 / アセット {a} 行を取り込みました。")
    except Exception as e:  # noqa: BLE001
        log_sync("meta", "error", 0, message=str(e), started_at=started)
        print(f"[meta] エラー: {e}", file=sys.stderr)
        raise


if __name__ == "__main__":
    main()
