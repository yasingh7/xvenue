"""Pairwise YES-outcome relation, with a temporal pass in front of Z3.

Model, and what it deliberately does not assume:

* A contract is YES when some instant in its window satisfies the predicate
  and none of its void conditions hold (``compiler/RDSL.md``).
* The overlap of the two windows shares one real per ``(source, metric,
  revision)``. Time that belongs to only one window is a different real.
  Values on disjoint stretches are independent: there is no continuity
  assumption, so a shifted window does not inherit implication from the
  predicate alone.
* A window that contains the other can still support implication, because a
  witness inside the smaller window is also inside the larger one.
* Different sources, metrics, or revision policies are independent. Two
  ``latest_before`` cutoffs are different policies.
* Void text is a boolean, shared when the canonical text matches. The dispute
  path and the timezone label are not in the formula; they are reported as
  divergent fields. Differing windows are not UNKNOWN.

The solver timeout matches the architecture note: 200 ms, then UNKNOWN.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from z3 import And, Bool, BoolVal, Not, Or, Real, Solver, sat, unsat

from xvenue.spec import Rel, ResolutionSpec
from xvenue.temporal import classify_windows, format_utc

_DEFAULT_TIMEOUT_MS = 200
_SAFE = re.compile(r"[^A-Za-z0-9_]+")


@dataclass(frozen=True)
class Divergence:
    field: str
    a: str
    b: str


@dataclass(frozen=True)
class PairReport:
    a: str
    b: str
    relation: Rel
    divergent_fields: tuple[str, ...]
    details: tuple[Divergence, ...]
    window_relation: str


def relate(a: ResolutionSpec, b: ResolutionSpec, timeout_ms: int = _DEFAULT_TIMEOUT_MS) -> PairReport:
    details = tuple(_divergences(a, b))
    window_relation = classify_windows(a.t0, a.t1, b.t0, b.t1)
    left, right = _lower_pair(a, b)
    a_implies_b = _unsat(And(left, Not(right)), timeout_ms)
    b_implies_a = _unsat(And(right, Not(left)), timeout_ms)
    both_unsat = _unsat(And(left, right), timeout_ms)
    if None in (a_implies_b, b_implies_a, both_unsat):
        relation = Rel.UNKNOWN
    elif a_implies_b and b_implies_a:
        relation = Rel.EQUIV
    elif a_implies_b:
        relation = Rel.IMPLIES
    elif b_implies_a:
        relation = Rel.IMPLIED_BY
    elif both_unsat:
        relation = Rel.DISJOINT
    else:
        relation = Rel.NONE
    return PairReport(
        a=a.contract_id,
        b=b.contract_id,
        relation=relation,
        divergent_fields=tuple(item.field for item in details),
        details=details,
        window_relation=window_relation,
    )


def format_report(report: PairReport) -> str:
    fields = ", ".join(report.divergent_fields) if report.divergent_fields else "(none)"
    lines = [
        f"relation: {report.relation.value}",
        f"divergent_fields: {fields}",
        f"window_relation: {report.window_relation}",
    ]
    for item in report.details:
        lines.append(f"{item.field}: {item.a} | {item.b}")
    return "\n".join(lines) + "\n"


def _divergences(a: ResolutionSpec, b: ResolutionSpec) -> list[Divergence]:
    found: list[Divergence] = []
    if a.dispute != b.dispute:
        found.append(Divergence("dispute_path", a.dispute, b.dispute))
    if a.predicate_identity() != b.predicate_identity():
        found.append(Divergence("predicate", a.predicate_display(), b.predicate_display()))
    if a.revision_key() != b.revision_key():
        found.append(Divergence("revision_policy", _revision_text(a), _revision_text(b)))
    if a.source != b.source:
        found.append(Divergence("source", a.source, b.source))
    if a.tz != b.tz:
        found.append(Divergence("tz", a.tz, b.tz))
    if tuple(sorted(a.void_if)) != tuple(sorted(b.void_if)):
        found.append(Divergence("void_if", _void_text(a), _void_text(b)))
    if (a.t0, a.t1) != (b.t0, b.t1):
        found.append(Divergence("window", _window_text(a), _window_text(b)))
    found.sort(key=lambda item: item.field)
    return found


def _revision_text(spec: ResolutionSpec) -> str:
    if spec.revision == "latest_before" and spec.revision_at is not None:
        return f"latest_before({format_utc(spec.revision_at)})"
    return spec.revision


def _void_text(spec: ResolutionSpec) -> str:
    if not spec.void_if:
        return "none"
    return ", ".join(spec.void_if)


def _window_text(spec: ResolutionSpec) -> str:
    return f"[{format_utc(spec.t0)}, {format_utc(spec.t1)})"


def _lower_pair(a: ResolutionSpec, b: ResolutionSpec):
    cache: dict[str, object] = {}

    def symbol(key: str):
        if key not in cache:
            digest = hashlib.sha256(key.encode()).hexdigest()[:10]
            safe = _SAFE.sub("_", key).strip("_")[:40] or "v"
            if safe[0].isdigit():
                safe = "v_" + safe
            cache[key] = f"{safe}_{digest}"
        return cache[key]

    def obs(spec: ResolutionSpec, region: str):
        key = f"obs:{spec.source}:{spec.metric()}:{spec.revision_key()}:{region}"
        return Real(str(symbol(key)))

    def pred(spec: ResolutionSpec, region: str):
        value = obs(spec, region)
        threshold = spec.threshold
        if isinstance(threshold, float) and threshold.is_integer():
            threshold = int(threshold)
        return {
            "<": value < threshold,
            "<=": value <= threshold,
            ">": value > threshold,
            ">=": value >= threshold,
            "==": value == threshold,
        }[spec.op]

    def voided(spec: ResolutionSpec):
        if not spec.void_if:
            return BoolVal(False)
        flags = []
        for text in spec.void_if:
            flags.append(Bool(str(symbol("void:" + text))))
        if len(flags) == 1:
            return flags[0]
        return Or(*flags)

    def formula(spec: ResolutionSpec, regions: list[str]):
        if not regions:
            body = BoolVal(False)
        elif len(regions) == 1:
            body = pred(spec, regions[0])
        else:
            body = Or(*[pred(spec, region) for region in regions])
        return And(body, Not(voided(spec)))

    overlap = max(a.t0, b.t0) < min(a.t1, b.t1)
    only_a = a.t0 < b.t0 or a.t1 > b.t1
    only_b = b.t0 < a.t0 or b.t1 > a.t1
    a_regions = [name for name, keep in (("overlap", overlap), ("only_a", only_a)) if keep]
    b_regions = [name for name, keep in (("overlap", overlap), ("only_b", only_b)) if keep]
    return formula(a, a_regions), formula(b, b_regions)


def _unsat(formula, timeout_ms: int) -> bool | None:
    solver = Solver()
    solver.set("timeout", timeout_ms)
    solver.add(formula)
    result = solver.check()
    if result == unsat:
        return True
    if result == sat:
        return False
    return None
