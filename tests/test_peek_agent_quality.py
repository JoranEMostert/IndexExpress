import asyncio
import json
from types import SimpleNamespace

from agents.quicksearch import PeekAgent, PeekResult
from server import MCPRequestHandler


class FakeSearXNG:
    def __init__(self, rows: list[dict[str, str]]):
        self.rows = rows

    async def search(self, query: str, max_results: int = 20, strict: bool = False):
        del query, max_results, strict
        return [SimpleNamespace(**row) for row in self.rows]

    async def enrich_sources_with_content(self, sources, max_length: int = 4000, max_parallel: int = 6):
        del max_parallel
        enriched = []
        for source in sources:
            row = dict(source)
            row["fetched_markdown"] = (row.get("content", "") + "\n\nmore context")[:max_length]
            enriched.append(row)
        return enriched


def test_peek_agent_prefers_diverse_domains_without_losing_count():
    rows = [
        {
            "url": "https://dominant.example.com/slug-facts-1",
            "title": "Slug facts 1",
            "content": "Slug facts and habitat details.",
            "engine": "duckduckgo",
        },
        {
            "url": "https://dominant.example.com/slug-facts-2",
            "title": "Slug facts 2",
            "content": "Slug facts and diet details.",
            "engine": "duckduckgo",
        },
        {
            "url": "https://dominant.example.com/slug-facts-3",
            "title": "Slug facts 3",
            "content": "Slug facts and behavior details.",
            "engine": "duckduckgo",
        },
        {
            "url": "https://www.extension.umn.edu/yard-and-garden-insects/slugs",
            "title": "Slug facts and controls",
            "content": "Slug facts from extension experts.",
            "engine": "duckduckgo",
        },
        {
            "url": "https://www.cdc.gov/parasites/resources/slug-facts.html",
            "title": "Slug facts guidance",
            "content": "Slug facts and public health references.",
            "engine": "duckduckgo",
        },
        {
            "url": "https://en.wikipedia.org/wiki/Slug",
            "title": "Slug - encyclopedia",
            "content": "Slug facts overview and taxonomy.",
            "engine": "duckduckgo",
        },
        {
            "url": "https://www.nationalgeographic.com/animals/invertebrates/facts/slug",
            "title": "Slug facts article",
            "content": "Slug facts and anatomy.",
            "engine": "duckduckgo",
        },
    ]
    agent = PeekAgent(FakeSearXNG(rows), max_urls=6)

    result = asyncio.run(agent.search(query="slug facts", max_results=6, fetch_content=False))

    assert len(result.sources) == 6
    domains = [source["domain"] for source in result.sources]
    assert len(set(domains)) >= 4
    assert max(domains.count(domain) for domain in set(domains)) <= 2

    first_keys = set(result.sources[0].keys())
    assert first_keys == {
        "source_id",
        "url",
        "title",
        "domain",
        "relevance_score",
        "domain_trust_score",
        "freshness_timestamp",
        "intent_category",
    }


def test_peek_tool_response_contract_is_links_plus_metadata_only():
    async def run_case():
        handler = MCPRequestHandler()
        try:
            async def fake_search(query: str, max_results=None, fetch_content=True, max_content_chars=4000):
                del max_results, fetch_content, max_content_chars
                return PeekResult(
                    query=query,
                    sources=[
                        {
                            "source_id": "src_01",
                            "url": "https://example.com/a",
                            "title": "Example",
                            "domain": "example.com",
                            "relevance_score": 0.9,
                            "domain_trust_score": 0.72,
                            "freshness_timestamp": "2026-01-01T00:00:00Z",
                            "intent_category": "general",
                        }
                    ],
                    meta={"compute_ms": 1, "token_estimate": 1},
                    search_time=0.001,
                )

            handler.peek.search = fake_search
            return await handler._handle_tools_call({"name": "peek", "arguments": {"query": "slug facts"}})
        finally:
            await handler.searxng.close()
            await handler.llm.close()

    result = asyncio.run(run_case())
    payload = json.loads(result["content"][0]["text"])

    assert set(payload.keys()) == {"schema_version", "query", "sources", "_meta"}
