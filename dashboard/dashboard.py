"""
Live Store Intelligence Dashboard.
Auto-refreshes every 2 seconds to show real-time metrics as events flow in.
Proves end-to-end pipeline → API → dashboard connection.
"""

import time
import os
import requests
import streamlit as st

API_BASE = os.environ.get("API_BASE", "http://localhost:8000")
STORE_ID = os.environ.get("STORE_ID", "STORE_BLR_002")
REFRESH_INTERVAL = 2  # seconds

st.set_page_config(
    page_title="Store Intelligence — Live",
    page_icon="🏪",
    layout="wide",
)

# ── header ────────────────────────────────────────────────────────────────────
st.title("🏪 Purplle Store Intelligence")
st.caption(f"Live dashboard · Store: `{STORE_ID}` · Refreshes every {REFRESH_INTERVAL}s")

# ── fetch data ────────────────────────────────────────────────────────────────
@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_metrics(store_id: str):
    try:
        r = requests.get(f"{API_BASE}/stores/{store_id}/metrics", timeout=3)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_funnel(store_id: str):
    try:
        r = requests.get(f"{API_BASE}/stores/{store_id}/funnel", timeout=3)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_anomalies(store_id: str):
    try:
        r = requests.get(f"{API_BASE}/stores/{store_id}/anomalies", timeout=3)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_health():
    try:
        r = requests.get(f"{API_BASE}/health", timeout=3)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)


metrics,   metrics_err   = fetch_metrics(STORE_ID)
funnel,    funnel_err    = fetch_funnel(STORE_ID)
anomalies, anomaly_err   = fetch_anomalies(STORE_ID)
health,    health_err    = fetch_health()

# ── health status bar ─────────────────────────────────────────────────────────
if health:
    store_health = health.get("stores", {}).get(STORE_ID, {})
    feed_status  = store_health.get("feed_status", "UNKNOWN")
    if feed_status == "STALE_FEED":
        st.error(f"⚠️ STALE FEED — Last event: {store_health.get('last_event_timestamp', 'never')}")
    else:
        st.success(f"✅ Live feed active · Last event: {store_health.get('last_event_timestamp', '—')}")

st.divider()

# ── key metrics row ───────────────────────────────────────────────────────────
if metrics:
    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Unique Visitors",    metrics.get("unique_visitors", 0))
    col2.metric("Conversion Rate",    f"{metrics.get('conversion_rate', 0):.1%}")
    col3.metric("Queue Depth",        metrics.get("queue_depth", 0))
    col4.metric("Abandonment Rate",   f"{metrics.get('abandonment_rate', 0):.1%}")

    pos = metrics.get("pos", {})
    col5.metric("Revenue",            f"₹{pos.get('total_revenue_inr', 0):,.0f}")
else:
    st.warning(f"Could not reach API: {metrics_err}")

st.divider()

# ── funnel + anomalies row ────────────────────────────────────────────────────
left, right = st.columns(2)

with left:
    st.subheader("Conversion Funnel")
    if funnel:
        stages = funnel.get("funnel", [])
        for stage in stages:
            pct   = stage.get("conversion_pct", 0)
            count = stage.get("count", 0)
            drop  = stage.get("drop_off_pct", 0)
            bar_width = max(int(pct), 2)

            st.markdown(
                f"**{stage['label']}** &nbsp; `{count}` visitors"
                + (f" &nbsp; ↓ {drop}% drop-off" if drop > 0 else ""),
                unsafe_allow_html=True,
            )
            st.progress(bar_width / 100)
    else:
        st.info("No funnel data yet.")

with right:
    st.subheader("Active Anomalies")
    if anomalies:
        items = anomalies.get("anomalies", [])
        if not items:
            st.success("No anomalies detected.")
        else:
            for a in items:
                sev = a.get("severity", "INFO")
                if sev == "CRITICAL":
                    st.error(f"🔴 **{a['type']}** — {a['message']}\n\n_{a.get('suggested_action', '')}_")
                elif sev == "WARN":
                    st.warning(f"🟡 **{a['type']}** — {a['message']}\n\n_{a.get('suggested_action', '')}_")
                else:
                    st.info(f"🔵 **{a['type']}** — {a['message']}")
    else:
        st.info("No anomaly data yet.")

st.divider()

# ── zone dwell heatmap ────────────────────────────────────────────────────────
st.subheader("Zone Dwell Heatmap")

@st.cache_data(ttl=REFRESH_INTERVAL)
def fetch_heatmap(store_id: str):
    try:
        r = requests.get(f"{API_BASE}/stores/{store_id}/heatmap", timeout=3)
        r.raise_for_status()
        return r.json(), None
    except Exception as e:
        return None, str(e)

heatmap, heatmap_err = fetch_heatmap(STORE_ID)

if heatmap and heatmap.get("heatmap"):
    import pandas as pd
    df = pd.DataFrame(heatmap["heatmap"])
    st.dataframe(
        df[["zone_id", "visit_count", "avg_dwell_ms", "visit_score", "dwell_score"]],
        use_container_width=True,
        hide_index=True,
    )
    if heatmap.get("data_confidence") == "LOW":
        st.caption("⚠️ Data confidence: LOW — fewer than 20 sessions in window")
else:
    st.info("No zone data yet — run the detection pipeline first.")

# ── auto-refresh ──────────────────────────────────────────────────────────────
# This is what makes it a LIVE dashboard — proves pipeline → API connection
time.sleep(REFRESH_INTERVAL)
st.rerun()
