#!/usr/bin/env python3
import argparse
import asyncio
import json
import re
import sys
import time
from itertools import cycle
from typing import Any, Dict, Optional

import aiohttp


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="SearXNG Research TUI")
    parser.add_argument("mode", choices=["peek", "skim", "analyze", "research"], help="Search tier")
    parser.add_argument("query", help="Query text")
    parser.add_argument("--url", default="http://localhost:8000/mcp", help="Server endpoint")
    parser.add_argument("--max-results", type=int, default=None, help="Result limit for peek/skim")
    parser.add_argument("--num-sub-queries", type=int, default=None, help="Sub-queries for research")
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
    parser.add_argument("--save-md", default=None, help="Write report output to markdown file")
    parser.add_argument("--stream", action="store_true", help="Typewriter stream output")
    return parser.parse_args()


async def spinner(message: str, done_event: asyncio.Event) -> None:
    symbols = cycle(["|", "/", "-", "\\"])
    start = time.time()
    while not done_event.is_set():
        elapsed = time.time() - start
        sys.stdout.write(f"\r{next(symbols)} {message} ({elapsed:0.1f}s)")
        sys.stdout.flush()
        await asyncio.sleep(0.12)
    sys.stdout.write("\r")
    sys.stdout.flush()


def strip_think_tags(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<think>[\s\S]*?(</think>|$)", "", text, flags=re.IGNORECASE)
    return cleaned.strip()


def sanitize_payload(payload: Dict[str, Any]) -> Dict[str, Any]:
    cleaned = dict(payload)
    for key in ("report", "final_report", "agent_a_report", "agent_b_report"):
        if isinstance(cleaned.get(key), str):
            cleaned[key] = strip_think_tags(cleaned[key])
    for list_key in ("cluster_reports", "synthesis_reports", "merge_reports", "skim_reports"):
        rows = cleaned.get(list_key)
        if isinstance(rows, list):
            patched = []
            for item in rows:
                if isinstance(item, dict):
                    row = dict(item)
                    if isinstance(row.get("report"), str):
                        row["report"] = strip_think_tags(row["report"])
                    patched.append(row)
                else:
                    patched.append(item)
            cleaned[list_key] = patched
    return cleaned


async def call_tool(
    url: str,
    mode: str,
    query: str,
    max_results: Optional[int],
    num_sub_queries: Optional[int],
    fetch_content: bool,
    max_content_chars: int,
) -> Dict[str, Any]:
    args: Dict[str, Any] = {"query": query}
    if max_results is not None and mode in {"peek", "skim"}:
        args["max_results"] = max_results
    if mode == "peek":
        args["fetch_content"] = fetch_content
        args["max_content_chars"] = max_content_chars
    if num_sub_queries is not None and mode == "research":
        args["num_sub_queries"] = num_sub_queries

    payload = {
        "jsonrpc": "2.0",
        "id": int(time.time()),
        "method": "tools/call",
        "params": {"name": mode, "arguments": args},
    }

    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=None)) as response:
            if response.status != 200:
                text = await response.text()
                raise RuntimeError(f"Server error {response.status}: {text}")
            result = await response.json()
            if "error" in result:
                raise RuntimeError(result["error"].get("message", "Unknown server error"))
            return result["result"]


def extract_text_blob(result: Dict[str, Any]) -> Dict[str, Any]:
    content = result.get("content", [])
    if not content:
        return {}
    raw = content[0].get("text", "{}")
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"report": raw}


async def print_output(data: Dict[str, Any], stream: bool) -> None:
    if "report" in data:
        print("Report\n------")
        text = data.get("report", "")
        if stream:
            for ch in text:
                sys.stdout.write(ch)
                sys.stdout.flush()
                await asyncio.sleep(0.003)
            print()
        else:
            print(text)
    elif "final_report" in data:
        print("Report\n------")
        text = data.get("final_report", "")
        if stream:
            for ch in text:
                sys.stdout.write(ch)
                sys.stdout.flush()
                await asyncio.sleep(0.002)
            print()
        else:
            print(text)
    else:
        print("Sources\n-------")
        for idx, src in enumerate(data.get("sources", []), start=1):
            print(f"{idx}. {src.get('title', 'Untitled')}\n   {src.get('url', '')}")

    count = data.get("sources_count") or data.get("total_sources")
    if count is not None:
        print(f"\nSources: {count}")
    if "search_time" in data:
        print(f"Time: {data['search_time']}s")


def markdown_from_data(mode: str, data: Dict[str, Any], query: str) -> str:
    lines = [f"# {mode.title()} Report", "", f"Query: {query}", ""]
    if "report" in data:
        lines.append(data["report"])
    elif "final_report" in data:
        lines.append(data["final_report"])
    else:
        lines.append("## Sources")
        for idx, src in enumerate(data.get("sources", []), start=1):
            lines.append(f"{idx}. [{src.get('title', 'Untitled')}]({src.get('url', '')})")
    lines.append("")
    if "search_time" in data:
        lines.append(f"Search time: {data['search_time']}s")
    return "\n".join(lines)


async def main() -> None:
    args = parse_args()
    done = asyncio.Event()
    spin_message = f"Thinking ({args.mode})" if args.mode in {"skim", "analyze", "research"} else f"Running {args.mode}"
    spin_task = asyncio.create_task(spinner(spin_message, done))

    try:
        result = await call_tool(
            args.url,
            args.mode,
            args.query,
            args.max_results,
            args.num_sub_queries,
            args.fetch_content,
            args.max_content_chars,
        )
        done.set()
        await spin_task
        print(f"Done: {args.mode} complete")
        payload = sanitize_payload(extract_text_blob(result))
        await print_output(payload, args.stream)

        if args.save_md:
            md = markdown_from_data(args.mode, payload, args.query)
            with open(args.save_md, "w", encoding="utf-8") as fh:
                fh.write(md)
            print(f"Saved markdown: {args.save_md}")
    except Exception as exc:
        done.set()
        await spin_task
        print(f"Error: {exc}")
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
