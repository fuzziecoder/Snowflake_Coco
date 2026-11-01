import streamlit as st
import pandas as pd
import altair as alt

st.set_page_config(page_title="QuickBite refund incident", page_icon=":material/delivery_dining:", layout="wide")

conn = st.connection("fuzziecoder", type="snowflake")


def q(sql):
    df = conn.query(sql)
    for c in df.columns:
        if df[c].dtype == object:
            converted = pd.to_numeric(df[c], errors="coerce")
            if converted.notna().all():
                df[c] = converted
    return df


V23_DATE = "2026-09-08"
WFE = "Whitefield-East"


@st.cache_data(ttl="1h")
def load_monthly():
    return q(
        """
        SELECT TO_CHAR(DATE_TRUNC('month', o.PLACED_AT), 'YYYY-MM') AS month,
               COUNT(*) AS orders,
               SUM(o.ORDER_VALUE_INR) AS gmv_inr,
               COALESCE(SUM(r.REFUND_AMOUNT_INR), 0) AS refunds_inr,
               ROUND(100 * COALESCE(SUM(r.REFUND_AMOUNT_INR), 0) / SUM(o.ORDER_VALUE_INR), 2) AS refund_pct
        FROM QUICKBITE_DB.RAW.ORDERS o
        LEFT JOIN QUICKBITE_DB.RAW.REFUNDS r ON r.ORDER_ID = o.ORDER_ID
        WHERE o.PLACED_AT >= '2026-01-01' AND o.PLACED_AT < '2027-01-01'
        GROUP BY 1 ORDER BY 1
        """
    )


@st.cache_data(ttl="1h")
def load_zone_increase():
    return q(
        """
        WITH b AS (
          SELECT o.ZONE_ID, z.ZONE_NAME, o.CITY, TO_CHAR(o.PLACED_AT, 'MM') m, r.REFUND_AMOUNT_INR ra
          FROM QUICKBITE_DB.RAW.ORDERS o
          JOIN QUICKBITE_DB.RAW.CITIES_ZONES z USING (ZONE_ID)
          LEFT JOIN QUICKBITE_DB.RAW.REFUNDS r ON r.ORDER_ID = o.ORDER_ID
          WHERE o.PLACED_AT >= '2026-08-01' AND o.PLACED_AT < '2026-11-01'
            AND TO_CHAR(o.PLACED_AT, 'MM') IN ('08', '10'))
        SELECT CITY, ZONE_NAME, ZONE_ID,
               SUM(IFF(m = '08', ra, 0)) AS aug_ref,
               SUM(IFF(m = '10', ra, 0)) AS oct_ref,
               SUM(IFF(m = '10', ra, 0)) - SUM(IFF(m = '08', ra, 0)) AS increase
        FROM b GROUP BY 1, 2, 3 ORDER BY increase DESC
        """
    )


@st.cache_data(ttl="1h")
def load_zones():
    return q(
        """
        SELECT ZONE_ID, ZONE_NAME, CITY FROM QUICKBITE_DB.RAW.CITIES_ZONES ORDER BY CITY, ZONE_NAME
        """
    )


@st.cache_data(ttl="1h")
def load_weekly_late():
    return q(
        """
        SELECT o.ZONE_ID, z.ZONE_NAME,
               TO_CHAR(DATE_TRUNC('week', o.PLACED_AT), 'YYYY-MM-DD') AS week,
               COUNT(*) AS orders,
               ROUND(100 * COUNT_IF(DATEDIFF('second', o.PLACED_AT, o.DELIVERED_AT) > 2700) / COUNT(*), 1) AS late_pct
        FROM QUICKBITE_DB.RAW.ORDERS o
        JOIN QUICKBITE_DB.RAW.CITIES_ZONES z USING (ZONE_ID)
        WHERE o.PLACED_AT >= '2026-07-01'
        GROUP BY 1, 2, 3
        """
    )


@st.cache_data(ttl="1h")
def load_rain():
    return q(
        """
        SELECT IFF(o.ZONE_ID = 1, 'Whitefield-East', 'All other zones') AS grp,
               IFF(o.PLACED_AT >= '2026-09-08', 'After v2.3', 'Before v2.3') AS period,
               CASE WHEN w.RAIN_MM > 0 THEN 'Rain' ELSE 'Dry' END AS weather,
               COUNT(*) AS orders,
               ROUND(AVG(o.RIDER_ASSIGN_DISTANCE_KM), 2) AS avg_assign_km,
               ROUND(100 * COUNT_IF(DATEDIFF('second', o.PLACED_AT, o.DELIVERED_AT) > 2700) / COUNT(*), 1) AS late_pct
        FROM QUICKBITE_DB.RAW.ORDERS o
        LEFT JOIN QUICKBITE_DB.RAW.WEATHER_HOURLY w
               ON w.CITY = o.CITY AND w.HOUR_TS = DATE_TRUNC('hour', o.PLACED_AT)
        WHERE o.PLACED_AT >= '2026-07-08' AND o.PLACED_AT < '2026-11-01'
        GROUP BY 1, 2, 3
        """
    )


@st.cache_data(ttl="1h")
def load_ckh():
    return q(
        """
        SELECT IFF(rs.CLUSTER = 'Cloud Kitchens Hub', 'Cloud Kitchens Hub',
                   IFF(o.ZONE_ID = 1, 'Whitefield-East', 'All other')) AS grp,
               TO_CHAR(o.PLACED_AT, 'YYYY-MM') AS m, COUNT(*) AS orders,
               COALESCE(SUM(r.REFUND_AMOUNT_INR), 0) AS refunds_inr
        FROM QUICKBITE_DB.RAW.ORDERS o
        JOIN QUICKBITE_DB.RAW.RESTAURANTS rs USING (RESTAURANT_ID)
        LEFT JOIN QUICKBITE_DB.RAW.REFUNDS r ON r.ORDER_ID = o.ORDER_ID
        WHERE o.PLACED_AT >= '2026-08-01' AND o.PLACED_AT < '2026-11-01'
        GROUP BY 1, 2
        """
    )


@st.cache_data(ttl="1h")
def load_themes():
    return q(
        """
        SELECT THEME, COUNT(*) AS chats, ROUND(100 * RATIO_TO_REPORT(COUNT(*)) OVER (), 1) AS pct
        FROM QUICKBITE_DB.ANALYTICS.CHAT_THEMES
        GROUP BY 1 ORDER BY 2 DESC
        """
    )


@st.cache_data(ttl="1h")
def load_theme_examples():
    return q(
        """
        SELECT THEME, MIN(MESSAGE) AS example
        FROM QUICKBITE_DB.ANALYTICS.CHAT_THEMES
        GROUP BY 1
        """
    )


THEME_SUMMARIES = {
    "Rider assigned too far away": (
        "Riders were consistently assigned from far away (6-9 km), resulting in long wait "
        "times (55-85 minutes) and cold food upon arrival, despite some customers "
        "acknowledging it was raining."
    ),
    "General late delivery": (
        "Deliveries took 55-84 minutes against an expected 30. Customers mentioned rain "
        "but did not accept it as an excuse; some riders did not answer calls. Several "
        "requested refunds after repeated late orders."
    ),
    "Food arrived cold": (
        "Cold pizza and biryani. Customers said the food had clearly been left waiting at "
        "the restaurant, sometimes in rain."
    ),
    "Missing or wrong item": (
        "Missing drinks or desserts, veg sent instead of chicken, and someone else's order "
        "delivered."
    ),
    "Food quality": (
        "Oily, salty or stale food and small portions, seen as a decline in overall quality."
    ),
}

monthly = load_monthly()
zones_inc = load_zone_increase()
zones = load_zones()
weekly = load_weekly_late()
rain = load_rain()
ckh = load_ckh()
themes = load_themes()

st.title("QuickBite refund incident — October 2026")
st.caption(
    "Delivery-ops review of the Aug → Oct refund increase. Data: QUICKBITE_DB.RAW; "
    "chat themes classified with AI_CLASSIFY into QUICKBITE_DB.ANALYTICS.CHAT_THEMES."
)

# ---- KPI row -------------------------------------------------------------
oct_row = monthly[monthly["MONTH"] == "2026-10"].iloc[0]
sep_ref = monthly[monthly["MONTH"] == "2026-09"]["REFUNDS_INR"].iloc[0]
wfe_inc = zones_inc[zones_inc["ZONE_NAME"] == WFE]["INCREASE"].iloc[0]
total_inc = zones_inc["INCREASE"].sum()
wfe_share = 100 * wfe_inc / total_inc

with st.container(horizontal=True):
    st.metric(
        "October refunds",
        f"₹{oct_row['REFUNDS_INR'] / 1000:,.0f}K",
        f"+{100 * (oct_row['REFUNDS_INR'] - sep_ref) / sep_ref:.0f}%",
        border=True,
    )
    st.metric(
        "Refunds % of GMV",
        f"{oct_row['REFUND_PCT']:.2f}%",
        "+1.05 pp",
        border=True,
    )
    st.metric(
        "October orders",
        f"{oct_row['ORDERS'] / 1000:.1f}K",
        border=True,
    )
    st.metric(
        "Refund increase from one zone",
        f"{wfe_share:.0f}%",
        border=True,
    )
st.caption(
    "Deltas: refunds vs September; refund % of GMV vs 3.71% in August. The one zone is "
    "Bengaluru Whitefield-East, whose share is of the ₹205K company-wide Aug → Oct increase; "
    "its orders grew only ~10% while its refunds ~4×."
)

# ---- Monthly trend -------------------------------------------------------
with st.container(border=True):
    st.subheader("Monthly orders, GMV and refunds")
    trend = monthly.rename(columns={"REFUND_PCT": "Refund % of GMV"})
    bars = alt.Chart(trend).mark_bar().encode(
        x=alt.X("MONTH:O", title=None),
        y=alt.Y("GMV_INR:Q", axis=alt.Axis(format="~s", title="GMV (₹)")),
        tooltip=["MONTH", "ORDERS", "GMV_INR", "REFUNDS_INR", "Refund % of GMV"],
    )
    line = alt.Chart(trend).mark_line(color="#e4572e", point=True).encode(
        x="MONTH:O", y=alt.Y("Refund % of GMV:Q", scale=alt.Scale(zero=False))
    )
    combined = alt.layer(bars, line).resolve_scale(y="independent")
    st.altair_chart(combined, width="stretch")

# ---- Zone increase -------------------------------------------------------
with st.container(border=True):
    st.subheader("Refund increase by zone, August → October 2026")
    top = zones_inc.head(10).copy()
    top["Label"] = top["CITY"] + " — " + top["ZONE_NAME"]
    st.bar_chart(
        top, x="Label", y="INCREASE",
    )
    st.caption(
        f"Whitefield-East alone contributed ₹{wfe_inc / 1000:,.0f}K of the ₹{total_inc / 1000:,.0f}K "
        "company-wide increase."
    )

# ---- Zone selector: weekly late % ---------------------------------------
with st.container(border=True):
    st.subheader("Weekly late-delivery rate by zone")
    st.caption("Late = more than 45 minutes from placement to delivery. The red line marks rider-assign v2.3 (expanded assignment radius), released 2026-09-08.")

    zone_opts = [
        f"{z.CITY} — {z.ZONE_NAME} (zone {z.ZONE_ID})"
        for z in zones.itertuples()
        if z.ZONE_ID in set(weekly["ZONE_ID"])
    ]
    default_zone = next(
        (o for o in zone_opts if WFE in o),
        zone_opts[0],
    )
    selected_label = st.selectbox("Zone", zone_opts, index=zone_opts.index(default_zone))
    sel_zone_id = int(selected_label.split("zone ")[-1].rstrip(")"))

    w = weekly.copy()
    w_sel = w[w["ZONE_ID"] == sel_zone_id][["WEEK", "LATE_PCT"]].rename(columns={"LATE_PCT": "This zone"})
    w_rest = (
        w[w["ZONE_ID"] != sel_zone_id].groupby("WEEK", as_index=False)["LATE_PCT"].mean().rename(columns={"LATE_PCT": "All other zones"})
    )
    merged = pd.merge(w_sel, w_rest, on="WEEK", how="outer").sort_values("WEEK")
    for c in ("This zone", "All other zones"):
        merged[c] = pd.to_numeric(merged[c], errors="coerce")
    v23 = pd.DataFrame([{"Week starting": V23_DATE}])

    base = alt.Chart(merged).transform_fold(
        ["This zone", "All other zones"], as_=["Series", "Late %"]
    )
    lines = base.mark_line(point=True).encode(
        x=alt.X("WEEK:T", title="Week starting", axis=alt.Axis(format="%b %d")),
        y=alt.Y("Late %:Q", scale=alt.Scale(zero=False)),
        color="Series:N",
    )
    rule = alt.Chart(v23).mark_rule(color="#d62728", strokeDash=[6, 4]).encode(
        x="Week starting:T"
    )
    rule_text = alt.Chart(v23).mark_text(
        align="left", dx=5, dy=-110, color="#d62728", text="rider-assign v2.3"
    ).encode(x="Week starting:T")
    st.altair_chart(
        (lines + rule + rule_text).properties(height=340),
        width="stretch",
    )

# ---- Rain effect ---------------------------------------------------------
with st.container(border=True):
    st.subheader("Rain makes it worse")
    st.caption("Whitefield-East after v2.3: 58% of orders placed in rain were late — versus 16% in dry weather and ~10% in rain elsewhere.")
    rain_wide = rain.pivot_table(index=["GRP", "PERIOD"], columns="WEATHER", values="LATE_PCT").reset_index()
    st.dataframe(rain_wide, hide_index=True)

# ---- Cloud Kitchens red herring ------------------------------------------
with st.container(border=True):
    st.subheader("Red herring: the Cloud Kitchens Hub launch")
    ckh_wide = ckh.pivot_table(index="M", columns="GRP", values="REFUNDS_INR", aggfunc="sum").reset_index()
    ckh_wide["Cloud Kitchens Hub"] = ckh_wide.get("Cloud Kitchens Hub", 0)
    st.dataframe(ckh_wide, hide_index=True)
    ckh_oct = ckh[(ckh["GRP"] == "Cloud Kitchens Hub") & (ckh["M"] == "2026-10")]["REFUNDS_INR"].sum()
    st.caption(
        f"The 60 Cloud Kitchens Hub restaurants (launched 2026-09-01) are all in HITEC City, Hyderabad — "
        f"not Whitefield-East. They contributed ₹{ckh_oct / 1000:.0f}K of the ₹205K increase (~5%) and ~1% of orders. "
        "Their ~6.5% refund rate is above baseline and worth watching, but it is not the cause of the spike."
    )

# ---- AI chat themes ------------------------------------------------------
with st.container(border=True):
    st.subheader("What customers said (AI-classified support chats)")
    st.caption("446 Whitefield-East customer chats since 2026-09-08, classified with AI_CLASSIFY. One label per chat.")
    left, right = st.columns([1, 1.4], gap="large")
    with left:
        st.bar_chart(themes, x="THEME", y="CHATS", x_label="Theme", y_label="Chats")
    with right:
        for row in themes.itertuples():
            st.markdown(f"**:material/chat_bubble: {row.THEME}** — {row.CHATS} chats ({row.PCT}%)")
            st.caption(THEME_SUMMARIES.get(row.THEME, ""))

# ---- Recommendation ------------------------------------------------------
with st.container(border=True):
    st.subheader("Recommendation")
    st.markdown(
        """
**Root cause (high confidence):** rider-assign **v2.3** (2026-09-08) expanded the assignment
radius to 10 km. In Whitefield-East, average rider assignment distance jumped from ~2.1 km to
~6.0 km, pickup wait rose from 15 to 21 minutes, and late deliveries went from 7% to 28%.
Refunds for *Late delivery* (+₹98K) and *Cold food* (+₹61K) drove ~all of the zone's increase.
Rain compounds it: 58% of rainy-hour orders were late.

**Actions**
1. **Cap the assignment radius in Whitefield-East** (back toward ~3 km), at least during rain.
2. **Fix rider supply** in the zone — add or incentivise home-zone riders; point the existing
   "rain-mode surge incentives" (v2.2) at Whitefield-East.
3. **Interim mitigation:** rain-aware ETA buffers and proactive refunds for affected orders.
4. **Monitor:** weekly late % for the zone (chart above) and the CKH launch quality separately.
        """
    )
    st.info(
        "Note: the v2.3 link is strong correlation, not proven causation; zone rider-supply data "
        "has not yet been checked. Chat themes are AI-classified and not human-validated.",
        icon=":material/info:",
    )
