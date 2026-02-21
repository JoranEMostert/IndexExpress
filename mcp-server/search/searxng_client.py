import aiohttp
import asyncio
import json
import logging
import random
import re
from html import unescape
from html.parser import HTMLParser
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("searxng-client")


READABILITY_BLOCK_PATTERNS = [
    r"(?is)<main\b[^>]*>(.*?)</main>",
    r"(?is)<article\b[^>]*>(.*?)</article>",
]

READABILITY_DROP_TAGS = (
    "script",
    "style",
    "noscript",
    "svg",
    "canvas",
    "iframe",
    "form",
    "button",
    "input",
    "select",
    "textarea",
    "header",
    "footer",
    "nav",
    "aside",
    "menu",
)

READABILITY_DROP_ATTR_MARKERS = (
    "nav",
    "menu",
    "footer",
    "header",
    "sidebar",
    "breadcrumb",
    "cookie",
    "subscribe",
    "social",
    "share",
    "comment",
    "related",
    "recommend",
    "promo",
    "advert",
)

LOW_SIGNAL_LINE_MARKERS = (
    "skip to",
    "open menu",
    "open navigation",
    "log in",
    "sign in",
    "sign up",
    "privacy policy",
    "terms",
    "cookie",
    "newsletter",
    "follow us",
    "share this",
    "go to reddit home",
    "select citation style",
    "thank you for your feedback",
    "external websites",
    "related articles",
)

MARKUP_GARBAGE_MARKERS = (
    "href=",
    "class=",
    "id=",
    "aria-",
    "data-",
    "role=",
    " tw:",
    "</",
    "<script",
    "<style",
)


def _strip_tag_blocks(html: str, tag: str) -> str:
    return re.sub(fr"(?is)<{tag}\b[^>]*>.*?</{tag}>", " ", html)


def _strip_attr_marked_blocks(html: str) -> str:
    marker_pattern = "|".join(re.escape(item) for item in READABILITY_DROP_ATTR_MARKERS)
    pattern = (
        r"(?is)<(?P<tag>[a-z0-9]+)\b[^>]*(?:id|class)=[\"'][^\"']*"
        + marker_pattern
        + r"[^\"']*[\"'][^>]*>.*?</(?P=tag)>"
    )
    cleaned = html
    for _ in range(3):
        updated = re.sub(pattern, " ", cleaned)
        if updated == cleaned:
            break
        cleaned = updated
    return cleaned


def _candidate_text_score(fragment: str) -> float:
    plain = re.sub(r"(?is)<[^>]+>", " ", fragment)
    plain = re.sub(r"\s+", " ", plain).strip()
    if not plain:
        return 0.0
    link_count = len(re.findall(r"(?is)<a\b", fragment))
    punctuation = sum(plain.count(ch) for ch in ".?!")
    return float(len(plain) + (punctuation * 6) - (link_count * 65))


def _iter_jsonlike_nodes(payload: object) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    queue: list[object] = [payload]
    while queue:
        item = queue.pop(0)
        if isinstance(item, dict):
            nodes.append(item)
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)
            for value in item.values():
                if isinstance(value, list):
                    queue.extend(value)
                elif isinstance(value, dict):
                    queue.append(value)
        elif isinstance(item, list):
            queue.extend(item)
    return nodes


def _extract_structured_article_text(html: str) -> str:
    blobs = re.findall(
        r"(?is)<script[^>]*type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        html,
    )
    candidates: list[str] = []
    for blob in blobs:
        text = unescape((blob or "").strip())
        if not text:
            continue
        try:
            payload = json.loads(text)
        except Exception:
            continue

        for node in _iter_jsonlike_nodes(payload):
            body = node.get("articleBody")
            if isinstance(body, str) and len(body.strip()) >= 60:
                headline = node.get("headline") or node.get("name") or ""
                if isinstance(headline, str) and headline.strip():
                    candidates.append(f"# {headline.strip()}\n\n{body.strip()}")
                else:
                    candidates.append(body.strip())

            description = node.get("description")
            if isinstance(description, str) and len(description.strip()) >= 120:
                candidates.append(description.strip())

    if candidates:
        candidates.sort(key=len, reverse=True)
        return candidates[0]

    meta = re.search(
        r"(?is)<meta[^>]+(?:name|property)=[\"'](?:description|og:description)[\"'][^>]+content=[\"']([^\"']+)[\"']",
        html,
    )
    if meta and len(meta.group(1).strip()) >= 120:
        return meta.group(1).strip()

    return ""


def _extract_paragraph_fallback(html: str) -> str:
    chunks = re.findall(r"(?is)<(?:p|li|h2|h3|h4)[^>]*>(.*?)</(?:p|li|h2|h3|h4)>", html)
    lines: list[str] = []
    for chunk in chunks:
        plain = re.sub(r"(?is)<[^>]+>", " ", chunk)
        plain = re.sub(r"\s+", " ", unescape(plain)).strip()
        if len(plain) < 45:
            continue
        lines.append(plain)
        if len(lines) >= 28:
            break
    return "\n\n".join(lines)


def _extract_readability_fragment(html: str) -> str:
    best = ""
    best_score = 0.0
    for pattern in READABILITY_BLOCK_PATTERNS:
        for match in re.findall(pattern, html):
            score = _candidate_text_score(match)
            if score > best_score:
                best_score = score
                best = match

    if best and best_score >= 300:
        return best

    paragraph_fallback = _extract_paragraph_fallback(html)
    if paragraph_fallback:
        return paragraph_fallback

    return html


def _prepare_html_for_readability(html: str) -> str:
    cleaned = re.sub(r"(?is)<!--.*?-->", " ", html)
    for tag in READABILITY_DROP_TAGS:
        cleaned = _strip_tag_blocks(cleaned, tag)
    cleaned = _strip_attr_marked_blocks(cleaned)
    return _extract_readability_fragment(cleaned)


def _post_process_markdown(text: str) -> str:
    lines = [line.strip() for line in text.splitlines()]
    kept: List[str] = []
    for line in lines:
        if not line:
            continue
        lowered = line.lower()
        if any(marker in lowered for marker in LOW_SIGNAL_LINE_MARKERS):
            continue
        if any(marker in lowered for marker in MARKUP_GARBAGE_MARKERS):
            continue
        if lowered.startswith("(http"):
            continue
        if lowered.endswith('">') or lowered.startswith("-") and "\">" in lowered:
            continue
        if ".jpg" in lowered or ".png" in lowered or ".svg" in lowered:
            continue
        if len(re.findall(r"https?://|www\.", line)) >= 1:
            continue
        if line.count(" - ") >= 4:
            continue
        alpha_chars = sum(1 for ch in line if ch.isalpha())
        punct_chars = sum(1 for ch in line if ch in "<>/=:_\"'[]{}")
        if alpha_chars > 0 and (punct_chars / alpha_chars) > 0.22:
            continue
        kept.append(line)

    compact = "\n\n".join(kept)
    compact = re.sub(r"\n{3,}", "\n\n", compact)
    return compact.strip()


class _SimpleHTMLToMarkdown(HTMLParser):
    """Small HTML -> markdown-ish converter for fetched pages."""

    def __init__(self):
        super().__init__()
        self.parts: List[str] = []
        self._skip_depth = 0

    @staticmethod
    def _should_skip_tag(tag: str) -> bool:
        return tag in READABILITY_DROP_TAGS

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if self._should_skip_tag(tag):
            self._skip_depth += 1
            return
        if self._skip_depth > 0:
            return

        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            level = int(tag[1])
            self.parts.append("\n" + ("#" * level) + " ")
        elif tag in {"p", "section", "article", "div"}:
            self.parts.append("\n\n")
        elif tag == "br":
            self.parts.append("\n")
        elif tag in {"li"}:
            self.parts.append("\n- ")
        elif tag in {"pre", "code"}:
            self.parts.append("`")
        elif tag in {"table"}:
            self.parts.append("\n\n")
        elif tag in {"tr"}:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append(" | ")

        del attrs

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if self._should_skip_tag(tag):
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth > 0:
            return

        if tag in {"pre", "code"}:
            self.parts.append("`")
        elif tag in {"td", "th"}:
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if self._skip_depth > 0:
            return
        if data:
            self.parts.append(data)

    def markdown(self) -> str:
        text = unescape("".join(self.parts))
        text = re.sub(r"\r", "", text)
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


@dataclass
class SearchResult:
    url: str
    title: str
    content: str
    engine: str
    score: float = 0.0


class SearXNGClient:
    """Async client for interacting with SearXNG instance."""
    
    def __init__(self, base_url: str, timeout: Optional[int] = 30):
        self.base_url = base_url.rstrip('/')
        self.timeout = timeout
        self.retries = 2
        self.retry_base_ms = 250
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

    def configure_retries(self, retries: int, retry_base_ms: int) -> None:
        self.retries = max(0, retries)
        self.retry_base_ms = max(20, retry_base_ms)

    def _retry_delay(self, attempt: int) -> float:
        base = self.retry_base_ms / 1000.0
        jitter = random.uniform(0, base * 0.2)
        return (base * (2**attempt)) + jitter

    @staticmethod
    def _is_retryable_status(status: int) -> bool:
        return status in {408, 409, 425, 429} or status >= 500

    async def _get_session(self) -> aiohttp.ClientSession:
        async with self._session_lock:
            if self._session is None or self._session.closed:
                self._session = aiohttp.ClientSession()
            return self._session

    async def close(self) -> None:
        async with self._session_lock:
            if self._session is not None and not self._session.closed:
                await self._session.close()
            self._session = None

    def _request_timeout(self) -> aiohttp.ClientTimeout:
        if self.timeout is None or self.timeout <= 0:
            return aiohttp.ClientTimeout(total=None)
        return aiohttp.ClientTimeout(total=self.timeout)
        
    async def search(
        self, 
        query: str, 
        engines: Optional[List[str]] = None,
        categories: Optional[List[str]] = None,
        max_results: int = 20,
        language: str = "en",
        strict: bool = False
    ) -> List[SearchResult]:
        """Perform a search query against SearXNG."""
        search_url = f"{self.base_url}/search"
        
        params = {
            'q': query,
            'format': 'json',
            'language': language,
            'max_results': max_results
        }
        
        if engines:
            params['engines'] = ','.join(engines)
        if categories:
            params['categories'] = ','.join(categories)
            
        for attempt in range(self.retries + 1):
            try:
                session = await self._get_session()
                async with session.get(
                    search_url,
                    params=params,
                    timeout=self._request_timeout()
                ) as response:
                    if response.status != 200:
                        msg = f"SearXNG returned status {response.status}"
                        retryable = self._is_retryable_status(response.status)
                        if retryable and attempt < self.retries:
                            logger.warning("SearXNG retrying status=%s attempt=%s", response.status, attempt + 1)
                            await asyncio.sleep(self._retry_delay(attempt))
                            continue
                        logger.error(msg)
                        if strict:
                            raise RuntimeError(msg)
                        return []

                    data = await response.json()
                    results = []

                    for item in data.get('results', []):
                        result = SearchResult(
                            url=item.get('url', ''),
                            title=item.get('title', ''),
                            content=item.get('content', ''),
                            engine=item.get('engine', 'unknown'),
                            score=item.get('score', 0.0)
                        )
                        results.append(result)

                    logger.info("Found %s results for query: %s", len(results), query)
                    return results

            except asyncio.TimeoutError:
                msg = f"Search timeout for query: {query}"
                if attempt < self.retries:
                    logger.warning("%s; retrying attempt=%s", msg, attempt + 1)
                    await asyncio.sleep(self._retry_delay(attempt))
                    continue
                logger.error(msg)
                if strict:
                    raise RuntimeError(msg)
                return []
            except aiohttp.ClientError as e:
                msg = f"Search error: {e}"
                if attempt < self.retries:
                    logger.warning("%s; retrying attempt=%s", msg, attempt + 1)
                    await asyncio.sleep(self._retry_delay(attempt))
                    continue
                logger.error(msg)
                if strict:
                    raise RuntimeError(msg)
                return []
            except Exception as e:
                msg = f"Search error: {e}"
                logger.error(msg)
                if strict:
                    raise RuntimeError(msg)
                return []

        return []
            
    async def fetch_url_content(self, url: str, max_length: int = 5000) -> str:
        """Fetch and extract markdown-ish text content from a URL."""
        for attempt in range(self.retries + 1):
            try:
                session = await self._get_session()
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=15),
                    headers={'User-Agent': 'Mozilla/5.0 (compatible; SearXNG-MCP/1.0)'}
                ) as response:
                    if response.status == 200:
                        content_type = (response.headers.get("Content-Type") or "").lower()
                        body = await response.text(errors="ignore")
                        if not body:
                            return ""

                        if "html" in content_type or "<html" in body.lower():
                            structured = _extract_structured_article_text(body)
                            if structured:
                                markdown = _post_process_markdown(structured)
                                if markdown:
                                    return markdown[:max_length]

                            prepared = _prepare_html_for_readability(body)
                            parser = _SimpleHTMLToMarkdown()
                            parser.feed(prepared)
                            parser.close()
                            markdown = _post_process_markdown(parser.markdown())
                            return markdown[:max_length]

                        plain = _post_process_markdown(re.sub(r"\s+", " ", body).strip())
                        return plain[:max_length]

                    if self._is_retryable_status(response.status) and attempt < self.retries:
                        await asyncio.sleep(self._retry_delay(attempt))
                        continue
                    return ""
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                if attempt < self.retries:
                    logger.warning("Failed to fetch %s attempt=%s: %s", url, attempt + 1, e)
                    await asyncio.sleep(self._retry_delay(attempt))
                    continue
                logger.warning("Failed to fetch %s: %s", url, e)
                return ""
            except Exception as e:
                logger.warning("Failed to fetch %s: %s", url, e)
                return ""

        return ""

    async def enrich_sources_with_content(
        self,
        sources: List[Dict[str, Any]],
        max_length: int = 4000,
        max_parallel: int = 6,
    ) -> List[Dict[str, Any]]:
        """Fetch page content for each source URL and attach it."""

        semaphore = asyncio.Semaphore(max(1, max_parallel))

        async def enrich_one(source: Dict[str, Any]) -> Dict[str, Any]:
            row = dict(source)
            url = row.get("url", "")
            if not url:
                row["fetched_markdown"] = ""
                return row

            async with semaphore:
                text = await self.fetch_url_content(url, max_length=max_length)
            row["fetched_markdown"] = text
            return row

        tasks = [asyncio.create_task(enrich_one(source)) for source in sources]
        return await asyncio.gather(*tasks)
            
    async def health_check(self) -> bool:
        """Check if SearXNG is healthy."""
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/healthz",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                return response.status == 200
        except Exception:
            return False
