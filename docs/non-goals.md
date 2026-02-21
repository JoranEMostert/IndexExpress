# Simplification Non-Goals

These non-goals are fixed guardrails for the simplification effort.

- Do not redesign product behavior or invent new user-facing features.
- Do not change MCP tool names, payload keys, or JSON-RPC envelope shape unless versioned migration is planned.
- Do not remove compatibility aliases (`quicksearch`, `deepresearch`) until deprecation phases explicitly allow it.
- Do not broaden external dependency footprint without a clear simplification need.
- Do not optimize for benchmark wins at the expense of readability and maintainability.
- Do not convert deterministic unit tests into network-dependent tests.
- Do not collapse docs into implementation details; keep contributor navigation docs explicit.
- Do not perform large opportunistic refactors outside the active phase scope.
