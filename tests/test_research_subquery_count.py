import asyncio
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server"))

from agents.deepresearch import DeepSearchOrchestrator  # noqa: E402
from search.llm_client import LLMResponse  # noqa: E402


class FakeLLM:
    def __init__(self, payload: str):
        self.payload = payload

    async def complete(self, prompt: str, temperature: float = 0.7):
        del prompt, temperature
        return LLMResponse(content=self.payload, model="fake", usage={})


def test_ensure_sub_query_count_pads_to_target():
    items = ["topic overview", "topic overview", "topic key facts"]
    out = DeepSearchOrchestrator._ensure_sub_query_count("topic", items, 5)
    assert len(out) == 5
    assert out[0] == "topic overview"
    assert out[1] == "topic key facts"
    assert out[-1] == "topic perspective 3"


def test_generate_sub_queries_expands_model_short_list():
    llm = FakeLLM(json.dumps(["topic overview", "topic key facts"]))
    orchestrator = DeepSearchOrchestrator(
        searxng_client=None,
        llm_client=llm,
        max_concurrent_agents=12,
        max_results_per_agent=8,
        llm_parallel=2,
    )
    out = asyncio.run(orchestrator._generate_sub_queries("topic", 6))
    assert len(out) == 6
    assert out[0] == "topic overview"
    assert out[1] == "topic key facts"
    assert out[-1] == "topic perspective 4"


def test_group_clusters_targets_three_per_synthesis():
    clusters = [{"query": f"q{i}", "report": "r"} for i in range(1, 7)]
    grouped = DeepSearchOrchestrator._group_clusters(clusters)
    assert len(grouped) == 2
    assert [len(g) for g in grouped] == [3, 3]


def test_group_clusters_handles_eleven_as_three_three_three_two():
    clusters = [{"query": f"q{i}", "report": "r"} for i in range(1, 12)]
    grouped = DeepSearchOrchestrator._group_clusters(clusters)
    assert [len(g) for g in grouped] == [3, 3, 3, 2]
