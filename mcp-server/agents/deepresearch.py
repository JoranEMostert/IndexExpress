import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from agents.quicksearch import QuickSearchSubAgent, SkimAgent, SkimResult
from reporting import ReportGenerator, dedupe_sources, normalize_url
from search.llm_client import LLMClient
from search.searxng_client import SearXNGClient

logger = logging.getLogger("deepresearch")


@dataclass
class AnalyzeResult:
    query: str
    report: str
    report_a: str
    report_b: str
    sources_a: int
    sources_b: int
    agent_reports: List[Dict[str, Any]]
    agent_count: int
    merge_reports: List[Dict[str, Any]]
    merge_agent_count: int
    search_time: float


@dataclass
class DeepSearchResult:
    query: str
    sub_queries: List[str]
    cluster_reports: List[Dict[str, Any]]
    synthesis_reports: List[Dict[str, Any]]
    agent_runs: List[Dict[str, Any]]
    final_report: str
    total_sources: int
    search_time: float
    agents_used: int


class AnalyzeOrchestrator:
    def __init__(
        self,
        searxng_client: SearXNGClient,
        llm_client: LLMClient,
        agent_urls: int = 12,
        agent_count: int = 2,
        contradiction_agents: int = 0,
        llm_parallel: int = 4,
    ):
        self.searxng = searxng_client
        self.llm = llm_client
        self.agent_urls = agent_urls
        self.agent_count = max(2, agent_count)
        self.contradiction_agents = max(0, contradiction_agents)
        self.reporter = ReportGenerator(llm_client)
        self._llm_semaphore = asyncio.Semaphore(max(1, llm_parallel))

    async def analyze(self, query: str) -> AnalyzeResult:
        start = time.time()

        async def run_agent(sub_query: str, excluded: Optional[set[str]] = None) -> SkimResult:
            agent = SkimAgent(self.searxng, self.llm, max_urls=self.agent_urls)
            return await agent.search_and_report(sub_query, max_results=self.agent_urls, exclude_urls=excluded)

        sub_queries = self._build_analyze_sub_queries(query, self.agent_count)
        agent_runs: List[SkimResult] = []
        excluded_urls: set[str] = set()

        for sub_query in sub_queries:
            run = await run_agent(sub_query, excluded=excluded_urls)
            agent_runs.append(run)
            for src in run.sources:
                key = normalize_url(src.get("url", ""))
                if key:
                    excluded_urls.add(key)

        reports = [run.report for run in agent_runs]
        labels = [f"Skim Agent {idx}" for idx in range(1, len(agent_runs) + 1)]

        merge_variants = await self._build_analyze_merge_variants(query, reports, labels)
        merged = await self.reporter.compose_comprehensive_analysis_report(
            query=query,
            agent_reports=[
                {
                    "agent": idx + 1,
                    "query": sub_queries[idx],
                    "report": run.report,
                    "sources_count": run.sources_count,
                }
                for idx, run in enumerate(agent_runs)
            ],
            contradiction_reports=merge_variants,
        )

        primary_a = agent_runs[0] if agent_runs else SkimResult(
            query=query,
            report="",
            sources=[],
            skim_reports=[],
            skim_agent_runs=[],
            sources_count=0,
            search_time=0.0,
        )
        primary_b = agent_runs[1] if len(agent_runs) > 1 else primary_a

        agent_reports = [
            {
                "agent": idx + 1,
                "query": sub_queries[idx],
                "report": run.report,
                "sources_count": run.sources_count,
            }
            for idx, run in enumerate(agent_runs)
        ]

        return AnalyzeResult(
            query=query,
            report=merged,
            report_a=primary_a.report,
            report_b=primary_b.report,
            sources_a=primary_a.sources_count,
            sources_b=primary_b.sources_count,
            agent_reports=agent_reports,
            agent_count=len(agent_runs),
            merge_reports=merge_variants,
            merge_agent_count=len(merge_variants),
            search_time=time.time() - start,
        )

    async def _build_analyze_merge_variants(
        self,
        query: str,
        reports: List[str],
        labels: List[str],
    ) -> List[Dict[str, Any]]:
        target = self.contradiction_agents if self.contradiction_agents > 0 else (len(reports) + 1) // 2
        target = max(1, target)

        goals = [
            "Focus on contradictions, disputed claims, and evidence-quality gaps.",
            "Focus on practical tradeoffs, risks, and implementation caveats.",
            "Focus on strongest consensus points and clearly supported findings.",
            "Focus on uncertainty, missing data, and assumptions.",
            "Focus on decision-making recommendations backed by citations.",
            "Focus on counterarguments and where evidence conflicts.",
        ]

        async def run_variant(idx: int) -> Dict[str, Any]:
            goal = goals[idx % len(goals)]
            async with self._llm_semaphore:
                text = await self.reporter.merge_multiple_reports(
                    query=query,
                    reports=reports,
                    labels=labels,
                    merge_goal=goal,
                )
            return {"agent": idx + 1, "label": f"Merge Agent {idx + 1}", "goal": goal, "report": text}

        tasks = [asyncio.create_task(run_variant(i)) for i in range(target)]
        return await asyncio.gather(*tasks)

    @staticmethod
    def _build_analyze_sub_queries(query: str, count: int) -> List[str]:
        templates = [
            "{q}",
            "{q} alternative viewpoints",
            "{q} pros and cons",
            "{q} expert consensus",
            "{q} recent developments",
            "{q} practical implications",
            "{q} risks and limitations",
            "{q} implementation guidance",
            "{q} case studies",
            "{q} evidence quality",
            "{q} policy and regulation",
            "{q} common misconceptions",
        ]
        built: List[str] = []
        for idx in range(count):
            if idx < len(templates):
                built.append(templates[idx].format(q=query))
            else:
                built.append(f"{query} perspective {idx + 1}")
        return built


class DeepSearchOrchestrator:
    """Orchestrates sub-queries and chunked synthesis for deep research."""

    def __init__(
        self,
        searxng_client: SearXNGClient,
        llm_client: LLMClient,
        max_concurrent_agents: int = 6,
        max_results_per_agent: int = 8,
        llm_parallel: int = 4,
    ):
        self.searxng = searxng_client
        self.llm = llm_client
        self.max_concurrent = max(1, max_concurrent_agents)
        self.max_results = max(3, max_results_per_agent)
        self.reporter = ReportGenerator(llm_client)
        self._agent_semaphore = asyncio.Semaphore(self.max_concurrent)
        self._llm_semaphore = asyncio.Semaphore(max(1, llm_parallel))

    async def search(self, query: str, num_sub_queries: int = 6, depth: int = 2) -> DeepSearchResult:
        del depth
        start_time = time.time()
        logger.info("Research: starting query='%s'", query)

        target_sub_queries = max(1, min(num_sub_queries, self.max_concurrent))
        sub_queries = await self._generate_sub_queries(query, target_sub_queries)
        agent_results = await self._run_sub_agents_parallel(sub_queries)
        agent_run_metrics = [
            item.get("_meta", {})
            for item in agent_results
            if isinstance(item, dict) and item.get("_meta")
        ]
        clustered = self._cluster_results(agent_results)
        cluster_reports = await self._write_cluster_reports(query, clustered["by_query"])
        synthesis_reports = await self._write_synthesis_reports(query, cluster_reports)

        return DeepSearchResult(
            query=query,
            sub_queries=sub_queries,
            cluster_reports=cluster_reports,
            synthesis_reports=synthesis_reports,
            agent_runs=agent_run_metrics,
            final_report="",
            total_sources=len(clustered["all_sources"]),
            search_time=time.time() - start_time,
            agents_used=len(agent_results),
        )

    async def _generate_sub_queries(self, query: str, num_queries: int) -> List[str]:
        prompt = (
            f"Generate {num_queries} focused web research sub-queries for: '{query}'.\n"
            "Return only a JSON array of strings. Avoid generic words like history/current/technology unless required."
        )
        response = await self.llm.complete(prompt=prompt, temperature=0.5)
        try:
            parsed = json.loads(response.content.strip())
            if isinstance(parsed, list):
                normalized = [str(item).strip() for item in parsed if str(item).strip()]
                if normalized:
                    return self._ensure_sub_query_count(query, normalized, num_queries)
        except Exception:
            logger.warning("Research sub-query parsing failed, using fallback")

        fallback = [
            f"{query} overview",
            f"{query} key facts",
            f"{query} expert analysis",
            f"{query} recent developments",
            f"{query} conflicting viewpoints",
            f"{query} practical implications",
        ]
        return self._ensure_sub_query_count(query, fallback, num_queries)

    @staticmethod
    def _ensure_sub_query_count(query: str, candidates: List[str], target: int) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()

        for item in candidates:
            text = (item or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(text)
            if len(normalized) >= target:
                return normalized

        idx = 1
        while len(normalized) < target:
            candidate = f"{query} perspective {idx}"
            key = candidate.lower()
            if key not in seen:
                seen.add(key)
                normalized.append(candidate)
            idx += 1

        return normalized

    async def _run_sub_agents_parallel(self, sub_queries: List[str]) -> List[Dict[str, Any]]:
        active_count = 0
        active_peak = 0
        counter_lock = asyncio.Lock()

        async def run_single(q: str) -> Dict[str, Any]:
            nonlocal active_count, active_peak
            async with self._agent_semaphore:
                start = time.time()
                async with counter_lock:
                    active_count += 1
                    active_peak = max(active_peak, active_count)
                    active_now = active_count
                logger.info("Research agent start query='%s' active=%s", q, active_now)
                worker = QuickSearchSubAgent(self.searxng, max_urls=self.max_results)
                try:
                    result = await worker.search_lightweight(q, self.max_results)
                    result["_meta"] = {
                        "query": q,
                        "started_at": start,
                        "duration_s": round(time.time() - start, 2),
                        "status": "ok",
                    }
                    return result
                except Exception as exc:
                    return {
                        "query": q,
                        "results": [],
                        "count": 0,
                        "error": str(exc),
                        "_meta": {
                            "query": q,
                            "started_at": start,
                            "duration_s": round(time.time() - start, 2),
                            "status": "error",
                        },
                    }
                finally:
                    async with counter_lock:
                        active_count = max(0, active_count - 1)
                        active_now = active_count
                    logger.info("Research agent done query='%s' active=%s", q, active_now)

        tasks = [asyncio.create_task(run_single(q)) for q in sub_queries]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        results: List[Dict[str, Any]] = []
        for i, item in enumerate(completed):
            if isinstance(item, Exception):
                logger.error("Research agent failed for '%s': %s", sub_queries[i], item)
                results.append({"query": sub_queries[i], "results": [], "count": 0, "error": str(item)})
            else:
                results.append(item)
        logger.info("Research agent parallel peak=%s", active_peak)
        return results

    def _cluster_results(self, agent_results: List[Dict[str, Any]]) -> Dict[str, Any]:
        all_sources: List[Dict[str, Any]] = []
        by_query = []

        for agent_result in agent_results:
            query = agent_result.get("query", "unknown")
            deduped = dedupe_sources(agent_result.get("results", []), self.max_results)
            by_query.append({"query": query, "results": deduped, "count": len(deduped)})
            for src in deduped:
                all_sources.append(
                    {
                        "query_origin": query,
                        "url": src.get("url", ""),
                        "title": src.get("title", ""),
                        "content": src.get("content", ""),
                        "engine": src.get("engine", "unknown"),
                    }
                )

        all_sources = dedupe_sources(all_sources, limit=400)
        return {"by_query": by_query, "all_sources": all_sources}

    async def _write_cluster_reports(self, query: str, clusters: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        async def write_for_cluster(cluster: Dict[str, Any]) -> Dict[str, Any]:
            title = cluster.get("query", "cluster")
            if not cluster.get("results"):
                return {"query": title, "report": "No evidence collected for this cluster.", "sources": 0}

            async with self._llm_semaphore:
                report = await self.reporter.write_report(
                    query=f"{query} / {title}",
                    sources=cluster["results"],
                    style="focused, evidence-based",
                )
            return {"query": title, "report": report.report, "sources": len(cluster["results"])}

        tasks = [asyncio.create_task(write_for_cluster(c)) for c in clusters]
        return await asyncio.gather(*tasks)

    async def _write_synthesis_reports(self, query: str, cluster_reports: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not cluster_reports:
            return []

        groups = self._group_clusters(cluster_reports)

        async def write_group(group_index: int, group_items: List[Dict[str, Any]]) -> Dict[str, Any]:
            reports = [item.get("report", "") for item in group_items]
            labels = [item.get("query", f"cluster-{i+1}") for i, item in enumerate(group_items)]
            merged = await self.reporter.merge_multiple_reports(
                query=f"{query} synthesis block {group_index + 1}",
                reports=reports,
                labels=labels,
                merge_goal="Produce a comprehensive synthesis preserving important details from each source cluster.",
            )
            return {
                "group": group_index + 1,
                "queries": labels,
                "report": merged,
                "cluster_count": len(group_items),
            }

        tasks = [asyncio.create_task(write_group(i, group)) for i, group in enumerate(groups)]
        return await asyncio.gather(*tasks)

    @staticmethod
    def _group_clusters(cluster_reports: List[Dict[str, Any]]) -> List[List[Dict[str, Any]]]:
        """Group cluster reports by sub-agent count, targeting groups of 3.

        Examples:
        - 12 clusters -> 4 groups of 3
        - 11 clusters -> 3 groups of 3 and 1 group of 2
        - avoids singleton tail groups by rebalancing (..., 3, 1) -> (..., 2, 2)
        """
        n = len(cluster_reports)
        if n <= 3:
            return [cluster_reports]

        sizes: List[int] = []
        remaining = n
        while remaining > 0:
            if remaining == 4:
                sizes.extend([2, 2])
                remaining = 0
                break
            if remaining == 2:
                sizes.append(2)
                remaining = 0
                break
            if remaining == 1:
                # Rebalance to avoid a singleton final group.
                if sizes:
                    sizes[-1] -= 1
                    sizes.append(2)
                else:
                    sizes.append(1)
                remaining = 0
                break
            sizes.append(3)
            remaining -= 3

        groups: List[List[Dict[str, Any]]] = []
        cursor = 0
        for size in sizes:
            groups.append(cluster_reports[cursor : cursor + size])
            cursor += size
        return groups

    def get_pool_status(self) -> Dict[str, Any]:
        return {
            "max_concurrent": self.max_concurrent,
            "available": getattr(self._agent_semaphore, "_value", 0),
            "mode": "research",
        }
