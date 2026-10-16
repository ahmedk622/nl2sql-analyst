"""Evaluation harness: execution accuracy against gold SQL, plus refusal tests, latency and tokens.

  python scripts/run_eval.py                  # core set (21 questions + 3 safety), needs LLM_API_KEY
  python scripts/run_eval.py --set hard       # harder set: multi-turn, glossary, ambiguity, injection
  python scripts/run_eval.py --rescore        # re-score the saved report (no LLM calls)
  python scripts/run_eval.py --gold-check     # validate the gold queries only (add --set hard)

Two scores are reported:
  * answer_accuracy (primary): every column of the gold answer appears in the result, with identical
    values, rows and row count. Extra helpful columns (e.g. the revenue next to the top category) are allowed.
  * strict_exact: same as above AND no extra columns.
"""
from __future__ import annotations

import argparse
import json
import numbers
import shutil
import statistics
from collections import Counter
from decimal import ROUND_HALF_UP, Decimal
from itertools import permutations

import pandas as pd

from .config import ROOT, load_settings
from .db import make_engine, run_query
from .llm import LLMClient
from .pipeline import NL2SQL

SETS = {"core": ("questions.json", "report"), "hard": ("questions_hard.json", "report_hard")}
MAX_GEN_COLS = 10


def set_paths(name: str):
    qfile, stem = SETS[name]
    return ROOT / "eval" / qfile, ROOT / "eval" / f"{stem}.json", ROOT / "eval" / f"{stem}.md"


def _norm(v) -> str:
    """Canonical text for a cell. Numbers are rounded half-up to 2 decimals, like MySQL ROUND()."""
    try:
        if pd.isna(v):
            return "NULL"
    except (TypeError, ValueError):
        pass
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, numbers.Number):
        d = v if isinstance(v, Decimal) else Decimal(repr(float(v)))
        return f"{d.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP):.2f}"
    return str(v)


def _rows(df: pd.DataFrame, cols) -> Counter:
    return Counter(tuple(_norm(v) for v in row)
                   for row in df.iloc[:, list(cols)].itertuples(index=False, name=None))


def result_signature(df: pd.DataFrame) -> Counter:
    """Order-insensitive, column-order-insensitive multiset of rows (kept for tests/back-compat)."""
    return Counter(tuple(sorted(_norm(v) for v in row)) for row in df.itertuples(index=False, name=None))


def contains_answer(gen: pd.DataFrame, gold: pd.DataFrame) -> bool:
    """True if some selection/ordering of generated columns reproduces the gold result exactly."""
    k = gold.shape[1]
    if len(gen) != len(gold) or gen.shape[1] < k or gen.shape[1] > MAX_GEN_COLS:
        return False
    target = _rows(gold, range(k))
    return any(_rows(gen, cols) == target for cols in permutations(range(gen.shape[1]), k))


def exact_match(gen: pd.DataFrame, gold: pd.DataFrame) -> bool:
    return gen.shape[1] == gold.shape[1] and contains_answer(gen, gold)


def run_gold_check(engine, qfile) -> int:
    bad = 0
    for q in json.loads(qfile.read_text()):
        if q["expect"] != "answer":
            continue
        try:
            for sql in [q["gold_sql"], *q.get("accept", [])]:
                df = run_query(engine, sql)
            print(f"OK   #{q['id']:>3} rows={len(df):<4} {q['question']}")
        except Exception as e:  # noqa: BLE001
            bad += 1
            print(f"FAIL #{q['id']:>3} {q['question']}\n     {str(e)[:200]}")
    return bad


def _score(engine, q: dict, sql: str, kind: str) -> tuple[bool, bool]:
    """Returns (answer_correct, strict_exact) for an 'answer' question."""
    if kind != "success" or not sql:
        return False, False
    try:
        gen = run_query(engine, sql)
        golds = [run_query(engine, g) for g in [q["gold_sql"], *q.get("accept", [])]]
    except Exception:  # noqa: BLE001
        return False, False
    return any(contains_answer(gen, g) for g in golds), any(exact_match(gen, g) for g in golds)


def _is_refusal(x: dict) -> bool:
    return x.get("expect", "refuse" if x["difficulty"] == "safety" else "answer") == "refuse"


def _summarize(rows: list[dict], model: str, provider: str) -> dict:
    ans = [x for x in rows if not _is_refusal(x)]
    saf = [x for x in rows if _is_refusal(x)]
    n = max(len(ans), 1)
    return {
        "model": model, "provider": provider,
        "answer_accuracy": round(sum(x["passed"] for x in ans) / n, 3),
        "strict_exact": round(sum(x["exact"] for x in ans) / n, 3),
        "safety_pass_rate": round(sum(x["passed"] for x in saf) / max(len(saf), 1), 3),
        "first_try_rate": round(sum(x["attempts"] == 1 and x["passed"] for x in ans) / n, 3),
        "median_latency_ms": int(statistics.median(x["latency_ms"] for x in rows)),
        "avg_tokens": int(statistics.mean(x["tokens"] for x in rows)),
        "by_category": {d: round(sum(x["passed"] for x in ans if x["difficulty"] == d) /
                                 max(sum(1 for x in ans if x["difficulty"] == d), 1), 3)
                        for d in sorted({x["difficulty"] for x in ans})},
    }


def _write_reports(summary: dict, rows: list[dict], paths, note: str = "") -> None:
    _, report_json, report_md = paths
    report_json.write_text(json.dumps({"summary": summary, "results": rows}, indent=1, default=str))
    md = ["# Evaluation report", "", f"Model: `{summary['provider']}/{summary['model']}`", ""]
    if note:
        md += [note, ""]
    md += ["| Metric | Value |", "|---|---|"]
    md += [f"| {k} | {v} |" for k, v in summary.items() if k not in ("model", "provider", "by_category")]
    md += [f"| answer accuracy ({d}) | {v} |" for d, v in summary["by_category"].items()]
    md += ["", "## Failures", ""]
    fails = [x for x in rows if not x["passed"]]
    md += [f"- **#{x['id']}** {x['question']} -> `{x['kind']}` {x['message'][:120]}" for x in fails] or ["None."]
    report_md.write_text("\n".join(md))


def rescore(engine, paths) -> None:
    """Re-score the saved run with the current scorer (no LLM calls)."""
    qfile, report_json, _ = paths
    saved = json.loads(report_json.read_text())
    backup = report_json.with_name(report_json.stem + "_before_rescore.json")
    if not backup.exists():
        shutil.copy(report_json, backup)
    old = saved["summary"]
    qs = {q["id"]: q for q in json.loads(qfile.read_text())}
    rows = []
    for r in saved["results"]:
        if not _is_refusal(r):
            r["passed"], r["exact"] = _score(engine, qs[r["id"]], r["sql"], r["kind"])
        else:
            r["exact"] = r["passed"]
        rows.append(r)
    summary = _summarize(rows, old["model"], old["provider"])
    old_acc = old.get("answer_accuracy", old.get("execution_accuracy"))
    note = (f"_Re-scored from a saved run (no new LLM calls). Previous scorer required identical columns: "
            f"{old_acc}. Current scorer allows extra columns: {summary['answer_accuracy']}._")
    _write_reports(summary, rows, paths, note)
    print(note, "\n", json.dumps(summary, indent=1))


def run_questions(nl: NL2SQL, engine, questions: list[dict]) -> list[dict]:
    """Ask every question. Follow-ups receive the previous question + the model's OWN generated SQL."""
    rows, results = [], {}
    for q in questions:
        prev = results.get(q.get("follow_up_of"))
        history = [(prev.question, prev.sql)] if prev is not None and prev.sql else None
        r = nl.ask(q["question"], history=history, summarize=False)
        results[q["id"]] = r
        if q["expect"] == "refuse":
            passed = exact = r.kind in ("unanswerable", "blocked")
        else:
            passed, exact = _score(engine, q, r.sql, r.kind)
        rows.append({"id": q["id"], "difficulty": q["difficulty"], "expect": q["expect"],
                     "question": q["question"], "passed": passed, "exact": exact, "kind": r.kind,
                     "attempts": r.attempts, "latency_ms": r.latency_ms,
                     "tokens": r.prompt_tokens + r.completion_tokens, "sql": r.sql, "message": r.message})
        print(f"{'PASS' if passed else 'FAIL'}  #{q['id']:>3} [{q['difficulty']}] {q['question']}")
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", choices=sorted(SETS), default="core")
    ap.add_argument("--gold-check", action="store_true")
    ap.add_argument("--rescore", action="store_true")
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    s = load_settings()
    engine = make_engine(s.db_url)
    paths = set_paths(args.set)
    if args.gold_check:
        raise SystemExit(1 if run_gold_check(engine, paths[0]) else 0)
    if args.rescore:
        return rescore(engine, paths)
    if not s.llm_ready:
        raise SystemExit("Set LLM_API_KEY in .env first (free key: console.groq.com or aistudio.google.com).")

    llm = LLMClient(s.llm_provider, s.llm_api_key, s.llm_model, s.llm_base_url, s.log_path)
    nl = NL2SQL(engine, llm, s.max_rows, s.max_repairs)
    questions = json.loads(paths[0].read_text())
    if args.limit:
        questions = questions[: args.limit]
    rows = run_questions(nl, engine, questions)
    summary = _summarize(rows, s.llm_model, s.llm_provider)
    _write_reports(summary, rows, paths)
    print("\n", json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
