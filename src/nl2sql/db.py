"""Database access: engine factory + safe query runner."""
from __future__ import annotations

from decimal import Decimal

import pandas as pd
from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine

QUERY_TIMEOUT_MS = 8000


def make_engine(url) -> Engine:
    engine = create_engine(url, pool_pre_ping=True, pool_recycle=1800,
                           connect_args={"read_timeout": 15} if "mysql" in str(url) else {})
    if engine.dialect.name == "mysql":
        @event.listens_for(engine, "connect")
        def _harden(dbapi_conn, _record):  # runs for every new connection
            cur = dbapi_conn.cursor()
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute(f"SET SESSION MAX_EXECUTION_TIME={QUERY_TIMEOUT_MS}")
            cur.close()
    return engine


def run_query(engine: Engine, sql: str) -> pd.DataFrame:
    """Execute a (pre-validated) query. Raises SQLAlchemyError directly (no pandas wrapper)."""
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        df = pd.DataFrame(result.fetchall(), columns=list(result.keys()))
    for col in df.columns:  # MySQL SUM()/AVG() return Decimal -> make them chartable floats
        non_null = df[col].dropna()
        if len(non_null) and all(isinstance(v, Decimal) for v in non_null):
            df[col] = df[col].astype(float)
    return df
