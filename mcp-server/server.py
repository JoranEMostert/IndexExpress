#!/usr/bin/env python3
"""
ExpressIndex MCP Server
Provides tiered research capabilities via MCP protocol.
"""

import asyncio
import json
import logging
import re
import uuid
from typing import Any, Dict

from aiohttp import web

from config import CONFIG, list_llm_models
from search.searxng_client import SearXNGClient
from search.llm_client import LLMClient
from agents.quicksearch import PeekAgent, SkimAgent, QuickSearchAgent
from agents.deepresearch import AnalyzeOrchestrator, DeepSearchOrchestrator

logging.basicConfig(
    level=getattr(logging, CONFIG.get('log_level', 'INFO')),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("expressindex-mcp")


def _strip_think_tags(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<think>[\s\S]*?(</think>|$)", "", text, flags=re.IGNORECASE)
    return cleaned.strip()


class MCPRequestHandler:
    """Handles MCP protocol requests."""
    
    def __init__(self):
        self.searxng = SearXNGClient(
            base_url=CONFIG['searxng_url'],
            timeout=CONFIG.get('searxng_timeout', 30)
        )
        
        self.llm = LLMClient(
            api_url=CONFIG['llm_api_url'],
            api_key=CONFIG.get('llm_api_key'),
            model=CONFIG.get('llm_model_id', ''),
            timeout=CONFIG.get('llm_timeout', 0)
        )

        self.peek = PeekAgent(
            searxng_client=self.searxng,
            max_urls=CONFIG.get('peek_max_urls', 5)
        )

        self.skim = SkimAgent(
            searxng_client=self.searxng,
            llm_client=self.llm,
            max_urls=CONFIG.get('skim_max_urls', 15),
            agent_count=CONFIG.get('skim_agent_count', 1),
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
        logger.info(f"MCP Server initialized - Session: {self.session_id}")
        
    async def handle_request(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Handle an incoming MCP request."""
        
        method = request.get('method')
        params = request.get('params', {})
        
        logger.info(f"Handling MCP request: {method}")
        
        if method == 'initialize':
            return await self._handle_initialize(params)
        elif method == 'tools/list':
            return await self._handle_tools_list()
        elif method == 'tools/call':
            return await self._handle_tools_call(params)
        elif method == 'resources/list':
            return await self._handle_resources_list()
        elif method == 'health':
            return await self._handle_health()
        else:
            return {
                'error': {
                    'code': -32601,
                    'message': f'Unknown method: {method}'
                }
            }
    
    async def _handle_initialize(self, params: Dict) -> Dict:
        """Handle initialize request."""
        return {
            'protocolVersion': '2024-11-05',
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
        return {
            'tools': [
                {
                    'name': 'peek',
                    'description': 'Fast URL peek (5 default) with optional fetched page content.',
                    'inputSchema': {
                        'type': 'object',
                        'properties': {
                            'query': {
                                'type': 'string',
                                'description': 'Search query'
                            },
                            'max_results': {
                                'type': 'integer',
                                'description': 'Maximum number of results (default: 5)',
                                'default': 5
                            },
                            'fetch_content': {
                                'type': 'boolean',
                                'description': 'Fetch markdown-ish page content for each URL (default: true)',
                                'default': True
                            },
                            'max_content_chars': {
                                'type': 'integer',
                                'description': 'Max fetched characters per source (default: 4000)',
                                'default': 4000
                            }
                        },
                        'required': ['query']
                    }
                },
                {
                    'name': 'skim',
                    'description': 'Parallel skim agents gather diversified sources and return per-agent reports.',
                    'inputSchema': {
                        'type': 'object',
                        'properties': {
                            'query': {
                                'type': 'string',
                                'description': 'Search query'
                            },
                            'max_results': {
                                'type': 'integer',
                                'description': 'Maximum number of sources (default: 15)',
                                'default': 15
                            }
                        },
                        'required': ['query']
                    }
                },
                {
                    'name': 'analyze',
                    'description': 'Multi-agent skim + multiple contradiction summaries + unified analyze report.',
                    'inputSchema': {
                        'type': 'object',
                        'properties': {
                            'query': {
                                'type': 'string',
                                'description': 'Analysis query'
                            }
                        },
                        'required': ['query']
                    }
                },
                {
                    'name': 'research',
                    'description': 'Deep multi-agent research with pair synthesis blocks and final unified report.',
                    'inputSchema': {
                        'type': 'object',
                        'properties': {
                            'query': {
                                'type': 'string',
                                'description': 'Research query'
                            },
                            'num_sub_queries': {
                                'type': 'integer',
                                'description': 'Number of sub-queries to generate (default: 6)',
                                'default': 6
                            }
                        },
                        'required': ['query']
                    }
                },
                {
                    'name': 'quicksearch',
                    'description': 'Deprecated alias for skim.',
                    'inputSchema': {
                        'type': 'object',
                        'properties': {
                            'query': {'type': 'string', 'description': 'Search query'},
                            'max_results': {'type': 'integer', 'default': 15}
                        },
                        'required': ['query']
                    }
                },
                {
                    'name': 'deepresearch',
                    'description': 'Deprecated alias for research.',
                    'inputSchema': {
                        'type': 'object',
                        'properties': {
                            'query': {'type': 'string', 'description': 'Research query'},
                            'num_sub_queries': {'type': 'integer', 'default': 6}
                        },
                        'required': ['query']
                    }
                },
                {
                    'name': 'search_engines',
                    'description': 'List available SearXNG search engines',
                    'inputSchema': {
                        'type': 'object',
                        'properties': {}
                    }
                },
                {
                    'name': 'agent_status',
                    'description': 'Get status of DeepSearch agent pool',
                    'inputSchema': {
                        'type': 'object',
                        'properties': {}
                    }
                },
                {
                    'name': 'list_models',
                    'description': 'List available LLM models from the configured API endpoint',
                    'inputSchema': {
                        'type': 'object',
                        'properties': {}
                    }
                }
            ]
        }
    
    async def _handle_tools_call(self, params: Dict) -> Dict:
        """Handle tool call request."""
        
        tool_name = params.get('name')
        arguments = params.get('arguments', {})
        
        logger.info(f"Calling tool: {tool_name} with args: {arguments}")
        
        try:
            if tool_name == 'quicksearch':
                tool_name = 'skim'
            if tool_name == 'deepresearch':
                tool_name = 'research'

            if tool_name == 'peek':
                result = await self.peek.search(
                    query=arguments['query'],
                    max_results=arguments.get('max_results'),
                    fetch_content=arguments.get('fetch_content', True),
                    max_content_chars=arguments.get('max_content_chars', 4000),
                )
                return {
                    'content': [
                        {
                            'type': 'text',
                            'text': json.dumps({
                                'query': result.query,
                                'sources': result.results,
                                'sources_count': result.sources_count,
                                'search_time': round(result.search_time, 2)
                            }, indent=2)
                        }
                    ]
                }

            if tool_name == 'skim':
                result = await self.quicksearch.search(
                    query=arguments['query'],
                    max_results=arguments.get('max_results')
                )
                safe_report = _strip_think_tags(result.report)
                skim_reports = [
                    {
                        **item,
                        'report': _strip_think_tags(item.get('report', '')),
                    }
                    for item in result.skim_reports
                ]
                return {
                    'content': [
                        {
                            'type': 'text',
                            'text': json.dumps({
                                'query': result.query,
                                'report': safe_report,
                                'skim_reports': skim_reports,
                                'skim_agent_runs': result.skim_agent_runs,
                                'sources': result.sources,
                                'sources_count': result.sources_count,
                                'search_time': round(result.search_time, 2)
                            }, indent=2)
                        }
                    ]
                }
                
            elif tool_name == 'analyze':
                result = await self.analyze.analyze(
                    query=arguments['query']
                )
                safe_report = _strip_think_tags(result.report)
                safe_a = _strip_think_tags(result.report_a)
                safe_b = _strip_think_tags(result.report_b)
                safe_agent_reports = [
                    {
                        **item,
                        'report': _strip_think_tags(item.get('report', '')),
                    }
                    for item in result.agent_reports
                ]
                return {
                    'content': [
                        {
                            'type': 'text',
                            'text': json.dumps({
                                'query': result.query,
                                'report': safe_report,
                                'agent_a_report': safe_a,
                                'agent_b_report': safe_b,
                                'agent_reports': safe_agent_reports,
                                'agent_count': result.agent_count,
                                'merge_reports': [
                                    {
                                        **item,
                                        'report': _strip_think_tags(item.get('report', '')),
                                    }
                                    for item in result.merge_reports
                                ],
                                'merge_agent_count': result.merge_agent_count,
                                'sources_a': result.sources_a,
                                'sources_b': result.sources_b,
                                'search_time': round(result.search_time, 2)
                            }, indent=2)
                        }
                    ]
                }

            elif tool_name == 'research':
                result = await self.deepresearch.search(
                    query=arguments['query'],
                    num_sub_queries=arguments.get('num_sub_queries', CONFIG.get('research_max_sub_queries', 6))
                )
                cluster_reports = [
                    {
                        **item,
                        'report': _strip_think_tags(item.get('report', '')),
                    }
                    for item in result.cluster_reports
                ]
                synthesis_reports = [
                    {
                        **item,
                        'report': _strip_think_tags(item.get('report', '')),
                    }
                    for item in result.synthesis_reports
                ]
                synthesis_count = len(synthesis_reports)
                return {
                    'content': [
                        {
                            'type': 'text',
                            'text': json.dumps({
                                'query': result.query,
                                'sub_queries': result.sub_queries,
                                'cluster_reports': cluster_reports,
                                'synthesis_reports': synthesis_reports,
                                'agent_runs': result.agent_runs,
                                'final_report': f"Returned {synthesis_count} reports.",
                                'total_sources': result.total_sources,
                                'agents_used': result.agents_used,
                                'search_time': round(result.search_time, 2)
                            }, indent=2)
                        }
                    ]
                }
                
            elif tool_name == 'search_engines':
                return {
                    'content': [
                        {
                            'type': 'text',
                            'text': 'Available engines: google, bing, duckduckgo, wikipedia, youtube, and 240+ more via SearXNG'
                        }
                    ]
                }
                
            elif tool_name == 'agent_status':
                status = self.deepresearch.get_pool_status()
                return {
                    'content': [
                        {
                            'type': 'text',
                            'text': json.dumps(status, indent=2)
                        }
                    ]
                }
                
            elif tool_name == 'list_models':
                models = await list_llm_models(
                    CONFIG['llm_api_url'],
                    CONFIG.get('llm_api_key')
                )
                return {
                    'content': [
                        {
                            'type': 'text',
                            'text': json.dumps({'models': models, 'api_url': CONFIG['llm_api_url']}, indent=2)
                        }
                    ]
                }
                
            else:
                return {
                    'error': {
                        'code': -32601,
                        'message': f'Unknown tool: {tool_name}'
                    }
                }
                
        except Exception as e:
            logger.error(f"Tool error: {e}", exc_info=True)
            return {
                'error': {
                    'code': -32603,
                    'message': str(e)
                }
            }
    
    async def _handle_resources_list(self) -> Dict:
        """List available resources."""
        return {
            'resources': [
                {
                    'uri': 'expressindex://health',
                    'name': 'ExpressIndex Health',
                    'description': 'Health status of ExpressIndex backend services'
                },
                {
                    'uri': 'config://current',
                    'name': 'Current Configuration',
                    'description': 'Current MCP server configuration'
                }
            ]
        }
    
    async def _handle_health(self) -> Dict:
        """Handle health check."""
        searxng_health = await self.searxng.health_check()
        llm_health = await self.llm.health_check()
        
        return {
            'status': 'healthy' if (searxng_health and llm_health) else 'degraded',
            'services': {
                'searxng': 'up' if searxng_health else 'down',
                'llm': 'up' if llm_health else 'down'
            },
            'session': self.session_id
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
        try:
            payload = await request.json()
        except Exception:
            return web.json_response(
                {
                    'jsonrpc': '2.0',
                    'error': {'code': -32700, 'message': 'Parse error'},
                    'id': None,
                },
                status=400,
            )

        result = await handler.handle_request(payload)
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

    app = web.Application()
    app.router.add_get('/health', health_endpoint)
    app.router.add_post('/mcp', mcp_endpoint)

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
