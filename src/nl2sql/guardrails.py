"""SQL safety layer. Every generated query passes through validate_sql() before it touches the DB.

Defence in depth: (1) this AST-level check, (2) a read-only MySQL user,
(3) READ ONLY session + execution timeout (see db.py).
"""
from __future__ import annotations

from dataclasses import dataclass

import re

import sqlglot
from sqlglot import exp


class GuardrailError(ValueError):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable  # False => never ask the LLM to "fix" it (e.g. a write attempt)


_FORBIDDEN_NAMES = ["Insert", "Update", "Delete", "Drop", "Create", "Alter", "AlterTable", "Command",
                    "TruncateTable", "Merge", "Into", "Set", "Use", "Commit", "Rollback", "Transaction",
                    "LoadData", "Lock", "Pragma", "Describe", "Show", "Grant", "Parameter", "SessionParameter"]
FORBIDDEN_NODES = tuple(getattr(exp, n) for n in _FORBIDDEN_NAMES if hasattr(exp, n))
FORBIDDEN_FUNCS = {"sleep", "benchmark", "load_file", "get_lock", "release_lock", "sys_exec", "sys_eval"}


@dataclass
class GuardResult:
    sql: str
    tables: set[str]
    limit_applied: bool


def _func_name(node: exp.Expression) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.this).lower()
    if isinstance(node, exp.Func):
        return node.sql_name().lower()
    return ""


def validate_sql(sql: str, allowed_tables: set[str], max_rows: int = 500,
                 database: str | None = None) -> GuardResult:
    sql = (sql or "").strip()
    if not sql:
        raise GuardrailError("Empty SQL.")
    if re.search(r"\binto\s+(outfile|dumpfile)\b", sql, re.I):
        raise GuardrailError("Writing query results to files is not allowed.", retryable=False)
    try:
        statements = [s for s in sqlglot.parse(sql, read="mysql") if s is not None]
    except sqlglot.errors.ParseError as e:
        raise GuardrailError(f"SQL could not be parsed: {str(e)[:200]}")
    if len(statements) != 1:
        raise GuardrailError("Exactly one SQL statement is allowed.", retryable=False)
    tree = statements[0]

    if not isinstance(tree, (exp.Select, exp.Union)):
        raise GuardrailError("Only read-only SELECT statements are allowed.", retryable=False)

    for node in tree.walk():
        if isinstance(node, FORBIDDEN_NODES):
            raise GuardrailError(f"Forbidden construct: {type(node).__name__}.", retryable=False)
        if _func_name(node) in FORBIDDEN_FUNCS:
            raise GuardrailError(f"Forbidden function: {_func_name(node)}.", retryable=False)

    cte_names = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    allowed = {t.lower() for t in allowed_tables}
    used: set[str] = set()
    for tbl in tree.find_all(exp.Table):
        name = tbl.name.lower()
        if name in cte_names:
            continue
        if tbl.db and database and tbl.db.lower() != database.lower():
            raise GuardrailError(f"Access to schema '{tbl.db}' is not allowed.", retryable=False)
        if tbl.db and not database:
            raise GuardrailError("Schema-qualified tables are not allowed.", retryable=False)
        if name not in allowed:
            raise GuardrailError(f"Unknown table '{tbl.name}'. Allowed: {', '.join(sorted(allowed))}.")
        used.add(name)

    limit_applied = False
    limit = tree.args.get("limit")
    current = None
    if limit is not None:
        try:
            current = int(limit.expression.name)
        except (ValueError, AttributeError, TypeError):
            current = None
    if limit is None or current is None or current > max_rows:
        tree = tree.limit(max_rows)
        limit_applied = True

    return GuardResult(sql=tree.sql(dialect="mysql"), tables=used, limit_applied=limit_applied)
