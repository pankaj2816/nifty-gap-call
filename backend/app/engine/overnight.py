"""Prior completed US-session gap context; never a post-open continuation call."""
import math
from datetime import datetime
from typing import Any, Dict, Optional, Sequence
from app.core.time_utils import now_ist
from app.core.market_calendar import (
    CalendarUnavailable, nse_session_to_describe, nse_session_bounds, preceding_us_sessions,
)

STRONG_MOVE = 0.01
# Frozen audit evidence. Separate targets, not calibrated forecasts.
DEVELOPMENT_EVIDENCE = {
    "sample_size": 580, "coverage_pct": 23.53,
    "close_to_close": {"correct": 395, "accuracy_pct": 68.10},
    "opening_gap": {"correct": 488, "accuracy_pct": 84.14},
    "open_to_close": {"correct": 271, "accuracy_pct": 46.72, "always_up_pct": 47.59},
    "status": "DEVELOPMENT_EVIDENCE",
}

def session_being_called(now: datetime):
    return nse_session_to_describe(now)

def us_return_before(bars: Sequence[Dict[str, Any]], session_date: str) -> Optional[Dict[str, Any]]:
    """Historical diagnostic only; live eligibility is checked by describe_overnight."""
    days = sorted((b for b in bars if b.get("date", "") < session_date and b.get("close")), key=lambda b: b["date"])
    if len(days) < 2:
        return None
    return {"us_date": days[-1]["date"], "return_pct": (days[-1]["close"] / days[-2]["close"] - 1) * 100}

def describe_overnight(bars: Sequence[Dict[str, Any]], now: Optional[datetime] = None,
                       is_stale: bool = False) -> Dict[str, Any]:
    clock = now or now_ist()
    base = {"session_date": None, "changes_weekly_trade": False, "available": False,
            "call": "NO_CALL", "gap_call": "NO_CALL", "strength": "unavailable",
            "target": "OPENING_GAP", "evidence": DEVELOPMENT_EVIDENCE}
    try:
        if clock.tzinfo is None:
            raise CalendarUnavailable("An aware decision timestamp is required.")
        session = session_being_called(clock)
        expected, previous, us_close = preceding_us_sessions(session)
        base.update(session_date=session.isoformat(), expected_us_date=expected.isoformat())
        if clock < us_close:
            return dict(base, strength="pending", text="No gap call yet. The immediately preceding US session has not completed.")
        if is_stale:
            return dict(base, strength="stale", text="No gap call. The US history source is stale.")
        required = {expected.isoformat(), previous.isoformat()}
        matched = [b for b in bars if b.get("date") in required]
        if len(matched) != 2 or {b["date"] for b in matched} != required:
            return dict(base, strength="stale", text="No gap call. The immediately preceding completed US session or its prior close is missing.")
        by_date = {b["date"]: b for b in matched}
        if any(b.get("is_complete") is False or not math.isfinite(float(b["close"])) or float(b["close"]) <= 0 for b in matched):
            return dict(base, strength="unavailable", text="No gap call. US closing observations are incomplete or invalid.")
        change = (float(by_date[expected.isoformat()]["close"]) / float(by_date[previous.isoformat()]["close"]) - 1) * 100
        post_open = clock >= nse_session_bounds(session)[0]
    except (CalendarUnavailable, ValueError, KeyError, TypeError) as exc:
        return dict(base, text=f"No gap call. {exc}")

    strong = abs(change) >= STRONG_MOVE * 100
    gap_call = ("UP" if change > 0 else "DOWN") if strong else "NO_CALL"
    text = f"S&P 500 {change:+.2f}% in the completed {expected.isoformat()} US session. "
    if not strong:
        text += "No gap call: the move is under the 1% line."
    elif post_open:
        text += "The Indian open has passed; this is opening-gap context only. No open-to-close continuation call."
    else:
        text += f"Pre-open gap tendency for {session.isoformat()}: {gap_call.lower()}. This is not an intraday continuation forecast."
    return dict(base, available=True, call=gap_call if not post_open else "NO_CALL", gap_call=gap_call,
                strength="context" if post_open else "strong" if strong else "quiet",
                phase="POST_OPEN" if post_open else "PRE_OPEN", us_date=expected.isoformat(),
                us_return_pct=round(change, 2), text=text)
