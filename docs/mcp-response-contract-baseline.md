# MCP Response Contract Baseline

This document freezes the currently observed MCP contract in `mcp-server/server.py` before simplification refactors.

## JSON-RPC Envelope

- Endpoint: `POST /mcp`
- Success response envelope: `{"jsonrpc": "2.0", "id": <same id>, "result": <method result>}`
- Error response envelope: `{"jsonrpc": "2.0", "id": <same id or null>, "error": {...}}`
- Error payload shape:
  - `error.code` (JSON-RPC or server-specific integer)
  - `error.message` (string)
  - `error.data.type` (stable error type string)
  - `error.data.schema_version` (currently `v2.0`)

## Methods and Result Shapes

- `initialize`
  - Returns `protocolVersion`, `schemaVersion`, `capabilities`, `serverInfo`.
- `tools/list`
  - Returns `tools: []` with each tool containing `name`, `description`, `inputSchema`.
- `tools/call`
  - Returns `result.content[0]` with `{ "type": "text", "text": "<JSON string>" }`.
  - The JSON string always includes `schema_version: "v2.0"` at top level.
- `resources/list`
  - Returns `resources: []` of static URI metadata entries.
- `health`
  - Returns `schemaVersion`, `status`, `services`, `session`.
- `ready`
  - Returns `schemaVersion`, `status`, `checks`, `require_llm`, `session`.
- `metrics`
  - Returns `schemaVersion`, `session`, `metrics`.

## Tool Output Keys (`tools/call`)

- `peek`
  - `query`, `sources`, `_meta`
- `skim`
  - `query`, `final_answer`, `claims`, `key_evidence`, `sources`, `uncertainties`, `_meta`
- `analyze` (standard path)
  - `query`, `query_mode`, `requested_mode`, `executed_mode`, `route_reason`, `analysis_type`, `options_compared`, `recommended_option`, `confidence`, `why_not`, `consensus_claims`, `disputed_claims`, `decision_matrix`, `recommended_position`, `sensitivity_factors`, `key_evidence`, `sources`, `_meta`
- `analyze` (routed to research)
  - `query`, `requested_mode`, `executed_mode`, `route_reason`, `analysis_type`, `options_compared`, `final_synthesis`, `evidence_graph`, `coverage_report`, `open_questions`, `trace_log`, `key_evidence`, `sources`, `_meta`
- `research`
  - `query`, `final_synthesis`, `evidence_graph`, `coverage_report`, `open_questions`, `trace_log`, `key_evidence`, `sources`, `_meta`
- `search_engines`
  - `message`
- `agent_status`
  - passthrough pool status object from `DeepSearchOrchestrator.get_pool_status()`
- `list_models`
  - `models`, `api_url`
- `fetch_url`
  - `url`, `fetched_markdown`, `chars`

## Alias Compatibility

- `quicksearch` resolves to `skim`.
- `deepresearch` resolves to `research`.

## Validation/Error Invariants

- For `peek|skim|analyze|research`, `query` must be non-empty string and under configured max length.
- `max_results` must be positive integer when supplied.
- `research.num_sub_queries` must be positive integer when supplied.
- `analyze.options` must be array of non-empty strings with max 8 entries.
- `fetch_url.url` must start with `http://` or `https://`.
- `fetch_url.max_chars` must be positive integer.
