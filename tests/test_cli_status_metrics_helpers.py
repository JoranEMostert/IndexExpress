from expressindex_cli.main import (
    _http_base_from_mcp,
    _parse_options_arg,
    _render_metrics_text,
    _render_report_text,
    _render_status_text,
    _tui_consumer_summary,
)


def test_http_base_from_mcp_extracts_origin():
    assert _http_base_from_mcp("http://localhost:8000/mcp") == "http://localhost:8000"


def test_parse_options_arg_splits_csv_and_strips_whitespace():
    assert _parse_options_arg("python, node.js , go") == ["python", "node.js", "go"]


def test_render_status_text_includes_core_fields():
    text = _render_status_text(
        {
            "health": {"status": "healthy", "services": {"searxng": "up", "llm": "up"}},
            "ready": {"status": "ready"},
            "agent_status": {"max_concurrent": 5, "available": 3},
        }
    )
    assert "health: healthy" in text
    assert "ready: ready" in text
    assert "agents: 2/5 active" in text


def test_render_metrics_text_includes_tools_and_requests():
    payload = {
        "metrics": {
            "uptime_s": 12.3,
            "tools": {"skim": {"count": 2, "errors": 0, "avg_s": 1.1, "max_s": 2.2}},
            "requests": {"tools/call": {"count": 2, "errors": 1, "avg_s": 0.3, "max_s": 0.7}},
        }
    }
    text = _render_metrics_text(payload)
    assert "uptime_s: 12.3" in text
    assert "- skim: count=2" in text
    assert "- tools/call: count=2" in text


def test_render_report_text_omits_decision_matrix_for_fact_style_analyze_payload():
    payload = {
        "recommended_position": "Key facts from retrieved sources:\n- Fact A [src_01]",
        "decision_matrix": [],
        "consensus_claims": [{"claim_id": "clm_001"}],
        "disputed_claims": [],
        "sensitivity_factors": ["1/6 extracted claims are disputed."],
    }
    text = _render_report_text("analyze", payload)
    assert "## Decision Matrix" not in text
    assert "Fact claims reviewed:" in text


def test_render_report_text_handles_analyze_routed_to_research():
    payload = {
        "requested_mode": "analyze",
        "executed_mode": "research",
        "route_reason": "non_comparative_query",
        "final_synthesis": "Report\n\nKey synthesis line.",
        "evidence_graph": {"nodes": [], "edges": []},
    }
    text = _render_report_text("analyze", payload)
    assert "Analyze routed to research: non_comparative_query" in text
    assert "Key synthesis line." in text


def test_tui_consumer_summary_avoids_duplicate_open_questions_section():
    payload = {
        "final_synthesis": "Report\n\n## Open Questions\n- Existing one",
        "open_questions": ["Existing one", "New one"],
    }
    text = _tui_consumer_summary("research", payload)
    assert text.count("## Open Questions") == 1
