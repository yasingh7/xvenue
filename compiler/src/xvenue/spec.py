"""Resolution specs produced by the RDSL parser.

The shape follows ``proto/xvenue.proto`` and the v0 grammar in ``compiler/RDSL.md``.
Times are unix seconds. ``t0`` is inclusive and ``t1`` is exclusive, both UTC.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


OPS = ("<", "<=", ">", ">=", "==")
REVISIONS = ("first_print", "latest_before", "final")


class Rel(Enum):
    """Relation of contract A to contract B.

    ``implies`` means A's YES outcome entails B's. ``implied_by`` is the
    opposite direction. ``equiv`` is both. ``disjoint`` means they cannot
    both be YES. ``none`` means the solver found no one of those facts.
    ``unknown`` means the solver timed out or returned unknown.
    """

    EQUIV = "equiv"
    IMPLIES = "implies"
    IMPLIED_BY = "implied_by"
    DISJOINT = "disjoint"
    NONE = "none"
    UNKNOWN = "unknown"


def canonical_cmp(ref: str, op: str, threshold: float, unit: str | None) -> str:
    """Stable spelling of a comparison, so ``14.0d`` and ``14d`` match."""
    unit_s = unit or ""
    if isinstance(threshold, float) and threshold.is_integer() and abs(threshold) < 10**15:
        number = str(int(threshold))
    else:
        number = format(threshold, ".12g")
    return f"{ref} {op} {number}{unit_s}"


@dataclass(frozen=True)
class ResolutionSpec:
    contract_id: str
    venue: str
    source: str
    alias: str
    predicate_ref: str
    op: str
    threshold: float
    threshold_unit: str | None
    predicate_lexeme: str
    t0: int
    t1: int
    tz: str
    revision: str
    revision_at: int | None
    void_if: tuple[str, ...]
    dispute: str

    def __post_init__(self) -> None:
        if self.op not in OPS:
            raise ValueError(f"unsupported comparison {self.op!r}")
        if self.revision not in REVISIONS:
            raise ValueError(f"unsupported revision {self.revision!r}")
        if self.t1 <= self.t0:
            raise ValueError("window must be a nonempty half-open interval")
        if self.revision_at is not None and not isinstance(self.revision_at, int):
            raise ValueError("revision_at must be unix seconds or None")
        if not isinstance(self.void_if, tuple) or not all(isinstance(v, str) for v in self.void_if):
            raise ValueError("void_if must be a tuple of strings")

    def metric(self) -> str:
        prefix = self.alias + "."
        if self.predicate_ref.startswith(prefix):
            return self.predicate_ref[len(prefix) :]
        return self.predicate_ref

    def revision_key(self) -> str:
        """Identity of the observation policy. Different keys do not share a variable."""
        if self.revision == "latest_before" and self.revision_at is not None:
            return f"latest_before@{self.revision_at}"
        return self.revision

    def predicate_display(self) -> str:
        unit = self.threshold_unit or ""
        return f"{self.predicate_ref} {self.op} {self.predicate_lexeme}{unit}"

    def predicate_identity(self) -> tuple[str, str, float, str | None]:
        return (self.metric(), self.op, self.threshold, self.threshold_unit)
