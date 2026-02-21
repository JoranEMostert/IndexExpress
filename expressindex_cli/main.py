import argparse
import asyncio
import json
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit

import aiohttp
from expressindex_core.sanitize import sanitize_payload
from prompt_toolkit import PromptSession
from prompt_toolkit.patch_stdout import patch_stdout
from rich.console import Console
from rich.panel import Panel
from rich.table import Table


MCP_URL_DEFAULT = "http://localhost:8000/mcp"
QUERY_MODES = ["peek", "skim", "analyze", "research"]
UTILITY_MODES = ["status", "metrics"]
MODES = QUERY_MODES + UTILITY_MODES


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return sanitize_payload(payload)


@dataclass
class QueryResult:
    mode: str
    payload: dict[str, Any]


async def call_mcp_tool(
    mode: str,
    query: str,
    mcp_url: str,
    max_results: Optional[int] = None,
    num_sub_queries: Optional[int] = None,
    fetch_content: Optional[bool] = None,
    max_content_chars: Optional[int] = None,
) -> QueryResult:
    arguments: dict[str, Any] = {"query": query}
    if mode in {"peek", "skim"} and max_results is not None:
        arguments["max_results"] = max_results
    if mode == "peek":
        arguments["fetch_content"] = True if fetch_content is None else fetch_content
        if max_content_chars is not None:
            arguments["max_content_chars"] = max_content_chars
    if mode == "research" and num_sub_queries is not None:
        arguments["num_sub_queries"] = num_sub_queries

    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": mode, "arguments": arguments},
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(mcp_url, json=body, timeout=aiohttp.ClientTimeout(total=None)) as response:
            raw = await response.text()
            if response.status != 200:
                raise RuntimeError(f"MCP request failed ({response.status}): {raw}")

    message = json.loads(raw)
    if "error" in message:
        err = message["error"].get("message", "Unknown error")
        raise RuntimeError(err)
    result_blob = message.get("result", {}).get("content", [])
    if not result_blob:
        return QueryResult(mode=mode, payload={})
    payload = json.loads(result_blob[0].get("text", "{}"))
    payload = _sanitize_payload(payload)
    return QueryResult(mode=mode, payload=payload)


async def call_agent_status(mcp_url: str) -> dict[str, Any]:
    body = {
        "jsonrpc": "2.0",
        "id": str(uuid.uuid4()),
        "method": "tools/call",
        "params": {"name": "agent_status", "arguments": {}},
    }
    async with aiohttp.ClientSession() as session:
        async with session.post(mcp_url, json=body, timeout=aiohttp.ClientTimeout(total=10)) as response:
            raw = await response.text()
            if response.status != 200:
                raise RuntimeError(f"agent_status failed ({response.status}): {raw}")

    message = json.loads(raw)
    if "error" in message:
        err = message["error"].get("message", "Unknown error")
        raise RuntimeError(err)

    result_blob = message.get("result", {}).get("content", [])
    if not result_blob:
        return {}
    text = result_blob[0].get("text", "{}")
    try:
        return json.loads(text)
    except Exception:
        return {}


def _http_base_from_mcp(mcp_url: str) -> str:
    parts = urlsplit(mcp_url)
    if not parts.scheme or not parts.netloc:
        raise RuntimeError(f"Invalid MCP URL: {mcp_url}")
    return f"{parts.scheme}://{parts.netloc}"


async def call_http_json(url: str, timeout_s: int = 10) -> dict[str, Any]:
    async with aiohttp.ClientSession() as session:
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=timeout_s)) as response:
            raw = await response.text()
            if response.status not in {200, 503}:
                raise RuntimeError(f"GET {url} failed ({response.status}): {raw}")
            try:
                return json.loads(raw)
            except json.JSONDecodeError as exc:
                raise RuntimeError(f"Invalid JSON from {url}: {exc}") from exc


async def call_status_bundle(mcp_url: str) -> dict[str, Any]:
    base = _http_base_from_mcp(mcp_url)
    health, ready, agent = await asyncio.gather(
        call_http_json(f"{base}/health", timeout_s=10),
        call_http_json(f"{base}/ready", timeout_s=10),
        call_agent_status(mcp_url),
    )
    return {"health": health, "ready": ready, "agent_status": agent}


async def call_metrics(mcp_url: str) -> dict[str, Any]:
    base = _http_base_from_mcp(mcp_url)
    return await call_http_json(f"{base}/metrics", timeout_s=10)


def _render_status_text(bundle: dict[str, Any]) -> str:
    health = bundle.get("health", {})
    ready = bundle.get("ready", {})
    agent = bundle.get("agent_status", {})
    max_concurrent = int(agent.get("max_concurrent", 0) or 0)
    available = int(agent.get("available", 0) or 0)
    active = max(0, max_concurrent - available)
    lines = [
        "ExpressIndex Status",
        "-------------------",
        f"health: {health.get('status', 'unknown')}",
        f"ready: {ready.get('status', 'unknown')}",
        f"searxng: {health.get('services', {}).get('searxng', 'unknown')}",
        f"llm: {health.get('services', {}).get('llm', 'unknown')}",
        f"agents: {active}/{max_concurrent} active",
    ]
    return "\n".join(lines)


def _render_metrics_text(metrics_payload: dict[str, Any]) -> str:
    metrics = metrics_payload.get("metrics", {})
    lines = [
        "ExpressIndex Metrics",
        "--------------------",
        f"uptime_s: {metrics.get('uptime_s', 0)}",
        "",
        "Tool Stats:",
    ]
    for tool, row in metrics.get("tools", {}).items():
        lines.append(
            f"- {tool}: count={row.get('count', 0)} errors={row.get('errors', 0)} "
            f"avg_s={row.get('avg_s', 0)} max_s={row.get('max_s', 0)}"
        )

    lines.append("")
    lines.append("Request Stats:")
    for method, row in metrics.get("requests", {}).items():
        lines.append(
            f"- {method}: count={row.get('count', 0)} errors={row.get('errors', 0)} "
            f"avg_s={row.get('avg_s', 0)} max_s={row.get('max_s', 0)}"
        )
    return "\n".join(lines)


def markdown_from_result(query: str, mode: str, payload: dict[str, Any]) -> str:
    lines = [f"# ExpressIndex {mode.title()} Report", "", f"Query: {query}", ""]
    report = (
        _tui_consumer_summary(mode, payload)
        or payload.get("final_answer")
        or payload.get("recommended_position")
        or payload.get("final_synthesis")
        or payload.get("report")
        or payload.get("final_report")
    )
    if report:
        lines.append(report)
    else:
        lines.append("## Sources")
        for i, src in enumerate(payload.get("sources", []), start=1):
            title = src.get("title", "Untitled")
            url = src.get("url", "")
            lines.append(f"{i}. [{title}]({url})")

    meta = payload.get("_meta", {})
    if isinstance(meta, dict):
        compute_ms = meta.get("compute_ms")
        token_estimate = meta.get("token_estimate")
        if compute_ms is not None or token_estimate is not None:
            lines.append("")
        if compute_ms is not None:
            lines.append(f"Compute time: {compute_ms}ms")
        if token_estimate is not None:
            lines.append(f"Token estimate: {token_estimate}")
    elif payload.get("search_time") is not None:
        lines.extend(["", f"Search time: {payload['search_time']}s"])
    return "\n".join(lines)


def _source_lines(payload: dict[str, Any]) -> list[str]:
    sources = payload.get("sources", [])
    lines = []
    for i, src in enumerate(sources, start=1):
        lines.append(f"[{i}] {src.get('title', 'Untitled')} - {src.get('url', '')}")
    return lines


def _detail_lines(mode: str, payload: dict[str, Any]) -> list[str]:
    if mode == "skim":
        if "claims" in payload:
            lines = [
                f"claims: {len(payload.get('claims', []))}",
                f"key_evidence: {len(payload.get('key_evidence', []))}",
                f"sources: {len(payload.get('sources', []))}",
            ]
            for item in payload.get("uncertainties", [])[:4]:
                lines.append(f"- uncertainty: {item}")
            return lines
        lines = [
            f"skim_reports: {len(payload.get('skim_reports', []))}",
            f"sources_count: {payload.get('sources_count', 0)}",
        ]
        runs = payload.get("skim_agent_runs", [])
        if isinstance(runs, list):
            for run in runs:
                if isinstance(run, dict):
                    lines.append(
                        f"- run agent {run.get('agent', '?')}: {run.get('status', 'unknown')} "
                        f"{run.get('duration_s', '?')}s :: {run.get('query', '')}"
                    )
        for item in payload.get("skim_reports", []):
            lines.append(f"- agent {item.get('agent', '?')}: {item.get('sources_count', 0)} sources :: {item.get('query', '')}")
        return lines

    if mode == "research":
        if "evidence_graph" in payload:
            graph = payload.get("evidence_graph", {})
            lines = [
                f"graph_nodes: {len(graph.get('nodes', [])) if isinstance(graph, dict) else 0}",
                f"graph_edges: {len(graph.get('edges', [])) if isinstance(graph, dict) else 0}",
            ]
            coverage = payload.get("coverage_report", {})
            if isinstance(coverage, dict):
                lines.append(f"stopping_reason: {coverage.get('stopping_reason', 'unknown')}")
                lines.append(f"nodes_explored: {coverage.get('nodes_explored', 0)}")
            lines.append(f"sources: {len(payload.get('sources', []))}")
            return lines
        lines = [
            f"sub_queries: {len(payload.get('sub_queries', []))}",
            f"cluster_reports: {len(payload.get('cluster_reports', []))}",
            f"synthesis_reports: {len(payload.get('synthesis_reports', []))}",
            f"agents_used: {payload.get('agents_used', 0)}",
            f"total_sources: {payload.get('total_sources', 0)}",
        ]
        for run in payload.get("agent_runs", []):
            q = run.get("query", "")
            d = run.get("duration_s", "?")
            s = run.get("status", "unknown")
            lines.append(f"- {s} {d}s :: {q}")
        return lines

    if mode == "analyze":
        decision_matrix = payload.get("decision_matrix")
        if isinstance(decision_matrix, list) and decision_matrix:
            lines = [
                f"consensus_claims: {len(payload.get('consensus_claims', []))}",
                f"disputed_claims: {len(payload.get('disputed_claims', []))}",
                f"decision_dimensions: {len(decision_matrix)}",
                f"sources: {len(payload.get('sources', []))}",
            ]
            for factor in payload.get("sensitivity_factors", [])[:3]:
                lines.append(f"- sensitivity: {factor}")
            return lines
        if isinstance(decision_matrix, list):
            lines = [
                f"consensus_claims: {len(payload.get('consensus_claims', []))}",
                f"disputed_claims: {len(payload.get('disputed_claims', []))}",
                f"sources: {len(payload.get('sources', []))}",
            ]
            for factor in payload.get("sensitivity_factors", [])[:3]:
                lines.append(f"- sensitivity: {factor}")
            return lines
        lines = [
            f"analyze_agents: {payload.get('agent_count', 0)}",
            f"merge_agents: {payload.get('merge_agent_count', 0)}",
        ]
        lines.extend(_source_lines(payload))
        return lines

    lines = _source_lines(payload)
    if not lines and payload.get("sources_count") is not None:
        lines.append(f"sources_count: {payload.get('sources_count')}")
    return lines


def _extract_signal_lines(text: str, max_lines: int = 4) -> list[str]:
    lines: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        lowered = line.lower()
        if lowered in {"report", "sources", "executive summary", "core findings", "final conclusions"}:
            continue
        if line.startswith("#"):
            continue
        if lowered.startswith("sources"):
            continue
        lines.append(line)
        if len(lines) >= max_lines:
            break
    return lines


def _tui_consumer_summary(mode: str, payload: dict[str, Any]) -> str:
    """TUI-only synthesis that mimics an MCP consumer reading many reports."""
    if mode == "peek":
        sources = payload.get("sources", [])
        if not isinstance(sources, list) or not sources:
            return "No sources returned."
        lines = [
            "# Peek Result",
            "",
            "## Top Sources",
        ]
        for src in sources[:6]:
            lines.append(f"- {src.get('source_id', 'src')} {src.get('url', '')}")
        return "\n".join(lines)

    if mode == "skim":
        if payload.get("final_answer"):
            lines = [
                "# Skim Final Answer",
                "",
                payload.get("final_answer", "").strip(),
            ]
            uncertainties = payload.get("uncertainties", [])
            if uncertainties:
                lines.extend(["", "## Uncertainties"])
                for item in uncertainties[:5]:
                    lines.append(f"- {item}")
            return "\n".join(lines).strip()
        reports = payload.get("skim_reports", [])
        if not reports:
            return payload.get("report", "No skim reports returned.")
        lines = [
            "# Final Answer",
            "",
            f"Synthesized from {len(reports)} skim reports.",
            "",
            "## Highlights Across Skim Agents",
        ]
        for item in reports:
            agent = item.get("agent", "?")
            query = item.get("query", "")
            points = _extract_signal_lines(item.get("report", ""), max_lines=2)
            lines.append(f"- Agent {agent} ({query})")
            for point in points:
                lines.append(f"  - {point}")
        lines.extend(["", "## Raw Skim Reports"])
        return "\n".join(lines).strip()

    if mode == "research":
        if payload.get("final_synthesis"):
            lines = [
                "# Research Final Synthesis",
                "",
                payload.get("final_synthesis", "").strip(),
            ]
            open_questions = payload.get("open_questions", [])
            if open_questions:
                lines.extend(["", "## Open Questions"])
                for item in open_questions[:5]:
                    lines.append(f"- {item}")
            return "\n".join(lines).strip()
        blocks = payload.get("synthesis_reports", [])
        if not blocks:
            return payload.get("final_report", "No synthesis reports were returned.")

        lines = [
            "# Final Answer",
            "",
            f"Synthesized from {len(blocks)} research report blocks.",
            "",
            "## Key Findings Across Blocks",
        ]
        for item in blocks:
            group = item.get("group", "?")
            queries = ", ".join(item.get("queries", []))
            signals = _extract_signal_lines(item.get("report", ""), max_lines=2)
            title = f"- Block {group}"
            if queries:
                title += f" ({queries})"
            lines.append(title)
            for point in signals:
                lines.append(f"  - {point}")

        lines.extend(
            [
                "",
                "## What To Do With These Reports",
                "- Use this final answer for decision-making.",
                "- Use the raw synthesis blocks below to inspect disagreements and citations.",
                "",
                "## Raw Synthesis Blocks",
            ]
        )
        return "\n".join(lines).strip()

    if mode == "analyze":
        if payload.get("recommended_position"):
            decision_matrix = payload.get("decision_matrix")
            fact_style = isinstance(decision_matrix, list) and not decision_matrix
            lines = [
                "# Analyze Findings" if fact_style else "# Analyze Recommendation",
                "",
                payload.get("recommended_position", "").strip(),
            ]
            if fact_style:
                lines.extend(
                    [
                        "",
                        f"Fact claims reviewed: {len(payload.get('consensus_claims', []))}",
                    ]
                )
                disputed_count = len(payload.get("disputed_claims", []))
                if disputed_count:
                    lines.append(f"Disputed claims: {disputed_count}")
            else:
                lines.extend(
                    [
                        "",
                        f"Consensus claims: {len(payload.get('consensus_claims', []))}",
                        f"Disputed claims: {len(payload.get('disputed_claims', []))}",
                    ]
                )
            factors = payload.get("sensitivity_factors", [])
            if factors:
                lines.extend(["", "## Sensitivity Factors"])
                for item in factors[:5]:
                    lines.append(f"- {item}")
            return "\n".join(lines).strip()
        base_reports = payload.get("agent_reports", [])
        merges = payload.get("merge_reports", [])
        lines = [
            "# Final Answer",
            "",
            f"Synthesized from {len(base_reports)} analyze agents and {len(merges)} contradiction reports.",
            "",
            "## Consensus and Contradictions",
        ]

        if merges:
            for item in merges:
                label = item.get("label", "Merge Agent")
                goal = item.get("goal", "")
                signals = _extract_signal_lines(item.get("report", ""), max_lines=2)
                header = f"- {label}"
                if goal:
                    header += f" ({goal})"
                lines.append(header)
                for point in signals:
                    lines.append(f"  - {point}")
        else:
            final = (payload.get("report") or "").strip()
            if final:
                lines.extend(_extract_signal_lines(final, max_lines=8))
            else:
                lines.append("- No contradiction reports were returned.")

        lines.extend(
            [
                "",
                "## What To Do Next",
                "- Use this summary for your decision baseline.",
                "- Inspect raw merge reports below for full nuance and citation depth.",
                "",
                "## Raw Merge Reports",
            ]
        )
        return "\n".join(lines).strip()

    return _render_report_text(mode, payload)


def _render_report_text(mode: str, payload: dict[str, Any]) -> str:
    if mode == "skim":
        if payload.get("final_answer"):
            parts = [payload.get("final_answer", "").strip(), "", "## Claims"]
            for claim in payload.get("claims", [])[:12]:
                parts.append(
                    f"- {claim.get('claim_id', '?')}: {claim.get('statement', '')} "
                    f"[{claim.get('confidence_tier', 'unknown')}]"
                )
            return "\n".join(parts).strip()
        reports = payload.get("skim_reports", [])
        if not reports:
            return (payload.get("report") or "").strip()
        blocks = []
        for item in reports:
            agent = item.get("agent", "?")
            query = item.get("query", "")
            text = (item.get("report", "") or "").strip()
            blocks.append(f"## Skim Agent {agent}\nQuery: {query}\n\n{text}")
        return "\n\n".join(blocks).strip()

    if mode == "research":
        if payload.get("final_synthesis"):
            graph = payload.get("evidence_graph", {})
            nodes = len(graph.get("nodes", [])) if isinstance(graph, dict) else 0
            edges = len(graph.get("edges", [])) if isinstance(graph, dict) else 0
            lines = [
                payload.get("final_synthesis", "").strip(),
                "",
                f"Graph nodes: {nodes}",
                f"Graph edges: {edges}",
            ]
            return "\n".join(lines).strip()
        synthesis = payload.get("synthesis_reports", [])
        if not synthesis:
            return payload.get("final_report", "No synthesis reports returned.")
        blocks = []
        for item in synthesis:
            group = item.get("group", "?")
            queries = ", ".join(item.get("queries", []))
            report = (item.get("report", "") or "").strip()
            head = f"## Synthesis Block {group}"
            if queries:
                head += f"\nSub-queries: {queries}"
            blocks.append(f"{head}\n\n{report}")
        return "\n\n".join(blocks).strip()

    if mode == "analyze":
        if payload.get("recommended_position"):
            decision_matrix = payload.get("decision_matrix")
            if isinstance(decision_matrix, list) and not decision_matrix:
                lines = [payload.get("recommended_position", "").strip()]
                disputed = len(payload.get("disputed_claims", []))
                lines.append("")
                lines.append(f"Fact claims reviewed: {len(payload.get('consensus_claims', []))}")
                if disputed:
                    lines.append(f"Disputed claims: {disputed}")
                factors = payload.get("sensitivity_factors", [])
                if factors:
                    lines.extend(["", "## Sensitivity Factors"])
                    for item in factors[:5]:
                        lines.append(f"- {item}")
                return "\n".join(lines).strip()

            lines = [
                payload.get("recommended_position", "").strip(),
                "",
                "## Decision Matrix",
            ]
            for row in decision_matrix or []:
                lines.append(f"### {row.get('dimension', 'Dimension')}")
                for option in row.get("options", []):
                    lines.append(
                        f"- {option.get('option_name', 'Option')}: score={option.get('score', 0)} "
                        f":: {option.get('rationale', '')}"
                    )
                lines.append("")
            return "\n".join(lines).strip()
        base = (payload.get("report") or "").strip()
        merges = payload.get("merge_reports", [])
        if not merges:
            return base
        parts = [base, "", "## Contradiction Merge Reports"] if base else ["## Contradiction Merge Reports"]
        for item in merges:
            label = item.get("label", "Merge Agent")
            goal = item.get("goal", "")
            text = (item.get("report", "") or "").strip()
            parts.append(f"### {label}")
            if goal:
                parts.append(f"Goal: {goal}")
            parts.append(text)
            parts.append("")
        return "\n".join(parts).strip()

    return (
        payload.get("final_answer")
        or payload.get("recommended_position")
        or payload.get("final_synthesis")
        or payload.get("report")
        or payload.get("final_report")
        or ""
    ).strip()


def _render_result_console(console: Console, mode: str, payload: dict[str, Any]) -> None:
    if mode in {"skim", "research", "analyze"}:
        raw = _render_report_text(mode, payload)
        if raw:
            console.print(Panel(raw, title="Raw Reports", border_style="cyan"))

    summary = _tui_consumer_summary(mode, payload)
    if summary:
        console.print(Panel(summary, title="Final Answer", border_style="green"))

    details = _detail_lines(mode, payload)
    if details:
        table = Table(title="Details", show_header=False)
        table.add_column("Key", style="yellow")
        for line in details:
            table.add_row(line)
        console.print(table)


async def run_tui(args: argparse.Namespace) -> int:
    console = Console()
    session = PromptSession()
    mode = "peek"
    last_query = ""
    last_payload: dict[str, Any] = {}
    last_mode = mode

    console.print("[bold]ExpressIndex[/bold] simple TUI")
    console.print("Commands: :mode <peek|skim|analyze|research>, :save [path], :status, :help, :quit")

    while True:
        prompt = f"[{mode}] query> "
        with patch_stdout():
            text = await session.prompt_async(prompt)
        text = text.strip()
        if not text:
            continue

        if text.startswith(":"):
            parts = text[1:].split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else ""

            if cmd in {"q", "quit", "exit"}:
                return 0
            if cmd == "help":
                console.print("Use normal text to run query in current mode.")
                console.print(":mode skim | :mode analyze | :mode research | :mode peek")
                console.print(":save report.md  (or :save for auto filename)")
                console.print(":status to check agent pool")
                continue
            if cmd == "mode":
                candidate = arg.strip().lower()
                if candidate in QUERY_MODES:
                    mode = candidate
                    console.print(f"Mode set to [bold]{mode}[/bold]")
                else:
                    console.print(f"Invalid mode: {candidate}")
                continue
            if cmd == "save":
                if not last_payload:
                    console.print("Nothing to save yet.")
                    continue
                path = arg.strip()
                if not path:
                    base = last_query.strip().replace(" ", "-")[:48] or "report"
                    path = f"{base}-{last_mode}.md"
                Path(path).write_text(markdown_from_result(last_query, last_mode, last_payload), encoding="utf-8")
                console.print(f"Saved markdown: {path}")
                continue
            if cmd == "status":
                try:
                    status = await call_agent_status(args.mcp_url)
                    max_concurrent = int(status.get("max_concurrent", 0) or 0)
                    available = int(status.get("available", 0) or 0)
                    active = max(0, max_concurrent - available)
                    console.print(f"Agents active: {active}/{max_concurrent} (available={available})")
                except Exception as exc:
                    console.print(f"agent_status failed: {exc}")
                continue

            console.print(f"Unknown command: {cmd}")
            continue

        query = text
        console.print(f"Running [bold]{mode}[/bold]...", style="cyan")
        try:
            result = await call_mcp_tool(mode=mode, query=query, mcp_url=args.mcp_url)
        except Exception as exc:
            console.print(Panel(str(exc), title="Error", border_style="red"))
            continue

        last_query = query
        last_mode = mode
        last_payload = result.payload

        _render_result_console(console, mode, result.payload)
        count = result.payload.get("sources_count") or result.payload.get("total_sources")
        if count is None:
            count = len(result.payload.get("sources", []))
        meta = result.payload.get("_meta", {})
        took = meta.get("compute_ms", "?") if isinstance(meta, dict) else result.payload.get("search_time", "?")
        suffix = "ms" if isinstance(meta, dict) and meta.get("compute_ms") is not None else "s"
        console.print(f"Done. mode={mode} sources={count} time={took}{suffix}", style="green")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="expressindex", description="ExpressIndex MCP search client")
    parser.add_argument("mode", nargs="?", choices=MODES, help="Run one mode directly")
    parser.add_argument("query", nargs="?", help="Query text for direct mode")
    parser.add_argument("--tui", action="store_true", help="Launch interactive TUI")
    parser.add_argument("--mcp-url", default=MCP_URL_DEFAULT, help="MCP endpoint URL")
    parser.add_argument("--max-results", type=int, default=None, help="Result cap for peek/skim")
    parser.add_argument("--num-sub-queries", type=int, default=None, help="Sub-query count for research")
    parser.add_argument(
        "--fetch-content",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="For peek mode, fetch page content for each URL",
    )
    parser.add_argument(
        "--max-content-chars",
        type=int,
        default=4000,
        help="For peek mode, max fetched characters per source",
    )
    parser.add_argument(
        "--output",
        choices=["text", "json", "markdown"],
        default="text",
        help="Output format for direct mode",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Shortcut to print JSON output (same as --output json)",
    )
    parser.add_argument("--save-md", default=None, help="Write report to markdown file")
    return parser.parse_args()


async def run_direct(args: argparse.Namespace) -> int:
    output = "json" if args.json else args.output

    if not args.mode:
        raise SystemExit("Direct mode requires a mode")

    if args.mode in QUERY_MODES and not args.query:
        raise SystemExit("Query mode requires: expressindex <mode> \"query\"")

    if args.mode == "status":
        status_bundle = await call_status_bundle(args.mcp_url)
        if output == "json":
            print(json.dumps(status_bundle, indent=2))
        elif output == "markdown":
            print("# ExpressIndex Status\n\n```json\n" + json.dumps(status_bundle, indent=2) + "\n```")
        else:
            print(_render_status_text(status_bundle))
        return 0

    if args.mode == "metrics":
        metrics_payload = await call_metrics(args.mcp_url)
        if output == "json":
            print(json.dumps(metrics_payload, indent=2))
        elif output == "markdown":
            print("# ExpressIndex Metrics\n\n```json\n" + json.dumps(metrics_payload, indent=2) + "\n```")
        else:
            print(_render_metrics_text(metrics_payload))
        return 0

    result = await call_mcp_tool(
        mode=args.mode,
        query=args.query,
        mcp_url=args.mcp_url,
        max_results=args.max_results,
        num_sub_queries=args.num_sub_queries,
        fetch_content=args.fetch_content,
        max_content_chars=args.max_content_chars,
    )
    payload = result.payload
    if output == "json":
        print(json.dumps(payload, indent=2))
    elif output == "markdown":
        print(markdown_from_result(args.query, args.mode, payload))
    else:
        report = (
            _tui_consumer_summary(args.mode, payload)
            or payload.get("final_answer")
            or payload.get("recommended_position")
            or payload.get("final_synthesis")
            or payload.get("report")
            or payload.get("final_report")
        )
        if report:
            print(report)
        else:
            print(json.dumps(payload, indent=2))

    if args.save_md:
        Path(args.save_md).write_text(markdown_from_result(args.query, args.mode, payload), encoding="utf-8")
        print(f"Saved markdown: {args.save_md}")
    return 0


def main() -> None:
    args = parse_args()
    if args.tui:
        raise_code = asyncio.run(run_tui(args))
        if raise_code:
            raise SystemExit(raise_code)
        return
    raise_code = asyncio.run(run_direct(args))
    if raise_code:
        raise SystemExit(raise_code)


if __name__ == "__main__":
    main()
