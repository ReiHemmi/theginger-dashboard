-- THE GINGER D2C ダッシュボード スキーマ
-- すべてのデータ源をこの1ファイル(SQLite)に集約する。

-- 注文（売上）: Stripe / BASE を共通の形でためる
CREATE TABLE IF NOT EXISTS orders (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    channel            TEXT    NOT NULL,           -- 'stripe' / 'base'
    external_id        TEXT    NOT NULL,           -- charge id / order id
    order_datetime_utc TEXT    NOT NULL,           -- ISO8601 (UTC)
    order_date_jst     TEXT    NOT NULL,           -- YYYY-MM-DD (日本時間)
    customer_id        TEXT,
    customer_email     TEXT,
    gross_amount       REAL    NOT NULL,           -- 売上総額(円)
    fee_amount         REAL    NOT NULL DEFAULT 0, -- 決済手数料(円)
    net_amount         REAL,                       -- 入金額(円)
    currency           TEXT    NOT NULL DEFAULT 'jpy',
    status             TEXT,                       -- succeeded / refunded ...
    is_refunded        INTEGER NOT NULL DEFAULT 0, -- 0/1
    description        TEXT,
    raw_json           TEXT,                       -- 元データ(後から項目を増やせるよう保持)
    fetched_at         TEXT    NOT NULL,
    UNIQUE(channel, external_id)
);
CREATE INDEX IF NOT EXISTS idx_orders_date    ON orders(order_date_jst);
CREATE INDEX IF NOT EXISTS idx_orders_channel ON orders(channel);
CREATE INDEX IF NOT EXISTS idx_orders_email   ON orders(customer_email);

-- 広告費（フェーズ1以降: Meta広告などをここへ）
CREATE TABLE IF NOT EXISTS ad_spend (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT    NOT NULL,                  -- 'meta' ...
    date_jst    TEXT    NOT NULL,                  -- YYYY-MM-DD
    campaign    TEXT,
    spend       REAL    NOT NULL DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    clicks      INTEGER DEFAULT 0,
    conversions REAL    DEFAULT 0,
    raw_json    TEXT,
    fetched_at  TEXT    NOT NULL,
    UNIQUE(channel, date_jst, campaign)
);

-- 広告プラットフォーム別（Meta）: 日次×配信面（Instagram/Facebook等）
CREATE TABLE IF NOT EXISTS ad_platform (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT    NOT NULL DEFAULT 'meta',
    date_jst    TEXT    NOT NULL,
    platform    TEXT,                            -- facebook / instagram ...
    spend       REAL    DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    clicks      INTEGER DEFAULT 0,
    conversions REAL    DEFAULT 0,
    raw_json    TEXT,
    fetched_at  TEXT    NOT NULL,
    UNIQUE(channel, date_jst, platform)
);
CREATE INDEX IF NOT EXISTS idx_adplatform_date ON ad_platform(date_jst);

-- 広告 配信面×掲載位置（Meta）: Instagram Feed/Stories/Reels 等の詳細
CREATE TABLE IF NOT EXISTS ad_placement (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT    NOT NULL DEFAULT 'meta',
    date_jst    TEXT    NOT NULL,
    platform    TEXT,                            -- facebook / instagram ...
    position    TEXT,                            -- feed / story / reels ...
    spend       REAL    DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    clicks      INTEGER DEFAULT 0,
    conversions REAL    DEFAULT 0,
    raw_json    TEXT,
    fetched_at  TEXT    NOT NULL,
    UNIQUE(channel, date_jst, platform, position)
);
CREATE INDEX IF NOT EXISTS idx_adplacement_date ON ad_placement(date_jst);

-- 広告 明細（Meta・level=ad）: 広告(クリエイティブ)×配信面×掲載位置×日次
-- campaign_id 等の安定IDで管理（キャンペーン改名による二重計上を防ぐ）。
-- これ1つで キャンペーン/広告セット/クリエイティブ/配信面/掲載位置 すべて集計可能。
CREATE TABLE IF NOT EXISTS ad_detail (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date_jst      TEXT    NOT NULL,
    campaign_id   TEXT,
    campaign_name TEXT,
    adset_id      TEXT,
    adset_name    TEXT,
    ad_id         TEXT,
    ad_name       TEXT,
    platform      TEXT,
    position      TEXT,
    spend         REAL    DEFAULT 0,
    impressions   INTEGER DEFAULT 0,
    clicks        INTEGER DEFAULT 0,
    link_clicks   INTEGER DEFAULT 0,               -- リンククリック（外部遷移）
    landing_views INTEGER DEFAULT 0,               -- LP表示（広告由来でLPが開かれた数）
    view_content  INTEGER DEFAULT 0,               -- 読了（LP80%スクロールのViewContent・広告由来）
    conversions   REAL    DEFAULT 0,
    raw_json      TEXT,
    fetched_at    TEXT    NOT NULL,
    UNIQUE(ad_id, date_jst, platform, position)
);
CREATE INDEX IF NOT EXISTS idx_addetail_date ON ad_detail(date_jst);
CREATE INDEX IF NOT EXISTS idx_addetail_camp ON ad_detail(campaign_id);

-- 広告 アセット別（Meta・画像/動画クリエイティブ）: 広告内のどの画像・動画が効くか
CREATE TABLE IF NOT EXISTS ad_asset (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    date_jst      TEXT    NOT NULL,
    ad_id         TEXT,
    ad_name       TEXT,
    asset_type    TEXT,                            -- image / video
    asset_id      TEXT,
    asset_name    TEXT,                            -- 元ファイル名等
    asset_url     TEXT,                            -- 画像サムネURL（動画は不可）
    impressions   INTEGER DEFAULT 0,
    clicks        INTEGER DEFAULT 0,
    spend         REAL    DEFAULT 0,
    link_clicks   INTEGER DEFAULT 0,               -- リンククリック（流入）
    landing_views INTEGER DEFAULT 0,               -- LP到達
    purchases     REAL    DEFAULT 0,
    raw_json      TEXT,
    fetched_at    TEXT    NOT NULL,
    UNIQUE(ad_id, date_jst, asset_type, asset_id)
);
CREATE INDEX IF NOT EXISTS idx_adasset_date ON ad_asset(date_jst);
CREATE INDEX IF NOT EXISTS idx_adasset_ad ON ad_asset(ad_id);

-- 流入（GA4）: 日次×チャネル別のアクセス・ファネル指標
CREATE TABLE IF NOT EXISTS traffic (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    source           TEXT    NOT NULL DEFAULT 'ga4',
    date_jst         TEXT    NOT NULL,
    channel          TEXT,                          -- 流入チャネル（Paid Social等）
    hostname         TEXT,                          -- LP(reihemmi.github.io)/BASE等
    sessions         INTEGER DEFAULT 0,
    users            INTEGER DEFAULT 0,
    new_users        INTEGER DEFAULT 0,
    engaged_sessions INTEGER DEFAULT 0,
    conversions      REAL    DEFAULT 0,
    raw_json         TEXT,
    fetched_at       TEXT    NOT NULL,
    UNIQUE(source, date_jst, channel, hostname)
);
CREATE INDEX IF NOT EXISTS idx_traffic_date ON traffic(date_jst);

-- GA4 イベント別（日次）: scroll / page_view など。ファネルのスクロール段階に使用
CREATE TABLE IF NOT EXISTS ga4_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date_jst    TEXT    NOT NULL,
    event_name  TEXT    NOT NULL,
    hostname    TEXT,
    event_count INTEGER DEFAULT 0,
    fetched_at  TEXT    NOT NULL,
    UNIQUE(date_jst, event_name, hostname)
);
CREATE INDEX IF NOT EXISTS idx_ga4events_date ON ga4_events(date_jst);

-- メルマガ→ショップ流入（GA4・campaign別）: utm_source=newsletter のセッション数
CREATE TABLE IF NOT EXISTS newsletter_clicks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date_jst    TEXT    NOT NULL,
    campaign    TEXT,                            -- utm_campaign（vol1, vol2 ...）
    hostname    TEXT,                            -- 着地ホスト（theginger.theshop.jp 等）
    sessions    INTEGER DEFAULT 0,
    users       INTEGER DEFAULT 0,
    fetched_at  TEXT    NOT NULL,
    UNIQUE(date_jst, campaign, hostname)
);
CREATE INDEX IF NOT EXISTS idx_nl_date ON newsletter_clicks(date_jst);

-- 自然検索（Search Console）: 日次×検索キーワード別
CREATE TABLE IF NOT EXISTS search_console (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    date_jst    TEXT    NOT NULL,
    query       TEXT,
    clicks      INTEGER DEFAULT 0,
    impressions INTEGER DEFAULT 0,
    ctr         REAL    DEFAULT 0,
    position    REAL    DEFAULT 0,
    raw_json    TEXT,
    fetched_at  TEXT    NOT NULL,
    UNIQUE(date_jst, query)
);
CREATE INDEX IF NOT EXISTS idx_sc_date ON search_console(date_jst);

-- 同期ログ（いつ・何件取れたかの記録。トラブル時の確認用）
CREATE TABLE IF NOT EXISTS sync_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source        TEXT    NOT NULL,
    started_at    TEXT    NOT NULL,
    finished_at   TEXT,
    status        TEXT,                            -- ok / error
    rows_upserted INTEGER DEFAULT 0,
    message       TEXT
);
