# Contracts

This document defines the baseline contracts that simplification work must preserve.

## MCP Envelope Invariants

- MCP transport endpoint is `POST /mcp`.
- JSON-RPC envelope remains `{"jsonrpc":"2.0","id":...,"result"|"error":...}`.
- Error payload shape remains:
  - `error.code` (int)
  - `error.message` (string)
  - `error.data.type` (string)
  - `error.data.schema_version` (string)
- Successful `tools/call` returns `result.content[0].type == "text"` and `result.content[0].text` contains JSON.

## Tool Name Invariants

- Primary tools: `peek`, `skim`, `analyze`, `research`, `search_engines`, `agent_status`, `list_models`, `fetch_url`.
- Compatibility aliases currently supported:
  - `quicksearch` -> `skim`
  - `deepresearch` -> `research`

## Shared Payload Invariants

- `tools/call` payload JSON includes `schema_version` (`v2.0` currently).
- Text fields from LLM output are sanitized to strip `<think>` content before returning to CLI.
- Source lists use object entries with stable URL/title style keys.
- Meta timing/token fields stay under `_meta` when available.

## Tool Payload Keys

- `peek`
  - `query`, `sources`, `_meta`
- `skim`
  - `query`, `final_answer`, `claims`, `key_evidence`, `sources`, `uncertainties`, `_meta`
- `analyze` (standard)
  - `query`, `query_mode`, `requested_mode`, `executed_mode`, `route_reason`, `analysis_type`
  - `options_compared`, `recommended_option`, `confidence`, `why_not`
  - `consensus_claims`, `disputed_claims`, `decision_matrix`, `recommended_position`
  - `sensitivity_factors`, `key_evidence`, `sources`, `_meta`
- `analyze` (routed to research)
  - `query`, `requested_mode`, `executed_mode`, `route_reason`, `analysis_type`, `options_compared`
  - `final_synthesis`, `evidence_graph`, `coverage_report`, `open_questions`, `trace_log`
  - `key_evidence`, `sources`, `_meta`
- `research`
  - `query`, `final_synthesis`, `evidence_graph`, `coverage_report`, `open_questions`, `trace_log`, `key_evidence`, `sources`, `_meta`
- `search_engines`
  - `message`
- `agent_status`
  - pool status object from `DeepSearchOrchestrator.get_pool_status()`
- `list_models`
  - `models`, `api_url`
- `fetch_url`
  - `url`, `fetched_markdown`, `chars`

## Validation Invariants

- `query` is required and non-empty for `peek|skim|analyze|research`.
- `query` length must not exceed configured max.
- `max_results` must be a positive integer when provided.
- `num_sub_queries` must be a positive integer when provided.
- `options` must be an array of non-empty strings (max 8).
- `fetch_url.url` must start with `http://` or `https://`.
- `fetch_url.max_chars` must be a positive integer.

## HTTP Endpoint Invariants

- `GET /health` returns `schemaVersion`, `status`, `services`, `session`.
- `GET /ready` returns `schemaVersion`, `status`, `checks`, `require_llm`, `session`.
- `GET /metrics` returns `schemaVersion`, `session`, `metrics`.
