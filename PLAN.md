# Extreme Simplification Plan

This document is a research-based roadmap to make this repository much easier to navigate, maintain, and extend.

## What I Found During Research

Current complexity snapshot (Python only):

- Total Python files: 34
- Total Python LOC: 8168
- Largest files:
  - `mcp-server/agents/deepresearch.py` (1390 LOC)
  - `mcp-server/workflow_primitives.py` (943 LOC)
  - `expressindex_cli/main.py` (897 LOC)
  - `mcp-server/server.py` (757 LOC)
  - `mcp-server/search/searxng_client.py` (548 LOC)

Structural pain points:

- Very large, multi-responsibility files dominate core behavior.
- Runtime logic, protocol contracts, heuristics, formatting, and transport are mixed together.
- Some legacy or duplicate surfaces remain (`quicksearch`/`deepresearch` aliases, legacy `mcp-server/tui.py`, duplicated sanitize logic fallback).
- There are likely dead or near-dead modules (`mcp-server/summarizer`, `mcp-server/agents/pool`, unused `self.skim` instance).
- Packaging is split across `mcp-server/`, `expressindex_cli/`, and `expressindex_core/` with mixed import styles.
- Config behavior is spread across YAML, env, docker-compose, and defaults.
- Tests focus heavily on utility behavior but less on strict architecture boundaries.

## Simplification Goals

1. Make the codebase discoverable in under 10 minutes for a new contributor.
2. Reduce largest-file complexity by splitting responsibilities into small modules.
3. Remove legacy/dead paths and make one obvious path for each feature.
4. Keep external contracts stable while internals are simplified.
5. Keep test coverage focused on critical contracts and core orchestration behavior.

## Target Shape (End State)

Desired top-level module shape (illustrative):

```text
expressindex/
  server/
    app.py
    routes.py
    handlers/
    validation.py
  agents/
    peek.py
    skim.py
    analyze.py
    research.py
  core/
    ranking.py
    evidence.py
    claims.py
    sanitize.py
    schemas.py
  clients/
    searxng.py
    llm.py
  cli/
    main.py
    render.py
    formatting.py
  config/
    settings.py
  tests/
```

## Long TODO List

### Phase 0 - Baseline and Safety Nets

- [x] Create a branch for simplification work only. - DONE (OpenCode, 2026-02-21T02:13:31Z)
- [x] Capture baseline metrics: LOC, file counts, largest files, test count. - DONE (OpenCode, 2026-02-21T02:14:12Z)
- [x] Record baseline test runtime with `pytest -q`. - DONE (OpenCode, 2026-02-21T02:14:31Z)
- [x] Record baseline lint state with `ruff check .`. - DONE (OpenCode, 2026-02-21T02:15:03Z)
- [x] Freeze current MCP response contracts in a short contract doc. - DONE (OpenCode, 2026-02-21T02:15:36Z)
- [x] Freeze current CLI user-visible behavior in snapshots (text/json/markdown). - DONE (OpenCode, 2026-02-21T02:16:44Z)
- [x] Add a `docs/architecture-current.md` map of existing runtime flows. - DONE (OpenCode, 2026-02-21T02:17:12Z)
- [x] Add a `docs/contracts.md` with tool payload keys and invariants. - DONE (OpenCode, 2026-02-21T02:17:40Z)
- [x] Add explicit non-goals for simplification to avoid accidental feature creep. - DONE (OpenCode, 2026-02-21T02:17:55Z)

### Phase 1 - Delete or Quarantine Dead/Legacy Code

- [x] Verify runtime references for `mcp-server/summarizer/__init__.py`. - DONE (1, 2026-02-21T03:13:39+01:00)
- [x] Remove `mcp-server/summarizer/` if truly unused. - DONE (1, 2026-02-21T03:13:58+01:00)
- [x] Verify runtime references for `mcp-server/agents/pool.py`. - DONE (1, 2026-02-21T03:14:09+01:00)
- [x] Remove `mcp-server/agents/pool.py` if truly unused. - DONE (1, 2026-02-21T03:14:21+01:00)
- [x] Verify whether `mcp-server/tui.py` is still needed. - DONE (1, 2026-02-21T03:14:36+01:00)
- [x] Remove `mcp-server/tui.py` once CLI parity is confirmed. - DONE (1, 2026-02-21T03:14:55+01:00)
- [x] Remove unused `self.skim` construction in `mcp-server/server.py`. - DONE (1, 2026-02-21T03:15:25+01:00)
- [x] Decide whether alias tools (`quicksearch`, `deepresearch`) should remain temporarily. - DONE (1, 2026-02-21T03:15:41+01:00)
- [x] If aliases remain, isolate aliasing in a tiny compatibility layer. - DONE (1, 2026-02-21T03:16:03+01:00)
- [x] Remove stale references in README and AGENTS docs for deleted files. - DONE (1, 2026-02-21T03:16:30+01:00)
- [x] Remove empty or placeholder dirs that cause confusion (`mcp-server/expressindex_core/` if still empty). - DONE (1, 2026-02-21T03:16:52+01:00)
- [x] Move benchmark output artifacts out of tracked tree (or document retention policy). - DONE (1, 2026-02-21T03:17:23+01:00)

### Phase 2 - Introduce Explicit Boundaries

- [x] Create a clear package root for runtime code (single Python package namespace). - IN PROGRESS
- [x] Replace cross-folder relative-style imports with package imports. - IN PROGRESS
- [ ] Introduce `schemas.py` for shared payload dataclasses/types.
- [x] Introduce `contracts.py` for MCP tool names, aliases, and schema version constants. - DONE (OpenCode)
- [x] Introduce `errors.py` for shared error codes/types. - DONE (OpenCode)
- [x] Introduce `validation.py` for all incoming request validation. - DONE (OpenCode)
- [x] Introduce `timeouts.py` for tool timeout policy. - DONE (OpenCode)
- [x] Introduce `compat.py` for temporary backward compatibility decisions. - DONE (OpenCode)
- [ ] Define strict boundaries: server layer cannot contain ranking/evidence internals.
- [ ] Define strict boundaries: agent layer cannot format CLI text.

### Phase 3 - Split `server.py` into Focused Modules

- [ ] Extract MCP method routing from `MCPRequestHandler` into `routes.py`.
- [ ] Extract `tools/list` schema definition into `tool_catalog.py`.
- [ ] Extract request validation from `_handle_tools_call` into `tool_validation.py`.
- [ ] Extract tool execution dispatch into `tool_dispatch.py`.
- [ ] Extract response envelope helpers (`_error_payload`, `_text_content`) into `responses.py`.
- [ ] Extract health/ready/metrics endpoint logic into `status_handlers.py`.
- [ ] Extract app bootstrap and aiohttp wiring into `app.py`.
- [ ] Replace long `if/elif` tool dispatch with dict-based registry.
- [ ] Centralize alias resolution in one function.
- [ ] Add unit tests for each dispatcher and validator branch.

### Phase 4 - Split `workflow_primitives.py` by Concern

- [x] Extract URL/domain utilities (`normalize_url`, trust, host category) into `core/url_utils.py`. - DONE (OpenCode)
- [x] Extract query classification into `core/query_mode.py`. - DONE (OpenCode)
- [ ] Extract scoring/ranking into `core/ranking.py`.
- [x] Extract quote cleaning and evidence extraction into `core/evidence.py`. - DONE (OpenCode)
- [x] Extract claim graph logic into `core/claims.py`. - DONE (OpenCode)
- [ ] Extract summary/meta helpers into `core/summary_meta.py`.
- [ ] Move hard-coded topic-specific heuristics (slug disambiguation) behind explicit hook or plugin.
- [ ] If topic heuristics stay, isolate into `core/topic_overrides.py`.
- [x] Keep a thin compatibility module exporting old names during migration. - DONE (core/__init__.py)
- [ ] Update tests to import new modules directly once stable.

### Phase 5 - Simplify `deepresearch.py`

- [ ] Split `AnalyzeOrchestrator` and `DeepSearchOrchestrator` into separate files.
- [ ] Move analyze option parsing helpers into `agents/analyze_options.py`.
- [ ] Move analyze scoring matrix logic into `agents/analyze_scoring.py`.
- [ ] Move research cycle planner logic into `agents/research_planner.py`.
- [ ] Move evidence graph/open-question synthesis into `agents/research_synthesis.py`.
- [ ] Replace giant static helpers with small pure functions.
- [ ] Reduce per-method length target to <= 60 lines where practical.
- [ ] Add typed intermediate objects for cycle state.
- [ ] Add deterministic tests for planner stop conditions and follow-up planning.
- [ ] Add deterministic tests for analyze recommendation confidence thresholds.

### Phase 6 - Simplify `quicksearch.py`

- [ ] Split `PeekAgent`, `SkimAgent`, and `QuickSearchSubAgent` into separate files.
- [ ] Move diversity rerank helper into `agents/rerank_diversity.py`.
- [ ] Move skim query template generation into dedicated helper module.
- [ ] Remove duplicate/legacy wrapper patterns where not needed.
- [ ] Ensure there is one clear path for `skim` and one compatibility alias path only.
- [ ] Add focused tests for each agent with fake clients.

### Phase 7 - Simplify CLI (`expressindex_cli/main.py`)

- [ ] Split transport calls into `cli/client.py`.
- [ ] Split argument parsing into `cli/args.py`.
- [ ] Split TUI command loop into `cli/tui.py`.
- [ ] Split report rendering into `cli/render_reports.py`.
- [ ] Split status/metrics rendering into `cli/render_status.py`.
- [ ] Split markdown export into `cli/export_markdown.py`.
- [ ] Reduce duplicated logic between `_tui_consumer_summary` and `_render_report_text`.
- [ ] Define one rendering contract per mode.
- [ ] Add snapshot tests for text output per mode.
- [ ] Add snapshot tests for markdown output per mode.

### Phase 8 - Consolidate Sanitization and Shared Utilities

- [x] Remove fallback duplicate implementation in `mcp-server/utils/sanitize.py`. - DONE (OpenCode)
- [x] Keep one canonical sanitize implementation in shared core package. - DONE (OpenCode)
- [x] Update server, reporting, and CLI to consume the same sanitizer import path. - DONE (OpenCode)
- [ ] Add one test module for sanitize behavior and import it from all consumers.
- [ ] Consolidate duplicated `normalize_url` implementations.
- [ ] Add one utility module for URL normalization used everywhere.

### Phase 9 - Simplify Client Layer

- [ ] Split readability extraction code in `searxng_client.py` into `search/readability.py`.
- [ ] Keep transport/retries/session logic in `search/http.py`.
- [ ] Keep SearXNG API integration in `search/searxng.py`.
- [ ] Keep URL fetch and conversion in `search/fetch_url.py`.
- [ ] Refactor `llm_client.py` to separate request building, retries, and stream parsing.
- [ ] Add contract tests for retry behavior and timeout behavior.

### Phase 10 - Simplify Configuration

- [ ] Replace ad hoc dict config with typed settings object used app-wide.
- [ ] Decide one source of truth order (env > file > defaults) and document clearly.
- [ ] Reduce env surface area to an "essential" set and "advanced" set.
- [ ] Remove or deprecate knobs with low practical value.
- [ ] Validate all config once at startup, fail fast for invalid critical values.
- [ ] Add tests for settings load and validation paths.
- [ ] Ensure docker-compose and `.env.example` match config docs exactly.

### Phase 11 - Testing Strategy Cleanup

- [ ] Reorganize tests by layer (`tests/server`, `tests/agents`, `tests/core`, `tests/cli`).
- [ ] Add fixture modules for fake LLM and fake SearXNG clients.
- [ ] Add contract tests for each MCP tool response shape.
- [ ] Add regression tests for alias behavior while aliases are supported.
- [ ] Add migration tests ensuring old import paths fail with clear messages (if removed).
- [ ] Keep fast deterministic unit tests as default.
- [ ] Mark slow/network tests explicitly.
- [ ] Add test for each deleted legacy path to prevent accidental reintroduction.

### Phase 12 - Documentation and Navigation

- [ ] Rewrite README around the simplified architecture only.
- [ ] Add `docs/architecture.md` with one diagram and module responsibilities.
- [ ] Add `docs/code-map.md` with "where to edit for X" table.
- [ ] Add `docs/deprecation.md` listing removed modules/aliases and migration paths.
- [ ] Update AGENTS.md project map after file moves.
- [ ] Add contributor quickstart with only essential commands.
- [ ] Add a troubleshooting page for common dev setup issues.

### Phase 13 - Controlled Deprecation and Compatibility Window

- [ ] Keep compatibility aliases for one planned release window.
- [ ] Emit clear warnings when deprecated aliases are used.
- [ ] Add release notes entry for each deprecation.
- [ ] Remove aliases once downstream usage is confirmed low/zero.
- [ ] Remove compatibility shims after sunset date.

### Phase 14 - Final Hardening and Cleanup

- [ ] Re-run LOC and file count metrics and compare with baseline.
- [ ] Verify largest files are below target thresholds.
- [ ] Run full lint, compile, and test suite.
- [ ] Run manual smoke checks for all four modes and status/metrics.
- [ ] Confirm CLI/TUI output quality and readability.
- [ ] Confirm docs reflect current behavior exactly.
- [ ] Tag simplification milestone and summarize wins/remaining debt.

## Success Criteria

- Largest module under ~400 LOC (stretch goal: under ~300 LOC).
- No dead/legacy runtime files in active path.
- One clear module per concern (server, agents, core primitives, clients, CLI).
- New contributor can trace `mode -> handler -> agent -> core functions` quickly.
- Test suite remains green with equal or better coverage of critical contracts.

## Practical Rollout Notes

- Keep behavior changes minimal while doing structural simplification.
- Use compatibility wrappers during migration, then remove in a later pass.
- Do the work in small, reviewable PRs grouped by phase.
- Run tests at each phase boundary before moving forward.
