import subprocess
import sys
from pathlib import Path

from xvenue.cli import main
from xvenue.parser import parse_rdsl
from xvenue.relate import format_report, relate
from xvenue.spec import Rel

ROOT = Path(__file__).resolve().parents[2]


def _pair(window_a: str, window_b: str, pred_a: str = "x.value < 3.0", pred_b: str = "x.value < 3.0") -> str:
    def block(cid: str, window: str, pred: str) -> str:
        return "\n".join([
            f"contract {cid} on example {{",
            "  observe sample.series as x",
            f"  window {window}",
            f"  predicate {pred}",
            "  revision final",
            "  void_if none",
            "  dispute docs.example",
            "}",
        ])

    return block("a", window_a, pred_a) + "\n" + block("b", window_b, pred_b) + "\n"


def _relate(text: str):
    specs = {spec.contract_id: spec for spec in parse_rdsl(text)}
    return relate(specs["a"], specs["b"])


def test_same_window_stronger_threshold_implies():
    report = _relate(_pair(
        "[2026-06-01T00:00, 2026-06-02T00:00) tz UTC",
        "[2026-06-01T00:00, 2026-06-02T00:00) tz UTC",
        "x.value < 2.5",
        "x.value < 3.0",
    ))
    assert report.relation == Rel.IMPLIES
    assert report.divergent_fields == ("predicate",)
    assert report.window_relation == "equal"


def test_containment_supports_implication():
    report = _relate(_pair(
        "[2026-06-01T00:00, 2026-06-02T00:00) tz UTC",
        "[2026-06-01T00:00, 2026-06-04T00:00) tz UTC",
        "x.value < 2.5",
        "x.value < 3.0",
    ))
    assert report.relation == Rel.IMPLIES
    assert report.window_relation == "b_contains_a"
    assert "window" in report.divergent_fields
    assert report.relation != Rel.UNKNOWN


def test_partial_overlap_does_not_inherit_implication():
    report = _relate(_pair(
        "[2026-06-01T00:00, 2026-06-02T00:00) tz UTC",
        "[2026-06-01T12:00, 2026-06-02T12:00) tz UTC",
        "x.value < 2.5",
        "x.value < 3.0",
    ))
    assert report.relation == Rel.NONE
    assert report.window_relation == "partial_overlap"


def test_same_window_contradiction_is_disjoint_and_other_days_are_not():
    same = _relate(_pair(
        "[2026-06-01T00:00, 2026-06-02T00:00) tz UTC",
        "[2026-06-01T00:00, 2026-06-02T00:00) tz UTC",
        "x.value < 0",
        "x.value > 1",
    ))
    apart = _relate(_pair(
        "[2026-06-01T00:00, 2026-06-02T00:00) tz UTC",
        "[2026-06-10T00:00, 2026-06-11T00:00) tz UTC",
        "x.value < 0",
        "x.value > 1",
    ))
    assert same.relation == Rel.DISJOINT
    assert apart.relation == Rel.NONE
    assert apart.window_relation == "disjoint"


def test_matching_utc_instants_with_different_tz_labels_are_equiv():
    report = _relate(_pair(
        "[2026-06-01T00:00, 2026-06-02T00:00) tz UTC",
        "[2026-05-31T20:00, 2026-06-01T20:00) tz America/New_York",
    ))
    assert report.relation == Rel.EQUIV
    assert report.divergent_fields == ("tz",)
    assert report.window_relation == "equal"


def test_spec_is_equiv_to_itself():
    text = _pair(
        "[2026-06-01T00:00, 2026-06-02T00:00) tz UTC",
        "[2026-06-01T00:00, 2026-06-02T00:00) tz UTC",
    )
    spec = {item.contract_id: item for item in parse_rdsl(text)}["a"]
    assert relate(spec, spec).relation == Rel.EQUIV


def test_cli_examples_and_unknown_id(capsys):
    cpi = ROOT / "compiler" / "examples" / "cpi_pair.rdsl"
    contained = ROOT / "compiler" / "examples" / "containment.rdsl"
    assert main(["relate", str(cpi), "KXCPI-26DEC-T3.0", "pm-cpi-below-3-dec"]) == 0
    cpi_out = capsys.readouterr().out
    assert cpi_out.startswith("relation: none\n")
    assert "divergent_fields: dispute_path, revision_policy, tz, void_if, window\n" in cpi_out
    assert "window_relation: b_contains_a\n" in cpi_out
    assert main(["relate", str(contained), "tight", "wide"]) == 0
    contained_out = capsys.readouterr().out
    assert contained_out.startswith("relation: implies\n")
    assert main(["relate", str(cpi), "missing", "pm-cpi-below-3-dec"]) == 1
    assert "unknown contract id: missing" in capsys.readouterr().err


def test_module_entrypoint_matches_library_report():
    script = ROOT / "compiler" / "examples" / "containment.rdsl"
    env = dict(**{k: v for k, v in __import__("os").environ.items()})
    env["PYTHONPATH"] = str(ROOT / "compiler" / "src")
    proc = subprocess.run(
        [sys.executable, "-m", "xvenue", "relate", str(script), "tight", "wide"],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    specs = {spec.contract_id: spec for spec in parse_rdsl(script.read_text())}
    assert proc.returncode == 0
    assert proc.stdout == format_report(relate(specs["tight"], specs["wide"]))


def test_original_prototype_demo_still_prints():
    proc = subprocess.run(
        [sys.executable, "compiler/src/lower_smt.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0
    assert proc.stdout == "kalshi vs polymarket: none\nk(<2.5) vs k(<3.0): implies\n"
