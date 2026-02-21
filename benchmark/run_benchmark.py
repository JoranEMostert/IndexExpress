#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import aiohttp


MODES = ("peek", "skim", "analyze", "research")


@dataclass
class ModeRunResult:
    run_index: int
    mode: str
    query: str
    ok: bool
    http_status: int
    latency_ms: int
    payload_bytes: int
    schema_version: str
    sources_count: int
    evidence_count: int
    claims_count: int
    consensus_count: int
    disputed_count: int
    decision_dimensions: int
    open_questions_count: int
    requested_mode: str
    executed_mode: str
    route_reason: str
    analysis_type: str
    options_count: int
    confidence: str
    message_preview: str
    error: str


def _iso_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _query_for_mode(args: argparse.Namespace, mode: str) -> str:
    override = getattr(args, f"{mode}_query")
    return (override or args.query).strip()


def _tool_arguments(mode: str, query: str, args: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {"query": query}
    if mode in {"peek", "skim"} and args.max_results is not None:
        payload["max_results"] = args.max_results
    if mode == "peek":
        payload["fetch_content"] = args.peek_fetch_content
        if args.max_content_chars is not None:
            payload["max_content_chars"] = args.max_content_chars
    if mode == "research":
        payload["num_sub_queries"] = args.research_sub_queries
    return payload


def _safe_len(value: Any) -> int:
    return len(value) if isinstance(value, list) else 0


def _message_preview(payload: dict[str, Any]) -> str:
    for key in ("recommended_position", "final_answer", "final_synthesis"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            one_line = " ".join(value.strip().split())
            return one_line[:220]
    return ""


async def _call_mode(
    session: aiohttp.ClientSession,
    mcp_url: str,
    mode: str,
    query: str,
    run_index: int,
    args: argparse.Namespace,
) -> ModeRunResult:
    body = {
        "jsonrpc": "2.0",
        "id": f"bench-{run_index}-{mode}",
        "method": "tools/call",
        "params": {
            "name": mode,
            "arguments": _tool_arguments(mode, query, args),
        },
    }

    started = time.perf_counter()
    try:
        async with session.post(
            mcp_url,
            json=body,
            timeout=aiohttp.ClientTimeout(total=args.timeout_s),
        ) as response:
            raw = await response.text()
            latency_ms = int((time.perf_counter() - started) * 1000)
            status = int(response.status)
    except Exception as exc:
        latency_ms = int((time.perf_counter() - started) * 1000)
        return ModeRunResult(
            run_index=run_index,
            mode=mode,
            query=query,
            ok=False,
            http_status=0,
            latency_ms=latency_ms,
            payload_bytes=0,
            schema_version="",
            sources_count=0,
            evidence_count=0,
            claims_count=0,
            consensus_count=0,
            disputed_count=0,
            decision_dimensions=0,
            open_questions_count=0,
            requested_mode=mode,
            executed_mode=mode,
            route_reason="",
            analysis_type="",
            options_count=0,
            confidence="",
            message_preview="",
            error=str(exc),
        )

    if status != 200:
        return ModeRunResult(
            run_index=run_index,
            mode=mode,
            query=query,
            ok=False,
            http_status=status,
            latency_ms=latency_ms,
            payload_bytes=len(raw.encode("utf-8", errors="ignore")),
            schema_version="",
            sources_count=0,
            evidence_count=0,
            claims_count=0,
            consensus_count=0,
            disputed_count=0,
            decision_dimensions=0,
            open_questions_count=0,
            requested_mode=mode,
            executed_mode=mode,
            route_reason="",
            analysis_type="",
            options_count=0,
            confidence="",
            message_preview="",
            error=raw[:300],
        )

    try:
        envelope = json.loads(raw)
    except Exception as exc:
        return ModeRunResult(
            run_index=run_index,
            mode=mode,
            query=query,
            ok=False,
            http_status=status,
            latency_ms=latency_ms,
            payload_bytes=len(raw.encode("utf-8", errors="ignore")),
            schema_version="",
            sources_count=0,
            evidence_count=0,
            claims_count=0,
            consensus_count=0,
            disputed_count=0,
            decision_dimensions=0,
            open_questions_count=0,
            requested_mode=mode,
            executed_mode=mode,
            route_reason="",
            analysis_type="",
            options_count=0,
            confidence="",
            message_preview="",
            error=f"Invalid JSON envelope: {exc}",
        )

    if "error" in envelope:
        message = envelope.get("error", {}).get("message", "Unknown MCP error")
        return ModeRunResult(
            run_index=run_index,
            mode=mode,
            query=query,
            ok=False,
            http_status=status,
            latency_ms=latency_ms,
            payload_bytes=len(raw.encode("utf-8", errors="ignore")),
            schema_version="",
            sources_count=0,
            evidence_count=0,
            claims_count=0,
            consensus_count=0,
            disputed_count=0,
            decision_dimensions=0,
            open_questions_count=0,
            requested_mode=mode,
            executed_mode=mode,
            route_reason="",
            analysis_type="",
            options_count=0,
            confidence="",
            message_preview="",
            error=message,
        )

    content = envelope.get("result", {}).get("content", [])
    if not content:
        payload = {}
    else:
        raw_payload = content[0].get("text", "{}")
        try:
            payload = json.loads(raw_payload)
        except Exception as exc:
            return ModeRunResult(
                run_index=run_index,
                mode=mode,
                query=query,
                ok=False,
                http_status=status,
                latency_ms=latency_ms,
                payload_bytes=len(raw_payload.encode("utf-8", errors="ignore")),
                schema_version="",
                sources_count=0,
                evidence_count=0,
                claims_count=0,
                consensus_count=0,
                disputed_count=0,
                decision_dimensions=0,
                open_questions_count=0,
                requested_mode=mode,
                executed_mode=mode,
                route_reason="",
                analysis_type="",
                options_count=0,
                confidence="",
                message_preview="",
                error=f"Invalid tool payload JSON: {exc}",
            )

    return ModeRunResult(
        run_index=run_index,
        mode=mode,
        query=query,
        ok=True,
        http_status=status,
        latency_ms=latency_ms,
        payload_bytes=len(json.dumps(payload).encode("utf-8", errors="ignore")),
        schema_version=str(payload.get("schema_version", "")),
        sources_count=_safe_len(payload.get("sources")),
        evidence_count=_safe_len(payload.get("key_evidence")),
        claims_count=_safe_len(payload.get("claims")),
        consensus_count=_safe_len(payload.get("consensus_claims")),
        disputed_count=_safe_len(payload.get("disputed_claims")),
        decision_dimensions=_safe_len(payload.get("decision_matrix")),
        open_questions_count=_safe_len(payload.get("open_questions")),
        requested_mode=str(payload.get("requested_mode", mode)),
        executed_mode=str(payload.get("executed_mode", mode)),
        route_reason=str(payload.get("route_reason", "")),
        analysis_type=str(payload.get("analysis_type", "")),
        options_count=_safe_len(payload.get("options_compared")),
        confidence=str(payload.get("confidence", "")),
        message_preview=_message_preview(payload),
        error="",
    )


def _aggregate(results: list[ModeRunResult]) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "total_runs": len(results),
        "ok_runs": len([item for item in results if item.ok]),
        "failed_runs": len([item for item in results if not item.ok]),
        "per_mode": {},
    }
    for mode in MODES:
        rows = [item for item in results if item.mode == mode]
        if not rows:
            continue
        ok_rows = [item for item in rows if item.ok]
        latencies = [item.latency_ms for item in ok_rows]
        summary["per_mode"][mode] = {
            "runs": len(rows),
            "ok": len(ok_rows),
            "failed": len(rows) - len(ok_rows),
            "avg_latency_ms": round(statistics.mean(latencies), 2) if latencies else None,
            "min_latency_ms": min(latencies) if latencies else None,
            "max_latency_ms": max(latencies) if latencies else None,
            "avg_sources": round(statistics.mean([item.sources_count for item in ok_rows]), 2)
            if ok_rows
            else None,
            "routed": len(
                [item for item in ok_rows if item.requested_mode == "analyze" and item.executed_mode == "research"]
            ),
        }
    return summary


def _write_csv(path: Path, results: list[ModeRunResult]) -> None:
    fieldnames = list(asdict(results[0]).keys()) if results else [
        "run_index",
        "mode",
        "query",
        "ok",
        "http_status",
        "latency_ms",
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in results:
            writer.writerow(asdict(row))


def _write_markdown(path: Path, summary: dict[str, Any], results: list[ModeRunResult], mcp_url: str) -> None:
    lines = [
        "# Benchmark Report",
        "",
        f"- Generated at: {_iso_now()}",
        f"- MCP URL: `{mcp_url}`",
        f"- Total runs: {summary['total_runs']}",
        f"- Successful: {summary['ok_runs']}",
        f"- Failed: {summary['failed_runs']}",
        "",
        "## Per-Mode Summary",
        "",
        "| Mode | Runs | OK | Failed | Avg Latency (ms) | Min | Max | Avg Sources | Routed |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]

    per_mode = summary.get("per_mode", {})
    for mode in MODES:
        row = per_mode.get(mode, {})
        lines.append(
            "| "
            f"{mode} | {row.get('runs', 0)} | {row.get('ok', 0)} | {row.get('failed', 0)} | "
            f"{row.get('avg_latency_ms', '-') } | {row.get('min_latency_ms', '-') } | "
            f"{row.get('max_latency_ms', '-') } | {row.get('avg_sources', '-') } | {row.get('routed', 0)} |"
        )

    lines.extend(
        [
            "",
            "## Detailed Runs",
            "",
            "| Run | Mode | Exec | OK | HTTP | Latency (ms) | Sources | Evidence | Claims | Consensus | Disputed | Notes |",
            "|---:|---|---|---|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )

    for item in results:
        note = item.error or item.message_preview
        note = " ".join(note.split())[:120]
        lines.append(
            "| "
            f"{item.run_index} | {item.mode} | {item.executed_mode} | {str(item.ok).lower()} | {item.http_status} | "
            f"{item.latency_ms} | {item.sources_count} | {item.evidence_count} | {item.claims_count} | "
            f"{item.consensus_count} | {item.disputed_count} | {note} |"
        )

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


async def _run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    results: list[ModeRunResult] = []
    async with aiohttp.ClientSession() as session:
        for run_index in range(1, args.runs + 1):
            for mode in MODES:
                query = _query_for_mode(args, mode)
                result = await _call_mode(session, args.mcp_url, mode, query, run_index, args)
                results.append(result)

    summary = _aggregate(results)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base = f"benchmark_{stamp}"

    json_path = out_dir / f"{base}.json"
    csv_path = out_dir / f"{base}.csv"
    md_path = out_dir / f"{base}.md"

    payload = {
        "generated_at": _iso_now(),
        "mcp_url": args.mcp_url,
        "config": {
            "runs": args.runs,
            "default_query": args.query,
            "peek_query": args.peek_query,
            "skim_query": args.skim_query,
            "analyze_query": args.analyze_query,
            "research_query": args.research_query,
            "max_results": args.max_results,
            "research_sub_queries": args.research_sub_queries,
            "peek_fetch_content": args.peek_fetch_content,
            "max_content_chars": args.max_content_chars,
            "timeout_s": args.timeout_s,
        },
        "summary": summary,
        "results": [asdict(item) for item in results],
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    _write_csv(csv_path, results)
    _write_markdown(md_path, summary, results, args.mcp_url)

    print(f"Benchmark complete. JSON: {json_path}")
    print(f"Benchmark complete. CSV:  {csv_path}")
    print(f"Benchmark complete. MD:   {md_path}")
    print(
        "Result summary: "
        f"ok={summary['ok_runs']}/{summary['total_runs']}, failed={summary['failed_runs']}"
    )
    return 0


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run repeatable benchmarks for all ExpressIndex search modes."
    )
    parser.add_argument("--mcp-url", default="http://localhost:8000/mcp")
    parser.add_argument("--query", default="slug facts", help="Default query used for all modes.")
    parser.add_argument("--peek-query", default="", help="Optional override query for peek.")
    parser.add_argument("--skim-query", default="", help="Optional override query for skim.")
    parser.add_argument("--analyze-query", default="", help="Optional override query for analyze.")
    parser.add_argument("--research-query", default="", help="Optional override query for research.")
    parser.add_argument("--runs", type=int, default=1, help="How many full mode cycles to run.")
    parser.add_argument(
        "--max-results",
        type=int,
        default=None,
        help="Optional max_results for peek and skim.",
    )
    parser.add_argument(
        "--research-sub-queries",
        type=int,
        default=6,
        help="num_sub_queries for research mode.",
    )
    parser.add_argument(
        "--peek-fetch-content",
        action="store_true",
        default=False,
        help="Enable content fetch during peek for ranking quality.",
    )
    parser.add_argument(
        "--max-content-chars",
        type=int,
        default=4000,
        help="Maximum content chars used by peek when content fetch is enabled.",
    )
    parser.add_argument(
        "--timeout-s",
        type=int,
        default=300,
        help="Per-tool timeout in seconds.",
    )
    parser.add_argument(
        "--out-dir",
        default="benchmark/output_reports",
        help="Directory for benchmark result reports.",
    )
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    if args.runs < 1:
        parser.error("--runs must be >= 1")
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
