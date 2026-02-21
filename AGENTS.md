# AGENTS.md

Minimal guide for coding agents in this repo.

## Project Surfaces

- MCP server: `mcp-server/`
- CLI: `expressindex_cli/`
- Core sanitize package: `expressindex_core/`
- Tests: `tests/`

## Run Commands

- Install: `pip install -e .`
- Start stack: `docker compose up -d --build`
- Run server directly: `python mcp-server/server.py`
- Run tests: `pytest -q`

## Style Rules

- Keep changes small and local.
- Prefer deleting dead code over adding abstraction.
- Keep MCP payload keys stable.
- Add tests for behavior changes.
- Do not commit secrets from `.env`.

## Main Files

- `mcp-server/server.py`
- `mcp-server/agents/quicksearch.py`
- `mcp-server/agents/deepresearch.py`
- `mcp-server/workflow_primitives.py`
- `mcp-server/search/searxng_client.py`
- `mcp-server/search/llm_client.py`
- `expressindex_cli/main.py`
