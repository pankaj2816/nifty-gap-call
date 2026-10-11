from datetime import datetime, date, time, timezone
from zoneinfo import ZoneInfo
from typing import Optional

IST = ZoneInfo("Asia/Kolkata")
UTC = timezone.utc

MARKET_OPEN_TIME = time(9, 15)
MARKET_CLOSE_TIME = time(15, 30)

def now_ist() -> datetime:
    """Return current datetime in Asia/Kolkata timezone."""
    return datetime.now(IST)

def now_utc() -> datetime:
    """Return current datetime in UTC timezone."""
    return datetime.now(UTC)

def to_ist(dt: datetime) -> datetime:
    """Convert any aware or naive datetime to IST."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC).astimezone(IST)
    return dt.astimezone(IST)

def format_ist(dt: Optional[datetime]) -> str:
    """Format datetime as IST string: YYYY-MM-DD HH:MM:SS IST."""
    if not dt:
        return ""
    ist_dt = to_ist(dt)
    return ist_dt.strftime("%Y-%m-%d %H:%M:%S IST")

def is_market_open(dt: Optional[datetime] = None) -> bool:
    """
    Check if the Indian market (NSE) is currently open.
    Regular trading session: Monday to Friday, 09:15 to 15:30 IST.
    """
    ist_dt = to_ist(dt or now_ist())
    if ist_dt.weekday() >= 5:  # Saturday or Sunday
        return False
    current_time = ist_dt.time()
    return MARKET_OPEN_TIME <= current_time <= MARKET_CLOSE_TIME

def calculate_time_to_expiry_years(expiry_date: date, current_dt: Optional[datetime] = None) -> float:
    """
    Calculate annualized time to expiry (T) assuming market close at 15:30 IST on expiry day.
    Returns float in years (minimum 0.0001 for zero-division safety).
    """
    curr = to_ist(current_dt or now_ist())
    expiry_dt = datetime.combine(expiry_date, MARKET_CLOSE_TIME, tzinfo=IST)
    
    delta = expiry_dt - curr
    seconds = max(delta.total_seconds(), 60.0)  # at least 1 minute remaining if same day
    
    # 365 days / year basis for option pricing
    return seconds / (365.25 * 86400.0)
