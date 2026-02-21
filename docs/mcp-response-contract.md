# MCP Response Contract (Baseline)

Captured from `mcp-server/server.py` on 2026-02-21.

## Transport Envelope (`POST /mcp`)

- Success envelope:

```json
{
  "jsonrpc": "2.0",
  "id": "<request-id>",
  "result": { }
}
```

- Error envelope:

```json
{
  "jsonrpc": "2.0",
  "id": "<request-id-or-null>",
  "error": {
    "code": -32602,
    "message": "...",
    "data": {
      "type": "validation_error",
      "schema_version": "v2.0"
    }
  }
}
```

## Method-Level Result Shapes

- `initialize` returns `protocolVersion`, `schemaVersion`, `capabilities`, `serverInfo`.
- `tools/list` returns `{ "tools": [ ... ] }` where each tool has `name`, `description`, `inputSchema`.
- `tools/call` success returns `{ "content": [{ "type": "text", "text": "<json-string>" }] }`.
  - The JSON string always includes `schema_version: "v2.0"`.
  - Aliases resolve as `quicksearch -> skim` and `deepresearch -> research`.
- `resources/list` returns `{ "resources": [ ... ] }`.
- `health` returns `schemaVersion`, `status`, `services`, `session`.
- `ready` returns `schemaVersion`, `status`, `checks`, `require_llm`, `session`.
- `metrics` returns `schemaVersion`, `session`, `metrics`.

## `tools/call` Payload Keys by Tool

- `peek`: `query`, `sources`, `_meta`
- `skim`: `query`, `final_answer`, `claims`, `key_evidence`, `sources`, `uncertainties`, `_meta`
- `analyze` (normal):
  - `query`, `query_mode`, `requested_mode`, `executed_mode`, `route_reason`, `analysis_type`
  - `options_compared`, `recommended_option`, `confidence`, `why_not`
  - `consensus_claims`, `disputed_claims`, `decision_matrix`, `recommended_position`
  - `sensitivity_factors`, `key_evidence`, `sources`, `_meta`
- `analyze` (routed to research):
  - `query`, `requested_mode`, `executed_mode`, `route_reason`, `analysis_type`, `options_compared`
  - `final_synthesis`, `evidence_graph`, `coverage_report`, `open_questions`, `trace_log`
  - `key_evidence`, `sources`, `_meta`
- `research`: `query`, `final_synthesis`, `evidence_graph`, `coverage_report`, `open_questions`, `trace_log`, `key_evidence`, `sources`, `_meta`
- `search_engines`: `message`
- `agent_status`: passthrough status object from orchestrator pool
- `list_models`: `models`, `api_url`
- `fetch_url`: `url`, `fetched_markdown`, `chars`

## Error Type Vocabulary (current)

- `parse_error` (invalid JSON body)
- `validation_error` (bad params)
- `unknown_method` / `unknown_tool`
- `upstream_timeout`
- `upstream_unavailable`
- `internal_error`
