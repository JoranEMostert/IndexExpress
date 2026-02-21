# ExpressIndex

[![Mode: Tiered Search](https://img.shields.io/badge/mode-peek%20%7C%20skim%20%7C%20analyze%20%7C%20research-0ea5e9)](./mcp-server/server.py)
[![Protocol: MCP JSON-RPC](https://img.shields.io/badge/protocol-MCP%20JSON--RPC-334155)](http://localhost:8000/mcp)
[![SearXNG](https://img.shields.io/badge/search-searxng-10b981)](https://searxng.org)
[![LLM Backend](https://img.shields.io/badge/llm-LM%20Studio%20(OpenAI--compat)-f59e0b)](https://lmstudio.ai)

Privacy-first web research with tiered retrieval/report modes, source-cited outputs, MCP tools, and a simple user-facing terminal experience.

## Feature Labels

- `peek`: pure link-discovery primitive returning ranked `sources`
- `skim`: citation-first distillation returning `final_answer`, `claims`, `key_evidence`
- `analyze`: comparative adjudication for explicit alternatives, with automatic fallback to `research` when comparison input is insufficient
- `research`: iterative planner-reviewer DAG returning `final_synthesis`, `evidence_graph`, and coverage status
- Citation contract: evidence links by `source_id` / `evidence_id`
- Output: optional markdown export for reports

## Tier Matrix

| Tier | Best For | Retrieval | LLM | Output |
|---|---|---|---|---|
| `peek` | Quick evidence frontier | Multi-intent retrieval + calibration | No | `sources` with rank metadata |
| `skim` | Fast grounded answer | Parallel evidence collection | Claim/evidence distillation | `final_answer`, `claims`, `key_evidence` |
| `analyze` | Compare alternatives and recommend one | Adversarial evidence pass | Decision adjudication | comparator payload or routed `research` payload with routing metadata |
| `research` | Exhaustive investigation | Iterative planner/reviewer loops | Graph synthesis | `evidence_graph`, `coverage_report`, `trace_log` |

## Architecture

```text
Client (MCP or TUI)
    |
    v
MCP Server (server.py)
    |- peek      -> PeekAgent (consensus-calibrated retrieval primitive)
    |- skim      -> SkimAgent (citation-first distillation pack)
    |- analyze   -> AnalyzeOrchestrator (adversarial claim adjudication)
    |- research  -> DeepSearchOrchestrator (iterative planner-reviewer DAG)
    |
    +-- SearXNGClient (retrieval)
    +-- LLMClient (OpenAI-compatible)
    +-- workflow_primitives.py (ranking/evidence/claims primitives)
```

## Quick Start

1. Copy env template and set your model:

```bash
cp .env.example .env
```

2. Set `LLM_MODEL_ID` in `.env` to your loaded LM Studio model ID.

Recommended minimal `.env` for most users:

```bash
LLM_API_URL=http://localhost:1234/v1
LLM_MODEL_ID=<your-model-id>
LLM_MAX_PARALLEL=4
SEARXNG_URL=http://localhost:8888
```

Everything else in `.env.example` is optional tuning.

3. Build and start backend services:

```bash
docker compose up -d --build
```

4. Health checks:

```bash
curl http://localhost:8000/health
curl http://localhost:8000/ready
curl http://localhost:8000/metrics
curl http://localhost:8888/healthz
```

`/ready` is a stricter readiness gate for deploy checks, and `/metrics` returns request/tool counters with latency aggregates.

## MCP Tools

Primary tools:

- `peek`
- `skim`
- `analyze`
- `research`
- `fetch_url` (raw page fetch helper for URL inspection)

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
expressindex analyze "python vs node.js for backend" --options "python,node.js"
expressindex research "vacation plan to aruba" --num-sub-queries 6 --save-md aruba.md
expressindex status
expressindex metrics --json
```

All terminal activations (all search modes + URL fetch helper):

```bash
# Search modes (CLI)
expressindex peek "slug facts"
expressindex skim "slug facts"
expressindex analyze "python vs node.js for backend" --options "python,node.js"
expressindex research "slug facts" --num-sub-queries 6

# URL fetch helper (MCP tool)
curl -sS http://localhost:8000/mcp \
  -H "Content-Type: application/json" \
  -d '{
    "jsonrpc": "2.0",
    "id": 1,
    "method": "tools/call",
    "params": {
      "name": "fetch_url",
      "arguments": {
        "url": "https://en.wikipedia.org/wiki/Slug",
        "max_chars": 4000
      }
    }
  }'
```

Direct mode output formats:

```bash
expressindex skim "fun facts" --output text
expressindex skim "fun facts" --output json
expressindex skim "fun facts" --output markdown
```

UI goals:

- clear progress prompts
- friendly error messages
- no MCP protocol noise in normal output
- simple command-loop UX with mock MCP-consumer summaries for multi-report modes

## Report Contract

All query tools now return strict MCP-first JSON with shared primitives:

- `sources[]`: `{source_id, url, title, domain, relevance_score, domain_trust_score, freshness_timestamp, intent_category}`
- `key_evidence[]`: `{evidence_id, source_id, exact_quote, relevance_score}`
- `claims[]`: `{claim_id, statement, support_evidence_ids, refute_evidence_ids, confidence_tier}`
- `_meta`: `{token_estimate, compute_ms, schema_version}`

Mode-specific outputs:

- `peek`: `query`, `sources`, `_meta`
- `skim`: `final_answer`, `claims`, `uncertainties`
- `analyze`: `requested_mode`, `executed_mode`, `route_reason`, `options_compared`, `recommended_option`, `confidence`, `why_not`, `recommended_position`, `decision_matrix`
- `research`: `final_synthesis`, `evidence_graph`, `coverage_report`, `open_questions`, `trace_log`

## Environment Variables

If the full table feels too configurable, use the 4-variable minimal config above and keep defaults for the rest.

| Variable | Purpose | Default |
|---|---|---|
| `LLM_API_URL` | OpenAI-compatible base URL | `http://localhost:1234/v1` |
| `LLM_API_KEY` | Optional API key | empty |
| `LLM_MODEL_ID` | Active model ID | `local-model` |
| `LLM_MODEL` | Legacy alias for model ID (used when `LLM_MODEL_ID` is empty) | empty |
| `LLM_TIMEOUT` | LLM timeout (`0` = no timeout) | `0` |
| `LLM_MAX_PARALLEL` | Max concurrent LLM calls | `4` |
| `LLM_RETRIES` | Retry attempts for transient LLM failures | `2` |
| `SEARXNG_URL` | SearXNG endpoint | `http://searxng:8080` |
| `SEARXNG_TIMEOUT` | Search timeout (`0` = no timeout) | `0` |
| `SEARXNG_RETRIES` | Retry attempts for transient search failures | `2` |
| `PEEK_MAX_URLS` | Default max URLs for `peek` | `5` |
| `SKIM_MAX_URLS` | Default max URLs for `skim` | `15` |
| `SKIM_AGENT_COUNT` | Parallel skim retrieval agents | `1` |
| `ANALYZE_SOURCES_PER_AGENT` | Sources per analyze agent | `12` |
| `ANALYZE_AGENT_COUNT` | Number of analyze retrieval variants | `2` |
| `ANALYZE_CONTRADICTION_AGENTS` | Compatibility knob for legacy analyze paths | `0` |
| `RESEARCH_MAX_SUB_QUERIES` | Research sub-queries (blank = inherit `MAX_CONCURRENT_AGENTS`) | inherited |
| `RESEARCH_SOURCES_PER_SUB_QUERY` | Sources per research sub-query | `8` |
| `MAX_CONCURRENT_AGENTS` | Parallel research workers | `7` |
| `QUERY_MAX_LENGTH` | Maximum accepted query length | `600` |
| `READINESS_REQUIRE_LLM` | Require LLM health for `/ready` | `true` |
| `TOOL_TIMEOUT_PEEK` | Max seconds for `peek` tool execution (`0` disables timeout) | `30` |
| `TOOL_TIMEOUT_SKIM` | Max seconds for `skim` tool execution (`0` disables timeout) | `120` |
| `TOOL_TIMEOUT_ANALYZE` | Max seconds for `analyze` tool execution (`0` disables timeout) | `300` |
| `TOOL_TIMEOUT_RESEARCH` | Max seconds for `research` tool execution (`0` disables timeout) | `900` |
| `HTTP_RETRY_BASE_MS` | Base delay for exponential retry backoff | `250` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `LOG_FORMAT` | `text` or structured `json` logs | `text` |

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

## Todo

- Manual mode: fetch provider documentation on retrieving whole pages as Markdown and add an explicit manual workflow.

## Project Map

- MCP server: `mcp-server/server.py`
- Tier agents: `mcp-server/agents/quicksearch.py`, `mcp-server/agents/deepresearch.py`
- Reporting engine: `mcp-server/reporting.py`
- Search/LLM clients: `mcp-server/search/searxng_client.py`, `mcp-server/search/llm_client.py`
- ExpressIndex CLI/TUI: `expressindex_cli/main.py`
- Skill profile: `.agents/skills/searxng-mcp-research/SKILL.md`
