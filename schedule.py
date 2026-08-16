"""EventBridge rate()/cron() matcher for the local emulator.

AWS rate() is relative to rule creation. Local matching uses wall-clock UTC,
which is more predictable while developing (rate(5 minutes) fires at :00, :05, …).
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

RATE_RE = re.compile(
    r"^rate\((\d+)\s+(minute|minutes|hour|hours|day|days)\)$",
    re.IGNORECASE,
)
CRON_RE = re.compile(r"^cron\((.+)\)$", re.IGNORECASE)

DOW_NAMES = {
    "SUN": 0,
    "MON": 1,
    "TUE": 2,
    "WED": 3,
    "THU": 4,
    "FRI": 5,
    "SAT": 6,
}


def expression_is_due(expression: str, now: datetime | None = None) -> bool:
    """Return True if a scheduled rule should fire at this UTC minute."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)
    expr = str(expression or "").strip()
    rate = RATE_RE.match(expr)
    if rate:
        return _rate_is_due(int(rate.group(1)), rate.group(2).lower().rstrip("s"), now)
    cron = CRON_RE.match(expr)
    if cron:
        return _cron_is_due(cron.group(1), now)
    return False


def _rate_is_due(n: int, unit: str, now: datetime) -> bool:
    if n < 1:
        return False
    if unit == "minute":
        return now.minute % n == 0
    if unit == "hour":
        return now.minute == 0 and now.hour % n == 0
    if unit == "day":
        if now.minute != 0 or now.hour != 0:
            return False
        return (now.timetuple().tm_yday - 1) % n == 0
    return False


def _cron_is_due(body: str, now: datetime) -> bool:
    parts = body.split()
    if len(parts) != 6:
        return False
    minute, hour, day_of_month, month, day_of_week, year = parts
    return (
        _field_matches(minute, now.minute)
        and _field_matches(hour, now.hour)
        and _field_matches(month, now.month)
        and _field_matches(year, now.year)
        and _cron_day_matches(day_of_month, day_of_week, now)
    )


def _cron_day_matches(dom: str, dow: str, now: datetime) -> bool:
    """EventBridge: one of DOM / DOW is usually '?'. '?' means unused (always true)."""
    dow_ok = _field_matches(dow, int(now.strftime("%w")), names=DOW_NAMES, kind="dow")
    dom_ok = _field_matches(dom, now.day)
    if dom == "?" and dow == "?":
        return True
    if dom == "?":
        return dow_ok
    if dow == "?":
        return dom_ok
    return dom_ok or dow_ok


def _field_matches(field: str, value: int, names: dict[str, int] | None = None, kind: str = "") -> bool:
    token = str(field or "").strip()
    if token in {"*", "?"}:
        return True
    for part in token.split(","):
        part = part.strip()
        if not part:
            continue
        if _part_matches(part, value, names=names, kind=kind):
            return True
    return False


def _part_matches(part: str, value: int, names: dict[str, int] | None = None, kind: str = "") -> bool:
    part = part.upper()
    if part.startswith("*/"):
        step = _atom(part[2:], names=names, kind=kind)
        return step > 0 and value % step == 0
    if "/" in part:
        start_s, step_s = part.split("/", 1)
        start = 0 if start_s in {"*", "?"} else _atom(start_s, names=names, kind=kind)
        step = _atom(step_s, names=names, kind=kind)
        return step > 0 and value >= start and (value - start) % step == 0
    if "-" in part:
        left, right = part.split("-", 1)
        lo = _atom(left, names=names, kind=kind)
        hi = _atom(right, names=names, kind=kind)
        if lo <= hi:
            return lo <= value <= hi
        return value >= lo or value <= hi
    return _atom(part, names=names, kind=kind) == value


def _atom(token: str, names: dict[str, int] | None = None, kind: str = "") -> int:
    token = str(token or "").strip().upper()
    if names and token in names:
        return names[token]
    n = int(token)
    if kind == "dow":
        if n == 0:
            return 0
        if 1 <= n <= 7:
            return n % 7
    return n
