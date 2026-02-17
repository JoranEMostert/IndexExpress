import asyncio
import logging
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from search.llm_client import LLMClient

logger = logging.getLogger("summarizer")


@dataclass
class SummarizationResult:
    original_count: int
    summary: str
    key_points: List[str]
    sources: List[Dict[str, str]]


class Summarizer:
    """Advanced summarization for research results."""
    
    def __init__(self, llm_client: LLMClient):
        self.llm = llm_client
        
    async def summarize(
        self,
        results: List[Dict[str, Any]],
        query: str,
        style: str = "detailed"
    ) -> SummarizationResult:
        """Summarize multiple search results."""
        
        content_text = ""
        sources = []
        
        for r in results[:15]:
            title = r.get('title', 'Unknown')
            content = r.get('content', '') or r.get('fetched_markdown', '') or r.get('fetched_content', '')
            url = r.get('url', '')
            
            content_text += f"\n### {title}\n{content[:1000]}\n"
            sources.append({'title': title, 'url': url})
        
        prompt = f"""Summarize the following research results for: "{query}"

Style: {style}

RESULTS:
{content_text}

Provide:
1. A comprehensive summary (2-3 paragraphs)
2. A list of key points (5-7 bullet points)

Format your response as JSON with keys: "summary", "key_points" (array)"""

        response = await self.llm.complete(
            prompt=prompt,
            temperature=0.5,
            max_tokens=1500
        )
        
        try:
            import json
            data = json.loads(response.content)
            summary = data.get('summary', response.content)
            key_points = data.get('key_points', [])
        except:
            summary = response.content
            key_points = []
        
        return SummarizationResult(
            original_count=len(results),
            summary=summary,
            key_points=key_points,
            sources=sources
        )
    
    async def extensive_report(
        self,
        clustered_data: Dict[str, Any],
        query: str
    ) -> str:
        """Generate an extensive, detailed report (used by DeepSearch)."""
        
        sources_text = ""
        
        for source in clustered_data.get('all_sources', [])[:40]:
            sources_text += f"""
[{source.get('title', 'Unknown')}]
{source.get('content', '')}
---
"""
        
        prompt = f"""Create a COMPREHENSIVE research report for: "{query}"

Use the following sources to create an in-depth analysis:

{sources_text}

Requirements:
- Executive summary with key findings
- Detailed breakdown by topic
- Source citations
- Any conflicting information
- Conclusions and implications

This is for deep research - be thorough and detailed."""
        
        response = await self.llm.complete(
            prompt=prompt,
            temperature=0.4,
            max_tokens=5000
        )
        
        return response.content
