import json
import logging
import re
from dataclasses import dataclass
from typing import Any, Dict, List

from search.llm_client import LLMClient

logger = logging.getLogger("reporting")


@dataclass
class ReportOutput:
    report: str
    sources: List[Dict[str, str]]


def normalize_url(url: str) -> str:
    cleaned = (url or "").strip().lower()
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = cleaned.rstrip("/")
    return cleaned


def dedupe_sources(results: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    seen = set()
    unique: List[Dict[str, Any]] = []
    for item in results:
        key = normalize_url(item.get("url", ""))
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break
    return unique


def strip_think_blocks(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<think>[\s\S]*?(</think>|$)", "", text, flags=re.IGNORECASE)
    return cleaned.strip()


def has_citations(text: str) -> bool:
    return bool(re.search(r"\(\d+\)", text or ""))


class ReportGenerator:
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client

    async def write_report(
        self,
        query: str,
        sources: List[Dict[str, Any]],
        style: str = "concise",
        max_tokens: int | None = None,
    ) -> ReportOutput:
        indexed_sources = []
        context_blocks = []
        for idx, source in enumerate(sources, start=1):
            title = source.get("title") or "Untitled"
            url = source.get("url") or ""
            content = (source.get("content") or "").strip()
            content = re.sub(r"\s+", " ", content)[:260]
            indexed_sources.append({"index": idx, "title": title, "url": url})
            context_blocks.append(
                f"[{idx}] {title}\nURL: {url}\nSnippet: {content}\n"
            )

        prompt = (
            f"You are an evidence-focused analyst. Write a report for query: \"{query}\".\n\n"
            "Rules:\n"
            "1) Use inline citations in the form (n), where n maps to the source index.\n"
            "2) Every factual claim must include a citation.\n"
            "3) Do not output internal reasoning or <think> tags.\n"
            "4) Title the first section as 'Report'.\n"
            "5) End with a section called 'Sources' and list each source as: [n] Title - URL.\n"
            f"6) Style: {style}.\n\n"
            "Evidence:\n"
            + "\n".join(context_blocks)
        )

        response = await self.llm.complete(prompt=prompt, temperature=0.3)
        if response.content.startswith("Error:"):
            raise RuntimeError(f"Report generation failed: {response.content}")

        raw_report = response.content or ""
        report = strip_think_blocks(raw_report)

        if not report and "<think" in raw_report.lower():
            logger.warning("Primary report output was think-only; retrying with final-only prompt")
            report = await self._force_final_only(
                query=query,
                indexed_sources=indexed_sources,
                context_blocks=context_blocks,
                style=style,
            )

        if not report:
            logger.warning("Report still empty after first retry; attempting concise final-only retry")
            report = await self._force_concise_final_only(
                query=query,
                indexed_sources=indexed_sources,
                context_blocks=context_blocks,
            )

        if not has_citations(report):
            report = await self._repair_citations(query, indexed_sources, report)

        if not report:
            report = self._fallback_report(query, sources)

        return ReportOutput(report=report, sources=[{"title": s["title"], "url": s["url"]} for s in indexed_sources])

    async def merge_reports(
        self,
        query: str,
        report_a: str,
        report_b: str,
        label_a: str = "Agent A",
        label_b: str = "Agent B",
    ) -> str:
        prompt = (
            f"Merge two reports for query: \"{query}\" into one comprehensive report.\n"
            "Rules:\n"
            "1) Keep inline citations as provided; do not invent new source numbers.\n"
            "2) Add a section 'Agreement' and a section 'Contradictions or Gaps'.\n"
            "3) Add a final section 'Unified Report'.\n"
            "4) Do not output internal reasoning or <think> tags.\n\n"
            f"{label_a} report:\n{report_a}\n\n"
            f"{label_b} report:\n{report_b}\n"
        )
        response = await self.llm.complete(prompt=prompt, temperature=0.2)
        if response.content.startswith("Error:"):
            raise RuntimeError(f"Report merge failed: {response.content}")
        merged = strip_think_blocks(response.content)
        if merged:
            return merged
        return "Unified Report\n\nUnable to merge reports due to empty model output."

    async def merge_multiple_reports(
        self,
        query: str,
        reports: List[str],
        labels: List[str] | None = None,
        merge_goal: str | None = None,
    ) -> str:
        clean_reports = [r for r in reports if (r or "").strip()]
        if not clean_reports:
            return "Unified Report\n\nNo agent reports were available to merge."
        if len(clean_reports) == 1:
            return clean_reports[0]

        effective_labels = labels or [f"Agent {i}" for i in range(1, len(clean_reports) + 1)]
        sections = []
        for idx, report in enumerate(clean_reports):
            label = effective_labels[idx] if idx < len(effective_labels) else f"Agent {idx + 1}"
            sections.append(f"{label} report:\n{report}")

        prompt = (
            f"Merge all reports for query: \"{query}\" into one comprehensive report.\n"
            "Rules:\n"
            "1) Keep inline citations as provided; do not invent new source numbers.\n"
            "2) Add sections: Agreement, Contradictions or Gaps, Unified Report.\n"
            "3) Reconcile overlap and remove duplication.\n"
            "4) Do not output internal reasoning or <think> tags.\n\n"
            + "\n\n".join(sections)
        )
        if merge_goal:
            prompt = (
                f"Merge goal: {merge_goal}.\n"
                + prompt
            )
        response = await self.llm.complete(prompt=prompt, temperature=0.2)
        if response.content.startswith("Error:"):
            raise RuntimeError(f"Report merge failed: {response.content}")
        merged = strip_think_blocks(response.content)
        if merged:
            return merged
        return "Unified Report\n\nUnable to merge reports due to empty model output."

    async def compose_comprehensive_analysis_report(
        self,
        query: str,
        agent_reports: List[Dict[str, Any]],
        contradiction_reports: List[Dict[str, Any]],
    ) -> str:
        if not contradiction_reports:
            return "Unified Report\n\nNo contradiction reports were available for final synthesis."

        base_blocks = []
        for item in agent_reports:
            label = f"Skim Agent {item.get('agent', '?')}"
            sub_query = item.get("query", "")
            sources_count = item.get("sources_count", 0)
            report = (item.get("report", "") or "")[:3200]
            base_blocks.append(
                f"{label}\nSub-query: {sub_query}\nSources: {sources_count}\n{report}"
            )

        contradiction_blocks = []
        for item in contradiction_reports:
            label = item.get("label", "Merge Agent")
            goal = item.get("goal", "")
            report = (item.get("report", "") or "")[:4200]
            contradiction_blocks.append(f"{label}\nGoal: {goal}\n{report}")

        prompt = (
            f"Create an EXTREMELY comprehensive final analysis report for query: \"{query}\".\n"
            "You are the final synthesis agent and MUST integrate all evidence from both layers below.\n"
            "Layer A: Base skim-agent reports.\n"
            "Layer B: Contradiction-focused merge reports.\n"
            "Rules:\n"
            "1) Preserve citation markers like (n) when present; never invent source numbers.\n"
            "2) Cover all major claims, disagreements, uncertainty, and practical implications.\n"
            "3) Include sections: Executive Summary, Consensus, Contradictions, Evidence Gaps, Practical Guidance, Final Conclusions, Sources.\n"
            "4) Prefer completeness over brevity while staying coherent and non-redundant.\n"
            "5) Do not include internal reasoning or <think> tags.\n\n"
            "Layer A (Skim-Agent Reports):\n"
            + "\n\n".join(base_blocks)
            + "\n\nLayer B (Contradiction-Merge Reports):\n"
            + "\n\n".join(contradiction_blocks)
        )

        response = await self.llm.complete(prompt=prompt, temperature=0.2)
        if response.content.startswith("Error:"):
            raise RuntimeError(f"Final analysis synthesis failed: {response.content}")

        merged = strip_think_blocks(response.content)
        if merged:
            return merged

        return await self.merge_multiple_reports(
            query=query,
            reports=[item.get("report", "") for item in contradiction_reports],
            labels=[item.get("label", "Merge Agent") for item in contradiction_reports],
            merge_goal="Fallback final synthesis across contradiction reports.",
        )

    async def _repair_citations(self, query: str, indexed_sources: List[Dict[str, Any]], report: str) -> str:
        if not report:
            return ""

        source_text = "\n".join(
            f"[{s['index']}] {s['title']} - {s['url']}" for s in indexed_sources
        )
        prompt = (
            f"Repair citations for this report on \"{query}\".\n"
            "Add inline citations in format (n) for factual claims using only provided sources.\n"
            "Keep original meaning. Do not include <think> tags.\n\n"
            f"Sources:\n{source_text}\n\n"
            f"Report:\n{report}"
        )
        response = await self.llm.complete(prompt=prompt, temperature=0.1)
        repaired = strip_think_blocks(response.content)
        if repaired:
            return repaired
        return report

    async def _force_final_only(
        self,
        query: str,
        indexed_sources: List[Dict[str, Any]],
        context_blocks: List[str],
        style: str,
    ) -> str:
        source_index = "\n".join(f"[{s['index']}] {s['title']} - {s['url']}" for s in indexed_sources)
        prompt = (
            f"Write the FINAL report for query: \"{query}\" using evidence below.\n"
            "Output only user-facing report text.\n"
            "Do NOT include <think> tags, hidden reasoning, or analysis traces.\n"
            "Do NOT include any preamble.\n"
            "Required sections: Report, Sources.\n"
            "Use inline citations (n) for factual claims and only source numbers that exist.\n"
            f"Style: {style}.\n\n"
            f"Sources index:\n{source_index}\n\n"
            "Evidence snippets:\n"
            + "\n".join(context_blocks)
        )
        response = await self.llm.complete(prompt=prompt, temperature=0.2)
        cleaned = strip_think_blocks(response.content)
        return cleaned

    async def _force_concise_final_only(
        self,
        query: str,
        indexed_sources: List[Dict[str, Any]],
        context_blocks: List[str],
    ) -> str:
        source_index = "\n".join(f"[{s['index']}] {s['title']} - {s['url']}" for s in indexed_sources)
        prompt = (
            f"Return the FINAL answer for query: \"{query}\".\n"
            "Output only final user-facing text.\n"
            "Never output <think> or hidden reasoning.\n"
            "Format strictly:\n"
            "Report\n"
            "- 4 to 7 short bullet points with citations (n)\n"
            "Sources\n"
            "- [n] Title - URL\n"
            "Keep it concise and under 300 words before Sources.\n\n"
            f"Sources index:\n{source_index}\n\n"
            "Evidence snippets:\n"
            + "\n".join(context_blocks)
        )
        response = await self.llm.complete(prompt=prompt, temperature=0.0)
        return strip_think_blocks(response.content)

    def _fallback_report(self, query: str, sources: List[Dict[str, Any]]) -> str:
        lines = ["Report", "", f"Summary for '{query}':"]
        for idx, src in enumerate(sources[:8], start=1):
            title = src.get("title", "Untitled")
            url = src.get("url", "")
            snippet = re.sub(r"\s+", " ", (src.get("content") or "").strip())[:200]
            if snippet:
                lines.append(f"- {title}: {snippet} ({idx})")
            else:
                lines.append(f"- {title} ({idx})")
        lines.append("")
        lines.append("Sources")
        for idx, src in enumerate(sources[:8], start=1):
            lines.append(f"[{idx}] {src.get('title', 'Untitled')} - {src.get('url', '')}")
        return "\n".join(lines)
