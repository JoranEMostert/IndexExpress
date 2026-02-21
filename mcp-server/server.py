#!/usr/bin/env python3
"""
ExpressIndex MCP Server
Provides tiered research capabilities via MCP protocol.
"""

import asyncio
import json
import logging
import time
import uuid
from typing import Any, Dict

from aiohttp import web

from compat import resolve_tool_name
from config import CONFIG
from contracts import SCHEMA_VERSION
from errors import JSONRPC_INVALID_PARAMS, ERROR_TYPE_VALIDATION
from logging_utils import configure_logging
from request_context import request_id_var
from search.searxng_client import SearXNGClient
from search.llm_client import LLMClient
from agents.quicksearch import PeekAgent, QuickSearchAgent
from agents.deepresearch import AnalyzeOrchestrator, DeepSearchOrchestrator
from telemetry import MetricsRegistry
from timeouts import get_tool_timeout
from utils.sanitize import strip_think_tags
from validation import validate_query_tool_args, validate_fetch_url_args
configure_logging(CONFIG.get("log_level", "INFO"), CONFIG.get("log_format", "text"))
logger = logging.getLogger("expressindex-mcp")


class MCPRequestHandler:
    """Handles MCP protocol requests."""
    
    def __init__(self):
        self.searxng = SearXNGClient(
            base_url=CONFIG['searxng_url'],
            timeout=CONFIG.get('searxng_timeout', 30)
        )
        self.searxng.configure_retries(CONFIG.get("searxng_retries", 2), CONFIG.get("http_retry_base_ms", 250))
        
        self.llm = LLMClient(
            api_url=CONFIG['llm_api_url'],
            api_key=CONFIG.get('llm_api_key'),
            model=CONFIG.get('llm_model_id', ''),
            timeout=CONFIG.get('llm_timeout', 0),
            retries=CONFIG.get("llm_retries", 2),
            retry_base_ms=CONFIG.get("http_retry_base_ms", 250),
        )

        self.peek = PeekAgent(
            searxng_client=self.searxng,
            max_urls=CONFIG.get('peek_max_urls', 5)
        )

        self.quicksearch = QuickSearchAgent(
            searxng_client=self.searxng,
            llm_client=self.llm,
            max_urls=CONFIG.get('skim_max_urls', 15),
            agent_count=CONFIG.get('skim_agent_count', 1),
        )

        self.analyze = AnalyzeOrchestrator(
            searxng_client=self.searxng,
            llm_client=self.llm,
            agent_urls=CONFIG.get('analyze_sources_per_agent', 12),
            agent_count=CONFIG.get('analyze_agent_count', 2),
            contradiction_agents=CONFIG.get('analyze_contradiction_agents', 0),
            llm_parallel=CONFIG.get('llm_max_parallel', 4)
        )

        self.deepresearch = DeepSearchOrchestrator(
            searxng_client=self.searxng,
            llm_client=self.llm,
            max_concurrent_agents=CONFIG.get('max_concurrent_agents', 3),
            max_results_per_agent=CONFIG.get('research_sources_per_sub_query', 8),
            llm_parallel=CONFIG.get('llm_max_parallel', 4)
        )
        
        self.session_id = str(uuid.uuid4())
        self.metrics = MetricsRegistry()
        self.query_max_length = int(CONFIG.get("query_max_length", 600))
        logger.info("MCP Server initialized", extra={"status": "ok", "method": "boot"})

    @staticmethod
    def _error_payload(code: int, message: str, error_type: str) -> Dict[str, Any]:
        return {
            "error": {
                "code": code,
                "message": message,
                "data": {"type": error_type, "schema_version": SCHEMA_VERSION},
            }
        }

    @staticmethod
    def _classify_exception(exc: Exception) -> tuple[int, str, str]:
        text = str(exc).lower()
        if isinstance(exc, asyncio.TimeoutError) or "timeout" in text:
            return (-32001, "Tool execution timed out", "upstream_timeout")
        if "api returned" in text or "unavailable" in text or "search error" in text:
            return (-32002, "Upstream service unavailable", "upstream_unavailable")
        return (-32603, str(exc), "internal_error")

    async def _run_with_timeout(self, tool_name: str, coro: Any) -> Any:
        timeout_s = get_tool_timeout(tool_name, CONFIG)
        if timeout_s <= 0:
            return await coro
        return await asyncio.wait_for(coro, timeout=timeout_s)

    @staticmethod
    def _text_content(payload: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "content": [{"type": "text", "text": json.dumps({"schema_version": SCHEMA_VERSION, **payload}, indent=2)}]
        }
        
    async def handle_request(self, request: Dict[str, Any], request_id: str = "-") -> Dict[str, Any]:
        """Handle an incoming MCP request."""
        started_at = time.perf_counter()
        method = request.get('method')
        params = request.get('params', {})

        logger.info(
            "Handling MCP request",
            extra={"method": str(method), "status": "started", "request_id": request_id},
        )
        status = 'ok'
        try:
            if method == 'initialize':
                return await self._handle_initialize(params)
            elif method == 'tools/list':
                return await self._handle_tools_list()
            elif method == 'tools/call':
                tool_result = await self._handle_tools_call(params, request_id=request_id)
                if 'error' in tool_result:
                    status = 'error'
                return tool_result
            elif method == 'health':
                return await self._handle_health()
            elif method == 'ready':
                return await self._handle_ready()
            elif method == 'metrics':
                return self._handle_metrics()
            else:
                status = 'error'
                return self._error_payload(-32601, f'Unknown method: {method}', 'unknown_method')
        except Exception as exc:
            status = 'error'
            code, message, error_type = self._classify_exception(exc)
            logger.error("MCP request failure: %s", exc, exc_info=True)
            return self._error_payload(code, message, error_type)
        finally:
            elapsed_s = time.perf_counter() - started_at
            self.metrics.record_request(str(method or 'unknown'), status, elapsed_s)
            logger.info(
                "MCP request completed",
                extra={
                    "method": str(method),
                    "status": status,
                    "duration_ms": round(elapsed_s * 1000, 2),
                    "request_id": request_id,
                },
            )
    
    async def _handle_initialize(self, params: Dict) -> Dict:
        """Handle initialize request."""
        del params
        return {
            'protocolVersion': '2024-11-05',
            'schemaVersion': SCHEMA_VERSION,
            'capabilities': {
                'tools': {},
                'resources': {}
            },
            'serverInfo': {
                'name': 'expressindex-mcp-server',
                'version': '1.0.0'
            }
        }
    
    async def _handle_tools_list(self) -> Dict:
        """List available tools."""
        query_prop = {"query": {"type": "string", "description": "Query"}}
        return {
            "tools": [
                {
                    "name": "peek",
                    "description": "Retrieve ranked sources.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            **query_prop,
                            "max_results": {"type": "integer", "default": 5},
                            "fetch_content": {"type": "boolean", "default": True},
                            "max_content_chars": {"type": "integer", "default": 4000},
                        },
                        "required": ["query"],
                    },
                },
                {
                    "name": "skim",
                    "description": "Generate citation-first summary.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {**query_prop, "max_results": {"type": "integer", "default": 15}},
                        "required": ["query"],
                    },
                },
                {
                    "name": "analyze",
                    "description": "Compare options with research fallback.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            **query_prop,
                            "options": {"type": "array", "items": {"type": "string"}},
                        },
                        "required": ["query"],
                    },
                },
                {
                    "name": "research",
                    "description": "Deep iterative research synthesis.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {**query_prop, "num_sub_queries": {"type": "integer", "default": 6}},
                        "required": ["query"],
                    },
                },
                {
                    "name": "quicksearch",
                    "description": "Deprecated alias for skim.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {**query_prop, "max_results": {"type": "integer", "default": 15}},
                        "required": ["query"],
                    },
                },
                {
                    "name": "deepresearch",
                    "description": "Deprecated alias for research.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {**query_prop, "num_sub_queries": {"type": "integer", "default": 6}},
                        "required": ["query"],
                    },
                },
                {"name": "agent_status", "description": "Get agent pool status", "inputSchema": {"type": "object", "properties": {}}},
                {
                    "name": "fetch_url",
                    "description": "Fetch markdown-ish URL content.",
                    "inputSchema": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "Fully-qualified URL"},
                            "max_chars": {"type": "integer", "default": 4000},
                        },
                        "required": ["url"],
                    },
                },
            ]
        }
    
    async def _handle_tools_call(self, params: Dict, request_id: str = "-") -> Dict:
        """Handle tool call request."""
        started_at = time.perf_counter()
        tool_name = params.get('name')
        arguments = params.get('arguments', {})
        metric_tool_name = str(tool_name or 'unknown')

        def record_tool(status: str, error_type: str = "") -> None:
            self.metrics.record_tool(metric_tool_name, status, time.perf_counter() - started_at)
            log_extra = {
                "tool": metric_tool_name,
                "status": status,
                "duration_ms": round((time.perf_counter() - started_at) * 1000, 2),
                "request_id": request_id,
            }
            if error_type:
                log_extra["error_type"] = error_type
            logger.info("Tool execution finished", extra=log_extra)

        if not isinstance(arguments, dict):
            record_tool('error', 'validation_error')
            return self._error_payload(JSONRPC_INVALID_PARAMS, 'Invalid params: arguments must be an object', ERROR_TYPE_VALIDATION)

        resolved_tool_name = resolve_tool_name(str(tool_name or ""))
        metric_tool_name = resolved_tool_name

        if resolved_tool_name in {'peek', 'skim', 'analyze', 'research'}:
            is_valid, error_response = validate_query_tool_args(arguments, resolved_tool_name, self.query_max_length)
            if not is_valid:
                record_tool('error', 'validation_error')
                return error_response

        if resolved_tool_name == 'fetch_url':
            is_valid, error_response = validate_fetch_url_args(arguments)
            if not is_valid:
                record_tool('error', 'validation_error')
                return error_response

        logger.info(
            "Calling tool",
            extra={
                "request_id": request_id,
                "tool": resolved_tool_name,
                "status": "started",
            },
        )
        
        try:
            if resolved_tool_name == 'peek':
                result = await self._run_with_timeout(
                    "peek",
                    self.peek.search(
                    query=arguments['query'],
                    max_results=arguments.get('max_results'),
                    fetch_content=arguments.get('fetch_content', True),
                    max_content_chars=arguments.get('max_content_chars', 4000),
                    ),
                )
                record_tool('ok')
                return self._text_content({
                    'query': result.query,
                    'sources': result.sources,
                    '_meta': result.meta,
                })

            if resolved_tool_name == 'skim':
                result = await self._run_with_timeout(
                    "skim",
                    self.quicksearch.search(
                    query=arguments['query'],
                    max_results=arguments.get('max_results')
                    ),
                )
                safe_answer = strip_think_tags(result.final_answer)
                record_tool('ok')
                return self._text_content({
                    'query': result.query,
                    'final_answer': safe_answer,
                    'claims': result.claims,
                    'key_evidence': result.key_evidence,
                    'sources': result.sources,
                    'uncertainties': result.uncertainties,
                    '_meta': result.meta,
                })
                
            elif resolved_tool_name == 'analyze':
                result = await self._run_with_timeout(
                    "analyze",
                    self.analyze.analyze(
                    query=arguments['query'],
                    options=arguments.get('options'),
                    ),
                )

                if result.route_reason:
                    routed = await self._run_with_timeout(
                        "research",
                        self.deepresearch.search(
                            query=arguments['query'],
                            num_sub_queries=CONFIG.get('research_max_sub_queries', 6),
                        ),
                    )
                    record_tool('ok')
                    return self._text_content({
                        'query': routed.query,
                        'requested_mode': 'analyze',
                        'executed_mode': 'research',
                        'route_reason': result.route_reason,
                        'analysis_type': result.analysis_type,
                        'options_compared': result.options_compared,
                        'final_synthesis': strip_think_tags(routed.final_synthesis),
                        'evidence_graph': routed.evidence_graph,
                        'coverage_report': routed.coverage_report,
                        'open_questions': routed.open_questions,
                        'trace_log': routed.trace_log,
                        'key_evidence': routed.key_evidence,
                        'sources': routed.sources,
                        '_meta': routed.meta,
                    })

                record_tool('ok')
                return self._text_content({
                    'query': result.query,
                    'query_mode': result.query_mode,
                    'requested_mode': result.requested_mode,
                    'executed_mode': result.executed_mode,
                    'route_reason': result.route_reason,
                    'analysis_type': result.analysis_type,
                    'options_compared': result.options_compared,
                    'recommended_option': result.recommended_option,
                    'confidence': result.confidence,
                    'why_not': result.why_not,
                    'consensus_claims': result.consensus_claims,
                    'disputed_claims': result.disputed_claims,
                    'decision_matrix': result.decision_matrix,
                    'recommended_position': strip_think_tags(result.recommended_position),
                    'sensitivity_factors': result.sensitivity_factors,
                    'key_evidence': result.key_evidence,
                    'sources': result.sources,
                    '_meta': result.meta,
                })

            elif resolved_tool_name == 'research':
                result = await self._run_with_timeout(
                    "research",
                    self.deepresearch.search(
                    query=arguments['query'],
                    num_sub_queries=arguments.get('num_sub_queries', CONFIG.get('research_max_sub_queries', 6))
                    ),
                )
                record_tool('ok')
                return self._text_content({
                    'query': result.query,
                    'final_synthesis': strip_think_tags(result.final_synthesis),
                    'evidence_graph': result.evidence_graph,
                    'coverage_report': result.coverage_report,
                    'open_questions': result.open_questions,
                    'trace_log': result.trace_log,
                    'key_evidence': result.key_evidence,
                    'sources': result.sources,
                    '_meta': result.meta,
                })
                
            elif resolved_tool_name == 'agent_status':
                status = self.deepresearch.get_pool_status()
                record_tool('ok')
                return self._text_content(status)

            elif resolved_tool_name == 'fetch_url':
                url = arguments.get('url', '').strip()
                max_chars = arguments.get('max_chars', 4000)
                fetched = await self.searxng.fetch_url_content(url, max_length=min(max_chars, 12000))
                record_tool('ok')
                return self._text_content({'url': url, 'fetched_markdown': fetched, 'chars': len(fetched)})
                
            else:
                record_tool('error', 'unknown_tool')
                return self._error_payload(-32601, f'Unknown tool: {resolved_tool_name}', 'unknown_tool')
                
        except Exception as e:
            code, message, error_type = self._classify_exception(e)
            logger.error("Tool error: %s", e, exc_info=True)
            record_tool('error', error_type)
            return self._error_payload(code, message, error_type)
    
    async def _handle_health(self) -> Dict:
        """Handle health check."""
        searxng_health = await self.searxng.health_check()
        llm_health = await self.llm.health_check()
        
        return {
            'schemaVersion': SCHEMA_VERSION,
            'status': 'healthy' if (searxng_health and llm_health) else 'degraded',
            'services': {
                'searxng': 'up' if searxng_health else 'down',
                'llm': 'up' if llm_health else 'down'
            },
            'session': self.session_id
        }

    async def _handle_ready(self) -> Dict[str, Any]:
        searxng_health = await self.searxng.health_check()
        llm_health = await self.llm.health_check()
        require_llm = bool(CONFIG.get("readiness_require_llm", True))

        ready = searxng_health and (llm_health or not require_llm)
        return {
            "schemaVersion": SCHEMA_VERSION,
            "status": "ready" if ready else "not_ready",
            "checks": {
                "searxng": "pass" if searxng_health else "fail",
                "llm": "pass" if llm_health else ("optional" if not require_llm else "fail"),
            },
            "require_llm": require_llm,
            "session": self.session_id,
        }

    def _handle_metrics(self) -> Dict[str, Any]:
        return {
            'schemaVersion': SCHEMA_VERSION,
            'session': self.session_id,
            'metrics': self.metrics.snapshot(),
        }


async def main():
    """Main entry point for MCP server."""
    handler = MCPRequestHandler()
    
    logger.info("ExpressIndex MCP Server starting...")
    logger.info(f"SearXNG URL: {CONFIG['searxng_url']}")
    logger.info(f"LLM API URL: {CONFIG['llm_api_url']}")
    logger.info(f"LLM model ID: {CONFIG.get('llm_model_id', '')}")
    logger.info(f"Max concurrent agents: {CONFIG.get('max_concurrent_agents', 3)}")
    
    searxng_health = await handler.searxng.health_check()
    logger.info(f"SearXNG health: {searxng_health}")
    
    llm_health = await handler.llm.health_check()
    logger.info(f"LLM health: {llm_health}")
    
    logger.info(f"Active LLM model: {handler.llm.model}")

    async def mcp_endpoint(request: web.Request) -> web.Response:
        started_at = time.perf_counter()
        try:
            payload = await request.json()
        except Exception:
            handler.metrics.record_request('parse_error', 'error', time.perf_counter() - started_at)
            return web.json_response(
                {
                    'jsonrpc': '2.0',
                    'error': {
                        'code': -32700,
                        'message': 'Parse error',
                        'data': {'type': 'parse_error', 'schema_version': SCHEMA_VERSION},
                    },
                    'id': None,
                },
                status=400,
            )

        request_id = str(payload.get('id') or uuid.uuid4())
        token = request_id_var.set(request_id)
        try:
            result = await handler.handle_request(payload, request_id=request_id)
        finally:
            request_id_var.reset(token)
        response = {'jsonrpc': '2.0', 'id': payload.get('id')}
        if 'error' in result:
            response['error'] = result['error']
        else:
            response['result'] = result
        return web.json_response(response)

    async def health_endpoint(_: web.Request) -> web.Response:
        health = await handler._handle_health()
        code = 200 if health['status'] == 'healthy' else 503
        return web.json_response(health, status=code)

    async def ready_endpoint(_: web.Request) -> web.Response:
        readiness = await handler._handle_ready()
        code = 200 if readiness["status"] == "ready" else 503
        return web.json_response(readiness, status=code)

    async def metrics_endpoint(_: web.Request) -> web.Response:
        return web.json_response(handler._handle_metrics())

    async def on_cleanup(_: web.Application) -> None:
        await handler.searxng.close()
        await handler.llm.close()

    app = web.Application()
    app.router.add_get('/health', health_endpoint)
    app.router.add_get('/ready', ready_endpoint)
    app.router.add_get('/metrics', metrics_endpoint)
    app.router.add_post('/mcp', mcp_endpoint)
    app.on_cleanup.append(on_cleanup)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, CONFIG.get('mcp_host', '0.0.0.0'), int(CONFIG.get('mcp_port', 8000)))
    await site.start()

    logger.info(
        "ExpressIndex MCP Server ready at http://%s:%s (POST /mcp)",
        CONFIG.get('mcp_host', '0.0.0.0'),
        CONFIG.get('mcp_port', 8000),
    )
    await asyncio.Event().wait()


if __name__ == '__main__':
    asyncio.run(main())
