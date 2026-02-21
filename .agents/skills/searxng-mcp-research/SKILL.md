---
name: searxng-mcp-research
description: Use the local ExpressIndex MCP server with tiered research modes (peek, skim, analyze, research)
compatibility: opencode
metadata:
  scope: local-project
  transport: http-jsonrpc
  endpoint: http://localhost:8000/mcp
---

## What I do

- Use the local ExpressIndex MCP server at `http://localhost:8000/mcp`.
- Use `peek` for link discovery (`query`, `sources`, `_meta`), with optional page fetching during ranking.
- Use `skim` for concise cited output (`final_answer`, `claims`, `key_evidence`, `sources`, `uncertainties`).
- Use `analyze` for fact-aware adjudication (`recommended_position`, `sensitivity_factors`, and optional `decision_matrix`).
- Use `research` for deep synthesis (`final_synthesis`, `evidence_graph`, `coverage_report`, `open_questions`, `trace_log`).
- Use `fetch_url` to inspect the extracted markdown-ish content for a single URL.
- Use `list_models` to inspect available model IDs from the configured OpenAI-compatible API.
- Use `agent_status` to monitor parallel agent capacity and active runs.
- Keep backward compatibility in mind: `quicksearch` is an alias for `skim`, `deepresearch` is an alias for `research`.

## When to use me

Use this skill when a task needs web research through your self-hosted ExpressIndex + MCP stack and you want consistent behavior across sessions.

## MCP workflow

1. Health-check stack:
    - `GET http://localhost:8000/health`
    - `GET http://localhost:8000/ready`
    - `GET http://localhost:8000/metrics`
    - `GET http://localhost:8888/healthz`
2. Discover MCP tools:
   - JSON-RPC `tools/list`
3. Pick mode:
    - URL-first quick scan: `tools/call` -> `peek`
    - Fast factual distillation: `tools/call` -> `skim`
    - Mid-depth adjudication/recommendation: `tools/call` -> `analyze`
    - Comprehensive deep research: `tools/call` -> `research`
    - Single URL content inspection: `tools/call` -> `fetch_url`
4. Optional diagnostics:
    - `tools/call` -> `list_models`
    - `tools/call` -> `agent_status`
    - `GET /metrics` for request/tool latency and error counters

## JSON-RPC templates

Use `POST http://localhost:8000/mcp` with `Content-Type: application/json`.

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}
```

```json
{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"peek","arguments":{"query":"<topic>","max_results":5}}}
```

```json
{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"skim","arguments":{"query":"<topic>","max_results":15}}}
```

```json
{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"analyze","arguments":{"query":"<topic>"}}}
```

```json
{"jsonrpc":"2.0","id":5,"method":"tools/call","params":{"name":"research","arguments":{"query":"<topic>","num_sub_queries":6}}}
```

```json
{"jsonrpc":"2.0","id":6,"method":"tools/call","params":{"name":"fetch_url","arguments":{"url":"https://example.com","max_chars":4000}}}
```

## Operating defaults

- Start with `peek` for quick URL lookups and `skim` for most standard research tasks.
- Use `analyze` when the user asks for comparison, contradictions, or reconciliation of viewpoints.
- Use `research` when the user needs a deep, multi-angle report.
- Use `fetch_url` when a specific URL needs extraction debugging or content validation.
- For `research`, keep `num_sub_queries` aligned with available parallel agents.
- When invoking MCP via the Bash tool, set an explicit command timeout of at least 60 minutes (`timeout: 3600000`) to avoid the default 120s cutoff for long-running `research`/`deepresearch` calls.
- For broad throughput, tune env:
  - `SKIM_AGENT_COUNT`
  - `ANALYZE_AGENT_COUNT`
  - `ANALYZE_CONTRADICTION_AGENTS`
  - `MAX_CONCURRENT_AGENTS`
  - `RESEARCH_MAX_SUB_QUERIES`
- If report generation times out, reduce depth (`num_sub_queries`) before retrying.
- Keep outputs source-grounded and include cited URLs from MCP results.
- Never surface `<think>...</think>` in user-visible output.
- Send valid non-empty string `query` values for tier tools; invalid query payloads are rejected with JSON-RPC `-32602`.
- Keep query length below `QUERY_MAX_LENGTH` and prefer concise, focused research prompts.
- Remember responses include `schema_version`; preserve it when transforming payloads in automation.
