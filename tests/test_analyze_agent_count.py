from agents.deepresearch import AnalyzeOrchestrator  # noqa: E402


def test_build_analyze_sub_queries_respects_requested_count():
    sub_queries = AnalyzeOrchestrator._build_analyze_sub_queries("home composting", 5)
    assert len(sub_queries) == 5
    assert sub_queries[0] == "home composting"
    assert "alternative viewpoints" in sub_queries[1]
    assert "expert consensus" in sub_queries[3]


def test_build_analyze_sub_queries_extends_beyond_templates():
    sub_queries = AnalyzeOrchestrator._build_analyze_sub_queries("home composting", 14)
    assert len(sub_queries) == 14
    assert sub_queries[-1] == "home composting perspective 14"


def test_build_analyze_sub_queries_uses_fact_templates_for_fact_mode():
    sub_queries = AnalyzeOrchestrator._build_analyze_sub_queries("slug facts", 6)
    assert len(sub_queries) == 6
    assert "definition and scope" in sub_queries[1]
    assert "pros and cons" not in " ".join(sub_queries[:6]).lower()


def test_factual_position_returns_cited_fact_bullets():
    consensus_claims = [
        {
            "claim_id": "clm_001",
            "statement": "Slugs are shell-less gastropods.",
            "support_evidence_ids": ["ev_001"],
            "refute_evidence_ids": [],
            "confidence_tier": "consensus",
        }
    ]
    evidence_rows = [
        {
            "evidence_id": "ev_001",
            "source_id": "src_01",
            "exact_quote": "Slugs are shell-less gastropods.",
            "relevance_score": 0.9,
        }
    ]
    text = AnalyzeOrchestrator._factual_position(
        "slug facts",
        consensus_claims,
        disputed_claims=[],
        evidence_rows=evidence_rows,
    )
    assert text.startswith("Key facts from retrieved sources:")
    assert "[src_01]" in text


def test_decision_matrix_scores_are_bounded_and_not_perfect():
    consensus_claims = [
        {
            "claim_id": f"clm_{idx:03d}",
            "statement": f"Consensus claim {idx}",
            "support_evidence_ids": [f"ev_{idx:03d}", f"ev_{idx+100:03d}"],
            "refute_evidence_ids": [],
            "confidence_tier": "consensus",
        }
        for idx in range(1, 11)
    ]
    disputed_claims = [
        {
            "claim_id": "clm_501",
            "statement": "Disputed claim A",
            "support_evidence_ids": ["ev_501"],
            "refute_evidence_ids": ["ev_601"],
            "confidence_tier": "disputed",
        }
    ]
    sources = [
        {
            "source_id": f"src_{idx:02d}",
            "url": f"https://example{idx}.org/article",
            "domain_trust_score": 0.9,
            "freshness_timestamp": "2025-01-01T00:00:00Z",
            "intent_category": "general",
        }
        for idx in range(1, 7)
    ]

    matrix = AnalyzeOrchestrator._build_decision_matrix(consensus_claims, disputed_claims, sources)
    evidence_strength = matrix[0]["options"]
    proceed = next(item for item in evidence_strength if item["option_name"] == "Proceed")
    assert 5 <= proceed["score"] <= 95
    assert proceed["score"] < 100


def test_recommended_position_can_choose_non_proceed_when_conflicts_are_high():
    consensus_claims = [
        {
            "claim_id": "clm_001",
            "statement": "Consensus claim",
            "support_evidence_ids": ["ev_001"],
            "refute_evidence_ids": [],
            "confidence_tier": "likely",
        }
    ]
    disputed_claims = [
        {
            "claim_id": f"clm_{idx:03d}",
            "statement": f"Disputed claim {idx}",
            "support_evidence_ids": [f"ev_{idx:03d}"],
            "refute_evidence_ids": [f"ev_{idx+100:03d}"],
            "confidence_tier": "disputed",
        }
        for idx in range(2, 8)
    ]
    sources = [
        {
            "source_id": f"src_{idx:02d}",
            "url": f"https://lowtrust{idx}.example.com/article",
            "domain_trust_score": 0.5,
            "freshness_timestamp": "2024-01-01T00:00:00Z",
            "intent_category": "general",
        }
        for idx in range(1, 6)
    ]

    matrix = AnalyzeOrchestrator._build_decision_matrix(consensus_claims, disputed_claims, sources)
    recommendation = AnalyzeOrchestrator._recommended_position(matrix)
    assert recommendation.startswith("Recommended position: ")
    assert any(
        recommendation.startswith(f"Recommended position: {choice}")
        for choice in ("Proceed with Guardrails", "Defer")
    )


def test_sensitivity_factors_include_measurable_signals():
    consensus_claims = [
        {
            "claim_id": "clm_001",
            "statement": "Consensus claim",
            "support_evidence_ids": ["ev_001"],
            "refute_evidence_ids": [],
            "confidence_tier": "likely",
        }
    ]
    disputed_claims = [
        {
            "claim_id": "clm_101",
            "statement": "Disputed claim about projected impact.",
            "support_evidence_ids": ["ev_101"],
            "refute_evidence_ids": ["ev_201"],
            "confidence_tier": "disputed",
        }
    ]
    sources = [
        {
            "source_id": "src_01",
            "url": "https://example.com/a",
            "domain_trust_score": 0.6,
            "freshness_timestamp": "2024-01-01T00:00:00Z",
            "intent_category": "general",
        },
        {
            "source_id": "src_02",
            "url": "https://example.com/b",
            "domain_trust_score": 0.58,
            "freshness_timestamp": "2024-01-01T00:00:00Z",
            "intent_category": "general",
        },
    ]

    factors = AnalyzeOrchestrator._sensitivity_factors(
        consensus_claims,
        disputed_claims,
        sources,
        query_mode="comparative",
    )
    assert factors
    assert any("disputed" in item.lower() for item in factors)
    assert any("trust < 0.65" in item for item in factors)


def test_resolve_compare_options_prefers_explicit_then_query_inference():
    explicit = AnalyzeOrchestrator._resolve_compare_options(
        "python vs node for backend",
        options=["Python", "Node.js"],
    )
    assert explicit == ["Python", "Node.js"]

    inferred = AnalyzeOrchestrator._resolve_compare_options(
        "python vs node for backend",
        options=None,
    )
    assert len(inferred) >= 2
    assert inferred[0].lower().startswith("python")


def test_recommendation_details_extracts_best_option_and_confidence():
    matrix = [
        {
            "dimension": "Evidence Coverage",
            "options": [
                {
                    "option_name": "Python",
                    "score": 82,
                    "rationale": "More corroborated sources",
                },
                {
                    "option_name": "Node.js",
                    "score": 64,
                    "rationale": "Less consistent evidence",
                },
            ],
        }
    ]
    option, confidence, why_not = AnalyzeOrchestrator._recommendation_details(matrix)
    assert option == "Python"
    assert confidence in {"moderate", "high"}
    assert why_not
