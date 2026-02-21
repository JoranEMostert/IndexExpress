"""
Request validation for MCP tool calls.
"""
from typing import Any, Dict, Optional, Tuple

from errors import (
    JSONRPC_INVALID_PARAMS,
    ERROR_TYPE_VALIDATION,
)


def validate_query_tool_args(
    arguments: Dict[str, Any],
    tool_name: str,
    query_max_length: int,
) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """
    Validate arguments for query tools (peek, skim, analyze, research).
    Returns (is_valid, error_response).
    """
    if not isinstance(arguments, dict):
        return False, _validation_error("arguments must be an object")

    query = arguments.get("query")
    if not isinstance(query, str) or not query.strip():
        return False, _validation_error("query must be a non-empty string")

    if len(query.strip()) > query_max_length:
        return False, _validation_error(f"query length exceeds max {query_max_length}")

    max_results = arguments.get("max_results")
    if max_results is not None:
        if not isinstance(max_results, int) or max_results <= 0:
            return False, _validation_error("max_results must be a positive integer")

    if tool_name == "research":
        sub_q = arguments.get("num_sub_queries")
        if sub_q is not None:
            if not isinstance(sub_q, int) or sub_q <= 0:
                return False, _validation_error("num_sub_queries must be a positive integer")

    if tool_name == "analyze":
        options = arguments.get("options")
        if options is not None:
            if not isinstance(options, list):
                return False, _validation_error("options must be an array of strings")
            if len(options) > 8:
                return False, _validation_error("options must contain at most 8 items")
            for option in options:
                if not isinstance(option, str) or not option.strip():
                    return False, _validation_error("each option must be a non-empty string")

    return True, None


def validate_fetch_url_args(arguments: Dict[str, Any]) -> Tuple[bool, Optional[Dict[str, Any]]]:
    """Validate arguments for fetch_url tool."""
    if not isinstance(arguments, dict):
        return False, _validation_error("arguments must be an object")

    url = arguments.get("url")
    if not isinstance(url, str) or not url.startswith(("http://", "https://")):
        return False, _validation_error("url must start with http:// or https://")

    max_chars = arguments.get("max_chars")
    if max_chars is not None:
        if not isinstance(max_chars, int) or max_chars <= 0:
            return False, _validation_error("max_chars must be a positive integer")

    return True, None


def _validation_error(message: str) -> Dict[str, Any]:
    return {
        "error": {
            "code": JSONRPC_INVALID_PARAMS,
            "message": f"Invalid params: {message}",
            "data": {"type": ERROR_TYPE_VALIDATION},
        }
    }
