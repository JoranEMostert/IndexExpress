"""
Shared error codes and types for MCP protocol.
"""
from typing import Final

JSONRPC_PARSE_ERROR: Final[int] = -32700
JSONRPC_INVALID_REQUEST: Final[int] = -32600
JSONRPC_METHOD_NOT_FOUND: Final[int] = -32601
JSONRPC_INVALID_PARAMS: Final[int] = -32602
JSONRPC_INTERNAL_ERROR: final[int] = -32603

ERROR_TYPE_VALIDATION: Final[str] = "validation_error"
ERROR_TYPE_TIMEOUT: Final[str] = "timeout_error"
ERROR_TYPE_INTERNAL: Final[str] = "internal_error"
ERROR_TYPE_TOOL_NOT_FOUND: Final[str] = "tool_not_found"
ERROR_TYPE_EXTERNAL: Final[str] = "external_service_error"
