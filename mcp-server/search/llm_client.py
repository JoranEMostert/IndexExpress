import aiohttp
import asyncio
import json
import logging
import random
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
        timeout: Optional[int] = None,
        retries: int = 2,
        retry_base_ms: int = 250,
    ):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.model = model
        self.timeout = timeout
        self.retries = max(0, retries)
        self.retry_base_ms = max(20, retry_base_ms)
        self._session: aiohttp.ClientSession | None = None
        self._session_lock = asyncio.Lock()

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

        for attempt in range(self.retries + 1):
            try:
                session = await self._get_session()
                async with session.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self._request_timeout()
                ) as response:
                    if response.status != 200:
                        error = await response.text()
                        retryable = self._is_retryable_status(response.status)
                        if retryable and attempt < self.retries:
                            logger.warning(
                                "LLM API retrying after status=%s attempt=%s", response.status, attempt + 1
                            )
                            await asyncio.sleep(self._retry_delay(attempt))
                            continue
                        logger.error("LLM API error: %s - %s", response.status, error)
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
                if attempt < self.retries:
                    logger.warning("LLM request timeout; retrying attempt=%s", attempt + 1)
                    await asyncio.sleep(self._retry_delay(attempt))
                    continue
                logger.error("LLM request timeout")
                return LLMResponse(
                    content="Error: Request timeout",
                    model=self.model,
                    usage={}
                )
            except aiohttp.ClientError as e:
                if attempt < self.retries:
                    logger.warning("LLM client error; retrying attempt=%s err=%s", attempt + 1, e)
                    await asyncio.sleep(self._retry_delay(attempt))
                    continue
                logger.error("LLM request error: %s", e)
                return LLMResponse(
                    content=f"Error: {str(e)}",
                    model=self.model,
                    usage={}
                )
            except Exception as e:
                logger.error("LLM request error: %s", e)
                return LLMResponse(
                    content=f"Error: {str(e)}",
                    model=self.model,
                    usage={}
                )

        return LLMResponse(content="Error: Request failed", model=self.model, usage={})
            
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

        session = await self._get_session()
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
            session = await self._get_session()
            async with session.get(
                url,
                timeout=aiohttp.ClientTimeout(total=5)
            ) as response:
                return response.status == 200
        except Exception:
            return False
