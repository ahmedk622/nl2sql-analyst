"""Harness tests for the hard set: follow-ups get history, alternative golds are accepted, refusals scored."""
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from nl2sql.config import ROOT, load_settings
from nl2sql.db import make_engine
from nl2sql.evaluate import _summarize, run_questions, set_paths
from nl2sql.llm import LLMResponse
from nl2sql.pipeline import NL2SQL

HARD = json.loads(set_paths("hard")[0].read_text())


@pytest.fixture(scope="module")
def engine():
    try:
        e = make_engine(load_settings().db_url)
        with e.connect() as c:
            c.execute(text("SELECT 1"))
        return e
    except OperationalError:
        pytest.skip("MySQL demo database not reachable")


class ScriptedLLM:
    def __init__(self, questions, prefer_alt=()):
        self.by_q = {q["question"]: q for q in questions}
        self.prefer_alt, self.seen = set(prefer_alt), {}

    def chat(self, messages, purpose="generate", **kw):
        q = self.by_q[messages[-1]["content"].removeprefix("Question: ")]
        self.seen[q["id"]] = [m["content"] for m in messages]
        if q["expect"] == "refuse":
            return LLMResponse(text="-- CANNOT_ANSWER: not allowed")
        sql = q["accept"][0] if q["id"] in self.prefer_alt else q["gold_sql"]
        return LLMResponse(text=f"```sql\n{sql}\n```")


def test_hard_set_end_to_end_with_perfect_model(engine):
    llm = ScriptedLLM(HARD)
    rows = run_questions(NL2SQL(engine, llm), engine, HARD)
    failed = [r["id"] for r in rows if not r["passed"]]
    assert not failed, failed
    summary = _summarize(rows, "scripted", "test")
    assert summary["answer_accuracy"] == 1.0 and summary["safety_pass_rate"] == 1.0
    assert {"hard", "glossary", "ambiguous", "followup"} <= set(summary["by_category"])


def test_follow_up_receives_previous_question_and_sql(engine):
    llm = ScriptedLLM(HARD)
    run_questions(NL2SQL(engine, llm), engine, HARD)
    sent = " ".join(llm.seen[117])
    assert "net revenue by sales channel" in sent and "GROUP BY o.channel" in sent


def test_ambiguous_alternative_reading_is_accepted(engine):
    llm = ScriptedLLM(HARD, prefer_alt={114, 115})
    rows = {r["id"]: r for r in run_questions(NL2SQL(engine, llm), engine, HARD)}
    assert rows[114]["passed"] and rows[115]["passed"]


def test_wrong_answer_is_scored_wrong(engine):
    class Wrong(ScriptedLLM):
        def chat(self, messages, purpose="generate", **kw):
            return LLMResponse(text="```sql\nSELECT COUNT(*) FROM customers\n```")
    qs = [q for q in HARD if q["id"] in (101, 111)]
    rows = run_questions(NL2SQL(engine, Wrong(qs)), engine, qs)
    assert not any(r["passed"] for r in rows)
