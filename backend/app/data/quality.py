"""Eligibility of daily history at the decision clock (independent of cache TTL)."""
import math
from datetime import date, datetime, timezone
from app.core.market_calendar import latest_completed_nse_session, nse_session_bounds, CalendarUnavailable

def daily_history_issue(history, now: datetime):
    if history.get("is_stale", True):
        return "Daily history is stale; refresh completed NIFTY and VIX observations."
    bars = history.get("bars", [])
    if not bars:
        return "No daily history available."
    try:
        dates = [b["date"] for b in bars]
        if dates != sorted(set(dates)):
            return "Daily dates are duplicated or out of order."
        last = bars[-1]
        day = date.fromisoformat(last["date"])
        bounds = nse_session_bounds(day)
        if not bounds or now < bounds[1] or last.get("is_complete") is False:
            return "The latest daily bar is unfinished or is not a verified trading session."
        fetched = datetime.fromtimestamp(float(history["fetched_at"]), timezone.utc)
        if fetched < bounds[1] or fetched > now:
            return "The daily snapshot was fetched before its close or has an invalid timestamp."
        if day != latest_completed_nse_session(now):
            return "The latest completed NSE session is missing from daily history."
        if last.get("vix_date", last["date"]) != last["date"] or last.get("vix_complete") is False:
            return "India VIX is stale or unfinished for the decision bar."
        if any(not math.isfinite(float(last[k])) or float(last[k]) <= 0 for k in ("open", "high", "low", "close", "vix")):
            return "Daily prices or VIX are invalid."
    except (CalendarUnavailable, ValueError, KeyError, TypeError, OverflowError) as exc:
        return f"Daily history cannot be verified: {exc}"
    return None
