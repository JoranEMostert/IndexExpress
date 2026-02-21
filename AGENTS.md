# AGENTS.md

Guidance for coding agents working in this repository.

## Scope

- Repository: `index-express`
- Primary language: Python 3.11+
- Main runtime surfaces:
  - MCP server in `mcp-server/`
  - CLI in `expressindex_cli/`
  - Tests in `tests/`

## Quick Project Map

- `pyproject.toml`: package metadata for `expressindex` CLI
- `docker-compose.yml`: local orchestration for SearXNG + MCP server
- `mcp-server/server.py`: JSON-RPC MCP HTTP server (`/mcp`, `/health`, `/ready`, `/metrics`)
- `mcp-server/agents/quicksearch.py`: `PeekAgent`, `SkimAgent`
- `mcp-server/agents/deepresearch.py`: `AnalyzeOrchestrator`, `DeepSearchOrchestrator`
- `mcp-server/search/`: SearXNG + LLM async clients
- `mcp-server/workflow_primitives.py`: ranking/evidence/claim graph primitives
- `mcp-server/reporting.py`: report writing/merging/citation repair
- `expressindex_cli/main.py`: user-facing CLI
- `tests/`: pytest suite for sanitization and orchestration logic

## Environment Setup

Use one of the following setup flows.

### Local Python setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -r mcp-server/requirements.txt
```

### Docker setup (recommended for backend integration)

```bash
cp .env.example .env
docker compose up -d --build
curl http://localhost:8000/health
curl http://localhost:8888/healthz
```

## Build, Lint, and Test Commands

There is no dedicated Makefile or CI workflow in this repo, so use commands below directly.

### Build / run checks

- Install editable package: `pip install -e .`
- Build backend containers: `docker compose up -d --build`
- Server health check: `curl http://localhost:8000/health`
- Bytecode sanity check: `python -m compileall expressindex_cli mcp-server tests`

### Lint / format commands

The repo does not currently contain committed linter config files, but cache entries indicate common tooling.

- Ruff lint (default rules): `ruff check .`
- Ruff auto-fix: `ruff check . --fix`
- Ruff formatting: `ruff format .`
- Optional type check: `mypy expressindex_cli mcp-server`

If these tools are not installed, install ad hoc:

```bash
pip install ruff mypy
```

### Test commands (pytest)

- Run all tests: `pytest`
- Verbose full run: `pytest -vv`
- Stop on first failure: `pytest -x`
- Run a single file: `pytest tests/test_reporting_retry_flow.py`
- Run a single test: `pytest tests/test_reporting_retry_flow.py::test_write_report_retries_when_first_output_is_think_only`
- Filter by name: `pytest -k think_tag`

### Fast iteration recipes

- Lint + tests: `ruff check . && pytest -q`
- One-file loop: `ruff check tests/test_think_tag_sanitization.py && pytest tests/test_think_tag_sanitization.py -vv`

## Running the App

- Start MCP server directly:

```bash
python mcp-server/server.py
```

- Direct CLI mode examples:

```bash
expressindex peek "what is searxng"
expressindex skim "fun facts about slugs" --save-md report.md
expressindex analyze "best python web framework"
expressindex research "vacation plan to aruba" --num-sub-queries 6
```

## Code Style Guidelines

Follow existing patterns in the touched file; keep changes minimal and local.

### Imports

- Group imports as: standard library, third-party, local modules.
- Prefer one import per logical module line.
- Keep `from ... import ...` explicit (avoid wildcard imports).
- In tests, `sys.path.insert(...)` is currently used to make `mcp-server` importable; preserve this pattern unless refactoring all tests.

### Formatting

- Use 4-space indentation.
- Keep lines readable; target ~100 chars when practical.
- Prefer double quotes in new/edited code unless file-local style strongly uses single quotes.
- Keep blank lines between top-level declarations (functions/classes/dataclasses).
- Do not introduce unrelated reformatting.

### Types and data modeling

- Add type hints to new/changed function signatures.
- Use `@dataclass` for structured return payloads (existing pattern: `LLMResponse`, `SkimResult`, `DeepSearchResult`).
- Prefer concrete types (`list[str]`, `dict[str, Any]`) in modern Python code.
- Use `Optional[T]` or `T | None` consistently within a file.

### Naming conventions

- Classes: `PascalCase`
- Functions/methods/variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Internal helpers: prefix with `_` (for module-private or class-private intent)
- Keep tool and payload keys stable (`sources`, `final_answer`, `recommended_position`, `final_synthesis`, etc.) to avoid protocol breaks.

### Async and concurrency patterns

- Prefer async APIs end-to-end in server/search/reporting paths.
- Use `asyncio.Semaphore` to bound parallelism (existing pattern in research/analyze flows).
- Use `asyncio.create_task` + `asyncio.gather` for fan-out work.
- Handle per-task failures gracefully and return structured fallback payloads when possible.

### Error handling and logging

- Use module-level loggers: `logger = logging.getLogger("name")`.
- Log contextual errors; include query/operation when useful.
- For recoverable external failures, return safe defaults (`[]`, empty strings, fallback report).
- Raise `RuntimeError` when a call site must treat failure explicitly (for example, failed strict mode or merge/report generation failure path).
- Avoid leaking hidden reasoning text; preserve `<think>` tag sanitization behavior.

### MCP/CLI contract safety

- Keep JSON-RPC response shape stable: `{jsonrpc, id, result|error}`.
- Preserve tool names and aliases (`quicksearch` -> `skim`, `deepresearch` -> `research`).
- Keep report payload fields backward compatible for CLI rendering.
- When changing report schema, update CLI sanitization/rendering and tests together.

### Testing expectations

- Add/adjust pytest coverage for behavior changes.
- Favor deterministic unit tests with fake LLM clients over networked integration in default suite.
- For async code, use `asyncio.run(...)` pattern already used in tests.
- Validate both happy paths and fallback/error paths.

## Cursor/Copilot Rules Status

Checked locations:

- `.cursor/rules/`
- `.cursorrules`
- `.github/copilot-instructions.md`

Current status: no Cursor or Copilot instruction files were found in this repository.

## Agent Workflow Notes

- Before editing, read nearby code and keep style consistent with the specific module.
- Prefer small, reviewable diffs; avoid opportunistic refactors.
- Do not commit secrets from `.env`.
- If adding dependencies/tools, document commands in this file and `README.md` when relevant.
