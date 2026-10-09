"""Auto mode: which panel set the clock calls for, and when a running game may take over."""
from __future__ import annotations

import time

# Monday is 0. Weekdays work 09:00-18:00 with a daylight morning; weekends are daylight until 19:00.
WEEKDAY = ((7, "daylight"), (9, "work"), (18, "night"))
WEEKEND = ((7, "daylight"), (19, "night"))


def _local(ts):
    local = time.localtime(ts)
    return local.tm_wday >= 5, local.tm_hour


def scheduled_mode(ts: float) -> str:
    weekend, hour = _local(ts)
    mode = "night"  # before the first slot of the day it is still night
    for start, name in WEEKEND if weekend else WEEKDAY:
        if hour >= start:
            mode = name
    return mode


def game_allowed(ts: float) -> bool:
    """Games may take over at weekends and on weekdays outside 07:00-18:00."""
    weekend, hour = _local(ts)
    return weekend or not 7 <= hour < 18


def next_change(ts: float) -> float:
    """The next time scheduled_mode or game_allowed changes, scanned at hour boundaries."""
    current = (scheduled_mode(ts), game_allowed(ts))
    local = time.localtime(ts)
    hour_start = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, local.tm_hour, 0, 0, 0, 0, -1))
    for step in range(1, 7 * 24 + 1):
        candidate = hour_start + step * 3600
        if (scheduled_mode(candidate), game_allowed(candidate)) != current:
            return candidate
    return ts + 7 * 86400
