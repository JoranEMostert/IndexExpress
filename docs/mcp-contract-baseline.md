# MCP Response Contract Baseline (Phase 0)

This file freezes the current MCP wire contract before simplification refactors.

## JSON-RPC Envelope

- Transport endpoint: `POST /mcp`
- Request envelope: `{"jsonrpc":"2.0","id":<any>,"method":<string>,"params":<object>}`
- Success envelope: `{"jsonrpc":"2.0","id":<same>,"result":<object>}`
- Error envelope: `{"jsonrpc":"2.0","id":<same|null>,"error":{...}}`

`tools/call` success shape currently returns `result.content[0].type == "text"` and
`result.content[0].text` is a JSON string.

## Schema Version Fields

- MCP tool payload JSON includes `schema_version` (snake case) from `SCHEMA_VERSION`.
- Health/ready/metrics HTTP JSON includes `schemaVersion` (camel case).

Current `SCHEMA_VERSION`: `v2.0`.

## Error Contract

Error object shape:

```json
{
  "code": -32602,
  "message": "Invalid params: ...",
  "data": {
    "type": "validation_error",
    "schema_version": "v2.0"
  }
}
```

Common error `data.type` values:

- `validation_error`
- `unknown_tool`
- `unknown_method`
- `upstream_timeout`
- `upstream_unavailable`
- `internal_error`
- `parse_error` (JSON parse failures at transport boundary)

## Tool Name Contract

Primary tools:

- `peek`
- `skim`
- `analyze`
- `research`
- `search_engines`
- `agent_status`
- `list_models`
- `fetch_url`

Compatibility aliases currently accepted:

- `quicksearch` -> `skim`
- `deepresearch` -> `research`

## Tool Payload Key Baseline

`peek` keys:

- `schema_version`, `query`, `sources`, `_meta`

`skim` keys:

- `schema_version`, `query`, `final_answer`, `claims`, `key_evidence`, `sources`, `uncertainties`, `_meta`

`analyze` (normal) keys:

- `schema_version`, `query`, `query_mode`, `requested_mode`, `executed_mode`, `route_reason`, `analysis_type`, `options_compared`, `recommended_option`, `confidence`, `why_not`, `consensus_claims`, `disputed_claims`, `decision_matrix`, `recommended_position`, `sensitivity_factors`, `key_evidence`, `sources`, `_meta`

`analyze` (routed to research) keys:

- `schema_version`, `query`, `requested_mode`, `executed_mode`, `route_reason`, `analysis_type`, `options_compared`, `final_synthesis`, `evidence_graph`, `coverage_report`, `open_questions`, `trace_log`, `key_evidence`, `sources`, `_meta`

`research` keys:

- `schema_version`, `query`, `final_synthesis`, `evidence_graph`, `coverage_report`, `open_questions`, `trace_log`, `key_evidence`, `sources`, `_meta`

`search_engines` keys:

- `schema_version`, `message`

`agent_status` keys:

- `schema_version` plus pool status fields from `DeepSearchOrchestrator.get_pool_status()`

`list_models` keys:

- `schema_version`, `models`, `api_url`

`fetch_url` keys:

- `schema_version`, `url`, `fetched_markdown`, `chars`
