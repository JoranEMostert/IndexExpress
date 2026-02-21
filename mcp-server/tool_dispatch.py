"""
Tool dispatch registry for MCP server.
"""
from typing import Any, Dict, Callable, Awaitable


ToolFunc = Callable[..., Awaitable[Any]]


class ToolDispatch:
    """Maps tool names to their handler methods."""

    def __init__(self, handler: Any):
        self.handler = handler
        self._registry: Dict[str, str] = {}

    def register(self, tool_name: str, method_name: str) -> None:
        """Register a tool to a handler method."""
        self._registry[tool_name] = method_name

    async def dispatch(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Dispatch a tool call to the appropriate handler method."""
        method_name = self._registry.get(tool_name)
        if not method_name:
            return None

        method = getattr(self.handler, method_name, None)
        if not method:
            return None

        return await method(arguments)


def create_dispatch(handler: Any) -> ToolDispatch:
    """Create and populate a tool dispatch registry."""
    dispatch = ToolDispatch(handler)

    dispatch.register("peek", "_dispatch_peek")
    dispatch.register("skim", "_dispatch_skim")
    dispatch.register("analyze", "_dispatch_analyze")
    dispatch.register("research", "_dispatch_research")
    dispatch.register("search_engines", "_dispatch_search_engines")
    dispatch.register("agent_status", "_dispatch_agent_status")
    dispatch.register("list_models", "_dispatch_list_models")
    dispatch.register("fetch_url", "_dispatch_fetch_url")

    return dispatch
