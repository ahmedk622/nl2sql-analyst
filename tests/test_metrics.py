import json

import pandas as pd

from nl2sql.metrics import daily_usage, estimated_cost, latency_summary, load_calls, repair_rate


def write(tmp_path, rows, extra=""):
    p = tmp_path / "calls.jsonl"
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n" + extra, encoding="utf-8")
    return p


def row(ts, purpose="generate", model="m1", pt=100, ct=20, lat=1000, retries=0):
    return {"ts": ts, "provider": "groq", "model": model, "purpose": purpose,
            "prompt_tokens": pt, "completion_tokens": ct, "latency_ms": lat, "retries": retries}


def test_missing_file_gives_empty_frame(tmp_path):
    df = load_calls(tmp_path / "nope.jsonl")
    assert df.empty and "total_tokens" in df.columns
    assert estimated_cost(df, 1, 1) == 0.0 and repair_rate(df) == 0.0
    assert latency_summary(df).empty and daily_usage(df).empty


def test_corrupt_and_blank_lines_are_skipped(tmp_path):
    p = write(tmp_path, [row("2026-10-12T10:00:00+00:00")], extra='{"broken json\n\n')
    assert len(load_calls(p)) == 1


def test_cost_uses_caller_prices(tmp_path):
    df = load_calls(write(tmp_path, [row("2026-10-12T10:00:00+00:00", pt=1_000_000, ct=500_000)]))
    assert estimated_cost(df, 0.10, 0.50) == 0.10 + 0.25
    assert estimated_cost(df, 0, 0) == 0


def test_repair_rate_and_summary(tmp_path):
    rows = [row("2026-10-12T10:00:00+00:00", lat=100), row("2026-10-12T10:01:00+00:00", lat=300),
            row("2026-10-12T10:02:00+00:00", purpose="repair", lat=500, retries=2),
            row("2026-10-13T09:00:00+00:00", purpose="summarize", lat=200)]
    df = load_calls(write(tmp_path, rows))
    assert repair_rate(df) == 0.5
    s = latency_summary(df).set_index("purpose")
    assert s.loc["generate", "p50_ms"] == 200 and s.loc["repair", "http_retries"] == 2
    d = daily_usage(df)
    assert list(d["calls"]) == [3, 1]


def test_sorted_by_time_and_types(tmp_path):
    df = load_calls(write(tmp_path, [row("2026-10-12T11:00:00+00:00"), row("2026-10-12T10:00:00+00:00")]))
    assert df["ts"].is_monotonic_increasing and pd.api.types.is_integer_dtype(df["latency_ms"])
