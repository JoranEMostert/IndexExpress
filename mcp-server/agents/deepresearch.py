import asyncio
import json
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Optional
from urllib.parse import urlparse

from agents.quicksearch import QuickSearchSubAgent
from reporting import dedupe_sources
from search.llm_client import LLMClient
from search.searxng_client import SearXNGClient
from workflow_primitives import (
    build_meta,
    cited_bullet_summary,
    classify_query_intent,
    classify_query_mode,
    make_claim_primitives,
    make_edges_from_claims,
    make_evidence_primitives,
    make_source_primitives,
    normalize_url,
    rank_sources,
    split_consensus_disputed,
)

logger = logging.getLogger("deepresearch")


@dataclass
class AnalyzeResult:
    query: str
    query_mode: str
    requested_mode: str
    executed_mode: str
    route_reason: str
    analysis_type: str
    options_compared: list[str]
    recommended_option: str
    confidence: str
    why_not: list[str]
    consensus_claims: list[dict[str, Any]]
    disputed_claims: list[dict[str, Any]]
    decision_matrix: list[dict[str, Any]]
    recommended_position: str
    sensitivity_factors: list[str]
    sources: list[dict[str, Any]]
    key_evidence: list[dict[str, Any]]
    meta: dict[str, Any]
    search_time: float


@dataclass
class DeepSearchResult:
    query: str
    final_synthesis: str
    evidence_graph: dict[str, Any]
    coverage_report: dict[str, Any]
    open_questions: list[str]
    trace_log: list[str]
    sources: list[dict[str, Any]]
    key_evidence: list[dict[str, Any]]
    meta: dict[str, Any]
    search_time: float


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
        self.agent_urls = max(4, agent_urls)
        self.agent_count = max(2, agent_count)
        self.contradiction_agents = max(1, contradiction_agents or 2)
        self._llm_semaphore = asyncio.Semaphore(max(1, llm_parallel))

    async def analyze(self, query: str, options: Optional[list[str]] = None) -> AnalyzeResult:
        started_at = time.perf_counter()
        intent = classify_query_intent(query)
        query_mode = classify_query_mode(query)
        options_compared = self._resolve_compare_options(query, options)

        if len(options_compared) < 2:
            route_reason = "non_comparative_query"
            payload = {
                "query": query,
                "query_mode": query_mode,
                "requested_mode": "analyze",
                "executed_mode": "analyze",
                "route_reason": route_reason,
                "analysis_type": "mode_mismatch",
                "options_compared": options_compared,
                "recommended_option": "",
                "confidence": "low",
                "why_not": [
                    "Analyze requires at least two concrete options to compare.",
                    "Route to research for broad evidence exploration.",
                ],
                "consensus_claims": [],
                "disputed_claims": [],
                "decision_matrix": [],
                "recommended_position": "",
                "sensitivity_factors": [
                    "Query did not include clear comparison candidates for decision analysis."
                ],
                "sources": [],
                "key_evidence": [],
            }
            payload["_meta"] = build_meta(started_at, payload)
            return AnalyzeResult(
                query=query,
                query_mode=query_mode,
                requested_mode="analyze",
                executed_mode="analyze",
                route_reason=route_reason,
                analysis_type="mode_mismatch",
                options_compared=options_compared,
                recommended_option="",
                confidence="low",
                why_not=payload["why_not"],
                consensus_claims=[],
                disputed_claims=[],
                decision_matrix=[],
                recommended_position="",
                sensitivity_factors=payload["sensitivity_factors"],
                sources=[],
                key_evidence=[],
                meta=payload["_meta"],
                search_time=time.perf_counter() - started_at,
            )

        sub_queries = self._build_analyze_sub_queries(query, self.agent_count, query_mode=query_mode)
        logger.info("Analyze v2: query=%s sub_queries=%s", query, len(sub_queries))

        async def run_variant(sub_query: str) -> list[Any]:
            return await self.searxng.search(
                query=sub_query,
                max_results=self.agent_urls * 3,
                strict=False,
            )

        batches = await asyncio.gather(*[run_variant(sub_query) for sub_query in sub_queries])
        candidates = [
            {
                "url": row.url,
                "title": row.title,
                "content": row.content,
                "engine": row.engine,
            }
            for batch in batches
            for row in batch
        ]
        candidates = dedupe_sources(candidates, limit=max(self.agent_urls * self.agent_count * 3, 30))
        if candidates:
            candidates = await self.searxng.enrich_sources_with_content(
                candidates,
                max_length=5000,
                max_parallel=6,
            )

        ranked_rows = rank_sources(query, candidates, self.agent_urls * self.agent_count, intent)
        source_primitives = make_source_primitives(ranked_rows)
        evidence_rows = make_evidence_primitives(query, ranked_rows)
        max_claims = max(16, self.agent_count * 10)
        if query_mode == "fact":
            max_claims = min(max_claims, 24)
        claims = make_claim_primitives(evidence_rows, max_claims=max_claims)
        consensus_claims, disputed_claims = split_consensus_disputed(claims)

        decision_matrix = self._build_decision_matrix(
            consensus_claims,
            disputed_claims,
            source_primitives,
            options=options_compared,
            evidence_rows=evidence_rows,
        )
        recommended_position = self._recommended_position(decision_matrix)
        recommended_option, confidence, why_not = self._recommendation_details(decision_matrix)
        sensitivity_factors = self._sensitivity_factors(
            consensus_claims,
            disputed_claims,
            source_primitives,
            query_mode="comparative",
        )

        payload = {
            "query": query,
            "query_mode": "comparative",
            "requested_mode": "analyze",
            "executed_mode": "analyze",
            "route_reason": "",
            "analysis_type": "comparative",
            "options_compared": options_compared,
            "recommended_option": recommended_option,
            "confidence": confidence,
            "why_not": why_not,
            "consensus_claims": consensus_claims,
            "disputed_claims": disputed_claims,
            "decision_matrix": decision_matrix,
            "recommended_position": recommended_position,
            "sensitivity_factors": sensitivity_factors,
            "sources": source_primitives,
            "key_evidence": evidence_rows,
        }
        payload["_meta"] = build_meta(started_at, payload)

        return AnalyzeResult(
            query=query,
            query_mode="comparative",
            requested_mode="analyze",
            executed_mode="analyze",
            route_reason="",
            analysis_type="comparative",
            options_compared=options_compared,
            recommended_option=recommended_option,
            confidence=confidence,
            why_not=why_not,
            consensus_claims=consensus_claims,
            disputed_claims=disputed_claims,
            decision_matrix=decision_matrix,
            recommended_position=recommended_position,
            sensitivity_factors=sensitivity_factors,
            sources=source_primitives,
            key_evidence=evidence_rows,
            meta=payload["_meta"],
            search_time=time.perf_counter() - started_at,
        )

    @staticmethod
    def _resolve_compare_options(query: str, options: Optional[list[str]]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()

        for row in options or []:
            value = str(row or "").strip()
            if not value:
                continue
            key = value.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(value)

        if len(normalized) >= 2:
            return normalized[:5]

        inferred = AnalyzeOrchestrator._extract_options_from_query(query)
        for option in inferred:
            key = option.lower()
            if key in seen:
                continue
            seen.add(key)
            normalized.append(option)
            if len(normalized) >= 5:
                break

        return normalized

    @staticmethod
    def _extract_options_from_query(query: str) -> list[str]:
        raw = (query or "").strip().rstrip("?")
        if not raw:
            return []

        if re.search(r"\s+vs\s+|\s+versus\s+", raw, flags=re.IGNORECASE):
            parts = re.split(r"\s+(?:vs|versus)\s+", raw, flags=re.IGNORECASE)
            cleaned = [AnalyzeOrchestrator._clean_option_label(item) for item in parts]
            cleaned = [item for item in cleaned if item]
            if len(cleaned) >= 2:
                return cleaned[:5]

        compare_match = re.search(r"compare\s+(.+?)\s+(?:and|vs|versus)\s+(.+)$", raw, flags=re.IGNORECASE)
        if compare_match:
            left = AnalyzeOrchestrator._clean_option_label(compare_match.group(1))
            right = AnalyzeOrchestrator._clean_option_label(compare_match.group(2))
            out = [item for item in [left, right] if item]
            if len(out) >= 2:
                return out

        between_match = re.search(r"between\s+(.+?)\s+and\s+(.+)$", raw, flags=re.IGNORECASE)
        if between_match:
            left = AnalyzeOrchestrator._clean_option_label(between_match.group(1))
            right = AnalyzeOrchestrator._clean_option_label(between_match.group(2))
            out = [item for item in [left, right] if item]
            if len(out) >= 2:
                return out

        return []

    @staticmethod
    def _clean_option_label(text: str) -> str:
        value = (text or "").strip()
        value = re.sub(r"^(compare|between|best|should i choose)\s+", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\b(for|in|on)\s+.+$", "", value, flags=re.IGNORECASE)
        return value.strip(" ,.-")

    @staticmethod
    def _option_tokens(option_name: str) -> list[str]:
        stopwords = {
            "the",
            "and",
            "for",
            "with",
            "from",
            "into",
            "than",
            "versus",
            "compare",
            "between",
            "best",
            "option",
        }
        tokens = re.findall(r"[a-z0-9]{3,}", (option_name or "").lower())
        return [token for token in tokens if token not in stopwords][:6]

    @staticmethod
    def _text_mentions_option(text: str, option_name: str, option_tokens: list[str]) -> bool:
        lowered = (text or "").lower()
        if not lowered:
            return False
        if option_name.lower() in lowered:
            return True
        if not option_tokens:
            return False
        token_hits = sum(1 for token in option_tokens if token in lowered)
        min_hits = 1 if len(option_tokens) <= 2 else 2
        return token_hits >= min_hits

    @staticmethod
    def _recommendation_details(decision_matrix: list[dict[str, Any]]) -> tuple[str, str, list[str]]:
        if not decision_matrix:
            return "", "low", []
        first_dimension = decision_matrix[0]
        options = first_dimension.get("options", [])
        if not options:
            return "", "low", []
        ranked = sorted(options, key=lambda row: row.get("score", 0), reverse=True)
        best = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None
        margin = int(best.get("score", 0)) - int(runner_up.get("score", 0)) if runner_up else 0
        confidence = "high" if int(best.get("score", 0)) >= 75 and margin >= 12 else "moderate"
        if int(best.get("score", 0)) < 60:
            confidence = "low"

        why_not: list[str] = []
        for alternative in ranked[1:3]:
            rationale = (alternative.get("rationale", "") or "").strip().rstrip(".")
            if rationale:
                why_not.append(f"{alternative.get('option_name', 'Alternative')}: {rationale}.")

        return str(best.get("option_name", "")), confidence, why_not

    @staticmethod
    def _factual_position(
        query: str,
        consensus_claims: list[dict[str, Any]],
        disputed_claims: list[dict[str, Any]],
        evidence_rows: list[dict[str, Any]],
    ) -> str:
        ranked = sorted(
            consensus_claims,
            key=lambda claim: len(claim.get("support_evidence_ids", [])),
            reverse=True,
        )
        if not ranked and disputed_claims:
            ranked = sorted(
                disputed_claims,
                key=lambda claim: len(claim.get("support_evidence_ids", [])),
                reverse=True,
            )
        if not ranked:
            return "Insufficient evidence to extract stable factual findings."

        facts = cited_bullet_summary(query, ranked, evidence_rows, max_lines=6)
        if disputed_claims:
            return "Key facts from retrieved sources (some evidence remains disputed):\n" + facts
        return "Key facts from retrieved sources:\n" + facts

    @staticmethod
    def _build_decision_matrix(
        consensus_claims: list[dict[str, Any]],
        disputed_claims: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        options: Optional[list[str]] = None,
        evidence_rows: Optional[list[dict[str, Any]]] = None,
    ) -> list[dict[str, Any]]:
        option_names = [item for item in (options or []) if str(item).strip()]
        if len(option_names) >= 2 and isinstance(evidence_rows, list):
            source_map = {
                row.get("source_id", ""): float(row.get("domain_trust_score", 0.0))
                for row in sources
                if isinstance(row, dict)
            }

            evidence_strength_rows: list[dict[str, Any]] = []
            trust_rows: list[dict[str, Any]] = []
            risk_rows: list[dict[str, Any]] = []

            for option_name in option_names:
                tokens = AnalyzeOrchestrator._option_tokens(option_name)

                matched_evidence = [
                    row
                    for row in evidence_rows
                    if AnalyzeOrchestrator._text_mentions_option(
                        row.get("exact_quote", ""), option_name, tokens
                    )
                ]
                source_ids = {
                    row.get("source_id", "")
                    for row in matched_evidence
                    if row.get("source_id", "")
                }
                trust_values = [source_map.get(source_id, 0.6) for source_id in source_ids]
                avg_trust = (sum(trust_values) / len(trust_values)) if trust_values else 0.6

                related_consensus_ids = [
                    row.get("claim_id", "")
                    for row in consensus_claims
                    if AnalyzeOrchestrator._text_mentions_option(
                        row.get("statement", ""), option_name, tokens
                    )
                ]
                related_disputed_ids = [
                    row.get("claim_id", "")
                    for row in disputed_claims
                    if AnalyzeOrchestrator._text_mentions_option(
                        row.get("statement", ""), option_name, tokens
                    )
                ]

                coverage_score = int(
                    max(5, min(95, 20 + (len(matched_evidence) * 6) + (len(source_ids) * 7)))
                )
                trust_score = int(max(5, min(95, round(15 + (avg_trust * 75)))))
                risk_score = int(
                    max(
                        5,
                        min(
                            95,
                            round(86 - (len(related_disputed_ids) * 12) - (max(0, 2 - len(source_ids)) * 6)),
                        ),
                    )
                )

                evidence_strength_rows.append(
                    {
                        "option_name": option_name,
                        "score": coverage_score,
                        "rationale": (
                            f"Matched {len(matched_evidence)} evidence items from {len(source_ids)} sources."
                        ),
                        "relevant_claim_ids": related_consensus_ids[:4] + related_disputed_ids[:2],
                    }
                )
                trust_rows.append(
                    {
                        "option_name": option_name,
                        "score": trust_score,
                        "rationale": f"Average source trust for matched evidence is {avg_trust:.2f}.",
                        "relevant_claim_ids": related_consensus_ids[:4],
                    }
                )
                risk_rows.append(
                    {
                        "option_name": option_name,
                        "score": risk_score,
                        "rationale": (
                            f"Detected {len(related_disputed_ids)} disputed claim links affecting this option."
                        ),
                        "relevant_claim_ids": related_disputed_ids[:5],
                    }
                )

            return [
                {"dimension": "Evidence Coverage", "options": evidence_strength_rows},
                {"dimension": "Source Trust", "options": trust_rows},
                {"dimension": "Contradiction Risk", "options": risk_rows},
            ]

        consensus_n = len(consensus_claims)
        disputed_n = len(disputed_claims)
        total_claims = max(1, consensus_n + disputed_n)
        consensus_ratio = consensus_n / total_claims
        dispute_ratio = disputed_n / total_claims

        support_counts = [
            len(claim.get("support_evidence_ids", [])) for claim in (consensus_claims + disputed_claims)
        ]
        avg_support = (sum(support_counts) / len(support_counts)) if support_counts else 0.0
        support_depth = min(1.0, avg_support / 3.0)

        trust_scores = [float(src.get("domain_trust_score", 0.0)) for src in sources]
        avg_trust = (sum(trust_scores) / len(trust_scores)) if trust_scores else 0.6
        low_trust_share = (
            len([score for score in trust_scores if score < 0.65]) / len(trust_scores) if trust_scores else 0.0
        )

        hosts = [urlparse(src.get("url", "")).netloc.lower() for src in sources if src.get("url")]
        unique_hosts = len(set(host for host in hosts if host))
        source_diversity = (unique_hosts / len(hosts)) if hosts else 0.6

        def bounded(value: float) -> int:
            return int(max(5, min(95, round(value))))

        proceed_score = bounded(
            46
            + (consensus_ratio * 30)
            + (support_depth * 14)
            + (avg_trust * 12)
            - (dispute_ratio * 32)
            - (low_trust_share * 16)
            - ((1.0 - source_diversity) * 10)
        )
        guardrails_score = bounded(
            proceed_score - 10 + (dispute_ratio * 34) + (low_trust_share * 14) + ((1.0 - support_depth) * 6)
        )
        defer_score = bounded(
            (100 - proceed_score) + (dispute_ratio * 25) + ((1.0 - support_depth) * 10)
        )

        risk_index = (
            28
            + (dispute_ratio * 46)
            + (low_trust_share * 26)
            + ((1.0 - source_diversity) * 12)
            - (consensus_ratio * 10)
        )
        low_risk_score = bounded(100 - risk_index)
        medium_risk_score = bounded(100 - (abs(50 - risk_index) * 1.7))
        high_risk_score = bounded(risk_index)

        ready_score = bounded(
            38
            + (consensus_ratio * 30)
            + (support_depth * 16)
            + (source_diversity * 10)
            - (dispute_ratio * 30)
            - (low_trust_share * 10)
        )
        pilot_score = bounded(56 + (dispute_ratio * 16) + ((1.0 - support_depth) * 8) + (low_trust_share * 6))
        not_ready_score = bounded((100 - ready_score) + (dispute_ratio * 22))

        return [
            {
                "dimension": "Evidence Strength",
                "options": [
                    {
                        "option_name": "Proceed",
                        "score": proceed_score,
                        "rationale": (
                            f"{consensus_n} corroborated claims across {len(sources)} sources "
                            f"(avg trust {avg_trust:.2f}) support moving forward."
                        ),
                        "relevant_claim_ids": [claim["claim_id"] for claim in consensus_claims[:6]],
                    },
                    {
                        "option_name": "Proceed with Guardrails",
                        "score": guardrails_score,
                        "rationale": (
                            f"{disputed_n} disputed claims ({dispute_ratio:.0%} of extracted claims) "
                            "justify mitigation steps and staged rollout."
                        ),
                        "relevant_claim_ids": [claim["claim_id"] for claim in disputed_claims[:4]]
                        + [claim["claim_id"] for claim in consensus_claims[:2]],
                    },
                    {
                        "option_name": "Defer",
                        "score": defer_score,
                        "rationale": (
                            "Defer if unresolved contradictions or shallow claim support would make a "
                            "wrong decision costly."
                        ),
                        "relevant_claim_ids": [claim["claim_id"] for claim in disputed_claims[:4]],
                    },
                ],
            },
            {
                "dimension": "Risk Exposure",
                "options": [
                    {
                        "option_name": "Low",
                        "score": low_risk_score,
                        "rationale": "Contradiction and source-risk signals are currently limited.",
                        "relevant_claim_ids": [claim["claim_id"] for claim in consensus_claims[:5]],
                    },
                    {
                        "option_name": "Medium",
                        "score": medium_risk_score,
                        "rationale": "Signals indicate manageable but non-trivial downside if assumptions fail.",
                        "relevant_claim_ids": [claim["claim_id"] for claim in disputed_claims[:5]],
                    },
                    {
                        "option_name": "High",
                        "score": high_risk_score,
                        "rationale": "Conflicts and lower-trust evidence could materially alter outcomes.",
                        "relevant_claim_ids": [claim["claim_id"] for claim in disputed_claims[:6]],
                    },
                ],
            },
            {
                "dimension": "Implementation Readiness",
                "options": [
                    {
                        "option_name": "Ready",
                        "score": ready_score,
                        "rationale": "Consensus depth and source spread are sufficient for full execution.",
                        "relevant_claim_ids": [claim["claim_id"] for claim in consensus_claims[:6]],
                    },
                    {
                        "option_name": "Pilot",
                        "score": pilot_score,
                        "rationale": "Best fit when directional evidence exists but uncertainty still matters.",
                        "relevant_claim_ids": [claim["claim_id"] for claim in consensus_claims[:3]]
                        + [claim["claim_id"] for claim in disputed_claims[:3]],
                    },
                    {
                        "option_name": "Not Ready",
                        "score": not_ready_score,
                        "rationale": "Hold if conflict resolution and corroboration are still too thin.",
                        "relevant_claim_ids": [claim["claim_id"] for claim in disputed_claims[:6]],
                    },
                ],
            },
        ]

    @staticmethod
    def _recommended_position(decision_matrix: list[dict[str, Any]]) -> str:
        if not decision_matrix:
            return "Insufficient evidence to form a stable recommendation."
        first_dimension = decision_matrix[0]
        options = first_dimension.get("options", [])
        if not options:
            return "Insufficient evidence to form a stable recommendation."
        ranked = sorted(options, key=lambda row: row.get("score", 0), reverse=True)
        best = ranked[0]
        runner_up = ranked[1] if len(ranked) > 1 else None
        margin = int(best.get("score", 0)) - int(runner_up.get("score", 0)) if runner_up else 0
        confidence = "high" if int(best.get("score", 0)) >= 75 and margin >= 12 else "moderate"
        if int(best.get("score", 0)) < 60:
            confidence = "low"
        rationale = (best.get("rationale", "") or "").strip().rstrip(".")
        return (
            f"Recommended position: {best.get('option_name', 'Proceed with Guardrails')} "
            f"(score={best.get('score', 0)}/100, confidence={confidence}). {rationale}."
        )

    @staticmethod
    def _sensitivity_factors(
        consensus_claims: list[dict[str, Any]],
        disputed_claims: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        query_mode: str = "general",
    ) -> list[str]:
        factors: list[str] = []
        total_claims = max(1, len(consensus_claims) + len(disputed_claims))
        disputed_n = len(disputed_claims)
        if disputed_n:
            label = "findings" if query_mode == "fact" else "recommendation"
            factors.append(
                f"{disputed_n}/{total_claims} extracted claims are disputed; {label} shifts if key conflicts resolve differently."
            )
            claim = disputed_claims[0]
            support = len(claim.get("support_evidence_ids", []))
            refute = len(claim.get("refute_evidence_ids", []))
            factors.append(
                f"Most sensitive claim: {claim.get('statement', '')[:140]} (support={support}, refute_links={refute})."
            )

        trust_scores = [float(src.get("domain_trust_score", 0.0)) for src in sources]
        low_trust_count = len([score for score in trust_scores if score < 0.65])
        if trust_scores and low_trust_count:
            factors.append(
                f"{low_trust_count}/{len(trust_scores)} sources have trust < 0.65; source vetting materially affects confidence."
            )

        hosts = [urlparse(src.get("url", "")).netloc.lower() for src in sources if src.get("url")]
        if hosts:
            host_counts: dict[str, int] = {}
            for host in hosts:
                host_counts[host] = host_counts.get(host, 0) + 1
            top_host, top_count = max(host_counts.items(), key=lambda item: item[1])
            concentration = top_count / len(hosts)
            if concentration >= 0.45 and len(hosts) >= 4:
                factors.append(
                    f"{top_count}/{len(hosts)} sources come from {top_host}; broader domain diversity could change conclusions."
                )

        if consensus_claims:
            thin_consensus = [claim for claim in consensus_claims if len(claim.get("support_evidence_ids", [])) <= 1]
            if len(thin_consensus) / len(consensus_claims) >= 0.5:
                factors.append(
                    f"{len(thin_consensus)}/{len(consensus_claims)} consensus claims are single-source and sensitive to new corroboration."
                )

        if not factors:
            avg_trust = (sum(trust_scores) / len(trust_scores)) if trust_scores else 0.0
            factors.append(
                f"No dominant sensitivity drivers detected (avg trust={avg_trust:.2f}, disputed={disputed_n}/{total_claims})."
            )
        return factors[:4]

    @staticmethod
    def _build_analyze_sub_queries(query: str, count: int, query_mode: Optional[str] = None) -> list[str]:
        mode = query_mode or classify_query_mode(query)
        if mode == "fact":
            templates = [
                "{q}",
                "{q} definition and scope",
                "{q} core characteristics",
                "{q} mechanisms and causes",
                "{q} prevalence and statistics",
                "{q} expert consensus",
                "{q} conflicting claims",
                "{q} recent evidence",
                "{q} common misconceptions",
                "{q} evidence quality",
                "{q} primary sources",
                "{q} unresolved questions",
            ]
        else:
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
        built: list[str] = []
        for idx in range(max(1, count)):
            if idx < len(templates):
                built.append(templates[idx].format(q=query))
            else:
                built.append(f"{query} perspective {idx + 1}")
        return built


class DeepSearchOrchestrator:
    """Iterative planner-reviewer deep research pipeline for MCP-first output."""

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
        self._agent_semaphore = asyncio.Semaphore(self.max_concurrent)
        self._llm_semaphore = asyncio.Semaphore(max(1, llm_parallel))

    async def search(self, query: str, num_sub_queries: int = 6, depth: int = 2) -> DeepSearchResult:
        started_at = time.perf_counter()
        logger.info("Research v2: query=%s", query)
        target_sub_queries = max(1, min(num_sub_queries, self.max_concurrent))
        max_cycles = max(1, min(depth, 4))

        active_queries = await self._generate_sub_queries(query, target_sub_queries)
        seen_queries = {item.lower() for item in active_queries}

        source_bank: dict[str, dict[str, Any]] = {}
        trace_log: list[str] = []
        open_questions: list[str] = []
        previous_claim_count = 0
        stopping_reason = "budget_exhausted"

        for cycle in range(1, max_cycles + 1):
            trace_log.append(f"cycle_{cycle}: planner selected {len(active_queries)} sub-queries")
            agent_results = await self._run_sub_agents_parallel(active_queries)

            added_in_cycle = 0
            for run in agent_results:
                for source in run.get("results", []):
                    key = normalize_url(source.get("url", ""))
                    if not key or key in source_bank:
                        continue
                    source_bank[key] = source
                    added_in_cycle += 1

            ranked_rows = rank_sources(
                query,
                list(source_bank.values()),
                target=min(len(source_bank), max(20, target_sub_queries * self.max_results)),
                default_intent=classify_query_intent(query),
            )
            sources = make_source_primitives(ranked_rows)
            evidence_rows = make_evidence_primitives(query, ranked_rows)
            claims = make_claim_primitives(evidence_rows, max_claims=160)
            consensus_claims, disputed_claims = split_consensus_disputed(claims)

            claim_delta = len(claims) - previous_claim_count
            previous_claim_count = len(claims)
            trace_log.append(
                f"cycle_{cycle}: +{added_in_cycle} sources, claims={len(claims)}, delta={claim_delta}"
            )

            open_questions = self._derive_open_questions(query, consensus_claims, disputed_claims, sources)
            if claim_delta <= 2:
                stopping_reason = "saturation_reached"
                trace_log.append(f"cycle_{cycle}: stopping, marginal claim gain <= 2")
                break

            if cycle >= max_cycles:
                stopping_reason = "budget_exhausted"
                trace_log.append(f"cycle_{cycle}: stopping, cycle budget exhausted")
                break

            planned = await self._plan_followup_queries(query, open_questions, target_sub_queries)
            next_queries: list[str] = []
            for sub_query in planned:
                key = sub_query.lower()
                if key in seen_queries:
                    continue
                seen_queries.add(key)
                next_queries.append(sub_query)
                if len(next_queries) >= target_sub_queries:
                    break

            if not next_queries:
                stopping_reason = "saturation_reached"
                trace_log.append(f"cycle_{cycle}: stopping, planner produced no novel sub-queries")
                break
            active_queries = next_queries

        ranked_rows = rank_sources(
            query,
            list(source_bank.values()),
            target=min(len(source_bank), max(25, target_sub_queries * self.max_results)),
            default_intent=classify_query_intent(query),
        )
        source_primitives = make_source_primitives(ranked_rows)
        evidence_rows = make_evidence_primitives(query, ranked_rows)
        claims = make_claim_primitives(evidence_rows, max_claims=200)
        consensus_claims, disputed_claims = split_consensus_disputed(claims)
        final_claims = consensus_claims + disputed_claims
        edges = make_edges_from_claims(final_claims)
        open_questions = self._derive_open_questions(
            query,
            consensus_claims,
            disputed_claims,
            source_primitives,
            edges=edges,
            evidence_rows=evidence_rows,
        )
        evidence_trace = self._build_evidence_trace(final_claims, edges, evidence_rows, max_items=8)

        final_synthesis = self._compose_final_synthesis(
            query=query,
            consensus_claims=consensus_claims,
            disputed_claims=disputed_claims,
            evidence_rows=evidence_rows,
            edges=edges,
            open_questions=open_questions,
        )
        coverage_report = {
            "nodes_explored": len(final_claims),
            "edges_explored": len(edges),
            "consensus_claims": len(consensus_claims),
            "disputed_claims": len(disputed_claims),
            "sources_considered": len(source_primitives),
            "evidence_items": len(evidence_rows),
            "contradiction_edges": sum(
                1 for edge in edges if edge.get("relationship") == "contradicts"
            ),
            "evidence_trace": evidence_trace,
            "stopping_reason": stopping_reason,
        }

        payload = {
            "query": query,
            "final_synthesis": final_synthesis,
            "evidence_graph": {
                "nodes": final_claims,
                "edges": edges,
            },
            "coverage_report": coverage_report,
            "open_questions": open_questions,
            "trace_log": trace_log,
            "sources": source_primitives,
            "key_evidence": evidence_rows,
        }
        payload["_meta"] = build_meta(started_at, payload)

        return DeepSearchResult(
            query=query,
            final_synthesis=final_synthesis,
            evidence_graph=payload["evidence_graph"],
            coverage_report=coverage_report,
            open_questions=open_questions,
            trace_log=trace_log,
            sources=source_primitives,
            key_evidence=evidence_rows,
            meta=payload["_meta"],
            search_time=time.perf_counter() - started_at,
        )

    async def _generate_sub_queries(self, query: str, num_queries: int) -> list[str]:
        mode = classify_query_mode(query)
        if mode == "fact":
            prompt = (
                f"Generate {num_queries} focused web research sub-queries for: '{query}'.\n"
                "Aim for broad factual coverage (definition, anatomy, habitat, behavior, lifecycle, ecology).\n"
                "Avoid shopping pages, pest-control-only pages, and acronym-only matches unless requested.\n"
                "Return only a JSON array of strings."
            )
        else:
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

        if mode == "fact":
            fallback = [
                f"{query} definition and taxonomy",
                f"{query} anatomy and physiology",
                f"{query} habitat and distribution",
                f"{query} diet and behavior",
                f"{query} lifecycle and reproduction",
                f"{query} ecological role and predators",
            ]
        else:
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
    def _ensure_sub_query_count(query: str, candidates: list[str], target: int) -> list[str]:
        normalized: list[str] = []
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

    async def _run_sub_agents_parallel(self, sub_queries: list[str]) -> list[dict[str, Any]]:
        active_count = 0
        active_peak = 0
        counter_lock = asyncio.Lock()

        async def run_single(sub_query: str) -> dict[str, Any]:
            nonlocal active_count, active_peak
            async with self._agent_semaphore:
                started = time.perf_counter()
                async with counter_lock:
                    active_count += 1
                    active_peak = max(active_peak, active_count)
                worker = QuickSearchSubAgent(self.searxng, max_urls=self.max_results)
                try:
                    result = await worker.search_lightweight(sub_query, self.max_results)
                    result["_meta"] = {
                        "query": sub_query,
                        "duration_s": round(time.perf_counter() - started, 2),
                        "status": "ok",
                    }
                    return result
                except Exception as exc:
                    return {
                        "query": sub_query,
                        "results": [],
                        "count": 0,
                        "error": str(exc),
                        "_meta": {
                            "query": sub_query,
                            "duration_s": round(time.perf_counter() - started, 2),
                            "status": "error",
                        },
                    }
                finally:
                    async with counter_lock:
                        active_count = max(0, active_count - 1)

        tasks = [asyncio.create_task(run_single(sub_query)) for sub_query in sub_queries]
        completed = await asyncio.gather(*tasks, return_exceptions=True)
        rows: list[dict[str, Any]] = []
        for idx, item in enumerate(completed):
            if isinstance(item, Exception):
                rows.append(
                    {
                        "query": sub_queries[idx],
                        "results": [],
                        "count": 0,
                        "error": str(item),
                        "_meta": {"query": sub_queries[idx], "status": "error", "duration_s": 0.0},
                    }
                )
            else:
                rows.append(item)
        logger.info("Research v2 sub-agent peak parallelism=%s", active_peak)
        return rows

    @staticmethod
    def _derive_open_questions(
        query: str,
        consensus_claims: list[dict[str, Any]],
        disputed_claims: list[dict[str, Any]],
        sources: list[dict[str, Any]],
        edges: Optional[list[dict[str, Any]]] = None,
        evidence_rows: Optional[list[dict[str, Any]]] = None,
    ) -> list[str]:
        questions: list[str] = []
        evidence_rows = evidence_rows or []
        edges = edges or []

        ranked_disputed = sorted(
            disputed_claims,
            key=lambda claim: (
                len(claim.get("support_evidence_ids", [])),
                len(claim.get("refute_evidence_ids", [])),
            ),
            reverse=True,
        )
        for claim in ranked_disputed[:3]:
            statement = (claim.get("statement", "") or "").strip().rstrip(".")
            if statement:
                questions.append(f"What primary-source evidence can confirm or refute: {statement}?")

        contradiction_edges = [edge for edge in edges if edge.get("relationship") == "contradicts"]
        if contradiction_edges:
            questions.append("Which contradiction clusters in the evidence graph are highest-impact to resolve first?")

        weak_consensus = [
            claim
            for claim in consensus_claims
            if len(claim.get("support_evidence_ids", [])) <= 1
        ]
        if weak_consensus and len(weak_consensus) >= max(2, len(consensus_claims) // 2):
            questions.append("Which consensus findings still rely on single-source support and need replication?")

        host_set = {
            urlparse((source.get("url", "") or "").strip()).netloc.lower().removeprefix("www.")
            for source in sources
            if isinstance(source, dict)
        }
        host_set = {host for host in host_set if host}
        if len(host_set) < max(4, min(8, len(sources) // 2)):
            questions.append("Which additional independent domains can improve evidence diversity and reduce bias?")

        if evidence_rows and len(consensus_claims) + len(disputed_claims) < max(5, len(evidence_rows) // 5):
            questions.append(f"What claims for '{query}' remain unmodeled in the current evidence graph?")

        if len(consensus_claims) < 4:
            questions.append(f"Gather stronger multi-source consensus evidence for: {query}.")
        if not questions:
            questions.append("No major unresolved questions; validate edge-case scenarios.")
        return questions[:5]

    @staticmethod
    def _compose_final_synthesis(
        query: str,
        consensus_claims: list[dict[str, Any]],
        disputed_claims: list[dict[str, Any]],
        evidence_rows: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        open_questions: list[str],
    ) -> str:
        all_claims = consensus_claims + disputed_claims
        if not all_claims:
            return "Report\n\nNo stable synthesis could be generated from retrieved evidence."

        evidence_map = {item.get("evidence_id", ""): item for item in evidence_rows}
        ranked_consensus = sorted(
            consensus_claims,
            key=lambda claim: len(claim.get("support_evidence_ids", [])),
            reverse=True,
        )
        ranked_disputed = sorted(
            disputed_claims,
            key=lambda claim: (
                len(claim.get("support_evidence_ids", [])),
                len(claim.get("refute_evidence_ids", [])),
            ),
            reverse=True,
        )
        contradiction_pairs = DeepSearchOrchestrator._top_contradiction_pairs(
            ranked_disputed,
            edges,
            evidence_map,
            max_pairs=3,
        )
        trace_rows = DeepSearchOrchestrator._build_evidence_trace(all_claims, edges, evidence_rows, max_items=6)

        lines: list[str] = ["Report", "", f"Query: {query}", "", "## Executive Summary"]

        summary_claims = ranked_consensus[:5] if ranked_consensus else all_claims[:5]
        for claim in summary_claims:
            statement = (claim.get("statement", "") or "").strip()
            if not statement:
                continue
            citation = DeepSearchOrchestrator._claim_citations(claim, evidence_map)
            lines.append(f"- {statement} {citation}".strip())

        if not summary_claims:
            lines.append("- Insufficient high-confidence evidence was available for synthesis.")

        lines.extend(["", "## Contradictions and Uncertainty"])
        if contradiction_pairs:
            for pair in contradiction_pairs:
                lines.append(
                    (
                        "- "
                        f"{pair['left_statement']} vs {pair['right_statement']} "
                        f"{pair['citations']}"
                    ).strip()
                )
        elif ranked_disputed:
            for claim in ranked_disputed[:3]:
                statement = (claim.get("statement", "") or "").strip()
                citation = DeepSearchOrchestrator._claim_citations(claim, evidence_map)
                lines.append(f"- Disputed finding: {statement} {citation}".strip())
        else:
            lines.append("- No material contradiction edges were detected in the final graph.")

        lines.extend(["", "## Evidence Graph Trace"])
        if trace_rows:
            for row in trace_rows:
                src_citations = " ".join(f"[{src}]" for src in row.get("source_ids", []))
                evidence_ids = ", ".join(row.get("evidence_ids", []))
                lines.append(
                    (
                        "- "
                        f"{row.get('claim_id', '?')} <- {evidence_ids} "
                        f"{src_citations} "
                        f"(contradiction_links={row.get('contradiction_links', 0)})"
                    ).strip()
                )
        else:
            lines.append("- Evidence trace links were too weak to summarize reliably.")

        if open_questions:
            lines.extend(["", "## Open Questions"])
            for item in open_questions[:5]:
                lines.append(f"- {item}")

        return "\n".join(lines).strip()

    @staticmethod
    def _claim_citations(claim: dict[str, Any], evidence_map: dict[str, dict[str, Any]], limit: int = 3) -> str:
        source_ids: list[str] = []
        evidence_ids = claim.get("support_evidence_ids", []) + claim.get("refute_evidence_ids", [])
        for evidence_id in evidence_ids:
            source_id = evidence_map.get(evidence_id, {}).get("source_id", "")
            if source_id and source_id not in source_ids:
                source_ids.append(source_id)
        if not source_ids:
            return ""
        return " ".join(f"[{source}]" for source in source_ids[:limit])

    @staticmethod
    def _top_contradiction_pairs(
        disputed_claims: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        evidence_map: dict[str, dict[str, Any]],
        max_pairs: int,
    ) -> list[dict[str, str]]:
        claim_map = {claim.get("claim_id", ""): claim for claim in disputed_claims}
        scored_pairs: list[tuple[int, dict[str, str]]] = []
        seen_pairs: set[str] = set()

        for edge in edges:
            if edge.get("relationship") != "contradicts":
                continue
            left_id = edge.get("source_claim_id", "")
            right_id = edge.get("target_claim_id", "")
            if left_id not in claim_map or right_id not in claim_map:
                continue

            pair_key = "::".join(sorted([left_id, right_id]))
            if pair_key in seen_pairs:
                continue
            seen_pairs.add(pair_key)

            left = claim_map[left_id]
            right = claim_map[right_id]
            support_weight = len(left.get("support_evidence_ids", [])) + len(right.get("support_evidence_ids", []))
            citation = DeepSearchOrchestrator._claim_citations(
                {
                    "support_evidence_ids": left.get("support_evidence_ids", [])
                    + right.get("support_evidence_ids", []),
                    "refute_evidence_ids": left.get("refute_evidence_ids", [])
                    + right.get("refute_evidence_ids", []),
                },
                evidence_map,
            )

            scored_pairs.append(
                (
                    support_weight,
                    {
                        "left_statement": (left.get("statement", "") or "").strip(),
                        "right_statement": (right.get("statement", "") or "").strip(),
                        "citations": citation,
                    },
                )
            )

        scored_pairs.sort(key=lambda item: item[0], reverse=True)
        return [item[1] for item in scored_pairs[:max_pairs]]

    @staticmethod
    def _build_evidence_trace(
        claims: list[dict[str, Any]],
        edges: list[dict[str, Any]],
        evidence_rows: list[dict[str, Any]],
        max_items: int = 8,
    ) -> list[dict[str, Any]]:
        evidence_map = {item.get("evidence_id", ""): item for item in evidence_rows}
        contradiction_counts: dict[str, int] = {}
        for edge in edges:
            if edge.get("relationship") != "contradicts":
                continue
            left = edge.get("source_claim_id", "")
            right = edge.get("target_claim_id", "")
            contradiction_counts[left] = contradiction_counts.get(left, 0) + 1
            contradiction_counts[right] = contradiction_counts.get(right, 0) + 1

        ranked_claims = sorted(
            claims,
            key=lambda claim: (
                len(claim.get("support_evidence_ids", [])),
                contradiction_counts.get(claim.get("claim_id", ""), 0),
            ),
            reverse=True,
        )

        trace_rows: list[dict[str, Any]] = []
        for claim in ranked_claims[:max_items]:
            support_ids = list(dict.fromkeys(claim.get("support_evidence_ids", [])[:4]))
            source_ids: list[str] = []
            for evidence_id in support_ids:
                source_id = evidence_map.get(evidence_id, {}).get("source_id", "")
                if source_id and source_id not in source_ids:
                    source_ids.append(source_id)
            trace_rows.append(
                {
                    "claim_id": claim.get("claim_id", ""),
                    "statement": claim.get("statement", ""),
                    "evidence_ids": support_ids,
                    "source_ids": source_ids,
                    "contradiction_links": contradiction_counts.get(claim.get("claim_id", ""), 0),
                }
            )
        return trace_rows

    async def _plan_followup_queries(self, query: str, open_questions: list[str], target: int) -> list[str]:
        if not open_questions:
            return [f"{query} unresolved evidence", f"{query} contradictory findings"][:target]

        prompt = (
            f"Given query '{query}', propose {target} concise follow-up sub-queries to close these gaps:\n"
            + "\n".join(f"- {item}" for item in open_questions)
            + "\nReturn only a JSON array of strings."
        )
        async with self._llm_semaphore:
            response = await self.llm.complete(prompt=prompt, temperature=0.4)
        try:
            parsed = json.loads(response.content.strip())
            if isinstance(parsed, list):
                normalized = [str(item).strip() for item in parsed if str(item).strip()]
                if normalized:
                    return self._ensure_sub_query_count(query, normalized, target)
        except Exception:
            logger.warning("Follow-up planner parse failed; using fallback follow-ups")

        fallback = [
            f"{query} unresolved evidence",
            f"{query} contradiction analysis",
            f"{query} primary source verification",
            f"{query} implementation caveats",
        ]
        return self._ensure_sub_query_count(query, fallback, target)

    @staticmethod
    def _group_clusters(cluster_reports: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
        """Group cluster reports by sub-agent count, targeting groups of 3.

        Examples:
        - 12 clusters -> 4 groups of 3
        - 11 clusters -> 3 groups of 3 and 1 group of 2
        - avoids singleton tail groups by rebalancing (..., 3, 1) -> (..., 2, 2)
        """
        n = len(cluster_reports)
        if n <= 3:
            return [cluster_reports]

        sizes: list[int] = []
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
                if sizes:
                    sizes[-1] -= 1
                    sizes.append(2)
                else:
                    sizes.append(1)
                remaining = 0
                break
            sizes.append(3)
            remaining -= 3

        groups: list[list[dict[str, Any]]] = []
        cursor = 0
        for size in sizes:
            groups.append(cluster_reports[cursor : cursor + size])
            cursor += size
        return groups

    @staticmethod
    def _stitch_synthesis_reports(query: str, synthesis_reports: list[dict[str, Any]]) -> str:
        if not synthesis_reports:
            return "No synthesis reports were generated."

        lines: list[str] = ["Report", "", f"Query: {query}", ""]
        for item in synthesis_reports:
            group = item.get("group", "?")
            queries = item.get("queries", [])
            report = (item.get("report", "") or "").strip()
            title = f"Synthesis Block {group}"
            if queries:
                title += f" ({', '.join(queries)})"
            lines.append(f"## {title}")
            lines.append(report or "No report content.")
            lines.append("")
        return "\n".join(lines).strip()

    def get_pool_status(self) -> dict[str, Any]:
        return {
            "max_concurrent": self.max_concurrent,
            "available": getattr(self._agent_semaphore, "_value", 0),
            "mode": "research-v2",
        }
