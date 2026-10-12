import json
import os
import time
from datetime import datetime, timezone, time as wall_time
from zoneinfo import ZoneInfo
from typing import Any, Dict, List, Optional

import requests

from app.core.time_utils import IST, now_ist
from app.data.quality import daily_history_issue

CACHE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "data_cache"))
CACHE_FILE = os.path.join(CACHE_DIR, "nifty_vix_daily.json")
CACHE_MAX_AGE_SECONDS = 12 * 3600

YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"
NIFTY_SYMBOL = "^NSEI"
VIX_SYMBOL = "^INDIAVIX"
SPX_SYMBOL = "^GSPC"
SPX_CACHE_FILE = os.path.join(CACHE_DIR, "spx_daily.json")

_memory_cache: Optional[Dict[str, Any]] = None


def _fetch_yahoo_daily(symbol: str, years: int = 10) -> Dict[str, Dict[str, float]]:
    """Return {YYYY-MM-DD: {open, high, low, close, volume}} for a Yahoo symbol."""
    result = None
    last_error = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        url = f"https://{host}/v8/finance/chart/{requests.utils.quote(symbol)}"
        try:
            resp = requests.get(
                url,
                params={"range": f"{years}y", "interval": "1d"},
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20,
            )
            resp.raise_for_status()
            result = resp.json()["chart"]["result"][0]
            break
        except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
            last_error = exc
    if result is None:
        raise requests.RequestException(str(last_error))
    quote = result["indicators"]["quote"][0]
    bars: Dict[str, Dict[str, float]] = {}
    for i, ts in enumerate(result["timestamp"]):
        close = quote["close"][i]
        if close is None:
            continue
        zone = ZoneInfo("America/New_York") if symbol == SPX_SYMBOL else IST
        session_day = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(zone).date()
        day = session_day.isoformat()
        if symbol == SPX_SYMBOL:
            from app.core.market_calendar import _us_calendar
            closed_at = _us_calendar(session_day.year).session_close(day).to_pydatetime()
        else:
            closed_at = datetime.combine(session_day, wall_time(15, 30), IST)
        bars[day] = {
            "open": quote["open"][i] if quote["open"][i] is not None else close,
            "high": quote["high"][i] if quote["high"][i] is not None else close,
            "low": quote["low"][i] if quote["low"][i] is not None else close,
            "close": close,
            "volume": quote["volume"][i] or 0,
            "is_complete": datetime.now(timezone.utc) >= closed_at,
        }
    return bars


def _merge(nifty: Dict[str, Dict[str, float]], vix: Dict[str, Dict[str, float]]) -> List[Dict[str, Any]]:
    """Join NIFTY bars with India VIX closes, carrying the last VIX forward on missing days."""
    merged = []
    last_vix = None
    vix_day, vix_complete = None, False
    for day in sorted(nifty):
        if day in vix:
            last_vix = vix[day]["close"]
            vix_day, vix_complete = day, vix[day].get("is_complete", True)
        if last_vix is None:
            continue
        bar = nifty[day]
        merged.append({
            "date": day,
            "open": round(bar["open"], 2),
            "high": round(bar["high"], 2),
            "low": round(bar["low"], 2),
            "close": round(bar["close"], 2),
            "volume": int(bar["volume"]),
            "vix": round(last_vix, 2),
            "is_complete": bar.get("is_complete", True),
            "vix_date": vix_day,
            "vix_complete": vix_complete,
        })
    return merged


def _read_cache() -> Optional[Dict[str, Any]]:
    if not os.path.exists(CACHE_FILE):
        return None
    try:
        with open(CACHE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def _write_cache(payload: Dict[str, Any]) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = CACHE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    os.replace(tmp, CACHE_FILE)


def get_daily_history(force_refresh: bool = False) -> Dict[str, Any]:
    """
    Real daily NIFTY 50 OHLCV joined with India VIX.
    Returns {"bars": [...], "source": str, "fetched_at": epoch, "is_stale": bool}.
    Bars are empty only if there is no network and no cache.
    """
    global _memory_cache
    now = time.time()
    cached = _memory_cache or _read_cache()
    if cached and not force_refresh and now - cached.get("fetched_at", 0) < CACHE_MAX_AGE_SECONDS and not daily_history_issue(cached, now_ist()):
        _memory_cache = cached
        return cached

    try:
        bars = _merge(_fetch_yahoo_daily(NIFTY_SYMBOL), _fetch_yahoo_daily(VIX_SYMBOL))
        if len(bars) < 300:
            raise ValueError(f"only {len(bars)} bars returned")
        payload = {"bars": bars, "source": "Yahoo Finance (^NSEI, ^INDIAVIX daily)", "fetched_at": now, "is_stale": False}
        _write_cache(payload)
        _memory_cache = payload
        return payload
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        if cached:
            stale = dict(cached, is_stale=True, error=str(exc))
            _memory_cache = stale
            return stale
        return {"bars": [], "source": "unavailable", "fetched_at": now, "is_stale": True, "error": str(exc)}


def cached_latest() -> Optional[Dict[str, Any]]:
    """Last cached close and VIX without touching the network (safe on request paths)."""
    global _memory_cache
    if _memory_cache is None:
        _memory_cache = _read_cache()
    bars = (_memory_cache or {}).get("bars", [])
    if not bars:
        return None
    last = bars[-1]
    return {"date": last["date"], "close": last["close"], "vix": last["vix"]}


_spx_memory: Optional[Dict[str, Any]] = None


def get_spx_history(force_refresh: bool = False) -> Dict[str, Any]:
    """Daily S&P 500 closes. The bar date is the US session date, known before the next NIFTY open."""
    global _spx_memory
    now = time.time()
    cached = _spx_memory
    if cached is None and os.path.exists(SPX_CACHE_FILE):
        try:
            with open(SPX_CACHE_FILE, "r", encoding="utf-8") as f:
                cached = json.load(f)
        except (OSError, ValueError):
            cached = None
    if cached and not force_refresh and now - cached.get("fetched_at", 0) < CACHE_MAX_AGE_SECONDS:
        _spx_memory = cached
        return cached
    try:
        raw = _fetch_yahoo_daily(SPX_SYMBOL)
        bars = [{"date": day, "close": round(raw[day]["close"], 2), "is_complete": raw[day]["is_complete"]} for day in sorted(raw)]
        if len(bars) < 100:
            raise ValueError(f"only {len(bars)} S&P bars returned")
        payload = {"bars": bars, "source": "Yahoo Finance (^GSPC daily)", "fetched_at": now, "is_stale": False}
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = SPX_CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f)
        os.replace(tmp, SPX_CACHE_FILE)
        _spx_memory = payload
        return payload
    except (requests.RequestException, KeyError, IndexError, ValueError) as exc:
        if cached:
            stale = dict(cached, is_stale=True, error=str(exc))
            _spx_memory = stale
            return stale
        return {"bars": [], "source": "unavailable", "fetched_at": now, "is_stale": True, "error": str(exc)}


def latest_spot_and_vix() -> Optional[Dict[str, Any]]:
    """Last real close and India VIX, or None if no data is available."""
    bars = get_daily_history().get("bars", [])
    if not bars:
        return None
    last = bars[-1]
    return {"date": last["date"], "close": last["close"], "vix": last["vix"]}
