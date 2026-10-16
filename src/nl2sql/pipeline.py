"""The NL -> SQL pipeline: prompt -> generate -> validate -> execute -> self-repair -> summarise."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError

from .db import run_query
from .guardrails import GuardrailError, validate_sql
from .llm import ChatModel, LLMError
from .schema import get_schema_text, get_table_names

GLOSSARY_PATH = Path(__file__).resolve().parents[2] / "config" / "glossary.md"

SYSTEM_PROMPT = """You are a senior data analyst who writes MySQL 8.0 queries.
Rules:
- Reply with exactly ONE read-only SELECT statement inside a ```sql fenced block. No explanation.
- Use ONLY the tables and columns in the schema. Never invent columns or tables.
- Never write INSERT, UPDATE, DELETE, DDL, or anything that changes data.
- Follow the business definitions exactly.
- Use explicit JOIN ... ON, table aliases, and qualified column names.
- Give result columns short, readable aliases.
- If the question cannot be answered from the schema, or asks to modify data, reply with only:
  -- CANNOT_ANSWER: <short reason>"""


@dataclass
class Result:
    question: str
    kind: str = "error"            # success | unanswerable | blocked | execution | llm
    sql: str = ""
    df: pd.DataFrame | None = None
    message: str = ""              # error text, refusal reason, or summary
    summary: str = ""
    attempts: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    latency_ms: int = 0
    trace: list[dict] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.kind == "success"


def extract_sql(text: str) -> str:
    m = re.search(r"```(?:sql)?\s*(.*?)```", text, re.S | re.I)
    return (m.group(1) if m else text).strip().rstrip(";").strip()


class NL2SQL:
    def __init__(self, engine: Engine, llm: ChatModel, max_rows: int = 500, max_repairs: int = 2):
        self.engine, self.llm = engine, llm
        self.max_rows, self.max_repairs = max_rows, max_repairs
        self.allowed_tables = get_table_names(engine)
        self.database = engine.url.database if engine.dialect.name == "mysql" else None
        glossary = GLOSSARY_PATH.read_text(encoding="utf-8") if GLOSSARY_PATH.exists() else ""
        self.context = f"# SCHEMA\n{get_schema_text(engine)}\n\n{glossary}"

    def _messages(self, question: str, history: list[tuple[str, str]] | None) -> list[dict]:
        msgs = [{"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": self.context}]
        for q, s in (history or [])[-3:]:  # lets follow-ups like "now only for India" work
            msgs += [{"role": "user", "content": f"Question: {q}"},
                     {"role": "assistant", "content": f"```sql\n{s}\n```"}]
        msgs.append({"role": "user", "content": f"Question: {question}"})
        return msgs

    def ask(self, question: str, history: list[tuple[str, str]] | None = None,
            summarize: bool = True) -> Result:
        res = Result(question=question)
        started = time.perf_counter()
        messages = self._messages(question, history)

        for attempt in range(self.max_repairs + 1):
            res.attempts = attempt + 1
            try:
                resp = self.llm.chat(messages, purpose="generate" if attempt == 0 else "repair")
            except LLMError as e:
                res.kind, res.message = "llm", str(e)
                break
            res.prompt_tokens += resp.prompt_tokens
            res.completion_tokens += resp.completion_tokens

            if "CANNOT_ANSWER" in resp.text:
                reason = resp.text.split("CANNOT_ANSWER", 1)[1].lstrip(": ").strip()
                res.kind, res.message = "unanswerable", reason or "Not answerable from this schema."
                res.trace.append({"attempt": attempt + 1, "status": "unanswerable", "detail": res.message})
                break

            sql = extract_sql(resp.text)
            res.sql = sql
            try:
                guard = validate_sql(sql, self.allowed_tables, self.max_rows, self.database)
                res.sql = guard.sql
                res.df = run_query(self.engine, guard.sql)
                res.kind, res.message = "success", ""
                res.trace.append({"attempt": attempt + 1, "status": "ok", "sql": guard.sql})
                break
            except GuardrailError as e:
                res.kind, res.message = "blocked", str(e)
                res.trace.append({"attempt": attempt + 1, "status": "blocked", "sql": sql, "detail": str(e)})
                if not e.retryable:
                    break
            except SQLAlchemyError as e:
                res.kind = "execution"
                res.message = str(getattr(e, "orig", e))[:300]
                res.trace.append({"attempt": attempt + 1, "status": "execution_error",
                                  "sql": sql, "detail": res.message})
            messages += [{"role": "assistant", "content": resp.text},
                         {"role": "user", "content": f"That query failed: {res.message}\n"
                          "Return the corrected SELECT only, in a ```sql block."}]

        if res.ok and summarize and res.df is not None and not res.df.empty:
            res.summary = self._summarize(question, res.df, res)
        res.latency_ms = int((time.perf_counter() - started) * 1000)
        return res

    def _summarize(self, question: str, df: pd.DataFrame, res: Result) -> str:
        try:
            data = df.head(25).to_csv(index=False)
            resp = self.llm.chat([
                {"role": "system", "content": "You explain query results to a business reader. "
                 "Answer in at most 2 sentences. Use ONLY numbers that appear in the data. "
                 "Do not speculate about causes."},
                {"role": "user", "content": f"Question: {question}\nResult (CSV):\n{data}"}],
                purpose="summarize", max_tokens=1000)
            res.prompt_tokens += resp.prompt_tokens
            res.completion_tokens += resp.completion_tokens
            return resp.text.strip()
        except LLMError:
            return ""
