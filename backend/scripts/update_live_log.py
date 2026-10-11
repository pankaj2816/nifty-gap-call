"""Refresh the gap log, the Excel file, and the static page. Used by GitHub Actions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.live_log import update_live_log


if __name__ == "__main__":
    result = update_live_log()
    print(result.get("updated_at"), result.get("summary"))
    if result.get("warning"):
        print(result["warning"])
        sys.exit(1)
