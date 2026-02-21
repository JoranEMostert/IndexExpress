# Current Architecture Map

This document maps how the repository behaves today (pre-simplification).

## Runtime Entry Points

- MCP server: `mcp-server/server.py`
- CLI: `expressindex_cli/main.py`
- Core sanitization package: `expressindex_core/sanitize.py`

## High-Level Runtime Flow

1. User runs `expressindex ...` in `expressindex_cli/main.py`.
2. CLI sends JSON-RPC `tools/call` requests to `POST /mcp`.
3. `mcp-server/server.py` validates input, resolves aliases, and dispatches tool handlers.
4. Tool handlers call agents in `mcp-server/agents/`.
5. Agents call search and LLM clients in `mcp-server/search/`.
6. Agents construct payloads and return results to server.
7. Server wraps payload in MCP `content[0].text` JSON and returns to CLI.
8. CLI sanitizes and renders output as text/json/markdown.

## MCP Server Internal Flow (`mcp-server/server.py`)

- `MCPRequestHandler.handle_request()` routes by JSON-RPC method:
  - `initialize`
  - `tools/list`
  - `tools/call`
  - `resources/list`
  - `health`
  - `ready`
  - `metrics`
- `_handle_tools_call()` does:
  - argument type and shape validation
  - alias mapping (`quicksearch` -> `skim`, `deepresearch` -> `research`)
  - tool execution timeout wrapping
  - tool-level metrics recording
  - error classification to MCP-compatible codes/types

## Tool-to-Agent Mapping

- `peek` -> `agents.quicksearch.PeekAgent.search()`
- `skim` -> `agents.quicksearch.QuickSearchAgent.search()`
- `analyze` -> `agents.deepresearch.AnalyzeOrchestrator.analyze()`
  - optional fallback route to `DeepSearchOrchestrator.search()`
- `research` -> `agents.deepresearch.DeepSearchOrchestrator.search()`
- `agent_status` -> `DeepSearchOrchestrator.get_pool_status()`
- `fetch_url` -> `search.searxng_client.SearXNGClient.fetch_url_content()`

## Agent/Core Dependencies

- `mcp-server/agents/quicksearch.py`
  - lightweight retrieval and skim orchestration
- `mcp-server/agents/deepresearch.py`
  - analyze/research orchestration and planning logic
- `mcp-server/workflow_primitives.py`
  - ranking, evidence extraction, claims, summaries, query mode heuristics
- `mcp-server/reporting.py`
  - report writing/merge and citation repair helpers

## Client Layer

- `mcp-server/search/searxng_client.py`
  - SearXNG API calls, URL fetching, readability extraction
- `mcp-server/search/llm_client.py`
  - LLM API calls, retries, output handling

## CLI Rendering Paths

- Text output uses `_render_report_text()` and fallback fields.
- JSON output prints payload as-is (post-sanitization).
- Markdown output uses `markdown_from_result()`.
- Status and metrics are fetched from HTTP endpoints (`/health`, `/ready`, `/metrics`) and rendered separately.

## Observability and Health

- `GET /health` checks SearXNG + LLM and returns healthy/degraded.
- `GET /ready` applies readiness policy (`readiness_require_llm`).
- `GET /metrics` exposes request/tool counters from `telemetry.MetricsRegistry`.

## Current Coupling Hotspots

- `mcp-server/server.py` combines transport, validation, dispatch, aliasing, and endpoint wiring.
- `expressindex_cli/main.py` combines args, transport, and rendering.
- `mcp-server/workflow_primitives.py` mixes URL utilities, ranking, evidence, and claim logic.
