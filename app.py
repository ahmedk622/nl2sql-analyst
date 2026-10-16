"""Streamlit UI for the AI SQL Assistant.   Run:  streamlit run app.py"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import pandas as pd  # noqa: E402
import streamlit as st  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.exc import SQLAlchemyError  # noqa: E402

from nl2sql.config import load_settings  # noqa: E402
from nl2sql.db import make_engine  # noqa: E402
from nl2sql.llm import LLMClient  # noqa: E402
from nl2sql.pipeline import NL2SQL, Result  # noqa: E402
from nl2sql.schema import get_schema_text  # noqa: E402

st.set_page_config(page_title="AI SQL Assistant", page_icon="🧠", layout="wide")
settings = load_settings()

EXAMPLES = [
    "What is the total net revenue?",
    "Which product category generates the most net revenue?",
    "What was the net revenue for each month of 2025?",
    "What is the cancellation rate for each sales channel?",
    "Who are the top 5 customers by net revenue?",
    "What are the top 3 products by net revenue within each category?",
]


@st.cache_resource
def get_engine():
    engine = make_engine(settings.db_url)
    with engine.connect() as c:
        c.execute(text("SELECT 1"))
    return engine


@st.cache_resource
def get_pipeline():
    llm = LLMClient(settings.llm_provider, settings.llm_api_key, settings.llm_model,
                    settings.llm_base_url, settings.log_path)
    return NL2SQL(get_engine(), llm, settings.max_rows, settings.max_repairs)


def auto_chart(df: pd.DataFrame) -> None:
    if df.shape[1] != 2 or not 2 <= len(df) <= 60:
        return
    x, y = df.columns
    if not pd.api.types.is_numeric_dtype(df[y]):
        return
    data = df.set_index(x)
    if re.match(r"^\d{4}-\d{2}", str(df[x].iloc[0])):
        st.line_chart(data)
    else:
        st.bar_chart(data)


def render(res: Result) -> None:
    if res.kind == "success":
        if res.summary:
            st.info(res.summary)
        if res.df is not None and res.df.empty:
            st.warning("The query ran but returned no rows.")
        else:
            st.dataframe(res.df, width="stretch", hide_index=True)
            auto_chart(res.df)
            st.download_button("Download CSV", res.df.to_csv(index=False), "result.csv", "text/csv",
                               key=f"dl-{id(res)}")
    elif res.kind == "unanswerable":
        st.warning(f"I can't answer that from this database: {res.message}")
    elif res.kind == "blocked":
        st.error(f"Blocked by the safety guardrails: {res.message}")
    elif res.kind == "execution":
        st.error(f"The query failed after {res.attempts} attempts: {res.message}")
    else:
        st.error(res.message)
    if res.sql:
        with st.expander("Generated SQL & trace"):
            st.code(res.sql, language="sql")
            st.json(res.trace)
    if res.attempts:
        st.caption(f"{res.attempts} attempt(s) · {res.latency_ms} ms · "
                   f"{res.prompt_tokens + res.completion_tokens} tokens")


# ---------------------------------------------------------------- page
st.title("🧠 AI SQL Assistant")
st.caption("Ask business questions in plain English. Queries are validated, read-only, and explained.")

try:
    get_engine()
except SQLAlchemyError as e:
    st.error("Cannot connect to MySQL. Check DB_* values in `.env` and run `python scripts/setup_db.py`.")
    st.code(str(getattr(e, "orig", e)))
    st.stop()

if not settings.llm_ready:
    st.warning("No LLM API key found. Get a free key (no card needed) from "
               "**console.groq.com** or **aistudio.google.com**, put it in `.env` as `LLM_API_KEY`, "
               "set `LLM_PROVIDER` (groq | gemini), then restart.")
    st.stop()

with st.sidebar:
    st.subheader("Try an example")
    for ex in EXAMPLES:
        if st.button(ex, width="stretch"):
            st.session_state["pending"] = ex
    st.divider()
    summarize = st.toggle("Explain results in plain English", value=True)
    st.caption(f"Model: `{settings.llm_provider}/{settings.llm_model}`")
    with st.expander("Database schema"):
        st.code(get_schema_text(get_engine(), include_samples=False), language="text")
    if st.button("Clear conversation"):
        st.session_state["messages"] = []

st.session_state.setdefault("messages", [])
for m in st.session_state["messages"]:
    with st.chat_message(m["role"]):
        if m["role"] == "user":
            st.markdown(m["content"])
        else:
            render(m["result"])

prompt = st.chat_input("e.g. Which country had the highest revenue in 2025?") or st.session_state.pop("pending", None)
if prompt:
    st.session_state["messages"].append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)
    history = [(m["result"].question, m["result"].sql) for m in st.session_state["messages"]
               if m["role"] == "assistant" and m["result"].ok][-3:]
    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            result = get_pipeline().ask(prompt, history=history, summarize=summarize)
        render(result)
    st.session_state["messages"].append({"role": "assistant", "result": result})
