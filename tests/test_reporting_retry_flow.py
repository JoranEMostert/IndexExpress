import asyncio

from reporting import ReportGenerator, has_invalid_citations  # noqa: E402
from search.llm_client import LLMResponse  # noqa: E402


class SequencedLLM:
    def __init__(self, responses: list[str]):
        self.responses = responses
        self.calls = 0

    async def complete(self, prompt: str, temperature: float = 0.7, max_tokens: int | None = None) -> LLMResponse:
        del prompt, temperature, max_tokens
        idx = min(self.calls, len(self.responses) - 1)
        self.calls += 1
        return LLMResponse(content=self.responses[idx], model="test-model", usage={})


def test_write_report_retries_when_first_output_is_think_only():
    llm = SequencedLLM(
        [
            "<think>scratch work only</think>",
            "Report\n\nSlug fact from source (1).\n\nSources\n[1] Source - https://example.com",
        ]
    )
    generator = ReportGenerator(llm)

    result = asyncio.run(
        generator.write_report(
            query="slug facts",
            sources=[
                {
                    "title": "Source",
                    "url": "https://example.com",
                    "content": "Slugs are gastropods.",
                }
            ],
            style="concise",
            max_tokens=200,
        )
    )

    assert "<think>" not in result.report.lower()
    assert "Report" in result.report
    assert "Sources" in result.report
    assert llm.calls >= 2


def test_write_report_uses_fallback_when_all_outputs_are_empty_after_strip():
    llm = SequencedLLM(["<think>private</think>", "<think>still private</think>", "<think>again</think>"])
    generator = ReportGenerator(llm)

    result = asyncio.run(
        generator.write_report(
            query="slug facts",
            sources=[
                {
                    "title": "Source",
                    "url": "https://example.com",
                    "content": "Slugs are gastropods.",
                }
            ],
            style="concise",
            max_tokens=200,
        )
    )

    assert "Summary for 'slug facts':" in result.report
    assert "<think>" not in result.report.lower()


def test_has_invalid_citations_detects_out_of_range_indexes():
    assert has_invalid_citations("Fact (1) and another (3)", max_index=2)
    assert not has_invalid_citations("Fact (1) and another (2)", max_index=2)
