# MCP v2 Productization Todo

## Completed in this overhaul

- [x] Introduce strict shared primitives (`Source`, `Evidence`, `Claim`, `_meta`) in runtime workflow code.
- [x] Replace `peek` with consensus-calibrated retrieval output (`query_intent_classified`, `coverage_tags`, followups).
- [x] Replace `skim` with citation-first distillation output (`final_answer`, `claims`, `key_evidence`, `uncertainties`).
- [x] Replace `analyze` with adversarial adjudication output (`consensus_claims`, `disputed_claims`, `decision_matrix`).
- [x] Replace `research` with iterative planner-reviewer DAG output (`evidence_graph`, `coverage_report`, `trace_log`).
- [x] Update MCP server payload wiring to expose v2 response contracts.
- [x] Update CLI/TUI rendering to validate and inspect new machine-first payloads.
- [x] Extend sanitization paths for new top-level fields.
- [x] Add regression tests for workflow primitive ranking, claim conflict detection, graph edges, and `_meta` contract.

## Next hardening passes

- [ ] Add strict JSON schema validation per mode before MCP response emission.
- [ ] Add configurable scoring weights (relevance/consensus/trust/freshness) in config.
- [ ] Add benchmark tests for latency and token footprint by mode.
- [ ] Add optional model-generated `decision_matrix` with deterministic fallback if JSON parse fails.
- [ ] Add snapshot tests for representative v2 payloads in `peek`, `skim`, `analyze`, `research`.
