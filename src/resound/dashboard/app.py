"""Streamlit dashboard.

Three views:
  1. Live signal feed (most recent ingested)
  2. Memory browser (filterable history)
  3. Routing audit log (which rules fired, where signals went)
"""

from __future__ import annotations

import os
from pathlib import Path

import pandas as pd
import streamlit as st

from resound.config import load_brand_config
from resound.memory import SqlMemory

st.set_page_config(page_title="Resound", layout="wide")

BRAND_SLUG = os.environ.get("RESOUND_BRAND", "liquiddeath")


@st.cache_resource
def get_memory():
    return SqlMemory()


@st.cache_data(ttl=10)
def load_signals(brand: str, limit: int = 200) -> pd.DataFrame:
    rows = get_memory().query_recent(brand, limit=limit)
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows)


def load_brand():
    brands_dir = Path("brands")
    if not brands_dir.is_dir():
        st.error(f"brands/ directory not found at {brands_dir.resolve()}")
        st.stop()
    try:
        return load_brand_config(BRAND_SLUG, brands_dir)
    except FileNotFoundError:
        st.error(f"Brand '{BRAND_SLUG}' not found in {brands_dir.resolve()}")
        st.stop()


brand = load_brand()

# ---- header ----

st.title(f"Resound — {brand.name}")
st.caption(brand.description or f"slug: {brand.slug}")

# ---- sidebar ----

st.sidebar.header("Filters")
df = load_signals(BRAND_SLUG, limit=500)

if df.empty:
    st.info(
        "No signals yet. Run `resound poll-once --brand "
        f"{BRAND_SLUG}` to ingest some, then refresh."
    )
    st.stop()

areas = ["(all)"] + sorted([a for a in df["area"].dropna().unique().tolist()])
sources = ["(all)"] + sorted([s for s in df["source"].dropna().unique().tolist()])
severities = ["(all)", "low", "medium", "high", "critical"]
actions = ["(all)", "ignore", "fyi", "roadmap", "sprint", "immediate"]

f_area = st.sidebar.selectbox("Area", areas)
f_source = st.sidebar.selectbox("Source", sources)
f_severity = st.sidebar.selectbox("Severity", severities)
f_action = st.sidebar.selectbox("Action class", actions)

filtered = df.copy()
if f_area != "(all)":
    filtered = filtered[filtered["area"] == f_area]
if f_source != "(all)":
    filtered = filtered[filtered["source"] == f_source]
if f_severity != "(all)":
    filtered = filtered[filtered["severity"] == f_severity]
if f_action != "(all)":
    filtered = filtered[filtered["action_class"] == f_action]

# ---- top metrics ----

cols = st.columns(5)
cols[0].metric("Total signals", len(df))
cols[1].metric("This view", len(filtered))
cols[2].metric(
    "Routed (excl. ignore)",
    int((df["action_class"] != "ignore").sum()) if "action_class" in df else 0,
)
cols[3].metric(
    "Critical", int((df["severity"] == "critical").sum()) if "severity" in df else 0
)
cols[4].metric(
    "Sources active", df["source"].nunique() if "source" in df else 0
)

# ---- tabs ----

tab1, tab2, tab3 = st.tabs(["Live feed", "Memory browser", "Routing audit"])

with tab1:
    st.subheader("Most recent signals")
    show_cols = [
        "ingested_at",
        "source",
        "area",
        "severity",
        "action_class",
        "summary",
        "owner",
        "url",
    ]
    show_cols = [c for c in show_cols if c in filtered.columns]
    st.dataframe(filtered[show_cols].head(100), use_container_width=True, hide_index=True)

with tab2:
    st.subheader("Memory browser")
    st.caption("All persisted signals for this brand. The asset that compounds.")
    memory_cols = [
        "signal_id",
        "ingested_at",
        "posted_at",
        "source",
        "area",
        "subarea",
        "sentiment",
        "severity",
        "action_class",
        "summary",
        "content",
        "url",
    ]
    memory_cols = [c for c in memory_cols if c in filtered.columns]
    st.dataframe(filtered[memory_cols], use_container_width=True, hide_index=True)
    csv = filtered[memory_cols].to_csv(index=False)
    st.download_button("Download as CSV", csv, file_name=f"{BRAND_SLUG}_memory.csv")

with tab3:
    st.subheader("Routing audit")
    st.caption("Where signals were sent and which rule fired.")
    audit_cols = ["ingested_at", "summary", "area", "severity", "action_class", "owner", "destination"]
    audit_cols = [c for c in audit_cols if c in filtered.columns]
    routed = filtered[filtered["owner"].notna() & (filtered["owner"] != "(none)")]
    st.dataframe(routed[audit_cols], use_container_width=True, hide_index=True)

    if "owner" in filtered.columns and len(routed) > 0:
        st.markdown("**Routing volume by owner:**")
        st.bar_chart(routed["owner"].value_counts())
