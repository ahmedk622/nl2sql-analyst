"""Runs against the real MySQL demo DB (skipped automatically if it is not reachable)."""
import json

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, OperationalError

from nl2sql.config import ROOT, load_settings
from nl2sql.db import make_engine
from nl2sql.evaluate import result_signature
from nl2sql.db import run_query
from nl2sql.llm import LLMResponse
from nl2sql.pipeline import NL2SQL

QUESTIONS = json.loads((ROOT / "eval" / "questions.json").read_text())


@pytest.fixture(scope="module")
def engine():
    try:
        e = make_engine(load_settings().db_url)
        with e.connect() as c:
            c.execute(text("SELECT 1"))
        return e
    except OperationalError:
        pytest.skip("MySQL demo database not reachable")


class GoldLLM:
    """Pretends to be a perfect model: returns the gold SQL for the question it is asked."""

    def chat(self, messages, purpose="generate", **kw):
        q = messages[-1]["content"].removeprefix("Question: ")
        if purpose == "summarize":
            return LLMResponse(text="ok")
        gold = next((x["gold_sql"] for x in QUESTIONS if x["question"] == q), "")
        return LLMResponse(text=f"```sql\n{gold}\n```" if gold else "-- CANNOT_ANSWER: out of scope")


def test_app_user_cannot_write(engine):
    with pytest.raises(DBAPIError):
        with engine.begin() as c:
            c.execute(text("DELETE FROM orders"))


def test_session_is_read_only_and_has_timeout(engine):
    with engine.connect() as c:
        assert c.execute(text("SELECT @@transaction_read_only")).scalar() == 1
        assert c.execute(text("SELECT @@max_execution_time")).scalar() == 8000


def test_schema_text_has_comments_and_values(engine):
    schema = NL2SQL(engine, GoldLLM()).context
    assert "completed | cancelled" in schema or "cancelled" in schema
    assert "Net revenue" in schema and "FK->customers.customer_id" in schema


@pytest.mark.parametrize("q", [x for x in QUESTIONS if x["expect"] == "answer"], ids=lambda x: str(x["id"]))
def test_gold_through_full_pipeline_matches_itself(engine, q):
    r = NL2SQL(engine, GoldLLM()).ask(q["question"], summarize=False)
    assert r.ok, r.message
    assert result_signature(r.df) == result_signature(run_query(engine, q["gold_sql"]))


def test_refusal_questions(engine):
    for q in [x for x in QUESTIONS if x["expect"] == "refuse"]:
        r = NL2SQL(engine, GoldLLM()).ask(q["question"])
        assert r.kind in ("unanswerable", "blocked")
