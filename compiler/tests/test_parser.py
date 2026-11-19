from datetime import datetime, timezone
from pathlib import Path

import pytest

from xvenue.errors import RDSLError, TemporalError
from xvenue.parser import parse_path, parse_rdsl
from xvenue.temporal import civil_to_utc, classify_windows

ROOT = Path(__file__).resolve().parents[2]
CPI = ROOT / "compiler" / "examples" / "cpi_pair.rdsl"


def _utc(year, month, day, hour, minute=0) -> int:
    return int(datetime(year, month, day, hour, minute, tzinfo=timezone.utc).timestamp())


def _contract(**fields) -> str:
    body = {
        "observe": "observe sample.series as x",
        "window": "window [2026-06-01T00:00, 2026-06-02T00:00) tz UTC",
        "predicate": "predicate x.value < 1.5",
        "revision": "revision final",
        "void_if": "void_if none",
        "dispute": "dispute docs.example",
    }
    body.update(fields)
    lines = ["contract c on example {"]
    for key in ("observe", "window", "predicate", "revision", "void_if", "dispute"):
        if key in body and body[key] is not None:
            lines.append(f"  {body[key]}")
    lines.append("}")
    return "\n".join(lines) + "\n"


def test_cpi_pair_normalizes_new_york_to_utc():
    specs = {spec.contract_id: spec for spec in parse_path(CPI)}
    kalshi = specs["KXCPI-26DEC-T3.0"]
    poly = specs["pm-cpi-below-3-dec"]
    assert kalshi.t0 == _utc(2027, 1, 13, 13, 30)
    assert kalshi.t1 == _utc(2027, 1, 13, 13, 31)
    assert kalshi.tz == "America/New_York"
    assert kalshi.revision == "first_print"
    assert kalshi.void_if == ("bls.release_delayed > 14d",)
    assert kalshi.predicate_display() == "cpi.value < 3.0"
    assert poly.t0 == _utc(2027, 1, 1, 0)
    assert poly.t1 == _utc(2027, 1, 31, 23, 59)
    assert poly.revision == "latest_before"
    assert poly.revision_at == _utc(2027, 1, 31, 23, 59)
    assert poly.void_if == ()


def test_unknown_timezone_names_the_zone_and_line():
    text = _contract(window="window [2026-06-01T00:00, 2026-06-02T00:00) tz Not/AZone")
    with pytest.raises(RDSLError, match=r"unknown timezone 'Not/AZone'") as caught:
        parse_rdsl(text, path="bad.rdsl")
    assert "bad.rdsl:3:" in str(caught.value)


def test_dst_gap_and_ambiguous_hour_are_errors():
    with pytest.raises(TemporalError, match="does not exist"):
        civil_to_utc(datetime(2026, 3, 8, 2, 30), "America/New_York")
    with pytest.raises(TemporalError, match="ambiguous"):
        civil_to_utc(datetime(2026, 11, 1, 1, 30), "America/New_York")
    gap = _contract(window="window [2026-03-08T02:30, 2026-03-08T04:00) tz America/New_York")
    with pytest.raises(RDSLError, match="does not exist"):
        parse_rdsl(gap)


def test_empty_window_reversed_window_and_missing_field():
    with pytest.raises(RDSLError, match="window is empty"):
        parse_rdsl(_contract(window="window [2026-06-01T00:00, 2026-06-01T00:00) tz UTC"))
    with pytest.raises(RDSLError, match="ends before it starts"):
        parse_rdsl(_contract(window="window [2026-06-02T00:00, 2026-06-01T00:00) tz UTC"))
    with pytest.raises(RDSLError, match="missing dispute"):
        parse_rdsl(_contract(dispute=None))


def test_void_spelling_and_latest_before_offset():
    text = _contract(
        void_if="void_if sample.b > 2d, sample.a > 1.0d",
        revision="revision latest_before(2026-06-01T00:00-04:00)",
    )
    spec = parse_rdsl(text)[0]
    assert spec.void_if == ("sample.a > 1d", "sample.b > 2d")
    assert spec.revision_at == _utc(2026, 6, 1, 4)


def test_classify_half_open_windows():
    assert classify_windows(0, 10, 0, 10) == "equal"
    assert classify_windows(0, 5, 5, 10) == "disjoint"
    assert classify_windows(0, 10, 2, 4) == "a_contains_b"
    assert classify_windows(2, 4, 0, 10) == "b_contains_a"
    assert classify_windows(0, 10, 5, 15) == "partial_overlap"
