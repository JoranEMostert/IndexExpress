import logging
import os
from typing import Any, Optional

import aiohttp
import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("searxng-mcp")

CONFIG_PATH = os.environ.get("CONFIG_PATH", "/app/config/settings.yaml")


def _env_int(name: str, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    try:
        return int(value)
    except ValueError:
        logger.warning("Invalid int for %s=%r, using %d", name, value, default)
        return default


def load_config() -> dict[str, Any]:
    """Load YAML config and apply environment overrides."""
    file_config: dict[str, Any] = {}
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            file_config = yaml.safe_load(f) or {}
    except FileNotFoundError:
        logger.warning("Config file not found at %s, using env/defaults", CONFIG_PATH)

    config = {
        "llm_api_url": file_config.get("llm_api_url", "http://host.docker.internal:1234/v1"),
        "llm_api_key": file_config.get("llm_api_key", ""),
        "llm_model_id": file_config.get("llm_model_id", "local-model"),
        "llm_timeout": int(file_config.get("llm_timeout", 0)),
        "llm_max_parallel": int(file_config.get("llm_max_parallel", 4)),
        "searxng_url": file_config.get("searxng_url", "http://searxng:8080"),
        "searxng_timeout": int(file_config.get("searxng_timeout", 0)),
        "max_concurrent_agents": int(file_config.get("max_concurrent_agents", 3)),
        "agent_timeout": int(file_config.get("agent_timeout", 60)),
        "peek_max_urls": int(file_config.get("peek_max_urls", 5)),
        "skim_max_urls": int(file_config.get("skim_max_urls", 15)),
        "skim_agent_count": int(file_config.get("skim_agent_count", 1)),
        "analyze_sources_per_agent": int(file_config.get("analyze_sources_per_agent", 12)),
        "analyze_agent_count": int(file_config.get("analyze_agent_count", 2)),
        "analyze_contradiction_agents": int(file_config.get("analyze_contradiction_agents", 0)),
        "research_max_sub_queries": int(file_config.get("research_max_sub_queries", 6)),
        "research_sources_per_sub_query": int(file_config.get("research_sources_per_sub_query", 8)),
        "mcp_host": file_config.get("mcp_host", "0.0.0.0"),
        "mcp_port": int(file_config.get("mcp_port", 8000)),
        "log_level": file_config.get("log_level", "INFO"),
    }

    config["llm_api_url"] = os.environ.get("LLM_API_URL", config["llm_api_url"])
    config["llm_api_key"] = os.environ.get("LLM_API_KEY", config["llm_api_key"])
    config["llm_model_id"] = os.environ.get("LLM_MODEL_ID", config["llm_model_id"])
    if not config["llm_model_id"]:
        config["llm_model_id"] = os.environ.get("LLM_MODEL", config["llm_model_id"])
    config["llm_timeout"] = _env_int("LLM_TIMEOUT", config["llm_timeout"])
    config["llm_max_parallel"] = _env_int("LLM_MAX_PARALLEL", config["llm_max_parallel"])
    config["searxng_url"] = os.environ.get("SEARXNG_URL", config["searxng_url"])
    config["searxng_timeout"] = _env_int("SEARXNG_TIMEOUT", config["searxng_timeout"])
    config["max_concurrent_agents"] = _env_int("MAX_CONCURRENT_AGENTS", config["max_concurrent_agents"])
    config["peek_max_urls"] = _env_int("PEEK_MAX_URLS", config["peek_max_urls"])
    config["skim_max_urls"] = _env_int("SKIM_MAX_URLS", config["skim_max_urls"])
    config["skim_agent_count"] = _env_int("SKIM_AGENT_COUNT", config["skim_agent_count"])
    config["analyze_sources_per_agent"] = _env_int("ANALYZE_SOURCES_PER_AGENT", config["analyze_sources_per_agent"])

    config["analyze_agent_count"] = _env_int("ANALYZE_AGENT_COUNT", config["analyze_agent_count"])
    config["analyze_contradiction_agents"] = _env_int(
        "ANALYZE_CONTRADICTION_AGENTS", config["analyze_contradiction_agents"]
    )
    if os.environ.get("RESEARCH_MAX_SUB_QUERIES") in (None, ""):
        config["research_max_sub_queries"] = config["max_concurrent_agents"]
    else:
        config["research_max_sub_queries"] = _env_int("RESEARCH_MAX_SUB_QUERIES", config["research_max_sub_queries"])

    config["research_sources_per_sub_query"] = _env_int(
        "RESEARCH_SOURCES_PER_SUB_QUERY", config["research_sources_per_sub_query"]
    )

    config["log_level"] = os.environ.get("LOG_LEVEL", config["log_level"])

    config["research_max_sub_queries"] = max(1, min(config["research_max_sub_queries"], config["max_concurrent_agents"]))
    config["skim_agent_count"] = max(1, config["skim_agent_count"])

    if config["llm_model_id"] == "local-model":
        logger.warning("LLM_MODEL_ID is using default 'local-model'. Set explicit model ID in env for best results.")

    return config


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
