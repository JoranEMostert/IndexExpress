from typing import Final

TOOL_ALIASES: Final[dict[str, str]] = {
    "quicksearch": "skim",
    "deepresearch": "research",
}


def resolve_tool_name(name: str) -> str:
    return TOOL_ALIASES.get(name, name)
