"""THE GINGER D2C ダッシュボード（Streamlit）。

D2C物販ブランドの広告改善・意思決定（どこに絞るか）のためのダッシュボード。
広告→流入→購入のファネル、ユニットエコノミクス（CPA/LTV）、配信面別・
チャネル別の成果を1画面で把握する。

起動:
    streamlit run app/dashboard.py
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from lib.db import get_connection, init_db  # noqa: E402

st.set_page_config(page_title="THE GINGER ダッシュボード", page_icon="🌿",
                   layout="wide")

GOLD = "#C9A017"
INK = "#3a342c"
LP_HOST = "reihemmi.github.io"   # 広告のLP。GA4はBASEショップと混在するためLPに絞る

# ──────────────────────────────────────────────
# データ読み込み
# ──────────────────────────────────────────────
@st.cache_data(ttl=300)
def _q(sql: str) -> pd.DataFrame:
    init_db()
    conn = get_connection()
    try:
        return pd.read_sql_query(sql, conn)
    finally:
        conn.close()


def load_orders() -> pd.DataFrame:
    df = _q("SELECT channel, external_id, order_date_jst, customer_id, "
            "customer_email, gross_amount, fee_amount, net_amount, "
            "is_refunded FROM orders")
    if not df.empty:
        df["order_date_jst"] = pd.to_datetime(df["order_date_jst"]).dt.date
        df["cust_key"] = (df["customer_email"].fillna(df["customer_id"])
                          .fillna(df["external_id"]))
    return df


def load_ad_detail() -> pd.DataFrame:
    """広告明細（広告×配信面×掲載位置×日次）。キャンペーンIDで管理＝改名でも二重計上なし。"""
    df = _q("SELECT date_jst, campaign_id, campaign_name, adset_name, ad_name, "
            "platform, position, spend, impressions, clicks, conversions "
            "FROM ad_detail")
    if not df.empty:
        df["date_jst"] = pd.to_datetime(df["date_jst"]).dt.date
    return df


def load_ad_asset() -> pd.DataFrame:
    """広告内の画像/動画アセット別の実績。"""
    df = _q("SELECT date_jst, ad_id, ad_name, asset_type, asset_id, asset_name, "
            "asset_url, impressions, clicks, spend, link_clicks, landing_views, "
            "purchases FROM ad_asset")
    if not df.empty:
        df["date_jst"] = pd.to_datetime(df["date_jst"]).dt.date
    return df


def load_traffic() -> pd.DataFrame:
    df = _q("SELECT date_jst, channel, hostname, sessions, users, new_users, "
            "engaged_sessions, conversions FROM traffic")
    if not df.empty:
        df["date_jst"] = pd.to_datetime(df["date_jst"]).dt.date
    return df


def load_ga4_events() -> pd.DataFrame:
    df = _q("SELECT date_jst, event_name, hostname, event_count FROM ga4_events")
    if not df.empty:
        df["date_jst"] = pd.to_datetime(df["date_jst"]).dt.date
    return df


def load_excluded() -> dict:
    """集計から除外する顧客（テスト購入等）。config/excluded_customers.json。"""
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "config", "excluded_customers.json")
    try:
        import json
        with open(path, encoding="utf-8") as f:
            d = json.load(f)
        return {"emails": [e.lower() for e in d.get("emails", [])],
                "order_ids": [str(i) for i in d.get("order_ids", [])]}
    except Exception:
        return {"emails": [], "order_ids": []}


def yen(v: float) -> str:
    return f"¥{v:,.0f}"


def pct(v: float) -> str:
    return f"{v:.1f}%"


def clip(df: pd.DataFrame, col: str, s: date, e: date) -> pd.DataFrame:
    if df.empty:
        return df
    return df[(df[col] >= s) & (df[col] <= e)]


# ──────────────────────────────────────────────
# ヘッダー & サイドバー
# ──────────────────────────────────────────────
st.title("🌿 THE GINGER ダッシュボード")
st.caption("広告→流入→購入を全チャネルで集約。毎朝7時に自動更新。")

orders = load_orders()
if orders.empty:
    st.info("まだデータがありません。`python run_daily.py` を実行してください。")
    st.stop()

# 除外（テスト購入・関係者）を集計から外す
_excl = load_excluded()
_email_lc = orders["customer_email"].fillna("").str.lower()
_excl_mask = _email_lc.isin(_excl["emails"]) | orders["external_id"].astype(str).isin(_excl["order_ids"])
excluded_orders = orders[_excl_mask].copy()
orders = orders[~_excl_mask].copy()

addet = load_ad_detail()
adasset = load_ad_asset()
traffic = load_traffic()
events = load_ga4_events()

min_d = orders["order_date_jst"].min()
maxes = [orders["order_date_jst"].max()]
for d in (addet, traffic):
    if not d.empty:
        maxes.append(d["date_jst"].max())
        min_d = min(min_d, d["date_jst"].min())
max_d = max(maxes)

with st.sidebar:
    st.header("表示設定")
    preset = st.radio("期間", ["過去7日", "過去30日", "過去90日", "全期間", "カスタム"],
                      index=1)
    if preset == "過去7日":
        start, end = max_d - timedelta(days=6), max_d
    elif preset == "過去30日":
        start, end = max_d - timedelta(days=29), max_d
    elif preset == "過去90日":
        start, end = max_d - timedelta(days=89), max_d
    elif preset == "全期間":
        start, end = min_d, max_d
    else:
        start = st.date_input("開始", value=max(min_d, max_d - timedelta(days=29)),
                              min_value=min_d, max_value=max_d)
        end = st.date_input("終了", value=max_d, min_value=min_d, max_value=max_d)
    start = max(start, min_d)

    st.divider()
    st.header("広告キャンペーン")
    all_campaigns = (sorted(addet["campaign_name"].dropna().unique().tolist())
                     if not addet.empty else [])
    # 既定は「売上/販売」目的のキャンペーンのみ（需要検証・アンケート等は外す）
    sales_default = [c for c in all_campaigns
                     if ("売上" in c) or ("販売" in c)] or all_campaigns
    sel_campaigns = st.multiselect(
        "① キャンペーン（販売広告だけに絞れます）",
        options=all_campaigns, default=sales_default,
        help="アンケート/需要検証など販売以外の広告を外して比較できます。")
    all_adsets = (sorted(addet["adset_name"].dropna().unique().tolist())
                  if not addet.empty else [])
    # 既定は販売目的（名前に売上/販売を含む）の広告セットのみ
    adset_default = [s for s in all_adsets
                     if ("売上" in s) or ("販売" in s)] or all_adsets
    sel_adsets = st.multiselect("② 広告セット", options=all_adsets,
                                default=adset_default)
    all_ads = (sorted(addet["ad_name"].dropna().unique().tolist())
               if not addet.empty else [])
    # 既定はLP①のみ（販売広告。比較したい時に②等をサイドバーで追加）
    ad_default = ([a for a in all_ads if "LP①" in a]
                  or [a for a in all_ads if ("売上" in a) or ("販売" in a)]
                  or all_ads)
    sel_ads = st.multiselect(
        "③ 広告（クリエイティブ）", options=all_ads, default=ad_default,
        help="例：LP①だけに絞ると、以降の数字・アセット分析がLP①だけになります。")

    st.divider()
    st.header("前提（試算用）")
    st.caption("下の「ユニットエコノミクス（試算）」のLTV・損益分岐ROASにのみ反映。"
               "上の主要KPI（実績）には影響しません。")
    margin = st.slider("粗利率（％）", 30, 90, 62,
                       help="原価率38%想定 → 粗利率62%") / 100
    ltv_orders = st.slider("想定 生涯購入回数", 1.0, 5.0, 1.5, 0.1,
                           help="1人の顧客が生涯で買う回数の想定。LTV試算に使用")

# 期間で切り出し
o = clip(orders, "order_date_jst", start, end)
o = o[o["is_refunded"] == 0].copy()
# 広告明細：期間＋階層（キャンペーン→広告セット→広告）で絞る
adD = clip(addet, "date_jst", start, end)
if not adD.empty and sel_campaigns:
    adD = adD[adD["campaign_name"].isin(sel_campaigns)]
if not adD.empty and sel_adsets:
    adD = adD[adD["adset_name"].isin(sel_adsets)]
if not adD.empty and sel_ads:
    adD = adD[adD["ad_name"].isin(sel_ads)]
# アセット（画像/動画）：期間＋選択広告で絞る
asD = clip(adasset, "date_jst", start, end)
if not asD.empty and sel_ads:
    asD = asD[asD["ad_name"].isin(sel_ads)]
trP = clip(traffic, "date_jst", start, end)

# 基本集計
gross = o["gross_amount"].sum()
orders_n = len(o)
aov = gross / orders_n if orders_n else 0
spend = adD["spend"].sum() if not adD.empty else 0
impressions = int(adD["impressions"].sum()) if not adD.empty else 0
clicks = int(adD["clicks"].sum()) if not adD.empty else 0
# GA4はLP(reihemmi.github.io)とBASEショップが混在 → LPに絞る
trP_lp = trP[trP["hostname"] == LP_HOST] if not trP.empty else trP
lp_sessions = int(trP_lp["sessions"].sum()) if not trP_lp.empty else 0
base_sessions = (int(trP[trP["hostname"] != LP_HOST]["sessions"].sum())
                 if not trP.empty else 0)
sessions = lp_sessions   # 以降「流入」はLPのみ

evP = clip(events, "date_jst", start, end)
evP_lp = evP[evP["hostname"] == LP_HOST] if not evP.empty else evP


def ev_count(name: str) -> int:
    if evP_lp.empty:
        return 0
    return int(evP_lp[evP_lp["event_name"] == name]["event_count"].sum())


scrolls = ev_count("scroll")
# LP流入はほぼ全てが広告経由（自然流入はほぼ0と確認済み）のため、LP流入=広告流入とみなす
paid_sessions = lp_sessions
# LP直販(Stripe)の購入数。ファネルの購入段階に使用
stripe_orders = int((o["channel"] == "stripe").sum()) if not o.empty else 0

# 新規/リピート（全期間基準で初回判定）
all_ok = orders[orders["is_refunded"] == 0]
first_order = all_ok.groupby("cust_key")["order_date_jst"].min()
if o.empty:
    o["is_first"] = pd.Series(dtype=bool)
    new_n = 0
else:
    o["is_first"] = o.apply(
        lambda r: first_order.get(r["cust_key"]) == r["order_date_jst"], axis=1)
    new_n = int(o["is_first"].sum())
repeat_n = orders_n - new_n

roas = gross / spend if spend else 0
cpa = spend / orders_n if orders_n else 0          # 1注文あたり広告費
cac = spend / new_n if new_n else 0                # 新規顧客獲得単価
cvr = stripe_orders / lp_sessions * 100 if lp_sessions else 0  # LP→Stripe購入率
ctr_top = clicks / impressions * 100 if impressions else 0     # 広告クリック率
breakeven_roas = 1 / margin if margin else 0
contrib_per_order = aov * margin                    # 1注文の粗利（変動費前の貢献）
ltv = aov * ltv_orders                              # 売上ベースLTV
ltv_contrib = ltv * margin                          # 粗利ベースLTV
ltv_cac = ltv_contrib / cac if cac else 0

st.caption(f"対象期間：{start} 〜 {end}")
if not excluded_orders.empty:
    _ex = excluded_orders[excluded_orders["is_refunded"] == 0]
    st.caption(f"🧪 集計から除外中：テスト/関係者の購入 {len(_ex)}件・"
               f"{yen(_ex['gross_amount'].sum())}（全期間）"
               f"／設定: config/excluded_customers.json")

# ──────────────────────────────────────────────
# 1. 主要KPI（すべて実績ベース＝追いかけるべき実数）
# ──────────────────────────────────────────────
st.subheader("主要KPI（すべて実績ベース）")
st.caption("試算の前提（粗利率・生涯購入回数）には左右されない、日々追いかける実数です。"
           "LTV・損益分岐など前提を置く試算は下の「ユニットエコノミクス」に分離しています。")
k = st.columns(4)
k[0].metric("売上（全チャネル）", yen(gross))
k[1].metric("広告費", yen(spend))
k[2].metric("ROAS（売上÷広告費）", f"{roas:.2f}")
k[3].metric("AOV（平均注文単価）", yen(aov))
k2 = st.columns(4)
k2[0].metric("注文数", f"{orders_n} 件")
k2[1].metric("新規顧客", f"{new_n} 人")
k2[2].metric("CPA（1注文あたり広告費）", yen(cpa))
k2[3].metric("CAC（新規獲得単価）", yen(cac))
k3 = st.columns(4)
k3[0].metric("CVR（LP流入→購入）", pct(cvr))
k3[1].metric("CTR（広告クリック率）", pct(ctr_top))
k3[2].metric("広告クリック", f"{clicks:,}")
k3[3].metric("LP流入", f"{lp_sessions:,}")

# 自動所見（どこに絞るか）— ボトルネックは実績ベースの率で判定
actions = []
_read = scrolls / paid_sessions * 100 if paid_sessions else 100
_scv = orders_n / scrolls * 100 if scrolls else 0
if impressions and (clicks / impressions * 100) < 1.0:
    actions.append("**最優先ボトルネック**：クリック率(CTR)が低い。"
                   "広告クリエイティブ／配信面の見直しが先（配信面別の表を参照）。")
elif paid_sessions and scrolls and _read < 40:
    actions.append(f"**最優先ボトルネック**：読了率 **{_read:.0f}%**（LPの冒頭で離脱）。"
                   f"改善すべきは**ファーストビュー（最初の画面）の訴求・表示速度**。")
elif scrolls and _scv < 3:
    actions.append(f"**最優先ボトルネック**：読んでも買わない（スクロール→購入 "
                   f"**{_scv:.1f}%**）。**オファー・価格・CTA・購入導線（カゴ落ち）**を見直し。")
elif sessions and cvr < 2.0:
    actions.append(f"**最優先ボトルネック**：購入率 CVR **{cvr:.1f}%**。"
                   f"LP・オファー・価格の改善余地が大きい。")
if not adD.empty:
    gg = (adD.groupby("platform")
          .agg(s=("spend", "sum"), i=("impressions", "sum"),
               c=("clicks", "sum")))
    gg["ctr"] = gg["c"] / gg["i"] * 100
    if len(gg) > 1:
        best, worst = gg["ctr"].idxmax(), gg["ctr"].idxmin()
        if gg.loc[worst, "s"] > 0 and gg.loc[worst, "ctr"] < gg.loc[best, "ctr"] / 2:
            actions.append(
                f"**予算配分**：配信面は **{best}**（CTR {gg.loc[best,'ctr']:.1f}%）が効率的。"
                f"**{worst}** はCTR {gg.loc[worst,'ctr']:.1f}% と低く "
                f"{yen(gg.loc[worst,'s'])} を消費。配分見直しの候補。")
if actions:
    st.markdown("#### 💡 今の打ち手（データからの所見）")
    for a in actions:
        st.markdown(f"- {a}")

st.divider()

# ──────────────────────────────────────────────
# 2. ファネル（ボトルネック把握）
# ──────────────────────────────────────────────
st.subheader("広告ファネル（広告 → LP → 購入の流れ）")
st.caption(f"LP（{LP_HOST}）の広告経由フロー。GA4のBASEショップ分は除外済み。"
           f"LP流入はほぼ全て広告経由（自然流入はほぼ0）。")
fc1, fc2 = st.columns([3, 2])

stages = ["広告表示", "広告クリック", "LP流入", "スクロール(90%)", "購入(LP直販)"]
values = [impressions, clicks, lp_sessions, scrolls, stripe_orders]
with fc1:
    if impressions or sessions:
        fig = go.Figure(go.Funnel(
            y=stages, x=values,
            textinfo="value+percent initial",
            marker={"color": [GOLD, "#d9b94a", "#e6cf86", "#cdaa5e", "#b0894f"]},
            connector={"line": {"color": "#e7dcc6"}},
        ))
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10), height=340,
                          paper_bgcolor="rgba(0,0,0,0)",
                          font=dict(color=INK, size=13))
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("ファネル表示にはMeta広告とGA4のデータが必要です。")

with fc2:
    ctr = clicks / impressions * 100 if impressions else 0
    read_rate = scrolls / lp_sessions * 100 if lp_sessions else 0       # LP流入→スクロール
    scroll_cvr = stripe_orders / scrolls * 100 if scrolls else 0        # スクロール→購入
    lp_cvr = stripe_orders / lp_sessions * 100 if lp_sessions else 0    # LP流入→購入
    st.markdown("**各段階の通過率**")
    rates = pd.DataFrame({
        "段階": ["表示 → クリック (CTR / 広告側)",
               "LP流入 → スクロール（読了率）",
               "スクロール → 購入",
               "LP流入 → 購入 (CVR / LP直販)"],
        "通過率": [pct(ctr), pct(read_rate), pct(scroll_cvr), pct(lp_cvr)],
    })
    st.dataframe(rates, use_container_width=True, hide_index=True)
    st.caption("※ 購入はLP直販(Stripe)。BASE経由は別経路のため除外。"
               "広告クリック(Meta)とLP流入(GA4)は別計測のため完全一致しません。")
    # ボトルネック指摘（スクロールで切り分け）
    bottleneck = None
    if impressions and ctr < 1.0:
        bottleneck = ("**表示→クリック**（CTR<1%）。広告クリエイティブ／配信面の問題。"
                      "配信面別の表でどの面が足を引っ張っているか確認を。")
    elif paid_sessions and read_rate < 40:
        bottleneck = ("**広告流入→スクロール**（読了率<40%）。LP冒頭で離脱。"
                      "ファーストビュー（最初の画面）の訴求・表示速度を見直し。")
    elif scrolls and scroll_cvr < 3:
        bottleneck = ("**スクロール→購入**（読んでも買わない）。"
                      "オファー・価格・CTA・購入導線（カゴ落ち）を見直し。")
    if bottleneck:
        st.warning(f"ボトルネック候補：{bottleneck}")

st.divider()

# ──────────────────────────────────────────────
# 3. ユニットエコノミクス（詳細）
# ──────────────────────────────────────────────
with st.expander("ユニットエコノミクス（試算：粗利率 "
                 f"{margin*100:.0f}% ／ 生涯購入 {ltv_orders} 回）", expanded=False):
    st.caption(f"⚠️ ここから下は前提（粗利率{margin*100:.0f}%・生涯購入{ltv_orders}回）"
               "を置いた**試算値**です。実績KPIとは別物。"
               "サイドバー「前提（試算用）」のスライダーで動かせます。")
    u = st.columns(4)
    u[0].metric("1注文の粗利", yen(contrib_per_order))
    u[1].metric("LTV（売上ベース）", yen(ltv))
    u[2].metric("LTV（粗利ベース）", yen(ltv_contrib))
    u[3].metric("損益分岐ROAS", f"{breakeven_roas:.2f}")
    u2 = st.columns(2)
    u2[0].metric("ROAS vs 損益分岐", f"{roas:.2f}", f"分岐 {breakeven_roas:.2f}",
                 delta_color="off")
    u2[1].metric("LTV:CAC", f"{ltv_cac:.2f}", "目標 3.0以上", delta_color="off")
    st.caption(
        "・損益分岐ROAS = 1 ÷ 粗利率。現状ROASがこれを超えれば広告は粗利で黒字。\n"
        "・LTV(粗利) = AOV × 生涯購入回数 × 粗利率。これがCACの3倍以上が健全の目安。\n"
        "・数値はサイドバーの前提（試算用）を変えると即再計算されます。"
    )
    # 試算ベースの判定メッセージ
    msgs = []
    if spend:
        if roas >= breakeven_roas:
            msgs.append(f"✅ ROAS {roas:.2f} は損益分岐 {breakeven_roas:.2f} を上回り、"
                        f"粗利ベースで黒字（前提：粗利率{margin*100:.0f}%）。")
        else:
            gap = (breakeven_roas / roas - 1) * 100 if roas else 0
            msgs.append(f"⚠️ ROAS {roas:.2f} は損益分岐 {breakeven_roas:.2f} を下回り赤字。"
                        f"黒字化には ROAS をあと約 **{gap:.0f}%** 改善が必要"
                        f"（or 粗利率/客単価UP）。")
    if cac and ltv_cac:
        if ltv_cac >= 3:
            msgs.append(f"✅ LTV:CAC {ltv_cac:.2f}（健全の目安3.0以上）。")
        else:
            msgs.append(f"⚠️ LTV:CAC {ltv_cac:.2f}。獲得単価に対し顧客価値が低い。"
                        f"CAC低減 or リピート（LTV）向上が必要。")
    for m in msgs:
        (st.success if m.startswith("✅") else st.warning)(m)

st.divider()

# ──────────────────────────────────────────────
# 4. 広告 配信面別（Instagram / Facebook / Threads）= どこに絞るか
# ──────────────────────────────────────────────
if not addet.empty:
    _scope = f"キャンペーン {len(sel_campaigns)}件"
    if all_ads and len(sel_ads) < len(all_ads):
        _scope += f" / 広告: {' , '.join(sel_ads)}"
    st.caption(f"広告セクションの対象：{_scope}（サイドバー①②③で変更可）")
st.subheader("広告：配信面別（どこに予算を寄せるか）")
if not adD.empty:
    g = (adD.groupby("platform")
         .agg(広告費=("spend", "sum"), 表示=("impressions", "sum"),
              クリック=("clicks", "sum"), CV=("conversions", "sum"))
         .reset_index().rename(columns={"platform": "配信面"}))
    g["CTR"] = (g["クリック"] / g["表示"] * 100).round(2)
    g["CPC"] = (g["広告費"] / g["クリック"]).round(0)
    g["費用比"] = (g["広告費"] / g["広告費"].sum() * 100).round(1)
    g = g.sort_values("広告費", ascending=False)

    pc1, pc2 = st.columns([3, 2])
    with pc1:
        show = g[["配信面", "広告費", "費用比", "表示", "クリック", "CTR", "CPC"]].copy()
        show["広告費"] = show["広告費"].map(yen)
        show["CPC"] = show["CPC"].map(lambda v: yen(v))
        show["費用比"] = show["費用比"].map(lambda v: f"{v}%")
        show["CTR"] = show["CTR"].map(lambda v: f"{v}%")
        st.dataframe(show, use_container_width=True, hide_index=True)
    with pc2:
        fig2 = go.Figure()
        fig2.add_bar(x=g["配信面"], y=g["広告費"], name="広告費",
                     marker_color=GOLD, yaxis="y1")
        fig2.add_scatter(x=g["配信面"], y=g["CTR"], name="CTR(%)",
                         mode="lines+markers", marker_color=INK, yaxis="y2")
        fig2.update_layout(
            height=260, margin=dict(l=10, r=10, t=30, b=10),
            paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
            yaxis=dict(title="広告費"),
            yaxis2=dict(title="CTR%", overlaying="y", side="right"),
            legend=dict(orientation="h", y=1.15), font=dict(color=INK),
        )
        st.plotly_chart(fig2, use_container_width=True)

    # 絞り込みヒント
    best = g.loc[g["CTR"].idxmax()]
    worst = g.loc[g["CTR"].idxmin()]
    st.info(
        f"💡 **{best['配信面']}** がCTR最高（{best['CTR']}%）。"
        f"一方 **{worst['配信面']}** はCTR {worst['CTR']}% で"
        f"広告費 {yen(worst['広告費'])} を消費。"
        f"成果の出る面に予算を寄せる判断材料に。"
    )
else:
    st.info("配信面別データがありません（Meta取得後に表示）。")

with st.expander("配信面 × 掲載位置（詳細）— どの面のどの枠が効いているか"):
    if not adD.empty:
        gp = (adD.groupby(["platform", "position"])
              .agg(広告費=("spend", "sum"), 表示=("impressions", "sum"),
                   クリック=("clicks", "sum"))
              .reset_index())
        gp = gp[gp["広告費"] > 0]
        gp["CTR(%)"] = (gp["クリック"] / gp["表示"] * 100).round(2)
        gp["CPC"] = gp.apply(
            lambda r: r["広告費"] / r["クリック"] if r["クリック"] else None, axis=1)
        gp = gp.sort_values("広告費", ascending=False).rename(
            columns={"platform": "配信面", "position": "掲載位置"})
        disp = gp.copy()
        disp["広告費"] = disp["広告費"].map(yen)
        disp["CPC"] = disp["CPC"].map(lambda v: yen(v) if pd.notna(v) else "-")
        st.dataframe(disp[["配信面", "掲載位置", "広告費", "表示", "クリック",
                           "CTR(%)", "CPC"]],
                     use_container_width=True, hide_index=True)
        # 拡大候補/削減候補
        spend_total = gp["広告費"].sum()
        cand = gp[(gp["表示"] >= 200)].copy()
        if not cand.empty:
            scale = cand.loc[cand["CTR(%)"].idxmax()]
            cut = cand.loc[cand["CTR(%)"].idxmin()]
            st.info(
                f"💡 **拡大候補**：{scale['配信面']} / {scale['掲載位置']}"
                f"（CTR {scale['CTR(%)']}%・費用 {yen(scale['広告費'])}）。"
                f"　**見直し候補**：{cut['配信面']} / {cut['掲載位置']}"
                f"（CTR {cut['CTR(%)']}%・費用 {yen(cut['広告費'])}）。")
    else:
        st.info("掲載位置別データがありません。")

st.divider()

# ──────────────────────────────────────────────
# 5. 広告 クリエイティブ別（どの広告が効いているか）
# ──────────────────────────────────────────────
st.subheader("広告：クリエイティブ別（どの広告が効いているか）")
if not adD.empty:
    gcr = (adD.groupby("ad_name")
           .agg(広告費=("spend", "sum"), 表示=("impressions", "sum"),
                クリック=("clicks", "sum"), 購入=("conversions", "sum"))
           .reset_index().rename(columns={"ad_name": "クリエイティブ"}))
    gcr = gcr[gcr["広告費"] > 0]
    gcr["CTR(%)"] = (gcr["クリック"] / gcr["表示"] * 100).round(2)
    gcr["CPC"] = gcr.apply(
        lambda r: r["広告費"] / r["クリック"] if r["クリック"] else None, axis=1)
    gcr["CPA(購入)"] = gcr.apply(
        lambda r: r["広告費"] / r["購入"] if r["購入"] else None, axis=1)
    gcr = gcr.sort_values("広告費", ascending=False)
    disp = gcr.copy()
    disp["広告費"] = disp["広告費"].map(yen)
    disp["CPC"] = disp["CPC"].map(lambda v: yen(v) if pd.notna(v) else "-")
    disp["CPA(購入)"] = disp["CPA(購入)"].map(lambda v: yen(v) if pd.notna(v) else "-")
    disp["購入"] = disp["購入"].map(lambda v: f"{v:.0f}")
    disp["CTR(%)"] = disp["CTR(%)"].map(lambda v: f"{v}%")
    st.dataframe(disp[["クリエイティブ", "広告費", "表示", "クリック", "CTR(%)",
                       "CPC", "購入", "CPA(購入)"]],
                 use_container_width=True, hide_index=True)
    if len(gcr) > 1:
        bestc = gcr.loc[gcr["CTR(%)"].idxmax()]
        st.info(f"💡 CTR最高は **{bestc['クリエイティブ']}**（CTR {bestc['CTR(%)']}%）。"
                f"このクリエイティブの訴求・切り口を軸に展開する判断材料に。")
    if gcr["購入"].sum() == 0:
        st.caption("※ クリエイティブ別の「購入」は、ピクセル計測開始（今回設定）以降に"
                   "蓄積されます。現状はCTR・CPCで比較してください。")
else:
    st.info("クリエイティブ別データがありません。")

# ── 画像・動画アセット別（広告内のどの素材が効くか）──
st.subheader("広告：画像・動画アセット別（どの素材が流入・購入につながるか）")
st.caption("選択中の広告に含まれる画像/動画ごとの成果。サイドバー③で広告を絞ると連動。"
           "画像はサムネイル表示。")
if not asD.empty:
    a = (asD.groupby(["asset_type", "asset_id"])
         .agg(asset_name=("asset_name", "max"), asset_url=("asset_url", "max"),
              表示=("impressions", "sum"), クリック=("clicks", "sum"),
              流入=("link_clicks", "sum"), 購入=("purchases", "sum"),
              広告費=("spend", "sum"))
         .reset_index())
    a = a[a["表示"] > 0]
    if not a.empty:
        a["CTR(%)"] = (a["クリック"] / a["表示"] * 100).round(2)

        def _asset_label(r):
            if pd.notna(r["asset_name"]) and str(r["asset_name"]).strip():
                return str(r["asset_name"])
            if r["asset_type"] == "video":
                return f"動画…{str(r['asset_id'])[-4:]}"
            return "画像"
        a["素材"] = a.apply(_asset_label, axis=1)
        a["サムネ"] = a.apply(
            lambda r: r["asset_url"] if r["asset_type"] == "image" else None, axis=1)
        a["種類"] = a["asset_type"].map({"image": "画像", "video": "動画"})
        a = a.sort_values("流入", ascending=False)
        show = a[["サムネ", "素材", "種類", "表示", "クリック", "CTR(%)",
                  "流入", "購入", "広告費"]].copy()
        show["広告費"] = show["広告費"].map(yen)
        show["購入"] = show["購入"].map(lambda v: f"{v:.0f}")
        st.dataframe(
            show, use_container_width=True, hide_index=True,
            column_config={
                "サムネ": st.column_config.ImageColumn("画像", width="small"),
                "CTR(%)": st.column_config.NumberColumn(format="%.2f%%"),
            })
        top = a.iloc[0]
        st.info(f"💡 流入が最も多い素材は **{top['素材']}**"
                f"（流入 {int(top['流入'])}・CTR {top['CTR(%)']}%）。"
                f"この素材の系統を増やす判断材料に。")
        if a["購入"].sum() == 0:
            st.caption("※ 素材別の「購入」はピクセル計測開始（今回設定）以降に蓄積。"
                       "今はCTR・流入で比較してください。")
    else:
        st.info("選択中の広告にアセット別データがありません。")
else:
    st.info("アセット別データがありません（複数素材の動的クリエイティブが対象）。")

with st.expander("広告：キャンペーン別の成果"):
    if not adD.empty:
        gc = (adD.groupby("campaign_name")
              .agg(広告費=("spend", "sum"), 表示=("impressions", "sum"),
                   クリック=("clicks", "sum"), 購入=("conversions", "sum"))
              .reset_index().rename(columns={"campaign_name": "キャンペーン"}))
        gc["CTR"] = (gc["クリック"] / gc["表示"] * 100).round(2).map(lambda v: f"{v}%")
        gc["CPC"] = gc.apply(
            lambda r: yen(r["広告費"] / r["クリック"]) if r["クリック"] else "-", axis=1)
        gc["広告費"] = gc["広告費"].map(yen)
        gc["購入"] = gc["購入"].map(lambda v: f"{v:.0f}")
        st.dataframe(gc.sort_values("クリック", ascending=False),
                     use_container_width=True, hide_index=True)
    else:
        st.info("キャンペーン別データがありません。")

# ──────────────────────────────────────────────
# 6. 流入チャネル（GA4）
# ──────────────────────────────────────────────
st.subheader("流入チャネル（GA4・LPのみ）")
st.caption(f"LP（{LP_HOST}）の流入。fbclid付きの『Organic Social』は実際は広告クリック"
           f"（UTM未設定のため誤分類）。LPはほぼ全て広告経由。")
if not trP_lp.empty:
    tc1, tc2 = st.columns([2, 3])
    with tc1:
        bych = (trP_lp.groupby("channel")
                .agg(セッション=("sessions", "sum"), 新規=("new_users", "sum"))
                .reset_index().rename(columns={"channel": "チャネル"})
                .sort_values("セッション", ascending=False))
        st.dataframe(bych, use_container_width=True, hide_index=True)
    with tc2:
        daily = (trP_lp.groupby("date_jst")["sessions"].sum()
                 .reset_index().set_index("date_jst"))
        st.markdown("**LP 日次セッション**")
        st.bar_chart(daily, y="sessions", height=240, color=GOLD)
    if base_sessions:
        st.caption(f"参考：同じGA4にBASEショップ（theginger.theshop.jp等）の "
                   f"{base_sessions} セッションも記録されていますが、上記から除外しています。")
else:
    st.info("LPのGA4データがありません。")

st.divider()

# ──────────────────────────────────────────────
# 7. 売上（チャネル別・日次・新規/リピート）
# ──────────────────────────────────────────────
st.subheader("売上")
ch_names = {"stripe": "Stripe（LP直販）", "base": "BASE"}
sc1, sc2 = st.columns(2)
with sc1:
    st.markdown("**チャネル別**")
    chg = (o.groupby("channel")["gross_amount"]
           .agg(売上="sum", 注文="count").reset_index())
    chg["チャネル"] = chg["channel"].map(ch_names).fillna(chg["channel"])
    chg["AOV"] = (chg["売上"] / chg["注文"]).round(0).map(yen)
    chg["売上"] = chg["売上"].map(yen)
    st.dataframe(chg[["チャネル", "売上", "注文", "AOV"]]
                 .sort_values("売上", ascending=False),
                 use_container_width=True, hide_index=True)
    st.metric("新規 / リピート 注文", f"{new_n} / {repeat_n}")
with sc2:
    st.markdown("**日次売上**")
    od = (o.groupby("order_date_jst")["gross_amount"].sum()
          .reset_index().set_index("order_date_jst"))
    st.bar_chart(od, y="gross_amount", height=240, color=GOLD)

with st.expander("直近の注文"):
    recent = (o.sort_values("order_date_jst", ascending=False).head(50)
              [["order_date_jst", "channel", "customer_email", "gross_amount",
                "is_first"]]
              .rename(columns={"order_date_jst": "日付", "channel": "チャネル",
                               "customer_email": "メール", "gross_amount": "金額",
                               "is_first": "新規"}))
    st.dataframe(recent, use_container_width=True, hide_index=True)

st.caption("※ 返金/キャンセル済みは集計から除外。LTV等の試算値はサイドバーの前提に基づく目安。")
