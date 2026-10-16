"""Pipeline tests with a scripted fake LLM on in-memory SQLite (no API key, no MySQL needed)."""
import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

from nl2sql.llm import LLMError, LLMResponse
from nl2sql.pipeline import NL2SQL, extract_sql


class FakeLLM:
    def __init__(self, replies):
        self.replies, self.calls = list(replies), []

    def chat(self, messages, purpose="generate", **kw):
        self.calls.append((purpose, messages))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return LLMResponse(text=r, prompt_tokens=10, completion_tokens=5, latency_ms=1)


@pytest.fixture()
def engine():
    e = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    with e.begin() as c:
        c.execute(text("CREATE TABLE customers (customer_id INTEGER PRIMARY KEY, name VARCHAR(40), country VARCHAR(20))"))
        c.execute(text("INSERT INTO customers VALUES (1,'A','India'),(2,'B','UAE'),(3,'C','India')"))
    return e


def sql_block(s):
    return f"```sql\n{s}\n```"


def test_extract_sql_variants():
    assert extract_sql("```sql\nSELECT 1;\n```") == "SELECT 1"
    assert extract_sql("SELECT 2") == "SELECT 2"


def test_happy_path(engine):
    llm = FakeLLM([sql_block("SELECT country, COUNT(*) AS n FROM customers GROUP BY country"), "India has 2 customers."])
    r = NL2SQL(engine, llm).ask("customers per country?")
    assert r.ok and len(r.df) == 2 and r.attempts == 1
    assert r.summary.startswith("India") and r.prompt_tokens == 20


def test_self_repair_after_execution_error(engine):
    llm = FakeLLM([sql_block("SELECT nme FROM customers"), sql_block("SELECT name FROM customers")])
    r = NL2SQL(engine, llm).ask("names?", summarize=False)
    assert r.ok and r.attempts == 2
    assert llm.calls[1][0] == "repair"
    assert "failed" in llm.calls[1][1][-1]["content"]


def test_write_attempt_blocked_without_retry(engine):
    llm = FakeLLM([sql_block("DELETE FROM customers")])
    r = NL2SQL(engine, llm).ask("delete everyone")
    assert r.kind == "blocked" and r.attempts == 1 and len(llm.calls) == 1
    with engine.connect() as c:
        assert c.execute(text("SELECT COUNT(*) FROM customers")).scalar() == 3


def test_unknown_table_triggers_repair(engine):
    llm = FakeLLM([sql_block("SELECT * FROM users"), sql_block("SELECT * FROM customers")])
    r = NL2SQL(engine, llm).ask("who?", summarize=False)
    assert r.ok and r.attempts == 2


def test_cannot_answer(engine):
    llm = FakeLLM(["-- CANNOT_ANSWER: no salary data in the schema"])
    r = NL2SQL(engine, llm).ask("CEO salary?")
    assert r.kind == "unanswerable" and "salary" in r.message


def test_gives_up_after_max_repairs(engine):
    llm = FakeLLM([sql_block("SELECT bad FROM customers")] * 3)
    r = NL2SQL(engine, llm, max_repairs=2).ask("x", summarize=False)
    assert r.kind == "execution" and r.attempts == 3


def test_llm_failure_is_reported_not_raised(engine):
    r = NL2SQL(engine, FakeLLM([LLMError("rate limited")])).ask("x")
    assert r.kind == "llm" and "rate limited" in r.message


def test_follow_up_history_is_sent(engine):
    llm = FakeLLM([sql_block("SELECT * FROM customers WHERE country='India'")])
    NL2SQL(engine, llm).ask("only India", history=[("all customers", "SELECT * FROM customers")], summarize=False)
    contents = [m["content"] for m in llm.calls[0][1]]
    assert any("all customers" in c for c in contents)


def test_empty_result_skips_summary(engine):
    llm = FakeLLM([sql_block("SELECT * FROM customers WHERE country='Mars'")])
    r = NL2SQL(engine, llm).ask("mars?")
    assert r.ok and r.df.empty and r.summary == "" and len(llm.calls) == 1
