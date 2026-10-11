"""NSE 2026 regular sessions (FAOP71777/72262); XNYS holidays, early closes and DST.
Unknown years/special NSE session hours fail closed until the calendar is updated.
"""
from datetime import date, datetime, time, timedelta
from functools import lru_cache
from app.core.time_utils import IST

class CalendarUnavailable(ValueError):
    pass

NSE_HOLIDAYS_2026 = {date.fromisoformat(d) for d in (
    "2026-01-15", "2026-01-26", "2026-03-03", "2026-03-26", "2026-03-31",
    "2026-04-03", "2026-04-14", "2026-05-01", "2026-05-28", "2026-06-26",
    "2026-09-14", "2026-10-02", "2026-10-20", "2026-11-10", "2026-11-24", "2026-12-25",
)}

def nse_session_bounds(day: date):
    if day.year != 2026:
        raise CalendarUnavailable(f"Verified NSE session calendar unavailable for {day.year}.")
    if day == date(2026, 11, 8):
        raise CalendarUnavailable("NSE November 8 special-session hours require a calendar update.")
    if day.weekday() >= 5 or day in NSE_HOLIDAYS_2026:
        return None
    return datetime.combine(day, time(9, 15), IST), datetime.combine(day, time(15, 30), IST)

def nse_session_to_describe(now: datetime) -> date:
    clock = now.astimezone(IST)
    day = clock.date()
    for _ in range(15):
        bounds = nse_session_bounds(day)
        if bounds and clock < bounds[1]:
            return day
        day += timedelta(days=1)
    raise CalendarUnavailable("No upcoming verified NSE session.")

def latest_completed_nse_session(now: datetime) -> date:
    clock = now.astimezone(IST)
    day = clock.date()
    for _ in range(15):
        bounds = nse_session_bounds(day)
        if bounds and clock >= bounds[1]:
            return day
        day -= timedelta(days=1)
    raise CalendarUnavailable("No completed verified NSE session.")

@lru_cache(maxsize=4)
def _us_calendar(year):
    import exchange_calendars as xcals
    return xcals.get_calendar("XNYS", start=f"{year-1}-01-01", end=f"{year+1}-12-31")

def preceding_us_sessions(indian_session: date):
    """Expected US session leading this Indian open, its predecessor and close."""
    try:
        cal = _us_calendar(indian_session.year)
        expected = cal.date_to_session(indian_session - timedelta(days=1), direction="previous")
        previous = cal.previous_session(expected)
        return expected.date(), previous.date(), cal.session_close(expected).to_pydatetime()
    except Exception as exc:
        raise CalendarUnavailable("US exchange session calendar unavailable.") from exc
