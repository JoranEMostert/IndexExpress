# Baseline Metrics

Captured at `2026-02-21T03:14:55+01:00` from the current simplification branch.

## Repository

- Tracked files: `50`
- Python files: `33`
- Total Python LOC: `8052`
- Collected tests: `62`

## Baseline Validation

- Test runtime: `python -m pytest -q` -> `62 passed in 0.21s`
- Lint state: `python -m ruff check .` -> `2` violations in `mcp-server/reporting.py`
  - `F401` unused import `json` at `mcp-server/reporting.py:1`
  - `F841` unused local `url` at `mcp-server/reporting.py:332`

## Largest Python Files (by LOC)

1. `mcp-server/agents/deepresearch.py` - `1390`
2. `mcp-server/workflow_primitives.py` - `943`
3. `expressindex_cli/main.py` - `897`
4. `mcp-server/server.py` - `757`
5. `mcp-server/search/searxng_client.py` - `548`
6. `benchmark/run_benchmark.py` - `490`
7. `mcp-server/agents/quicksearch.py` - `404`
8. `mcp-server/reporting.py` - `342`
9. `mcp-server/config.py` - `283`
10. `tests/test_workflow_primitives.py` - `271`

## Commands Used

- `python - <<'PY' ...` (count tracked files, Python files, LOC, and largest files)
- `python -m pytest --collect-only -q` (collect test count)
- `python -m pytest -q` (record baseline runtime)
- `python -m ruff check .` (record baseline lint state)

## Baseline Runtime and Lint

- Test runtime command: `python -m pytest -q` (equivalent to `pytest -q` here)
- Test runtime result: `62 passed in 0.16s` (wall time `0.49s`)
- Lint command: `python -m ruff check .` (equivalent to `ruff check .` here)
- Lint result: 2 violations
  - `F401` unused import `json` at `mcp-server/reporting.py:1`
  - `F841` unused variable `url` at `mcp-server/reporting.py:332`
