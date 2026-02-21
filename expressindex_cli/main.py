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


MCP_URL_DEFAULT = "http://localhost:8000/mcp"
QUERY_MODES = ["peek", "skim", "analyze", "research"]
UTILITY_MODES = ["status", "metrics"]
MODES = QUERY_MODES + UTILITY_MODES


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return sanitize_payload(payload)


def _parse_options_arg(raw: Optional[str]) -> Optional[list[str]]:
    if not raw:
        return None
    options = [item.strip() for item in str(raw).split(",") if item.strip()]
    return options or None


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
    options: Optional[list[str]] = None,
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
    if mode == "analyze" and options:
        arguments["options"] = options

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
        _render_report_text(mode, payload)
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
        if payload.get("executed_mode") == "research":
            reason = payload.get("route_reason", "insufficient_comparative_signal")
            research_text = _render_report_text("research", payload)
            return f"Analyze routed to research: {reason}\n\n{research_text}".strip()

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

            lines = [payload.get("recommended_position", "").strip(), ""]
            options_compared = payload.get("options_compared", [])
            if options_compared:
                lines.append("Options compared: " + ", ".join(str(item) for item in options_compared[:5]))
            if payload.get("recommended_option"):
                lines.append(
                    f"Recommended option: {payload.get('recommended_option')} ({payload.get('confidence', 'unknown')})"
                )
            why_not = payload.get("why_not", [])
            if why_not:
                lines.extend(["", "## Tradeoffs"])
                for item in why_not[:3]:
                    lines.append(f"- {item}")
            lines.extend(["", "## Decision Matrix"])
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="expressindex", description="ExpressIndex MCP search client")
    parser.add_argument("mode", nargs="?", choices=MODES, help="Run one mode directly")
    parser.add_argument("query", nargs="?", help="Query text for direct mode")
    parser.add_argument("--mcp-url", default=MCP_URL_DEFAULT, help="MCP endpoint URL")
    parser.add_argument("--max-results", type=int, default=None, help="Result cap for peek/skim")
    parser.add_argument("--num-sub-queries", type=int, default=None, help="Sub-query count for research")
    parser.add_argument(
        "--options",
        default=None,
        help="For analyze mode, comma-separated options to compare (example: 'python,node,go').",
    )
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
        options=_parse_options_arg(args.options),
    )
    payload = result.payload
    if output == "json":
        print(json.dumps(payload, indent=2))
    elif output == "markdown":
        print(markdown_from_result(args.query, args.mode, payload))
    else:
        report = (
            _render_report_text(args.mode, payload)
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
    raise_code = asyncio.run(run_direct(args))
    if raise_code:
        raise SystemExit(raise_code)


if __name__ == "__main__":
    main()
