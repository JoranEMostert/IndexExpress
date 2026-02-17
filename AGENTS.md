# AGENTS.md

Operational guide for coding agents in this repository.

## 1) Repository Shape

- CLI package: `expressindex_cli/` (installable from `pyproject.toml`).
- MCP server app: `mcp-server/` (run as scripts, not as a packaged module).
- Infra: `docker-compose.yml`, `mcp-server/Dockerfile`, `.env.example`.
- Search config: `searxng/settings.yml`.
- Agent skill reference: `.agents/skills/searxng-mcp-research/SKILL.md`.

## 2) Cursor/Copilot Rules Check

- `.cursor/rules/`: not present.
- `.cursorrules`: not present.
- `.github/copilot-instructions.md`: not present.
- No extra editor rule files are currently defined.

## 3) Python and Dependencies

- Python target: `>=3.11`.
- Root dependencies: `aiohttp`, `prompt_toolkit`, `rich`.
- Server dependencies: `aiohttp`, `pyyaml` (`mcp-server/requirements.txt`).
- CLI entrypoint: `expressindex = expressindex_cli.main:main`.

## 4) Setup Commands

```bash
cp .env.example .env
pip install -e .
pip install -r mcp-server/requirements.txt
```

## 5) Build / Run Commands

### Preferred full stack (Docker)

```bash
docker compose up -d --build
docker compose down
```

### Local run (without Docker)

```bash
python mcp-server/server.py
expressindex --tui
expressindex peek "what is searxng"
expressindex skim "fun facts about slugs" --save-md report.md
```

### Recreate server after env changes

```bash
docker compose up -d --force-recreate mcp-server
```

## 6) Health and Smoke Commands

```bash
curl http://localhost:8000/health
curl http://localhost:8888/healthz
curl -s http://localhost:8000/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}'
```

## 7) Lint / Format / Type Check Status

- No configured lint tool found (`ruff/flake8/black/isort` absent in repo config).
- No configured type-checker found (`mypy/pyright` absent in repo config).
- Follow PEP 8 and existing local style in touched files.
- Use this syntax sanity check before finishing substantial edits:

```bash
python -m compileall expressindex_cli mcp-server
```

## 8) Test Commands (Current + Future)

- Current tests are present under `tests/`.
- Standard test runner: `pytest`.

### Run all tests

```bash
pytest -q
```

### Run a single test file

```bash
pytest -q tests/test_reporting_retry_flow.py
```

### Run a single test case (most important)

```bash
pytest -q tests/test_research_subquery_count.py::test_generate_sub_queries_expands_model_short_list
```

### Fast sanity set for recent workflow changes

```bash
pytest -q tests/test_think_tag_sanitization.py tests/test_research_subquery_count.py tests/test_skim_agent_parallelism.py
```

## 9) Code Style Guidelines

### Imports

- Order imports: standard library, third-party, local modules.
- Separate groups with one blank line.
- Prefer explicit imports; never introduce wildcard imports.
- In `mcp-server/`, keep current import style (`from config import ...`, `from agents...`).

### Formatting

- 4-space indentation, no tabs.
- Keep functions small and single-purpose where practical.
- Preserve file-local conventions (quote style varies by module).
- Add comments only for non-obvious logic.

### Types and Data Modeling

- Add type hints on new/changed public functions.
- Prefer dataclasses for structured results/state.
- Keep container types explicit (`list[str]`, `dict[str, Any]`).
- Be consistent in a file with `Optional[T]` vs `T | None`.

### Naming

- `snake_case`: variables/functions/modules.
- `PascalCase`: classes/dataclasses.
- `UPPER_SNAKE_CASE`: constants.
- Keep MCP tool names stable: `peek`, `skim`, `analyze`, `research`.
- Preserve aliases for compatibility: `quicksearch`, `deepresearch`.
- Prefer current env names:
  - `ANALYZE_SOURCES_PER_AGENT` (not old `ANALYZE_AGENT_URLS`)
  - `RESEARCH_SOURCES_PER_SUB_QUERY` (not old `RESEARCH_RESULTS_PER_QUERY`)
  - `SKIM_MAX_URLS` (not old `QUICKSEARCH_MAX_URLS`)
  - Keep `LLM_MODEL` only as fallback alias for `LLM_MODEL_ID`.

### Async, I/O, and Concurrency

- Prefer async code for network paths.
- Use `aiohttp.ClientSession()` with async context managers.
- Keep semaphore guards in orchestrators for bounded parallelism.
- Avoid long blocking synchronous work in request paths.
- Preserve workflow-specific parallelism behavior:
  - `skim`: parallel retrieval agents (`SKIM_AGENT_COUNT`).
  - `analyze`: configurable skim agents + parallel contradiction merge variants.
  - `research`: parallel sub-agents + pair-group synthesis blocks; avoid adding an extra global summarizer pass unless explicitly requested.

### Error Handling

- Raise `RuntimeError` for hard failures that should propagate to callers.
- At API boundaries, include status/context in logs and errors.
- Keep graceful fallbacks where currently used (empty lists, fallback report text).
- Preserve JSON-RPC error envelope behavior in `server.py`.

### Logging

- Use module-level loggers (`logging.getLogger(...)`).
- Keep logs short and contextual (query/tool/status).
- Never log secrets (`LLM_API_KEY`, tokens, credentials).

### API Contract Discipline

- MCP endpoint: `POST /mcp`.
- Health endpoint: `GET /health`.
- Keep request/response payload keys backward compatible unless explicitly changing API.
- Report modes should keep citation markers and a `Sources` section.
- `skim` should return per-agent `skim_reports`; avoid collapsing to one backend summary report.
- Do not leak `<think>...</think>` content in any user-visible output.

## 10) High-Value Files to Read First

- `mcp-server/server.py` - MCP routing, tool schemas, JSON-RPC wrapping.
- `mcp-server/agents/quicksearch.py` - peek/skim behavior.
- `mcp-server/agents/deepresearch.py` - analyze/research orchestration.
- `mcp-server/reporting.py` - citation and report generation logic.
- `mcp-server/config.py` and `mcp-server/config/settings.yaml` - env names/defaults and concurrency controls.
- `mcp-server/search/searxng_client.py` and `mcp-server/search/llm_client.py` - external I/O clients.
- `expressindex_cli/main.py` - user-facing CLI/TUI behavior.

## 11) Change Policy for Agents

- Make minimal, targeted edits; avoid unrelated refactors.
- Do not silently break tool names, CLI flags, or JSON keys.
- Keep backward compatibility unless a task explicitly requires breaking changes.
- Update docs (`README.md`, this file) when commands or workflow change.
- If behavior changes, prefer adding tests (once test scaffolding exists).
