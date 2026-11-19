"""Civil-time windows to UTC, and how two windows sit relative to each other.

Windows in RDSL are half-open civil intervals ``[t0, t1)`` plus an IANA zone.
This module is the whole clock model: it does not guess a zone, and it refuses
DST gaps and repeated hours instead of picking a fold.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from xvenue.errors import TemporalError

_EPOCH = datetime(1970, 1, 1, tzinfo=timezone.utc)


def split_timestamp(text: str) -> tuple[datetime, str | None]:
    """Split ``YYYY-MM-DDTHH:MM[:SS][Z|±HH:MM]`` into a naive datetime and its suffix."""
    if len(text) < 16:
        raise TemporalError(f"invalid timestamp {text!r}", code="timestamp")
    offset: str | None = None
    body = text
    if text.endswith("Z"):
        offset = "Z"
        body = text[:-1]
    elif len(text) >= 22 and text[-6] in "+-" and text[-3] == ":":
        offset = text[-6:]
        body = text[:-6]
    if len(body) == 16:
        body += ":00"
    try:
        naive = datetime.strptime(body, "%Y-%m-%dT%H:%M:%S")
    except ValueError as exc:
        raise TemporalError(f"invalid timestamp {text!r}", code="timestamp") from exc
    return naive, offset


def civil_to_utc(naive: datetime, tz_name: str) -> int:
    """Convert a naive civil time in ``tz_name`` to unix seconds.

    Ambiguous times (the clock repeats) and nonexistent times (the clock skips)
    raise :class:`TemporalError`.
    """
    tz = _zone(tz_name)
    fold0 = naive.replace(tzinfo=tz, fold=0)
    fold1 = naive.replace(tzinfo=tz, fold=1)
    back = fold0.astimezone(timezone.utc).astimezone(tz).replace(tzinfo=None)
    stamp = naive.strftime("%Y-%m-%dT%H:%M")
    if back != naive:
        raise TemporalError(
            f"civil time {stamp} does not exist in {tz_name} (clock gap)",
            code="nonexistent",
        )
    if fold0.utcoffset() != fold1.utcoffset():
        raise TemporalError(
            f"ambiguous civil time {stamp} in {tz_name}; the clock repeats. Write the window in UTC",
            code="ambiguous",
        )
    return _unix(fold0)


def absolute_to_utc(naive: datetime, offset: str) -> int:
    """Convert a timestamp that already carries ``Z`` or ``±HH:MM``."""
    if offset == "Z":
        aware = naive.replace(tzinfo=timezone.utc)
    else:
        if len(offset) != 6 or offset[0] not in "+-" or offset[3] != ":":
            raise TemporalError(f"invalid UTC offset {offset!r}", code="offset")
        sign = 1 if offset[0] == "+" else -1
        hours = int(offset[1:3])
        minutes = int(offset[4:6])
        if hours > 14 or minutes > 59:
            raise TemporalError(f"invalid UTC offset {offset!r}", code="offset")
        aware = naive.replace(tzinfo=timezone(sign * timedelta(hours=hours, minutes=minutes)))
    return _unix(aware)


def classify_windows(a0: int, a1: int, b0: int, b1: int) -> str:
    """How A's ``[a0, a1)`` sits against B's ``[b0, b1)``.

    Returns ``equal``, ``disjoint``, ``a_contains_b``, ``b_contains_a``, or
    ``partial_overlap``. Endpoints that merely touch are disjoint because the
    intervals are half-open.
    """
    if a1 <= a0 or b1 <= b0:
        raise TemporalError("windows must be nonempty half-open intervals", code="order")
    if (a0, a1) == (b0, b1):
        return "equal"
    if a1 <= b0 or b1 <= a0:
        return "disjoint"
    if a0 <= b0 and b1 <= a1:
        return "a_contains_b"
    if b0 <= a0 and a1 <= b1:
        return "b_contains_a"
    return "partial_overlap"


def format_utc(unix: int) -> str:
    return datetime.fromtimestamp(unix, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _zone(tz_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(tz_name)
    except ZoneInfoNotFoundError as exc:
        raise TemporalError(f"unknown timezone {tz_name!r}", code="timezone") from exc


def _unix(aware: datetime) -> int:
    seconds = (aware.astimezone(timezone.utc) - _EPOCH).total_seconds()
    return int(seconds)
