# xvenue

Cross-venue prediction-market consistency and settlement-risk engine (Polymarket, Kalshi, Manifold).

**Status:** M1 prototype. RDSL parses to `ResolutionSpec`, windows are normalized to UTC, and Z3 checks equiv / implies / implied_by / disjoint / none. `compiler/examples/` is illustrative, not live venue data. Graph, exec, risk, and sim are not in this tree.

| Module | Lang | Purpose |
|---|---|---|
| `compiler/` | Rust + Python prototype | Rules text → `ResolutionSpec` → SMT-LIB, equivalence/implication/disjointness checks |
| `graph/` | Python/JAX | Consistency graph, Frank-Wolfe projection onto the marginal polytope |
| `exec/` | Rust (tokio) | Avellaneda-Stoikov quoting, saga-based multi-leg execution |
| `risk/` | Python/PyMC | Hierarchical Bayesian divergent-settlement model |
| `sim/` | Rust | Deterministic event-sourced L2 replay |
| `proto/` | protobuf | Service contracts over NATS JetStream |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`compiler/RDSL.md`](compiler/RDSL.md).

## Relate two contracts

```bash
pip install -e ".[dev]"
python -m xvenue relate compiler/examples/cpi_pair.rdsl KXCPI-26DEC-T3.0 pm-cpi-below-3-dec
pytest
```

The entry point is `xvenue relate <file.rdsl> <idA> <idB>`. Windows that differ are not `unknown`: containment can support implication when the other fields allow it. Distinct revision policies stay independent. A 200 ms solver timeout becomes `unknown`.

```text
relation: none
divergent_fields: dispute_path, revision_policy, tz, void_if, window
window_relation: b_contains_a
dispute_path: kalshi.rulebook_13_1 | uma.optimistic_oracle_v3
revision_policy: first_print | latest_before(2027-01-31T23:59:00Z)
tz: America/New_York | UTC
void_if: bls.release_delayed > 14d | none
window: [2027-01-13T13:30:00Z, 2027-01-13T13:31:00Z) | [2027-01-01T00:00:00Z, 2027-01-31T23:59:00Z)
```

`compiler/examples/containment.rdsl` is the other direction, a nested window plus a tighter threshold:

```bash
python -m xvenue relate compiler/examples/containment.rdsl tight wide
```

```text
relation: implies
divergent_fields: predicate, window
window_relation: b_contains_a
predicate: x.value < 2.5 | x.value < 3.0
window: [2026-06-01T00:00:00Z, 2026-06-02T00:00:00Z) | [2026-06-01T00:00:00Z, 2026-06-04T00:00:00Z)
```

`python3 compiler/src/lower_smt.py` still runs the original two-line demo (`kalshi vs polymarket: none`, `k(<2.5) vs k(<3.0): implies`).
