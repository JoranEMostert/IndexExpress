import asyncio
import json

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


def test_generate_sub_queries_fact_mode_uses_targeted_fallback_templates():
    llm = FakeLLM("not-json")
    orchestrator = DeepSearchOrchestrator(
        searxng_client=None,
        llm_client=llm,
        max_concurrent_agents=12,
        max_results_per_agent=8,
        llm_parallel=2,
    )
    out = asyncio.run(orchestrator._generate_sub_queries("slug facts", 6))
    assert len(out) == 6
    assert out[0] == "slug facts definition and taxonomy"
    assert out[1] == "slug facts anatomy and physiology"
    assert out[5] == "slug facts ecological role and predators"


def test_compose_final_synthesis_includes_contradictions_trace_and_open_questions():
    consensus_claims = [
        {
            "claim_id": "clm_001",
            "statement": "Slugs are shell-less gastropods in moist habitats.",
            "support_evidence_ids": ["ev_001", "ev_002"],
            "refute_evidence_ids": [],
            "confidence_tier": "consensus",
        }
    ]
    disputed_claims = [
        {
            "claim_id": "clm_002",
            "statement": "Slugs are mostly nocturnal in garden ecosystems.",
            "support_evidence_ids": ["ev_003"],
            "refute_evidence_ids": ["ev_004"],
            "confidence_tier": "disputed",
        },
        {
            "claim_id": "clm_003",
            "statement": "Slugs are commonly active during daylight in gardens.",
            "support_evidence_ids": ["ev_004"],
            "refute_evidence_ids": ["ev_003"],
            "confidence_tier": "disputed",
        },
    ]
    evidence_rows = [
        {"evidence_id": "ev_001", "source_id": "src_01", "exact_quote": "q", "relevance_score": 0.9},
        {"evidence_id": "ev_002", "source_id": "src_02", "exact_quote": "q", "relevance_score": 0.88},
        {"evidence_id": "ev_003", "source_id": "src_03", "exact_quote": "q", "relevance_score": 0.72},
        {"evidence_id": "ev_004", "source_id": "src_04", "exact_quote": "q", "relevance_score": 0.7},
    ]
    edges = [
        {
            "source_claim_id": "clm_002",
            "target_claim_id": "clm_003",
            "relationship": "contradicts",
        }
    ]
    synthesis = DeepSearchOrchestrator._compose_final_synthesis(
        query="slug facts",
        consensus_claims=consensus_claims,
        disputed_claims=disputed_claims,
        evidence_rows=evidence_rows,
        edges=edges,
        open_questions=["Which habitat factors explain contradictory activity windows?"],
    )
    assert "## Executive Summary" in synthesis
    assert "## Contradictions and Uncertainty" in synthesis
    assert "## Evidence Graph Trace" in synthesis
    assert "## Open Questions" in synthesis
    assert "[src_01]" in synthesis
    assert "[src_04]" in synthesis


def test_derive_open_questions_prioritizes_contradictions_and_diversity_gaps():
    questions = DeepSearchOrchestrator._derive_open_questions(
        query="slug facts",
        consensus_claims=[
            {
                "claim_id": "clm_001",
                "statement": "Slugs lose moisture quickly in dry air.",
                "support_evidence_ids": ["ev_001"],
                "refute_evidence_ids": [],
            }
        ],
        disputed_claims=[
            {
                "claim_id": "clm_002",
                "statement": "Slugs are primarily nocturnal.",
                "support_evidence_ids": ["ev_002"],
                "refute_evidence_ids": ["ev_003"],
            }
        ],
        sources=[{"url": "https://example.com/a"}, {"url": "https://example.com/b"}],
        edges=[
            {
                "source_claim_id": "clm_002",
                "target_claim_id": "clm_003",
                "relationship": "contradicts",
            }
        ],
        evidence_rows=[
            {"evidence_id": "ev_001"},
            {"evidence_id": "ev_002"},
            {"evidence_id": "ev_003"},
            {"evidence_id": "ev_004"},
            {"evidence_id": "ev_005"},
            {"evidence_id": "ev_006"},
            {"evidence_id": "ev_007"},
            {"evidence_id": "ev_008"},
            {"evidence_id": "ev_009"},
            {"evidence_id": "ev_010"},
        ],
    )
    joined = "\n".join(questions)
    assert "primary-source evidence" in joined
    assert "contradiction clusters" in joined
    assert "independent domains" in joined
