import streamlit as st
import requests

API_BASE = "http://127.0.0.1:8000"

st.set_page_config(page_title="Store Intelligence Dashboard", layout="wide")

st.title("Purplle Store Intelligence Dashboard")

pos = requests.get(f"{API_BASE}/pos-metrics").json()
metrics = requests.get(f"{API_BASE}/stores/STORE_001/metrics").json()

col1, col2, col3, col4 = st.columns(4)

col1.metric("Unique Visitors", pos["unique_visitors"])
col2.metric("Transactions", pos["transactions"])
col3.metric("Revenue", f"₹{pos['revenue']}")
col4.metric("Conversion Rate", pos["conversion_rate"])

st.divider()

st.subheader("Store Metrics")
st.json(metrics)

st.subheader("POS Metrics")
st.json(pos)