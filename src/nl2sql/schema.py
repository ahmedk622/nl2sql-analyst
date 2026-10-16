"""Schema introspection -> compact text the LLM can read (types, keys, comments, sample values)."""
from __future__ import annotations

from sqlalchemy import inspect, text
from sqlalchemy.engine import Engine
from sqlalchemy.types import String


def get_table_names(engine: Engine) -> set[str]:
    return set(inspect(engine).get_table_names())


def _sample_values(engine: Engine, table: str, column: str, max_distinct: int = 12) -> list[str]:
    q = text(f"SELECT DISTINCT `{column}` FROM `{table}` WHERE `{column}` IS NOT NULL LIMIT {max_distinct + 1}")
    with engine.connect() as conn:
        vals = [str(r[0]) for r in conn.execute(q)]
    return vals if len(vals) <= max_distinct else []


def get_schema_text(engine: Engine, include_samples: bool = True) -> str:
    insp = inspect(engine)
    blocks = []
    for table in sorted(insp.get_table_names()):
        pks = set(insp.get_pk_constraint(table).get("constrained_columns") or [])
        fks = {}
        for fk in insp.get_foreign_keys(table):
            for col, rcol in zip(fk["constrained_columns"], fk["referred_columns"]):
                fks[col] = f"{fk['referred_table']}.{rcol}"
        lines = [f"TABLE {table}"]
        for col in insp.get_columns(table):
            name = col["name"]
            parts = [f"  {name} {str(col['type']).split('(')[0]}"]
            if name in pks:
                parts.append("PK")
            if name in fks:
                parts.append(f"FK->{fks[name]}")
            if col.get("comment"):
                parts.append(f"-- {col['comment']}")
            if include_samples and isinstance(col["type"], String) and name not in pks:
                vals = _sample_values(engine, table, name)
                if vals:
                    parts.append("values: " + " | ".join(vals))
            lines.append(" ".join(parts))
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)
