# ExpressIndex

[![Mode: Tiered Search](https://img.shields.io/badge/mode-peek%20%7C%20skim%20%7C%20analyze%20%7C%20research-0ea5e9)](./mcp-server/server.py)
[![Protocol: MCP JSON-RPC](https://img.shields.io/badge/protocol-MCP%20JSON--RPC-334155)](http://localhost:8000/mcp)
[![SearXNG](https://img.shields.io/badge/search-searxng-10b981)](https://searxng.org)
[![LLM Backend](https://img.shields.io/badge/llm-LM%20Studio%20(OpenAI--compat)-f59e0b)](https://lmstudio.ai)

Privacy-first web research with tiered retrieval/report modes, source-cited outputs, MCP tools, and a simple user-facing terminal experience.

## Feature Labels

- `peek`: 5 URLs, no LLM report
- `skim`: configurable parallel skim agents + concise cited report
- `analyze`: configurable multi-agent skim passes + multi-merge contradiction synthesis
- `research`: deep multi-agent flow with pair synthesis blocks (no extra global summarizer)
- Citation contract: inline `(n)` references + final `Sources` list
- Output: optional markdown export for reports

## Tier Matrix

| Tier | Best For | Retrieval | LLM | Output |
|---|---|---|---|---|
| `peek` | Quick scanning | 5 URLs | No | Source list |
| `skim` | Fast grounded answer | Parallel multi-query retrieval | Single synthesis | Cited report |
| `analyze` | Compare viewpoints | Nx skim (configurable) | Multi-merge synthesis | Contradiction-aware report |
| `research` | Deep investigation | Multi-query parallel retrieval | Pair synthesis blocks | Comprehensive stitched output |

## Architecture

```text
Client (MCP or TUI)
    |
    v
MCP Server (server.py)
    |- peek      -> PeekAgent (search-only)
    |- skim      -> SkimAgent (parallel retrieval + report)
    |- analyze   -> AnalyzeOrchestrator (configurable skim runs + multi-merge)
    |- research  -> DeepSearchOrchestrator (sub-queries + pair synthesis blocks)
    |
    +-- SearXNGClient (retrieval)
    +-- LLMClient (OpenAI-compatible)
    +-- ReportGenerator (citation-aware reporting)
```

## Quick Start

1. Copy env template and set your model:

```bash
cp .env.example .env
```

2. Set `LLM_MODEL_ID` in `.env` to your loaded LM Studio model ID.

3. Build and start backend services:

```bash
docker compose up -d --build
```

4. Health checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8888/healthz
```

## MCP Tools

Primary tools:

- `peek`
- `skim`
- `analyze`
- `research`

Backward-compatible aliases:

- `quicksearch` -> `skim`
- `deepresearch` -> `research`

Example call:

```json
{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"skim","arguments":{"query":"fun facts about slugs","max_results":15}}}
```

## Terminal UI (User-Facing)

Install the local CLI:

```bash
pip install -e .
```

Launch TUI:

```bash
expressindex --tui
```

Run direct command mode:

```bash
expressindex peek "what is searxng"
expressindex skim "fun facts about slugs" --save-md report.md
expressindex analyze "best python web framework" --save-md compare.md
expressindex research "vacation plan to aruba" --num-sub-queries 6 --save-md aruba.md
```

UI goals:

- clear progress prompts
- friendly error messages
- no MCP protocol noise in normal output
- streaming report output in TUI report pane

## Report Contract

All LLM-backed tiers (`skim`, `analyze`, `research`) are expected to output:

- `Report` body
- inline citations like `(1)`, `(2)`
- final `Sources` section with indexed URLs
- sanitized output with no leaked `<think>...</think>` blocks

`research` response specifics:

- primary deliverable is `synthesis_reports` (grouped synthesis outputs)
- `final_report` is a status string indicating how many synthesis reports were returned

## Environment Variables

| Variable | Purpose | Default |
|---|---|---|
| `LLM_API_URL` | OpenAI-compatible base URL | `http://host.docker.internal:1234/v1` |
| `LLM_API_KEY` | Optional API key | empty |
| `LLM_MODEL_ID` | Active model ID | `local-model` |
| `LLM_MODEL` | Legacy alias for model ID (used when `LLM_MODEL_ID` is empty) | empty |
| `LLM_TIMEOUT` | LLM timeout (`0` = no timeout) | `0` |
| `LLM_MAX_PARALLEL` | Max concurrent LLM calls | `4` |
| `SEARXNG_URL` | SearXNG endpoint | `http://searxng:8080` |
| `SEARXNG_TIMEOUT` | Search timeout (`0` = no timeout) | `0` |
| `PEEK_MAX_URLS` | Default max URLs for `peek` | `5` |
| `SKIM_MAX_URLS` | Default max URLs for `skim` | `15` |
| `SKIM_AGENT_COUNT` | Parallel skim retrieval agents | `1` |
| `ANALYZE_SOURCES_PER_AGENT` | Sources per analyze agent | `12` |
| `ANALYZE_AGENT_COUNT` | Number of analyze agents/reports to merge | `2` |
| `ANALYZE_CONTRADICTION_AGENTS` | Number of parallel contradiction merge agents (`0` = auto) | `0` |
| `RESEARCH_MAX_SUB_QUERIES` | Research sub-queries (blank = inherit `MAX_CONCURRENT_AGENTS`) | inherited |
| `RESEARCH_SOURCES_PER_SUB_QUERY` | Sources per research sub-query | `8` |
| `MAX_CONCURRENT_AGENTS` | Parallel research workers | `7` |
| `LOG_LEVEL` | Logging level | `INFO` |

Legacy alias still supported:

- `LLM_MODEL` -> `LLM_MODEL_ID`

## LM Studio Parallelism Notes

- Increase model-side `Max Concurrent Predictions` in LM Studio.
- Keep `Unified KV Cache` enabled.
- Tune `LLM_MAX_PARALLEL` to match VRAM and model throughput.

## Troubleshooting

- LLM unavailable:
  - verify LM Studio server is up on `LLM_API_URL`
  - verify `LLM_MODEL_ID` matches currently loaded model
- Slow responses:
  - lower `LLM_MAX_PARALLEL`
  - lower `RESEARCH_MAX_SUB_QUERIES` and/or `MAX_CONCURRENT_AGENTS`
- Citation quality issues:
  - report generator performs a citation-repair pass automatically

## Project Map

- MCP server: `mcp-server/server.py`
- Tier agents: `mcp-server/agents/quicksearch.py`, `mcp-server/agents/deepresearch.py`
- Reporting engine: `mcp-server/reporting.py`
- Search/LLM clients: `mcp-server/search/searxng_client.py`, `mcp-server/search/llm_client.py`
- ExpressIndex CLI/TUI: `expressindex_cli/main.py`
- Legacy helper script: `mcp-server/tui.py`
- Skill profile: `.agents/skills/searxng-mcp-research/SKILL.md`
