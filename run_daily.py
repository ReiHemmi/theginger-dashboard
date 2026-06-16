"""毎日の自動実行エントリ。タスクスケジューラからこれを呼ぶ。

各データ源は .env に認証情報があるものだけ実行する（未設定はスキップ）。
今後 GA4 / SearchConsole / BASE を足していく。
"""
from __future__ import annotations

import os
import sys

from dotenv import load_dotenv

from lib.db import init_db, log_sync
from collectors import (
    stripe_collector, meta_collector,
    ga4_collector, search_console_collector, base_collector,
)


def main() -> int:
    load_dotenv()
    init_db()
    failures: list[tuple[str, str]] = []

    # --- Stripe（直近35日を取り直して返金等の変化も反映）---
    if os.getenv("STRIPE_API_KEY"):
        try:
            n = stripe_collector.fetch_stripe(days=35)
            log_sync("stripe", "ok", n)
            print(f"[stripe] {n} 件")
        except Exception as e:  # noqa: BLE001
            failures.append(("stripe", str(e)))
            print(f"[stripe] エラー: {e}", file=sys.stderr)
    else:
        print("[stripe] スキップ（キー未設定）")

    # --- Meta広告（直近35日）---
    if os.getenv("META_ACCESS_TOKEN") and os.getenv("META_AD_ACCOUNT_ID"):
        try:
            n = meta_collector.fetch_meta_detail(days=35)
            a = meta_collector.fetch_meta_assets(days=35)
            log_sync("meta", "ok", n + a)
            print(f"[meta] 広告明細{n}行 / アセット{a}行")
        except Exception as e:  # noqa: BLE001
            failures.append(("meta", str(e)))
            print(f"[meta] エラー: {e}", file=sys.stderr)
    else:
        print("[meta] スキップ（トークン未設定）")

    # --- GA4（直近35日）---
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and os.getenv("GA4_PROPERTY_ID"):
        try:
            n = ga4_collector.fetch_ga4(days=35)
            e = ga4_collector.fetch_ga4_events(days=35)
            log_sync("ga4", "ok", n + e)
            print(f"[ga4] 流入{n}行 / イベント{e}行")
        except Exception as e:  # noqa: BLE001
            failures.append(("ga4", str(e)))
            print(f"[ga4] エラー: {e}", file=sys.stderr)
    else:
        print("[ga4] スキップ（認証未設定）")

    # --- Search Console（直近35日）---
    if os.getenv("GOOGLE_APPLICATION_CREDENTIALS") and os.getenv("SEARCH_CONSOLE_SITE_URL"):
        try:
            n = search_console_collector.fetch_search_console(days=35)
            log_sync("search_console", "ok", n)
            print(f"[search_console] {n} 行")
        except Exception as e:  # noqa: BLE001
            failures.append(("search_console", str(e)))
            print(f"[search_console] エラー: {e}", file=sys.stderr)
    else:
        print("[search_console] スキップ（認証未設定）")

    # --- BASE（直近35日）---
    if os.getenv("BASE_CLIENT_ID") and os.path.exists(
            os.path.join("secrets", "base_token.json")):
        try:
            n = base_collector.fetch_base(days=35)
            log_sync("base", "ok", n)
            print(f"[base] {n} 件")
        except Exception as e:  # noqa: BLE001
            failures.append(("base", str(e)))
            print(f"[base] エラー: {e}", file=sys.stderr)
    else:
        print("[base] スキップ（未認証）")

    if failures:
        print(f"\n失敗: {len(failures)} 件 -> {failures}", file=sys.stderr)
        return 1
    print("\nすべて完了しました。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
