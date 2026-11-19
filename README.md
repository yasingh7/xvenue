# xvenue

Cross-venue prediction-market consistency and settlement-risk engine (Polymarket, Kalshi, Manifold).

**Status:** M1 in progress. The resolution DSL, spec schema, protobuf contracts and Z3 lowering prototype are here.

| Module | Lang | Purpose |
|---|---|---|
| `compiler/` | Rust + Python prototype | Rules text → `ResolutionSpec` → SMT-LIB, equivalence/implication/disjointness checks |
| `graph/` | Python/JAX | Consistency graph, Frank-Wolfe projection onto the marginal polytope |
| `exec/` | Rust (tokio) | Avellaneda-Stoikov quoting, saga-based multi-leg execution |
| `risk/` | Python/PyMC | Hierarchical Bayesian divergent-settlement model |
| `sim/` | Rust | Deterministic event-sourced L2 replay |
| `proto/` | protobuf | Service contracts over NATS JetStream |

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`compiler/RDSL.md`](compiler/RDSL.md).
