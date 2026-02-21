import logging
import os
from dataclasses import asdict, dataclass
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp
import yaml

logger = logging.getLogger("searxng-mcp")

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config/settings.yaml")


def _coerce_int(name: str, value: Any, default: int) -> int:
    if value is None or value == "":
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Invalid int for %s=%r, using %d", name, value, default)
        return default


def _coerce_bool(name: str, value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    logger.warning("Invalid bool for %s=%r, using %s", name, value, default)
    return default


def _coerce_choice(name: str, value: Any, default: str, allowed: set[str]) -> str:
    if value is None or value == "":
        return default
    text = str(value).strip().lower()
    if text in allowed:
        return text
    logger.warning("Invalid choice for %s=%r, using %s", name, value, default)
    return default


def _is_valid_url(text: str) -> bool:
    parsed = urlparse(text)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _env_or_file(name: str, file_config: dict[str, Any], key: str, default: Any) -> Any:
    return os.environ.get(name, file_config.get(key, default))


@dataclass
class RuntimeConfig:
    llm_api_url: str
    llm_api_key: str
    llm_model_id: str
    llm_timeout: int
    llm_max_parallel: int
    llm_retries: int

    searxng_url: str
    searxng_timeout: int
    searxng_retries: int

    max_concurrent_agents: int
    agent_timeout: int
    peek_max_urls: int
    skim_max_urls: int
    skim_agent_count: int
    analyze_sources_per_agent: int
    analyze_agent_count: int
    analyze_contradiction_agents: int
    research_max_sub_queries: int
    research_sources_per_sub_query: int

    mcp_host: str
    mcp_port: int

    log_level: str
    log_format: str
    query_max_length: int
    readiness_require_llm: bool

    tool_timeout_peek: int
    tool_timeout_skim: int
    tool_timeout_analyze: int
    tool_timeout_research: int

    http_retry_base_ms: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_config() -> dict[str, Any]:
    """Load YAML config and apply validated environment overrides."""
    file_config: dict[str, Any] = {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            file_config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("Config file not found at %s, using env/defaults", CONFIG_PATH)

    llm_model_id = _env_or_file("LLM_MODEL_ID", file_config, "llm_model_id", "local-model")
    if not llm_model_id:
        llm_model_id = os.environ.get("LLM_MODEL", "local-model")

    max_concurrent_agents = _coerce_int(
        "MAX_CONCURRENT_AGENTS",
        _env_or_file("MAX_CONCURRENT_AGENTS", file_config, "max_concurrent_agents", 7),
        7,
    )

    if os.environ.get("RESEARCH_MAX_SUB_QUERIES") in (None, ""):
        research_max_sub_queries = max_concurrent_agents
    else:
        research_max_sub_queries = _coerce_int(
            "RESEARCH_MAX_SUB_QUERIES",
            _env_or_file("RESEARCH_MAX_SUB_QUERIES", file_config, "research_max_sub_queries", 6),
            6,
        )

    config = RuntimeConfig(
        llm_api_url=str(_env_or_file("LLM_API_URL", file_config, "llm_api_url", "http://localhost:1234/v1")),
        llm_api_key=str(_env_or_file("LLM_API_KEY", file_config, "llm_api_key", "")),
        llm_model_id=str(llm_model_id),
        llm_timeout=_coerce_int("LLM_TIMEOUT", _env_or_file("LLM_TIMEOUT", file_config, "llm_timeout", 0), 0),
        llm_max_parallel=_coerce_int(
            "LLM_MAX_PARALLEL", _env_or_file("LLM_MAX_PARALLEL", file_config, "llm_max_parallel", 4), 4
        ),
        llm_retries=_coerce_int("LLM_RETRIES", _env_or_file("LLM_RETRIES", file_config, "llm_retries", 2), 2),
        searxng_url=str(_env_or_file("SEARXNG_URL", file_config, "searxng_url", "http://searxng:8080")),
        searxng_timeout=_coerce_int(
            "SEARXNG_TIMEOUT", _env_or_file("SEARXNG_TIMEOUT", file_config, "searxng_timeout", 0), 0
        ),
        searxng_retries=_coerce_int(
            "SEARXNG_RETRIES", _env_or_file("SEARXNG_RETRIES", file_config, "searxng_retries", 2), 2
        ),
        max_concurrent_agents=max_concurrent_agents,
        agent_timeout=_coerce_int("AGENT_TIMEOUT", _env_or_file("AGENT_TIMEOUT", file_config, "agent_timeout", 60), 60),
        peek_max_urls=_coerce_int("PEEK_MAX_URLS", _env_or_file("PEEK_MAX_URLS", file_config, "peek_max_urls", 5), 5),
        skim_max_urls=_coerce_int("SKIM_MAX_URLS", _env_or_file("SKIM_MAX_URLS", file_config, "skim_max_urls", 15), 15),
        skim_agent_count=_coerce_int(
            "SKIM_AGENT_COUNT", _env_or_file("SKIM_AGENT_COUNT", file_config, "skim_agent_count", 1), 1
        ),
        analyze_sources_per_agent=_coerce_int(
            "ANALYZE_SOURCES_PER_AGENT",
            _env_or_file("ANALYZE_SOURCES_PER_AGENT", file_config, "analyze_sources_per_agent", 12),
            12,
        ),
        analyze_agent_count=_coerce_int(
            "ANALYZE_AGENT_COUNT", _env_or_file("ANALYZE_AGENT_COUNT", file_config, "analyze_agent_count", 2), 2
        ),
        analyze_contradiction_agents=_coerce_int(
            "ANALYZE_CONTRADICTION_AGENTS",
            _env_or_file("ANALYZE_CONTRADICTION_AGENTS", file_config, "analyze_contradiction_agents", 0),
            0,
        ),
        research_max_sub_queries=research_max_sub_queries,
        research_sources_per_sub_query=_coerce_int(
            "RESEARCH_SOURCES_PER_SUB_QUERY",
            _env_or_file("RESEARCH_SOURCES_PER_SUB_QUERY", file_config, "research_sources_per_sub_query", 8),
            8,
        ),
        mcp_host=str(_env_or_file("MCP_HOST", file_config, "mcp_host", "0.0.0.0")),
        mcp_port=_coerce_int("MCP_PORT", _env_or_file("MCP_PORT", file_config, "mcp_port", 8000), 8000),
        log_level=str(_env_or_file("LOG_LEVEL", file_config, "log_level", "INFO")),
        log_format=_coerce_choice(
            "LOG_FORMAT", _env_or_file("LOG_FORMAT", file_config, "log_format", "text"), "text", {"text", "json"}
        ),
        query_max_length=_coerce_int(
            "QUERY_MAX_LENGTH", _env_or_file("QUERY_MAX_LENGTH", file_config, "query_max_length", 600), 600
        ),
        readiness_require_llm=_coerce_bool(
            "READINESS_REQUIRE_LLM",
            _env_or_file("READINESS_REQUIRE_LLM", file_config, "readiness_require_llm", True),
            True,
        ),
        tool_timeout_peek=_coerce_int(
            "TOOL_TIMEOUT_PEEK", _env_or_file("TOOL_TIMEOUT_PEEK", file_config, "tool_timeout_peek", 30), 30
        ),
        tool_timeout_skim=_coerce_int(
            "TOOL_TIMEOUT_SKIM", _env_or_file("TOOL_TIMEOUT_SKIM", file_config, "tool_timeout_skim", 120), 120
        ),
        tool_timeout_analyze=_coerce_int(
            "TOOL_TIMEOUT_ANALYZE", _env_or_file("TOOL_TIMEOUT_ANALYZE", file_config, "tool_timeout_analyze", 300), 300
        ),
        tool_timeout_research=_coerce_int(
            "TOOL_TIMEOUT_RESEARCH",
            _env_or_file("TOOL_TIMEOUT_RESEARCH", file_config, "tool_timeout_research", 900),
            900,
        ),
        http_retry_base_ms=_coerce_int(
            "HTTP_RETRY_BASE_MS", _env_or_file("HTTP_RETRY_BASE_MS", file_config, "http_retry_base_ms", 250), 250
        ),
    )

    config.llm_max_parallel = max(1, config.llm_max_parallel)
    config.max_concurrent_agents = max(1, config.max_concurrent_agents)
    config.skim_agent_count = max(1, config.skim_agent_count)
    config.analyze_agent_count = max(2, config.analyze_agent_count)
    config.research_max_sub_queries = max(1, min(config.research_max_sub_queries, config.max_concurrent_agents))
    config.query_max_length = max(32, config.query_max_length)
    config.http_retry_base_ms = max(20, config.http_retry_base_ms)

    for name in (
        "tool_timeout_peek",
        "tool_timeout_skim",
        "tool_timeout_analyze",
        "tool_timeout_research",
    ):
        value = getattr(config, name)
        if value < 0:
            logger.warning("%s cannot be negative; using 0", name)
            setattr(config, name, 0)

    if not _is_valid_url(config.llm_api_url):
        logger.warning("Invalid LLM_API_URL=%r, using default", config.llm_api_url)
        config.llm_api_url = "http://localhost:1234/v1"

    if not _is_valid_url(config.searxng_url):
        logger.warning("Invalid SEARXNG_URL=%r, using default", config.searxng_url)
        config.searxng_url = "http://searxng:8080"

    if config.llm_model_id == "local-model":
        logger.warning("LLM_MODEL_ID is using default 'local-model'. Set explicit model ID in env for best results.")

    return config.to_dict()


CONFIG = load_config()


def _models_url(api_url: str) -> str:
    if api_url.endswith("/chat/completions"):
        return api_url[: -len("/chat/completions")] + "/models"
    if api_url.endswith("/completions"):
        return api_url[: -len("/completions")] + "/models"
    return api_url.rstrip("/") + "/models"


async def list_llm_models(api_url: str, api_key: Optional[str] = None) -> list[str]:
    """List model IDs from an OpenAI-compatible /models endpoint."""
    url = _models_url(api_url)
    headers: dict[str, str] = {}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as response:
                if response.status != 200:
                    logger.warning("Model listing failed with status %s from %s", response.status, url)
                    return []
                payload = await response.json()
                raw_models = payload.get("data") or payload.get("models") or []
                models: list[str] = []
                for model in raw_models:
                    if isinstance(model, str):
                        models.append(model)
                    elif isinstance(model, dict):
                        model_id = model.get("id") or model.get("name")
                        if model_id:
                            models.append(str(model_id))
                return models
    except Exception as e:
        logger.warning("Failed to list models from %s: %s", url, e)
        return []


async def detect_llm_model(api_url: str, api_key: Optional[str] = None) -> Optional[str]:
    """Detect active/default model by using the first model from /models."""
    models = await list_llm_models(api_url, api_key)
    if not models:
        return None
    logger.info("Auto-detected LLM model: %s", models[0])
    return models[0]
