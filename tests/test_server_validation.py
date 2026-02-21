import asyncio

from server import MCPRequestHandler


async def _call_and_close(params):
    handler = MCPRequestHandler()
    try:
        return await handler._handle_tools_call(params)
    finally:
        await handler.searxng.close()
        await handler.llm.close()


def test_tools_call_rejects_non_object_arguments():
    result = asyncio.run(_call_and_close({"name": "peek", "arguments": "bad"}))
    assert result["error"]["code"] == -32602
    assert result["error"]["data"]["type"] == "validation_error"


def test_tools_call_rejects_empty_query():
    result = asyncio.run(_call_and_close({"name": "skim", "arguments": {"query": ""}}))
    assert result["error"]["code"] == -32602
    assert result["error"]["data"]["type"] == "validation_error"


def test_fetch_url_rejects_non_http_url():
    result = asyncio.run(_call_and_close({"name": "fetch_url", "arguments": {"url": "ftp://example.com"}}))
    assert result["error"]["code"] == -32602
    assert result["error"]["data"]["type"] == "validation_error"


def test_analyze_rejects_invalid_options_entries():
    result = asyncio.run(
        _call_and_close({"name": "analyze", "arguments": {"query": "python vs node", "options": ["python", ""]}})
    )
    assert result["error"]["code"] == -32602
    assert result["error"]["data"]["type"] == "validation_error"
