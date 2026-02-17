import aiohttp
import asyncio
import json
import logging
from typing import AsyncIterator, List, Dict, Any, Optional
from dataclasses import dataclass

logger = logging.getLogger("llm-client")


@dataclass
class LLMResponse:
    content: str
    model: str
    usage: Dict[str, int]


class LLMClient:
    """Async client for OpenAI-compatible LLM APIs (LM Studio, Ollama, OpenAI, etc.)."""
    
    def __init__(
        self, 
        api_url: str, 
        api_key: Optional[str] = None,
        model: str = "local-model",
        timeout: Optional[int] = None
    ):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def _request_timeout(self) -> aiohttp.ClientTimeout:
        if self.timeout is None or self.timeout <= 0:
            return aiohttp.ClientTimeout(total=None)
        return aiohttp.ClientTimeout(total=self.timeout)
        
    async def chat(
        self, 
        messages: List[Dict[str, str]], 
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> LLMResponse:
        """Send a chat completion request."""
        url = f"{self.api_url}/chat/completions"
        
        headers = {
            'Content-Type': 'application/json'
        }
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'
            
        payload = {
            'model': self.model,
            'messages': messages,
            'temperature': temperature
        }
        if max_tokens:
            payload['max_tokens'] = max_tokens
            
        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    url, 
                    json=payload, 
                    headers=headers,
                    timeout=self._request_timeout()
                ) as response:
                    if response.status != 200:
                        error = await response.text()
                        logger.error(f"LLM API error: {response.status} - {error}")
                        return LLMResponse(
                            content=f"Error: API returned {response.status}",
                            model=self.model,
                            usage={'prompt': 0, 'completion': 0}
                        )
                    
                    data = await response.json()
                    choice = data.get('choices', [{}])[0]
                    message = choice.get('message', {})
                    
                    return LLMResponse(
                        content=message.get('content', ''),
                        model=data.get('model', self.model),
                        usage=data.get('usage', {'prompt_tokens': 0, 'completion_tokens': 0})
                    )
                    
        except asyncio.TimeoutError:
            logger.error("LLM request timeout")
            return LLMResponse(
                content="Error: Request timeout",
                model=self.model,
                usage={}
            )
        except Exception as e:
            logger.error(f"LLM request error: {e}")
            return LLMResponse(
                content=f"Error: {str(e)}",
                model=self.model,
                usage={}
            )
            
    async def complete(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None
    ) -> LLMResponse:
        """Send a completion request (non-chat)."""
        messages = [{"role": "user", "content": prompt}]
        return await self.chat(messages, temperature, max_tokens)

    async def stream_chat(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        """Stream chat completion tokens/chunks when backend supports SSE."""
        url = f"{self.api_url}/chat/completions"
        headers = {'Content-Type': 'application/json'}
        if self.api_key:
            headers['Authorization'] = f'Bearer {self.api_key}'

        payload: Dict[str, Any] = {
            'model': self.model,
            'messages': messages,
            'temperature': temperature,
            'stream': True,
        }
        if max_tokens:
            payload['max_tokens'] = max_tokens

        async with aiohttp.ClientSession() as session:
            async with session.post(
                url,
                json=payload,
                headers=headers,
                timeout=self._request_timeout(),
            ) as response:
                if response.status != 200:
                    body = await response.text()
                    raise RuntimeError(f"Stream request failed: {response.status} - {body}")

                async for raw_line in response.content:
                    line = raw_line.decode("utf-8", errors="ignore").strip()
                    if not line.startswith("data:"):
                        continue
                    payload_text = line[5:].strip()
                    if payload_text == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_text)
                        delta = chunk.get("choices", [{}])[0].get("delta", {})
                        content = delta.get("content", "")
                        if content:
                            yield content
                    except json.JSONDecodeError:
                        continue

    async def stream_complete(
        self,
        prompt: str,
        temperature: float = 0.7,
        max_tokens: Optional[int] = None,
    ) -> AsyncIterator[str]:
        messages = [{"role": "user", "content": prompt}]
        async for chunk in self.stream_chat(messages, temperature, max_tokens):
            yield chunk
        
    async def health_check(self) -> bool:
        """Check if LLM API is reachable."""
        try:
            url = f"{self.api_url}/models"
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url,
                    timeout=aiohttp.ClientTimeout(total=5)
                ) as response:
                    return response.status == 200
        except Exception:
            return False
