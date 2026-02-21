"""
Tool timeout policy.
"""
from typing import Final

TOOL_TIMEOUTS: Final[dict[str, int]] = {
    "peek": 30,
    "skim": 120,
    "analyze": 300,
    "research": 900,
    "fetch_url": 30,
    "search_engines": 60,
    "list_models": 10,
    "agent_status": 10,
}


def get_tool_timeout(tool_name: str, config_overrides: dict = None) -> int:
    """
    Get timeout in seconds for a tool.
    Uses config overrides if provided, otherwise falls back to defaults.
    """
    if config_overrides:
        config_key = f"tool_timeout_{tool_name}"
        if config_key in config_overrides:
            return int(config_overrides[config_key])
    return TOOL_TIMEOUTS.get(tool_name, 60)
