import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

from reporting import dedupe_sources
from search.llm_client import LLMClient
from search.searxng_client import SearXNGClient
from workflow_primitives import (
    build_meta,
    cited_bullet_summary,
    classify_query_intent,
    make_claim_primitives,
    make_evidence_primitives,
    make_source_primitives,
    normalize_url,
    rank_sources,
    split_consensus_disputed,
)

logger = logging.getLogger("quicksearch")


@dataclass
class PeekResult:
    query: str
    sources: list[dict[str, Any]]
    meta: dict[str, Any]
    search_time: float


@dataclass
class SkimResult:
    query: str
    final_answer: str
    claims: list[dict[str, Any]]
    key_evidence: list[dict[str, Any]]
    sources: list[dict[str, Any]]
    uncertainties: list[str]
    meta: dict[str, Any]
    search_time: float


def _pick_peek_queries(query: str, intent: str) -> list[str]:
    if intent == "academic":
        return [query, f"{query} paper", f"{query} systematic review", f"{query} evidence"]
    if intent == "news":
        return [query, f"{query} latest", f"{query} analysis", f"{query} timeline"]
    if intent == "documentation":
        return [query, f"{query} documentation", f"{query} api reference", f"{query} examples"]
    return [query, f"{query} overview", f"{query} evidence", f"{query} expert sources"]


def _normalized_host(url: str) -> str:
    host = urlparse(url or "").netloc.lower()
    if host.startswith("www."):
        return host[4:]
    return host


def _peek_base_score(row: dict[str, Any]) -> float:
    relevance = float(row.get("_relevance", 0.0))
    trust = float(row.get("_trust", 0.0))
    quality = float(row.get("_quality", 0.0))
    freshness = float(row.get("_freshness", 0.0))
    score = float(row.get("_score", 0.0))
    return (
        (0.52 * relevance)
        + (0.24 * trust)
        + (0.12 * quality)
        + (0.08 * freshness)
        + (0.04 * score)
    )


def _rerank_for_diversity(ranked_rows: list[dict[str, Any]], target: int) -> list[dict[str, Any]]:
    if target <= 0 or not ranked_rows:
        return []

    scored_rows: list[tuple[dict[str, Any], str, float]] = []
    for row in ranked_rows:
        base_score = _peek_base_score(row)
        if base_score <= 0:
            continue
        scored_rows.append((row, _normalized_host(row.get("url", "")), base_score))

    if not scored_rows:
        return ranked_rows[:target]

    scored_rows.sort(key=lambda item: (item[2], float(item[0].get("_score", 0.0))), reverse=True)

    selected: list[dict[str, Any]] = []
    selected_keys: set[str] = set()
    host_counts: dict[str, int] = {}
    deferred: list[tuple[dict[str, Any], str, float]] = []

    for row, host, base_score in scored_rows:
        if len(selected) >= target:
            break
        key = normalize_url(row.get("url", ""))
        if key in selected_keys:
            continue
        if host and host_counts.get(host, 0) == 0:
            selected.append(row)
            selected_keys.add(key)
            host_counts[host] = 1
            continue
        deferred.append((row, host, base_score))

    if len(selected) < target:
        deferred.sort(
            key=lambda item: item[2] / (1.0 + (host_counts.get(item[1], 0) * 1.1)),
            reverse=True,
        )
        for row, host, _ in deferred:
            if len(selected) >= target:
                break
            key = normalize_url(row.get("url", ""))
            if key in selected_keys:
                continue
            if host and host_counts.get(host, 0) >= 2:
                continue
            selected.append(row)
            selected_keys.add(key)
            if host:
                host_counts[host] = host_counts.get(host, 0) + 1

    if len(selected) < target:
        for row, _, _ in scored_rows:
            if len(selected) >= target:
                break
            key = normalize_url(row.get("url", ""))
            if key in selected_keys:
                continue
            selected.append(row)
            selected_keys.add(key)

    return selected[:target]


def _source_url_map(ranked_rows: list[dict[str, Any]], source_primitives: list[dict[str, Any]]) -> dict[str, str]:
    out: dict[str, str] = {}
    for idx, row in enumerate(ranked_rows, start=1):
        if idx - 1 >= len(source_primitives):
            break
        out[row.get("url", "")] = source_primitives[idx - 1]["source_id"]
    return out


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
        started_at = time.perf_counter()
        target = max(1, min(max_results or self.max_urls, 20))
        intent = classify_query_intent(query)
        peek_queries = _pick_peek_queries(query, intent)

        logger.info("Peek v2: query=%s target=%s intent=%s", query, target, intent)

        async def run_variant(variant: str) -> list[Any]:
            return await self.searxng.search(query=variant, max_results=target * 4, strict=False)

        batches = await asyncio.gather(*[run_variant(item) for item in peek_queries])
        candidates = [
            {
                "url": result.url,
                "title": result.title,
                "content": result.content,
                "engine": result.engine,
            }
            for batch in batches
            for result in batch
        ]
        candidates = dedupe_sources(candidates, limit=max(target * 8, 24))

        if fetch_content and candidates:
            enrich_limit = min(len(candidates), max(target + 2, 6))
            enriched = await self.searxng.enrich_sources_with_content(
                candidates[:enrich_limit],
                max_length=max_content_chars,
                max_parallel=6,
            )
            candidates = enriched + candidates[enrich_limit:]

        ranking_pool_target = min(len(candidates), max(target * 4, 16))
        ranked_rows = rank_sources(query, candidates, ranking_pool_target, intent)
        selected_rows = _rerank_for_diversity(ranked_rows, target)
        source_primitives = make_source_primitives(selected_rows)

        payload = {
            "query": query,
            "sources": source_primitives,
        }
        payload["_meta"] = build_meta(started_at, payload)

        return PeekResult(
            query=query,
            sources=source_primitives,
            meta=payload["_meta"],
            search_time=time.perf_counter() - started_at,
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

    async def search_and_report(
        self,
        query: str,
        max_results: Optional[int] = None,
        exclude_urls: Optional[set[str]] = None,
    ) -> SkimResult:
        started_at = time.perf_counter()
        target = max(1, min(max_results or self.max_urls, 24))
        intent = classify_query_intent(query)
        skim_queries = self._build_skim_queries(query, self.agent_count)
        excluded = {normalize_url(url) for url in (exclude_urls or set()) if url}

        logger.info(
            "Skim v2: query=%s target=%s agents=%s intent=%s",
            query,
            target,
            self.agent_count,
            intent,
        )

        async def run_variant(variant: str) -> list[Any]:
            return await self.searxng.search(query=variant, max_results=target * 4, strict=False)

        batches = await asyncio.gather(*[run_variant(item) for item in skim_queries])
        candidates: list[dict[str, Any]] = []
        for variant_idx, batch in enumerate(batches):
            variant_query = skim_queries[variant_idx]
            for item in batch:
                key = normalize_url(item.url)
                if not key or key in excluded:
                    continue
                candidates.append(
                    {
                        "url": item.url,
                        "title": item.title,
                        "content": item.content,
                        "engine": item.engine,
                        "query_origin": variant_query,
                    }
                )

        candidates = dedupe_sources(candidates, limit=max(target * self.agent_count * 3, 30))
        if candidates:
            candidates = await self.searxng.enrich_sources_with_content(
                candidates,
                max_length=5000,
                max_parallel=6,
            )

        ranked_rows = rank_sources(query, candidates, target * self.agent_count, intent)
        source_primitives = make_source_primitives(ranked_rows)
        evidence_rows = make_evidence_primitives(query, ranked_rows)
        claims = make_claim_primitives(evidence_rows, max_claims=max(12, target))
        consensus_claims, disputed_claims = split_consensus_disputed(claims)
        ordered_claims = consensus_claims + disputed_claims
        final_answer = cited_bullet_summary(query, ordered_claims, evidence_rows, max_lines=5)

        uncertainties: list[str] = []
        coverage_floor = min(target, 5)
        if len(source_primitives) < coverage_floor:
            uncertainties.append("Coverage is lower than requested max_results target.")
        if disputed_claims:
            uncertainties.append("Conflicting evidence detected for one or more claims.")
        if not evidence_rows:
            uncertainties.append("No extractable high-relevance quotes were found in fetched content.")

        payload = {
            "query": query,
            "final_answer": final_answer,
            "claims": ordered_claims,
            "key_evidence": evidence_rows,
            "sources": source_primitives,
            "uncertainties": uncertainties,
        }
        payload["_meta"] = build_meta(started_at, payload)

        return SkimResult(
            query=query,
            final_answer=final_answer,
            claims=ordered_claims,
            key_evidence=evidence_rows,
            sources=source_primitives,
            uncertainties=uncertainties,
            meta=payload["_meta"],
            search_time=time.perf_counter() - started_at,
        )

    @staticmethod
    def _build_skim_queries(query: str, count: int) -> list[str]:
        templates = [
            "{q}",
            "{q} overview",
            "{q} risks",
            "{q} counterarguments",
            "{q} implementation",
            "{q} expert analysis",
            "{q} case studies",
            "{q} misconceptions",
        ]
        built: list[str] = []
        for idx in range(max(1, count)):
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
    """Lightweight search sub-agent used by deep/research pipelines."""

    def __init__(self, searxng_client: SearXNGClient, max_urls: int = 8):
        self.searxng = searxng_client
        self.max_urls = max_urls

    async def search_lightweight(self, query: str, max_results: int = 8) -> dict[str, Any]:
        started_at = time.perf_counter()
        target = max(1, min(max_results, self.max_urls))
        intent = classify_query_intent(query)
        batch = await self.searxng.search(query=query, max_results=target * 4, strict=False)
        candidates = dedupe_sources(
            [
                {
                    "url": item.url,
                    "title": item.title,
                    "content": item.content,
                    "engine": item.engine,
                }
                for item in batch
            ],
            limit=max(target * 3, 12),
        )
        if candidates:
            candidates = await self.searxng.enrich_sources_with_content(
                candidates,
                max_length=3500,
                max_parallel=4,
            )
        ranked_rows = rank_sources(query, candidates, target, intent)
        source_primitives = make_source_primitives(ranked_rows)
        url_to_source_id = _source_url_map(ranked_rows, source_primitives)

        results = []
        for row in ranked_rows:
            results.append(
                {
                    "url": row.get("url", ""),
                    "title": row.get("title", ""),
                    "content": (row.get("fetched_markdown") or row.get("content") or "")[:1600],
                    "engine": row.get("engine", "unknown"),
                    "source_id": url_to_source_id.get(row.get("url", ""), "src_00"),
                }
            )

        return {
            "query": query,
            "results": results,
            "sources": source_primitives,
            "count": len(results),
            "_meta": {
                "duration_s": round(time.perf_counter() - started_at, 3),
                "intent": intent,
            },
        }
