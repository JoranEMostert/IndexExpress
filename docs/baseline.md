# Baseline Metrics and Checks

Captured on 2026-02-21 (UTC) on branch `chore/simplification-phase0-baseline`.

## Repository Metrics (Python)

- Python files: 33
- Python LOC: 8052
- Test files (`tests/test_*.py`): 11
- Collected tests: 62

Largest Python files by LOC:

1. `mcp-server/agents/deepresearch.py` - 1390
2. `mcp-server/workflow_primitives.py` - 943
3. `expressindex_cli/main.py` - 897
4. `mcp-server/server.py` - 757
5. `mcp-server/search/searxng_client.py` - 548

## Baseline Test Runtime

Command run: `python -m pytest -q` (environment does not expose `pytest` as a direct shell command).

Result:

- 62 passed in 0.19s

## Baseline Lint State

Command run: `python -m ruff check .` (installed `ruff` first with `python -m pip install ruff`).

Result: 2 lint errors in `mcp-server/reporting.py`

- `F401` unused import: `json` at line 1
- `F841` unused local variable: `url` at line 332
