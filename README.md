# THE GINGER D2C ダッシュボード

THE GINGER（ハーブティーD2C）の数値を1画面に集約する自作ダッシュボード。
広告→LP/ショップ→購入の流れを見える化し、**どこに絞るか**を判断するための道具。

## 構成

```
データ源 → 収集スクリプト(Python) → SQLite(data/dashboard.db) → Streamlit画面
```

- **collectors/** … 各データ源の取得スクリプト（stripe / meta / ga4 / search_console / base）
- **lib/db.py** … SQLite 接続・初期化
- **db/schema.sql** … テーブル定義
- **app/dashboard.py** … 画面（Streamlit）
- **run_daily.py** / **run_daily.bat** … 毎日の自動実行（タスクスケジューラから呼ぶ）
- **secrets/** … 認証情報（Google鍵JSON・BASEトークン。gitignore済）

## データ源（接続状況）

| 源 | 取得内容 | 認証 |
|----|---------|------|
| Stripe | LP直販の売上・顧客 | `STRIPE_API_KEY`（制限付き読取） |
| Meta広告 | 広告費・表示・クリック・CV・**配信面別(IG/FB/Threads)** | `META_ACCESS_TOKEN`（60日・要再発行） |
| GA4 | 流入・チャネル別・CVR | サービスアカウント鍵 + `GA4_PROPERTY_ID` |
| Search Console | 自然検索（現状未使用） | 同上 + `SEARCH_CONSOLE_SITE_URL` |
| BASE | ショップ売上 | OAuth（`secrets/base_token.json`・自動更新） |

## ダッシュボードの見方

1. **主要KPI** … 売上 / 広告費 / ROAS / CVR / CPA / CAC / AOV / LTV:CAC
2. **今の打ち手** … データから自動生成する所見（収益性・ボトルネック・予算配分）
3. **ファネル** … 表示→クリック→流入→購入。離脱箇所(ボトルネック)を可視化
4. **ユニットエコノミクス** … 粗利・LTV・損益分岐ROAS（前提はサイドバーで調整）
5. **広告 配信面別** … Instagram / Facebook / Threads の効率比較（予算配分判断）
6. **広告 キャンペーン別** / **流入チャネル(GA4)** / **売上(チャネル別・日次)**

前提（サイドバー）：**粗利率62%（原価率38%想定）**・想定生涯購入回数。変更で即再計算。

## セットアップ

```powershell
& "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe" -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`.env` に各認証情報を設定する（`.env.example` 参照）。

## 使い方

```powershell
# データ取り込み（全部）
.\.venv\Scripts\python.exe run_daily.py

# 画面を起動
.\.venv\Scripts\streamlit.exe run app/dashboard.py
```

毎朝7:00にタスク `TheGingerDashboardDaily` が `run_daily.bat` を自動実行（PC起動が必要）。

## ロードマップ

- [x] フェーズ0: Stripe（LP直販の売上）
- [x] フェーズ1: Meta広告（ROAS・CAC・配信面別）
- [x] フェーズ2: GA4（ファネル・流入）※Search Consoleは自然検索ほぼ無のため未使用
- [x] フェーズ3: BASE（全チャネル売上合算）
- [x] 毎日自動更新（タスクスケジューラ）
- [ ] フェーズ4: 原価データ連携（注文ごとの本当の利益）
