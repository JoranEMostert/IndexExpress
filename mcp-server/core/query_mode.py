"""
Query mode classification.
"""
from typing import Final


FACT_QUERY_STOPWORDS: Final[set] = {
    "fact",
    "facts",
    "about",
    "overview",
    "information",
    "info",
    "basics",
    "quick",
    "guide",
    "what",
    "where",
    "when",
    "who",
    "why",
    "how",
    "define",
    "definition",
    "meaning",
    "explain",
}

COMPARATIVE_WORDS: Final[set] = {
    "vs",
    "versus",
    "compare",
    "comparison",
    "better",
    "best",
    "worse",
    "worst",
    "difference",
    "different",
    "alternative",
    "recommend",
    "pros",
    "cons",
    "review",
    "versus",
}


TASK_QUERY_MARKERS: Final[set] = {
    "how to",
    "how do i",
    "how can i",
    "ways to",
    "steps to",
    "guide to",
    "tutorial",
    "learn",
    "create",
    "build",
    "make",
    "fix",
    "solve",
    "install",
    "setup",
    "deploy",
}


def classify_query_mode(query: str) -> str:
    """Classify query into mode: fact, comparative, task, or general."""
    if not query:
        return "general"

    q = query.lower()
    words = set(q.split())

    if any(marker in q for marker in (" vs ", " versus ")):
        return "comparative"
    if words & COMPARATIVE_WORDS and len(words & COMPARATIVE_WORDS) >= 1:
        return "comparative"
    if any(marker in q for marker in TASK_QUERY_MARKERS):
        return "task"

    stopwords_in_query = words & FACT_QUERY_STOPWORDS
    if len(stopwords_in_query) >= 2:
        return "fact"
    if "?" in query:
        return "fact"

    return "general"
