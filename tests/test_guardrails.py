import pytest

from nl2sql.guardrails import GuardrailError, validate_sql

TABLES = {"customers", "orders", "order_items", "products"}


def ok(sql, **kw):
    return validate_sql(sql, TABLES, **kw)


def test_simple_select_gets_limit():
    r = ok("SELECT * FROM customers")
    assert "LIMIT 500" in r.sql and r.limit_applied


def test_existing_small_limit_kept():
    r = ok("SELECT * FROM customers LIMIT 5")
    assert "LIMIT 5" in r.sql and not r.limit_applied


def test_huge_limit_capped():
    assert "LIMIT 500" in ok("SELECT * FROM customers LIMIT 100000").sql


def test_cte_and_window_function_allowed():
    sql = ("WITH m AS (SELECT order_id, COUNT(*) n FROM order_items GROUP BY order_id) "
           "SELECT order_id, ROW_NUMBER() OVER (ORDER BY n DESC) FROM m")
    assert ok(sql).tables == {"order_items"}


def test_percent_in_date_format_survives():
    assert "%Y-%m" in ok("SELECT DATE_FORMAT(order_date,'%Y-%m') FROM orders").sql


def test_union_allowed_and_limited():
    assert "LIMIT" in ok("SELECT name FROM customers UNION SELECT name FROM products").sql


@pytest.mark.parametrize("sql", [
    "DELETE FROM orders",
    "DROP TABLE customers",
    "UPDATE customers SET name='x'",
    "INSERT INTO customers VALUES (1)",
    "TRUNCATE TABLE orders",
    "ALTER TABLE orders ADD COLUMN x INT",
    "CREATE TABLE t (a INT)",
    "SELECT * FROM customers INTO OUTFILE '/tmp/x'",
    "SET @a = 1",
    "SHOW TABLES",
])
def test_write_and_admin_statements_blocked_and_not_retryable(sql):
    with pytest.raises(GuardrailError) as e:
        ok(sql)
    assert e.value.retryable is False


def test_multi_statement_blocked():
    with pytest.raises(GuardrailError):
        ok("SELECT 1; DROP TABLE customers")


@pytest.mark.parametrize("sql", [
    "SELECT SLEEP(10)",
    "SELECT BENCHMARK(1000000, MD5('a'))",
    "SELECT LOAD_FILE('/etc/passwd')",
])
def test_dangerous_functions_blocked(sql):
    with pytest.raises(GuardrailError):
        ok(sql)


def test_unknown_table_is_retryable():
    with pytest.raises(GuardrailError) as e:
        ok("SELECT * FROM salaries")
    assert e.value.retryable is True


def test_system_schema_blocked():
    with pytest.raises(GuardrailError):
        ok("SELECT * FROM information_schema.tables")
    with pytest.raises(GuardrailError):
        validate_sql("SELECT * FROM mysql.user", TABLES, database="analytics_demo")


def test_own_database_qualifier_allowed():
    r = validate_sql("SELECT * FROM analytics_demo.customers", TABLES, database="analytics_demo")
    assert r.tables == {"customers"}


def test_garbage_and_empty():
    with pytest.raises(GuardrailError):
        ok("")
    with pytest.raises(GuardrailError):
        ok("this is not sql at all")
