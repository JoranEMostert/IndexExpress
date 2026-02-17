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
- Use `peek` for direct URL output with optional fetched page markdown.
- Use `skim` for parallel retrieval agents plus a concise cited report.
- Use `analyze` for configurable multi-agent skim passes plus parallel contradiction-merge variants.
- Use `research` for deep multi-agent investigation with pair synthesis blocks (no extra global summarizer pass).
- Use `list_models` to inspect available model IDs from the configured OpenAI-compatible API.
- Use `agent_status` to monitor parallel agent capacity and active runs.
- Keep backward compatibility in mind: `quicksearch` is an alias for `skim`, `deepresearch` is an alias for `research`.

## When to use me

Use this skill when a task needs web research through your self-hosted ExpressIndex + MCP stack and you want consistent behavior across sessions.

## MCP workflow

1. Health-check stack:
   - `GET http://localhost:8000/health`
   - `GET http://localhost:8888/healthz`
2. Discover MCP tools:
   - JSON-RPC `tools/list`
3. Pick mode:
    - URL-only quick scan: `tools/call` -> `peek`
    - Fast cited report: `tools/call` -> `skim`
    - Contradiction-focused mid-depth report: `tools/call` -> `analyze`
   - Comprehensive deep research: `tools/call` -> `research` (returns `cluster_reports`, `synthesis_reports`, and `final_report` as a report-count message)
4. Optional diagnostics:
   - `tools/call` -> `list_models`
   - `tools/call` -> `agent_status`

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

## Operating defaults

- Start with `peek` for quick URL lookups and `skim` for most standard research tasks.
- Use `analyze` when the user asks for comparison, contradictions, or reconciliation of viewpoints.
- Use `research` when the user needs a deep, multi-angle report.
- For `research`, keep `num_sub_queries` aligned with available parallel agents.
- For broad throughput, tune env:
  - `SKIM_AGENT_COUNT`
  - `ANALYZE_AGENT_COUNT`
  - `ANALYZE_CONTRADICTION_AGENTS`
  - `MAX_CONCURRENT_AGENTS`
  - `RESEARCH_MAX_SUB_QUERIES`
- If report generation times out, reduce depth (`num_sub_queries`) before retrying.
- Keep outputs source-grounded and include cited URLs from MCP results.
- Never surface `<think>...</think>` in user-visible output.
