"""Headless UI test: no stray 'None' text when earlier messages are replayed, and writes are refused."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from streamlit.testing.v1 import AppTest

from nl2sql.config import ROOT, load_settings
from nl2sql.db import make_engine
from nl2sql.llm import LLMClient, LLMResponse

SQL = ("SELECT country, COUNT(*) AS customers FROM customers GROUP BY country")


@pytest.fixture()
def app(monkeypatch):
    try:
        with make_engine(load_settings().db_url).connect() as c:
            c.execute(text("SELECT 1"))
    except OperationalError:
        pytest.skip("MySQL demo database not reachable")
    monkeypatch.setenv("LLM_API_KEY", "dummy")

    def fake(self, messages, purpose="generate", **kw):
        if purpose == "summarize":
            return LLMResponse(text="Five countries.")
        if "delete" in messages[-1]["content"].lower():
            return LLMResponse(text="-- CANNOT_ANSWER: modifying data not allowed")
        return LLMResponse(text=f"```sql\n{SQL}\n```", prompt_tokens=10, completion_tokens=5)

    monkeypatch.setattr(LLMClient, "chat", fake)
    return AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()


def walk(node):
    for child in getattr(node, "children", {}).values():
        yield child
        yield from walk(child)


def test_no_stray_none_after_replay_and_refusal(app):
    app.chat_input[0].set_value("customers per country?").run()
    app.chat_input[0].set_value("delete all orders").run()   # second run replays the first answer
    assert not app.exception
    text_types = ("markdown", "code", "text", "caption", "json")
    stray = [e for e in walk(app.main)
             if e.type in text_types and str(getattr(e, "value", "")).strip() in ("None", "`None`")]
    assert not stray, [(e.type, e.value) for e in stray]
    assert any("can't answer" in w.value for w in app.warning)
