"""Read logs/llm_calls.jsonl and compute cost / latency / usage metrics (used by the dashboard page)."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

COLUMNS = ["ts", "provider", "model", "purpose", "prompt_tokens", "completion_tokens", "latency_ms", "retries"]
NUMERIC = ["prompt_tokens", "completion_tokens", "latency_ms", "retries"]


def load_calls(path: Path) -> pd.DataFrame:
    """Parse the JSONL call log. Blank or corrupt lines are skipped, never fatal."""
    rows = []
    p = Path(path)
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    df = pd.DataFrame(rows, columns=COLUMNS)
    if df.empty:
        df["total_tokens"] = pd.Series(dtype="int64")
        return df
    df["ts"] = pd.to_datetime(df["ts"], utc=True, errors="coerce")
    for c in NUMERIC:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0).astype(int)
    df["total_tokens"] = df["prompt_tokens"] + df["completion_tokens"]
    return df.dropna(subset=["ts"]).sort_values("ts").reset_index(drop=True)


def estimated_cost(df: pd.DataFrame, in_price_per_m: float, out_price_per_m: float) -> float:
    """Dollar estimate from token counts. Prices are the caller's: nothing is hard-coded."""
    if df.empty:
        return 0.0
    return float((df["prompt_tokens"].sum() * in_price_per_m + df["completion_tokens"].sum() * out_price_per_m) / 1e6)


def repair_rate(df: pd.DataFrame) -> float:
    """Share of generate calls that needed at least one SQL self-repair call."""
    gen = int((df["purpose"] == "generate").sum())
    return float((df["purpose"] == "repair").sum() / gen) if gen else 0.0


def latency_summary(df: pd.DataFrame) -> pd.DataFrame:
    cols = ["model", "purpose", "calls", "p50_ms", "p95_ms", "avg_tokens", "http_retries"]
    if df.empty:
        return pd.DataFrame(columns=cols)
    out = (df.groupby(["model", "purpose"])
             .agg(calls=("latency_ms", "size"), p50_ms=("latency_ms", "median"),
                  p95_ms=("latency_ms", lambda s: s.quantile(0.95)),
                  avg_tokens=("total_tokens", "mean"), http_retries=("retries", "sum"))
             .reset_index())
    for c in ("p50_ms", "p95_ms", "avg_tokens"):
        out[c] = out[c].round().astype(int)
    return out[cols]


def daily_usage(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["calls", "tokens"])
    d = df.assign(day=df["ts"].dt.date)
    return d.groupby("day").agg(calls=("latency_ms", "size"), tokens=("total_tokens", "sum"))
