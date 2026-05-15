"""
Schedule expression parser for autonomous_tasks.

Supported formats
-----------------
Relative:   +Nm / +Nh / +Nd / +Nw   e.g. "+30m", "+6h", "+1d", "+2w"
Named:      @hourly  @daily  @weekly  @monthly
5-field cron (minute hour dom month weekday):
            "0 9 * * 1"  → 9 am every Monday (weekday 0=Sunday, 6=Saturday)

All public functions accept schedule strings and return the next Unix
timestamp (float) at or after `since` (defaults to now).

Never raises on user-supplied input — callers should use is_valid_schedule()
before writing to the DB.
"""

import math
import re
import time
from typing import Optional

# ── Relative ──────────────────────────────────────────────────────────────────

_RELATIVE_PAT = re.compile(r'^\+(\d+)([mhdw])$', re.IGNORECASE)
_UNIT_SECONDS = {'m': 60, 'h': 3600, 'd': 86400, 'w': 86400 * 7}

# ── Named shortcuts ───────────────────────────────────────────────────────────

_NAMED_SECONDS = {
    '@hourly':  3600,
    '@daily':   86400,
    '@weekly':  86400 * 7,
    '@monthly': 86400 * 30,
}

# ── 5-field cron helpers ──────────────────────────────────────────────────────

def _parse_cron_field(val: str, lo: int, hi: int) -> Optional[int]:
    """Return None for wildcard, int for fixed value."""
    if val == '*':
        return None
    try:
        v = int(val)
    except ValueError:
        raise ValueError(f"Cron field {val!r} must be '*' or an integer")
    if not (lo <= v <= hi):
        raise ValueError(f"Cron field {val!r} out of range [{lo}, {hi}]")
    return v


def _next_cron(expr: str, since: float) -> float:
    """Compute next firing time for a 5-field cron expression.

    Advances by the largest meaningful unit at each step so worst-case
    iteration count is bounded (days not minutes).
    """
    parts = expr.split()
    if len(parts) != 5:
        raise ValueError(f"5-field cron requires exactly 5 fields, got {len(parts)}: {expr!r}")

    m_f, h_f, dom_f, mon_f, dow_f = parts
    minute  = _parse_cron_field(m_f,   0, 59)
    hour    = _parse_cron_field(h_f,   0, 23)
    dom     = _parse_cron_field(dom_f, 1, 31)
    month   = _parse_cron_field(mon_f, 1, 12)
    weekday = _parse_cron_field(dow_f, 0,  6)  # 0 = Sunday

    # Start from the next minute boundary after since
    t = (math.floor(since / 60) + 1) * 60
    deadline = t + 366 * 86400  # give up after 1 year

    while t < deadline:
        lt = time.localtime(t)
        cur_min    = lt.tm_min
        cur_hour   = lt.tm_hour
        cur_dom    = lt.tm_mday
        cur_month  = lt.tm_mon
        cur_year   = lt.tm_year
        # Python tm_wday: 0=Monday; convert to 0=Sunday convention
        cur_dow    = (lt.tm_wday + 1) % 7

        # Check month — jump to first of next matching month
        if month is not None and cur_month != month:
            target_month = month
            target_year  = cur_year + (1 if target_month <= cur_month else 0)
            t = time.mktime((target_year, target_month, 1, 0, 0, 0, 0, 0, -1))
            continue

        # Check day-of-month
        if dom is not None and cur_dom != dom:
            try:
                # Jump to target dom in this month (may overflow → mktime normalises)
                t = time.mktime((cur_year, cur_month, dom, 0, 0, 0, 0, 0, -1))
                if t <= since or time.localtime(t).tm_mday != dom:
                    # dom doesn't exist this month — go to next month
                    t = time.mktime((cur_year, cur_month + 1, 1, 0, 0, 0, 0, 0, -1))
            except (OverflowError, OSError):
                t += 86400
            continue

        # Check weekday
        if weekday is not None and cur_dow != weekday:
            # Jump forward until weekday matches (at most 6 days)
            days_ahead = (weekday - cur_dow) % 7 or 7
            t = time.mktime((cur_year, cur_month, cur_dom + days_ahead, 0, 0, 0, 0, 0, -1))
            continue

        # Check hour
        if hour is not None and cur_hour != hour:
            if hour > cur_hour:
                t = time.mktime((cur_year, cur_month, cur_dom, hour, 0, 0, 0, 0, -1))
            else:
                t = time.mktime((cur_year, cur_month, cur_dom + 1, 0, 0, 0, 0, 0, -1))
            continue

        # Check minute
        if minute is not None and cur_min != minute:
            if minute > cur_min:
                t = time.mktime((cur_year, cur_month, cur_dom, cur_hour, minute, 0, 0, 0, -1))
            else:
                t = time.mktime((cur_year, cur_month, cur_dom, cur_hour + 1, 0, 0, 0, 0, -1))
            continue

        return float(t)

    raise ValueError(f"No firing time found within 1 year for cron {expr!r}")


# ── Public API ────────────────────────────────────────────────────────────────

def parse_next_run(schedule: str, since: Optional[float] = None) -> float:
    """Return the next Unix timestamp when *schedule* fires after *since*.

    Parameters
    ----------
    schedule:
        A schedule expression (see module docstring).
    since:
        Lower bound for the result (default: now).

    Raises
    ------
    ValueError
        If the expression is not recognised or has no firing time within 1 year.
    """
    if since is None:
        since = time.time()

    s = schedule.strip()

    # Named shortcuts
    if s in _NAMED_SECONDS:
        return since + _NAMED_SECONDS[s]

    # Relative: +Nm/h/d/w
    m = _RELATIVE_PAT.match(s)
    if m:
        n    = int(m.group(1))
        unit = m.group(2).lower()
        return since + n * _UNIT_SECONDS[unit]

    # 5-field cron
    if ' ' in s:
        return _next_cron(s, since)

    raise ValueError(
        f"Unrecognised schedule expression: {s!r}. "
        "Use +Nm/h/d/w, @hourly, @daily, @weekly, @monthly, or 5-field cron."
    )


def is_valid_schedule(schedule: str) -> bool:
    """Return True if *schedule* is a recognised, parseable expression."""
    try:
        parse_next_run(schedule.strip())
        return True
    except (ValueError, TypeError, OSError):
        return False


def describe_schedule(schedule: str) -> str:
    """Return a human-readable description of *schedule* (best-effort)."""
    s = schedule.strip()
    descriptions = {
        '@hourly':  'every hour',
        '@daily':   'every day',
        '@weekly':  'every week',
        '@monthly': 'every 30 days',
    }
    if s in descriptions:
        return descriptions[s]

    m = _RELATIVE_PAT.match(s)
    if m:
        n, unit = m.group(1), m.group(2).lower()
        names = {'m': 'minute', 'h': 'hour', 'd': 'day', 'w': 'week'}
        label = names[unit]
        return f"every {n} {label}{'s' if int(n) != 1 else ''}"

    if ' ' in s:
        return f"cron: {s}"

    return s
