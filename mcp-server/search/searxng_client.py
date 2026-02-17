import aiohttp
import asyncio
import logging
import re
from html import unescape
from html.parser import HTMLParser
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("searxng-client")


class _SimpleHTMLToMarkdown(HTMLParser):
    """Small HTML -> markdown-ish converter for fetched pages."""

    def __init__(self):
        super().__init__()
        self.parts: List[str] = []
        self._skip_depth = 0
        self._href_stack: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple[str, Optional[str]]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
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
        elif tag == "a":
            href = ""
            for key, value in attrs:
                if key == "href" and value:
                    href = value
                    break
            self._href_stack.append(href)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript"}:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if self._skip_depth > 0:
            return

        if tag in {"pre", "code"}:
            self.parts.append("`")
        elif tag == "a" and self._href_stack:
            href = self._href_stack.pop()
            if href:
                self.parts.append(f" ({href})")

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
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    search_url, 
                    params=params, 
                    timeout=self._request_timeout()
                ) as response:
                    if response.status != 200:
                        msg = f"SearXNG returned status {response.status}"
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
                    
                    logger.info(f"Found {len(results)} results for query: {query}")
                    return results
                    
        except asyncio.TimeoutError:
            msg = f"Search timeout for query: {query}"
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
            
    async def fetch_url_content(self, url: str, max_length: int = 5000) -> str:
        """Fetch and extract markdown-ish text content from a URL."""
        try:
            async with aiohttp.ClientSession() as session:
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
                            parser = _SimpleHTMLToMarkdown()
                            parser.feed(body)
                            parser.close()
                            markdown = parser.markdown()
                            return markdown[:max_length]

                        plain = re.sub(r"\s+", " ", body).strip()
                        return plain[:max_length]
                    return ""
        except Exception as e:
            logger.warning(f"Failed to fetch {url}: {e}")
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
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    f"{self.base_url}/healthz",
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    return response.status == 200
        except Exception:
            return False
