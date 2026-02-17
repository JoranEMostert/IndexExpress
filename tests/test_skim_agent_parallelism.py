import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "mcp-server"))

from agents.quicksearch import SkimAgent  # noqa: E402


def test_build_skim_queries_respects_count():
    queries = SkimAgent._build_skim_queries("slug facts", 3)
    assert len(queries) == 3
    assert queries[0] == "slug facts"
    assert "overview" in queries[1]


def test_build_skim_queries_extends_with_perspectives():
    queries = SkimAgent._build_skim_queries("slug facts", 10)
    assert len(queries) == 10
    assert queries[-1] == "slug facts perspective 10"
