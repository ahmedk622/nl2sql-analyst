"""Print generated SQL vs gold SQL (with sample rows) for every failed question in a saved report.

  python scripts/show_failures.py            # core set
  python scripts/show_failures.py hard       # hard set
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nl2sql.config import load_settings  # noqa: E402
from nl2sql.db import make_engine, run_query  # noqa: E402

name = sys.argv[1] if len(sys.argv) > 1 else "core"
qfile = {"core": "questions.json", "hard": "questions_hard.json"}[name]
rfile = {"core": "report.json", "hard": "report_hard.json"}[name]
e = make_engine(load_settings().db_url)
qs = {q["id"]: q for q in json.load(open("eval/" + qfile))}
for r in json.load(open("eval/" + rfile))["results"]:
    if r["passed"] or r["expect"] == "refuse":
        continue
    print("=" * 70)
    print("#%s %s" % (r["id"], r["question"]))
    print("\nGENERATED SQL:\n", r["sql"])
    try:
        print("\nGENERATED RESULT:\n", run_query(e, r["sql"]).head(5).to_string(index=False))
    except Exception as ex:  # noqa: BLE001
        print("ERROR:", ex)
    print("\nGOLD RESULT:\n", run_query(e, qs[r["id"]]["gold_sql"]).head(5).to_string(index=False))
