"""Refresh the gap log, the Excel file, and the static page. Used by GitHub Actions."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.engine.live_log import update_live_log
from app.engine.short_term import update_short_term


if __name__ == "__main__":
    result = update_live_log()
    latest = (result.get("rows") or [{}])[-1]
    print(result.get("updated_at"), result.get("summary"))
    print("data", result.get("data_status"), "open", latest.get("nifty_open"), "review", latest.get("review"))
    if result.get("warning"):
        print(result["warning"])
        sys.exit(1)
    try:
        short = update_short_term()
        print("short", short.get("summary"))
    except Exception as exc:
        print("short-term update failed:", exc)
