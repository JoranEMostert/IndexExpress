"""
MCP contracts: tool names, aliases, and schema version constants.
"""
from typing import Final

SCHEMA_VERSION: Final[str] = "v2.0"

TOOL_ALIASES: Final[dict[str, str]] = {
    "quicksearch": "skim",
    "deepresearch": "research",
}

PRIMARY_TOOLS: Final[set[str]] = {
    "peek",
    "skim",
    "analyze",
    "research",
    "search_engines",
    "agent_status",
    "list_models",
    "fetch_url",
}

QUERY_TOOLS: Final[set[str]] = {"peek", "skim", "analyze", "research"}

ALL_TOOLS: Final[set[str]] = PRIMARY_TOOLS | set(TOOL_ALIASES.keys())
