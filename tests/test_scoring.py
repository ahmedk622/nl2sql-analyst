import json
from decimal import Decimal

import pandas as pd
import pytest
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from nl2sql.config import ROOT, load_settings
from nl2sql.db import make_engine, run_query
from nl2sql.evaluate import contains_answer, exact_match


def df(cols, rows):
    return pd.DataFrame(rows, columns=cols)


def test_extra_column_counts_as_answer_but_not_exact():
    gold = df(["category"], [("Home",)])
    gen = df(["category", "rev"], [("Home", 207093.37)])
    assert contains_answer(gen, gold) and not exact_match(gen, gold)


def test_identical_is_exact_and_column_order_irrelevant():
    gold = df(["a", "b"], [("x", 1), ("y", 2)])
    assert exact_match(df(["b", "a"], [(2, "y"), (1, "x")]), gold)


def test_wrong_value_fails():
    assert not contains_answer(df(["c", "r"], [("Fashion", 1.0)]), df(["c"], [("Home",)]))


def test_row_count_must_match():
    gold = df(["c"], [("a",), ("b",)])
    assert not contains_answer(df(["c", "n"], [("a", 1)]), gold)


def test_half_cent_rounding_matches_mysql_round():
    # MySQL ROUND(17874.355, 2) = 17874.36; naive float round() would give 17874.35
    assert contains_answer(df(["m", "r"], [("2025-01", 17874.355)]), df(["m", "r"], [("2025-01", Decimal("17874.36"))]))


def test_nan_and_none_equal():
    assert exact_match(df(["g"], [(float("nan"),)]), df(["g"], [(None,)]))


@pytest.fixture(scope="module")
def engine():
    try:
        e = make_engine(load_settings().db_url)
        with e.connect() as c:
            c.execute(text("SELECT 1"))
        return e
    except OperationalError:
        pytest.skip("MySQL demo database not reachable")


QS = {str(q["id"]): q for q in json.loads((ROOT / "eval" / "questions.json").read_text())}
SAVED = json.loads((ROOT / "tests" / "fixtures" / "gpt_oss_failures.json").read_text())


@pytest.mark.parametrize("qid", sorted(SAVED, key=int))
def test_real_model_outputs_that_were_marked_wrong_are_correct_answers(engine, qid):
    """These 8 queries were written by openai/gpt-oss-120b and failed the old, stricter scorer."""
    gen = run_query(engine, SAVED[qid])
    gold = run_query(engine, QS[qid]["gold_sql"])
    assert contains_answer(gen, gold), f"#{qid} really is a wrong answer"
