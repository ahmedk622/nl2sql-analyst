"""Streamlit page: LLM cost, latency and usage, read from logs/llm_calls.jsonl."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

import streamlit as st  # noqa: E402

from nl2sql.config import load_settings  # noqa: E402
from nl2sql.metrics import daily_usage, estimated_cost, latency_summary, load_calls, repair_rate  # noqa: E402

st.set_page_config(page_title="Cost & Latency", page_icon="📈", layout="wide")
st.title("📈 LLM cost & latency")

log_path = load_settings().log_path
calls = load_calls(log_path)
if calls.empty:
    st.info("No LLM calls logged yet. Ask a question in the main app or run an evaluation, then refresh this page.")
    st.stop()

with st.sidebar:
    st.subheader("Filters")
    models = st.multiselect("Model", sorted(calls["model"].unique()), default=sorted(calls["model"].unique()))
    purposes = st.multiselect("Call type", sorted(calls["purpose"].unique()), default=sorted(calls["purpose"].unique()))
    st.subheader("Cost estimate")
    st.caption("Enter your provider's list price per 1M tokens. Free tiers cost $0.")
    in_price = st.number_input("Input $ / 1M tokens", min_value=0.0, value=0.0, step=0.05)
    out_price = st.number_input("Output $ / 1M tokens", min_value=0.0, value=0.0, step=0.05)

df = calls[calls["model"].isin(models) & calls["purpose"].isin(purposes)]
if df.empty:
    st.warning("No calls match the filters.")
    st.stop()

c = st.columns(6)
c[0].metric("LLM calls", f"{len(df):,}")
c[1].metric("Total tokens", f"{int(df['total_tokens'].sum()):,}")
c[2].metric("Estimated cost", f"${estimated_cost(df, in_price, out_price):,.4f}")
c[3].metric("Latency p50", f"{int(df['latency_ms'].median()):,} ms")
c[4].metric("Latency p95", f"{int(df['latency_ms'].quantile(0.95)):,} ms")
c[5].metric("SQL repair rate", f"{repair_rate(calls[calls['model'].isin(models)]):.1%}",
            help="Repair calls divided by generate calls: how often the first SQL failed and was retried.")

st.subheader("Latency by model and call type")
st.dataframe(latency_summary(df), width="stretch", hide_index=True)

left, right = st.columns(2)
with left:
    st.subheader("Latency over time (ms)")
    st.line_chart(df.set_index("ts")["latency_ms"])
with right:
    st.subheader("Tokens by call type")
    st.bar_chart(df.groupby("purpose")["total_tokens"].sum())

st.subheader("Daily usage")
st.bar_chart(daily_usage(df)["calls"])
st.caption(f"Source: {log_path.name}. The log mixes app use and evaluation runs; filter by model to separate them. "
           "'HTTP retries' counts rate-limit or server retries inside one call, not SQL repairs.")
