import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from reporting import ReportGenerator, dedupe_sources
from search.llm_client import LLMClient
from search.searxng_client import SearXNGClient

logger = logging.getLogger("quicksearch")


@dataclass
class PeekResult:
    query: str
    results: List[Dict[str, str]]
    sources_count: int
    search_time: float


@dataclass
class SkimResult:
    query: str
    report: str
    sources: List[Dict[str, str]]
    sources_count: int
    search_time: float


class PeekAgent:
    def __init__(self, searxng_client: SearXNGClient, max_urls: int = 5):
        self.searxng = searxng_client
        self.max_urls = max_urls

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        fetch_content: bool = True,
        max_content_chars: int = 4000,
    ) -> PeekResult:
        start_time = time.time()
        target = max(1, min(max_results or self.max_urls, 20))
        logger.info("Peek: query=%s max_results=%s fetch_content=%s", query, target, fetch_content)

        search_results = await self.searxng.search(query=query, max_results=target * 3, strict=True)
        unique = dedupe_sources(
            [
                {
                    "url": r.url,
                    "title": r.title,
                    "content": r.content,
                    "engine": r.engine,
                }
                for r in search_results
            ],
            limit=target,
        )

        if fetch_content:
            unique = await self.searxng.enrich_sources_with_content(
                unique,
                max_length=max_content_chars,
                max_parallel=6,
            )

        return PeekResult(
            query=query,
            results=[
                {
                    "url": item["url"],
                    "title": item["title"],
                    "content": item.get("content", ""),
                    "fetched_markdown": item.get("fetched_markdown", ""),
                    "engine": item.get("engine", "unknown"),
                }
                for item in unique
            ],
            sources_count=len(unique),
            search_time=time.time() - start_time,
        )


class SkimAgent:
    def __init__(
        self,
        searxng_client: SearXNGClient,
        llm_client: LLMClient,
        max_urls: int = 15,
        agent_count: int = 1,
    ):
        self.searxng = searxng_client
        self.llm = llm_client
        self.max_urls = max_urls
        self.agent_count = max(1, agent_count)
        self.reporter = ReportGenerator(llm_client)

    async def search_and_report(
        self,
        query: str,
        max_results: Optional[int] = None,
        exclude_urls: Optional[set[str]] = None,
    ) -> SkimResult:
        start_time = time.time()
        target = max(1, min(max_results or self.max_urls, 20))
        logger.info("Skim: query=%s max_results=%s agents=%s", query, target, self.agent_count)

        skim_queries = self._build_skim_queries(query, self.agent_count)

        async def run_skim_query(q: str) -> List[Any]:
            return await self.searxng.search(query=q, max_results=target * 4, strict=True)

        search_batches = await asyncio.gather(*[run_skim_query(q) for q in skim_queries])

        sources = []
        excluded = exclude_urls or set()
        for batch in search_batches:
            for item in batch:
                row = {
                    "url": item.url,
                    "title": item.title,
                    "content": item.content,
                    "engine": item.engine,
                }
                normalized = row["url"].strip().lower().rstrip("/")
                if normalized in excluded:
                    continue
                sources.append(row)

        unique_sources = dedupe_sources(sources, limit=target)

        fetched = await self.searxng.enrich_sources_with_content(
            unique_sources,
            max_length=5000,
            max_parallel=6,
        )

        enriched_sources = []
        for source in fetched:
            merged = dict(source)
            page_text = (source.get("fetched_markdown") or "").strip()
            if page_text:
                merged["content"] = page_text
            enriched_sources.append(merged)

        report = await self.reporter.write_report(
            query=query,
            sources=enriched_sources,
            style="concise but complete",
        )

        return SkimResult(
            query=query,
            report=report.report,
            sources=report.sources,
            sources_count=len(unique_sources),
            search_time=time.time() - start_time,
        )

    @staticmethod
    def _build_skim_queries(query: str, count: int) -> List[str]:
        templates = [
            "{q}",
            "{q} overview",
            "{q} practical guide",
            "{q} evidence",
            "{q} expert sources",
            "{q} recent developments",
            "{q} case studies",
            "{q} misconceptions",
        ]
        built: List[str] = []
        for idx in range(count):
            if idx < len(templates):
                built.append(templates[idx].format(q=query))
            else:
                built.append(f"{query} perspective {idx + 1}")
        return built


class QuickSearchAgent(SkimAgent):
    """Backward-compatible alias for existing quicksearch behavior."""

    async def search(
        self,
        query: str,
        max_results: Optional[int] = None,
        fetch_content: bool = False,
    ) -> SkimResult:
        del fetch_content
        return await self.search_and_report(query=query, max_results=max_results)


class QuickSearchSubAgent:
    """Lightweight search-only sub-agent for deep/research pipelines."""

    def __init__(self, searxng_client: SearXNGClient, max_urls: int = 8):
        self.searxng = searxng_client
        self.max_urls = max_urls

    async def search_lightweight(self, query: str, max_results: int = 8) -> Dict[str, Any]:
        target = max(1, min(max_results, self.max_urls))
        search_results = await self.searxng.search(query=query, max_results=target * 3)
        unique = dedupe_sources(
            [
                {
                    "url": r.url,
                    "title": r.title,
                    "content": r.content[:350] if r.content else "",
                    "engine": r.engine,
                }
                for r in search_results
            ],
            limit=target,
        )
        fetched = await self.searxng.enrich_sources_with_content(
            unique,
            max_length=3500,
            max_parallel=4,
        )
        for source in fetched:
            page_text = (source.get("fetched_markdown") or "").strip()
            if page_text:
                source["content"] = page_text[:1200]
        return {"query": query, "results": fetched, "count": len(fetched)}
