# RDSL — Resolution DSL v0

A contract is a guarded predicate over an observation from a named source inside a time window, plus settlement policy.

```
contract <id> on <venue> {
  observe   <source>.<series> [as <alias>]
  window    [<t0>, <t1>) tz <IANA tz>
  predicate <expr>
  revision  first_print | latest_before(<t>) | final
  void_if   <expr> [, <expr>]*
  dispute   <path>
}
```

Semantics: `YES  <=>  ∃ t ∈ window : predicate(observe@t, revision)  ∧  ¬void_if`.

Two contracts are **equivalent** iff their lowered formulas are equisatisfiable under every shared source valuation; **A implies B** iff `A ∧ ¬B` is UNSAT; **disjoint** iff `A ∧ B` is UNSAT. Any field that cannot be grounded in a span of the source rules text produces `UNKNOWN` and is routed to review.
