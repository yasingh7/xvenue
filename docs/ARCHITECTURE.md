# Architecture v0

Services communicate over NATS JetStream using `proto/xvenue.proto`. Ticks live in ClickHouse, specs and relations in Postgres.

1. **compiler**: ingest `RawContract{venue, rules_md, source_urls, clarifications[]}`. A schema-constrained LLM extractor emits `ResolutionSpec`, and a validator rejects fields without a grounding span. Specs are lowered to SMT-LIB, and Z3 checks equiv/implies/disjoint (200 ms timeout → UNKNOWN → review).
2. **graph**: nodes are specs and edges are proven relations. Every 500 ms it projects mids onto the marginal polytope via Frank-Wolfe with an LP oracle. Bregman divergence → `Opportunity`.
3. **exec**: Avellaneda-Stoikov quoting with a binary-payoff inventory penalty and per-venue fee and latency models. Saga coordinator for multi-leg fills with hedge/unwind, idempotency keys and a drawdown kill switch.
4. **risk**: hierarchical Bayesian `P(divergent settlement | spec diff, source type, venue history)`, trained on UMA disputes and Kalshi clarifications.
5. **sim**: deterministic event-sourced L2 replay with latency, queue position and adversarial takers. CI gates `exec/` and `graph/` on backtested Sharpe and max drawdown.

## Milestones
- **M1 (wk 1-2):** compiler, 500 labeled specs, Z3 relations
- **M2 (wk 3):** graph, offline Frank-Wolfe on historical snapshots
- **M3 (wk 4-5):** sim, paper trading
- **M4 (wk 6):** live exec, capped size
