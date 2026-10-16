import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nl2sql.evaluate import main  # noqa: E402

main()
