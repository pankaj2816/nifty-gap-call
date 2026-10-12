"""Frozen 2-minute paper test. The rule is not refit on the results.

At the close of each 1-minute NIFTY candle, if that candle moved at least 0.03%,
the next 2 minutes are called in the same direction. Otherwise there is no call.
The outcome is filled only after those 2 minutes have closed. A miss does not
change the threshold.
"""
from datetime import datetime, time, timedelta, timezone
import html
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from app.core.time_utils import IST, now_ist

LIVE_START = datetime(2026, 10, 12, 9, 15, tzinfo=IST)
MOVE = 0.0003
HORIZON = 2
SESSION_OPEN = time(9, 15)
SESSION_CLOSE = time(15, 30)
LOG_PATH = Path(__file__).resolve().parents[3] / "live_log" / "short_term_log.json"
PAGE_PATH = Path(__file__).resolve().parents[3] / "docs" / "short-term.html"


def fetch_minute_bars() -> List[Dict[str, Any]]:
    """Recent 1-minute NIFTY bars. The bar time is the start of the minute."""
    last_error = None
    result = None
    for host in ("query1.finance.yahoo.com", "query2.finance.yahoo.com"):
        try:
            resp = requests.get(
                f"https://{host}/v8/finance/chart/%5ENSEI",
                params={"range": "1d", "interval": "1m"},
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
    bars = []
    for i, ts in enumerate(result["timestamp"]):
        close = quote["close"][i]
        if close is None:
            continue
        start = datetime.fromtimestamp(ts, tz=timezone.utc).astimezone(IST).replace(second=0, microsecond=0)
        bars.append({
            "start": start.isoformat(),
            "open": float(quote["open"][i] or close),
            "high": float(quote["high"][i] or close),
            "low": float(quote["low"][i] or close),
            "close": float(close),
        })
    bars.sort(key=lambda b: b["start"])
    return bars


def _in_session(start: datetime) -> bool:
    clock = start.timetz().replace(tzinfo=None)
    return start.weekday() < 5 and SESSION_OPEN <= clock < SESSION_CLOSE and start >= LIVE_START


def _call(bar: Dict[str, Any]) -> str:
    move = bar["close"] / bar["open"] - 1.0
    if move >= MOVE:
        return "UP"
    if move <= -MOVE:
        return "DOWN"
    return "NO CALL"


def _exit(call: str, entry: float, future: List[Dict[str, Any]]) -> str:
    """Which paper level is touched first. One bar that touches both is ambiguous."""
    target = entry * (1.0 + MOVE if call == "UP" else 1.0 - MOVE)
    stop = entry * (1.0 - MOVE if call == "UP" else 1.0 + MOVE)
    for bar in future:
        if call == "UP":
            hit_target, hit_stop = bar["high"] >= target, bar["low"] <= stop
        else:
            hit_target, hit_stop = bar["low"] <= target, bar["high"] >= stop
        if hit_target and hit_stop:
            return "Ambiguous"
        if hit_target:
            return "Target first"
        if hit_stop:
            return "Stop first"
    return "Neither"


def score_bars(bars: List[Dict[str, Any]], now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """Score every completed minute. Future bars are used only as the result."""
    clock = now or now_ist()
    closed = []
    for bar in bars:
        start = datetime.fromisoformat(bar["start"])
        if start.tzinfo is None:
            start = start.replace(tzinfo=IST)
        if _in_session(start) and start + timedelta(minutes=1) <= clock:
            closed.append(dict(bar, start_dt=start))
    rows = []
    for i, bar in enumerate(closed):
        future = closed[i + 1:i + 1 + HORIZON]
        call = _call(bar)
        ready = len(future) == HORIZON
        direction = ""
        exit_result = "Waiting"
        if ready and call != "NO CALL":
            later = future[-1]["close"]
            direction = "Same way" if (later > bar["close"]) == (call == "UP") and later != bar["close"] else (
                "Flat" if later == bar["close"] else "Opposite"
            )
            exit_result = _exit(call, bar["close"], future)
        elif ready:
            direction = "No call — not scored"
            exit_result = "No call — not scored"
        rows.append({
            "minute": bar["start_dt"].strftime("%Y-%m-%d %H:%M"),
            "candle_move_pct": round((bar["close"] / bar["open"] - 1.0) * 100.0, 3),
            "call": call,
            "entry": round(bar["close"], 2),
            "result_close": round(future[-1]["close"], 2) if ready else "",
            "direction_outcome": direction or "Waiting",
            "exit_outcome": exit_result,
        })
    return rows


def _summary(rows: List[Dict[str, Any]]) -> Dict[str, int]:
    calls = [r for r in rows if r["call"] in ("UP", "DOWN")]
    scored = [r for r in calls if r["direction_outcome"] in ("Same way", "Opposite", "Flat")]
    exits = [r for r in calls if r["exit_outcome"] in ("Target first", "Stop first", "Ambiguous", "Neither")]
    return {
        "minutes": len(rows),
        "calls": len(calls),
        "no_calls": sum(r["call"] == "NO CALL" for r in rows),
        "direction_scored": len(scored),
        "direction_same_way": sum(r["direction_outcome"] == "Same way" for r in scored),
        "target_first": sum(r["exit_outcome"] == "Target first" for r in exits),
        "stop_first": sum(r["exit_outcome"] == "Stop first" for r in exits),
        "ambiguous": sum(r["exit_outcome"] == "Ambiguous" for r in exits),
        "waiting": sum(r["direction_outcome"] == "Waiting" for r in rows),
    }


def _write_page(payload: Dict[str, Any]) -> None:
    PAGE_PATH.parent.mkdir(parents=True, exist_ok=True)
    summary = payload["summary"]
    scored = summary["direction_scored"]
    rate = f"{summary['direction_same_way']} of {scored}" if scored else "None scored yet"
    body = []
    for row in payload["rows"][-40:]:
        body.append(
            "<tr>"
            f"<td>{html.escape(row['minute'])}</td>"
            f"<td>{html.escape(str(row['candle_move_pct']))}</td>"
            f"<td>{html.escape(row['call'])}</td>"
            f"<td>{html.escape(str(row['direction_outcome']))}</td>"
            f"<td>{html.escape(str(row['exit_outcome']))}</td>"
            "</tr>"
        )
    page = f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>Two-minute paper test</title>
<style>
body {{ margin:0; background:#0c1220; color:#e5e7eb; font-family:Georgia,serif; }}
main {{ max-width:980px; margin:0 auto; padding:32px 20px 64px; }}
table {{ width:100%; border-collapse:collapse; font-family:Arial,sans-serif; font-size:14px; }}
th,td {{ border-top:1px solid #243044; text-align:left; padding:8px; }}
.muted {{ color:#94a3b8; font-size:13px; }}
</style></head><body><main>
<p class="muted">Frozen rule from 12 Oct 2026 · updated {html.escape(payload['updated_at'])}</p>
<h1>Two-minute paper test</h1>
<p>A 1-minute candle that has already closed by at least 0.03% calls the next 2 minutes the same way. The rule is not changed when the result is wrong. This is not a bid, and it is not the daily S&amp;P call.</p>
<p>Direction after 2 minutes: {html.escape(rate)}. Target reached first: {summary['target_first']}. Stop reached first: {summary['stop_first']}. Ambiguous: {summary['ambiguous']}.</p>
<p class="muted"><a href="index.html">Daily opening-gap call</a></p>
<table><thead><tr><th>Minute</th><th>Candle %</th><th>Call</th><th>2-minute direction</th><th>Paper exit</th></tr></thead>
<tbody>{''.join(body) or '<tr><td colspan="5">No minutes yet.</td></tr>'}</tbody></table>
<p class="muted">The last 40 minutes are shown. The saved file keeps the whole session. A high count on one morning is not a future accuracy.</p>
</main></body></html>"""
    PAGE_PATH.write_text(page, encoding="utf-8")


def update_short_term(now: Optional[datetime] = None, bars: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    clock = now or now_ist()
    source = bars if bars is not None else fetch_minute_bars()
    rows = score_bars(source, clock)
    payload = {
        "updated_at": clock.strftime("%Y-%m-%d %H:%M IST"),
        "rule": "Frozen. Last 1-minute move of at least 0.03% continues for 2 minutes. Not refit.",
        "rows": rows,
        "summary": _summary(rows),
    }
    LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LOG_PATH.write_text(json.dumps(payload), encoding="utf-8")
    _write_page(payload)
    return payload
