import asyncio
from dataclasses import dataclass

from agents.quicksearch import SkimAgent  # noqa: E402


@dataclass
class _ResultRow:
    url: str
    title: str
    content: str
    engine: str = "test"


class _FakeSearxng:
    async def search(self, query: str, max_results: int, strict: bool = False):
        del query, max_results, strict
        return [
            _ResultRow(
                url="https://example.com/slug-1",
                title="Slug facts one",
                content="Slugs are shell-less gastropods and prefer moist habitats.",
            ),
            _ResultRow(
                url="https://example.org/slug-2",
                title="Slug facts two",
                content="Slugs are shell-less gastropods that move using a mucus trail.",
            ),
        ]

    async def enrich_sources_with_content(self, sources, max_length: int, max_parallel: int):
        del max_length, max_parallel
        enriched = []
        for row in sources:
            enriched.append(
                {
                    **row,
                    "fetched_markdown": (
                        "Slug facts: slugs are shell-less gastropods that move using mucus and prefer moist environments."
                    ),
                }
            )
        return enriched


def test_build_skim_queries_respects_count():
    queries = SkimAgent._build_skim_queries("slug facts", 3)
    assert len(queries) == 3
    assert queries[0] == "slug facts"
    assert "overview" in queries[1]


def test_build_skim_queries_extends_with_perspectives():
    queries = SkimAgent._build_skim_queries("slug facts", 10)
    assert len(queries) == 10
    assert queries[-1] == "slug facts perspective 10"


def test_search_and_report_returns_clean_answer_without_default_uncertainty_note():
    agent = SkimAgent(
        searxng_client=_FakeSearxng(),
        llm_client=None,
        max_urls=4,
        agent_count=1,
    )

    result = asyncio.run(agent.search_and_report(query="slug facts", max_results=2))

    assert result.final_answer
    assert "[src_" in result.final_answer
    assert "No major uncertainty flags" not in "\n".join(result.uncertainties)
