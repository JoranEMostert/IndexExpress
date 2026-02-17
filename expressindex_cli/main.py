import argparse
import asyncio
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import aiohttp
from rich.text import Text
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, RichLog, Select, Static


MCP_URL_DEFAULT = "http://localhost:8000/mcp"
MODES = ["peek", "skim", "analyze", "research"]


def _strip_think_tags(text: str) -> str:
    if not text:
        return ""
    cleaned = re.sub(r"<think>[\s\S]*?(</think>|$)", "", text, flags=re.IGNORECASE)
    return cleaned.strip()


def _sanitize_payload(payload: dict[str, Any]) -> dict[str, Any]:
    sanitized = dict(payload)
    for key in ("report", "final_report", "agent_a_report", "agent_b_report"):
        if key in sanitized and isinstance(sanitized[key], str):
            sanitized[key] = _strip_think_tags(sanitized[key])

    for list_key in ("cluster_reports", "synthesis_reports", "merge_reports"):
        report_rows = sanitized.get(list_key)
        if isinstance(report_rows, list):
            patched = []
            for item in report_rows:
                if isinstance(item, dict):
                    row = dict(item)
                    if isinstance(row.get("report"), str):
                        row["report"] = _strip_think_tags(row["report"])
                    patched.append(row)
                else:
                    patched.append(item)
            sanitized[list_key] = patched

    return sanitized


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
        "id": 1,
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


def markdown_from_result(query: str, mode: str, payload: dict[str, Any]) -> str:
    lines = [f"# ExpressIndex {mode.title()} Report", "", f"Query: {query}", ""]
    report = payload.get("report") or payload.get("final_report")
    if report:
        lines.append(report)
    else:
        lines.append("## Sources")
        for i, src in enumerate(payload.get("sources", []), start=1):
            title = src.get("title", "Untitled")
            url = src.get("url", "")
            lines.append(f"{i}. [{title}]({url})")

    if payload.get("search_time") is not None:
        lines.extend(["", f"Search time: {payload['search_time']}s"])
    return "\n".join(lines)


def _source_lines(payload: dict[str, Any]) -> list[str]:
    sources = payload.get("sources", [])
    lines = []
    for i, src in enumerate(sources, start=1):
        lines.append(f"[{i}] {src.get('title', 'Untitled')} - {src.get('url', '')}")
    return lines


class ExpressIndexTUI(App):
    CSS = """
    Screen { layout: vertical; }
    #controls { height: 3; }
    #query { width: 1fr; }
    #status { height: 3; border: round $accent; padding: 0 1; }
    #report { height: 1fr; border: round $primary; }
    #sources { height: 14; border: round $secondary; }
    #leftcol { width: 34%; }
    #rightcol { width: 66%; }
    #body { height: 1fr; }
    """

    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "run_query", "Run"),
        ("s", "save_report", "Save Markdown"),
    ]

    def __init__(self, mcp_url: str):
        super().__init__()
        self.mcp_url = mcp_url
        self._running = False
        self._last_query = ""
        self._last_mode = "peek"
        self._last_payload: dict[str, Any] = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="controls"):
            yield Select(((m, m.title()) for m in MODES), value="peek", id="mode")
            yield Input(placeholder="Type your query and press Run...", id="query")
            yield Button("Run", id="run", variant="primary")
            yield Button("Save MD", id="save", variant="success")

        with Horizontal(id="body"):
            with Vertical(id="leftcol"):
                yield Static("Ready.", id="status")
                yield RichLog(id="sources", wrap=True, highlight=True, markup=False)
            with Vertical(id="rightcol"):
                yield RichLog(id="report", wrap=True, highlight=True, markup=False)

        yield Footer()

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)

    async def action_run_query(self) -> None:
        if self._running:
            return
        await self._run()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run":
            await self._run()
        elif event.button.id == "save":
            await self.action_save_report()

    async def _run(self) -> None:
        query = self.query_one("#query", Input).value.strip()
        mode = str(self.query_one("#mode", Select).value)
        if not query:
            self._set_status("Please enter a query.")
            return

        report_log = self.query_one("#report", RichLog)
        sources_log = self.query_one("#sources", RichLog)
        report_log.clear()
        sources_log.clear()
        self._running = True
        self._set_status(f"Running {mode}...")

        spinner_task = asyncio.create_task(self._spinner(mode))
        try:
            result = await call_mcp_tool(mode=mode, query=query, mcp_url=self.mcp_url)
            self._last_query = query
            self._last_mode = mode
            self._last_payload = result.payload

            await self._stream_payload(result.payload, report_log, sources_log)
            count = result.payload.get("sources_count") or result.payload.get("total_sources") or 0
            took = result.payload.get("search_time", "?")
            self._set_status(f"Done. mode={mode} sources={count} time={took}s")
        except Exception as exc:
            self._set_status(f"Error: {exc}")
            report_log.write(Text(str(exc), style="bold red"))
        finally:
            self._running = False
            spinner_task.cancel()

    async def _spinner(self, mode: str) -> None:
        states = ["Searching", "Fetching pages", "Thinking", "Finalizing"]
        if mode in {"skim", "analyze", "research"}:
            states = ["Searching", "Thinking", "Thinking", "Finalizing"]
        idx = 0
        while True:
            self._set_status(f"{states[idx % len(states)]} ({mode}) ...")
            idx += 1
            await asyncio.sleep(0.45)

    async def _stream_payload(self, payload: dict[str, Any], report_log: RichLog, sources_log: RichLog) -> None:
        report = payload.get("report") or payload.get("final_report")
        if report:
            chunk = []
            for ch in report:
                chunk.append(ch)
                if len(chunk) >= 24 or ch == "\n":
                    report_log.write("".join(chunk))
                    chunk.clear()
                    await asyncio.sleep(0.01)
            if chunk:
                report_log.write("".join(chunk))
        else:
            for source in payload.get("sources", []):
                report_log.write(f"- {source.get('title', 'Untitled')}\n  {source.get('url', '')}")
                await asyncio.sleep(0.02)

        for line in _source_lines(payload):
            sources_log.write(line)

    async def action_save_report(self) -> None:
        if not self._last_payload:
            self._set_status("Nothing to save yet.")
            return
        base = self._last_query.strip().replace(" ", "-")[:48] or "report"
        path = Path.cwd() / f"{base}-{self._last_mode}.md"
        path.write_text(markdown_from_result(self._last_query, self._last_mode, self._last_payload), encoding="utf-8")
        self._set_status(f"Saved: {path.name}")


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
    parser.add_argument("--save-md", default=None, help="Write report to markdown file")
    return parser.parse_args()


async def run_direct(args: argparse.Namespace) -> int:
    if not args.mode or not args.query:
        raise SystemExit("Direct mode requires: expressindex <mode> \"query\"")

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
    report = payload.get("report") or payload.get("final_report")
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
        app = ExpressIndexTUI(mcp_url=args.mcp_url)
        app.run()
        return
    raise_code = asyncio.run(run_direct(args))
    if raise_code:
        raise SystemExit(raise_code)


if __name__ == "__main__":
    main()
