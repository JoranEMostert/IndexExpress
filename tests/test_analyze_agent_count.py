import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server"))

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
