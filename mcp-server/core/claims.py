"""
Claim extraction and graph building.
"""
import re
from typing import Any, Literal


ConfidenceTier = Literal["consensus", "likely", "disputed", "insufficient_data"]


def _normalize_fact_statement(text: str, max_chars: int = 220) -> str:
    """Normalize a fact statement for claim extraction."""
    if not text:
        return ""
    text = text.strip()
    text = re.sub(r"\s+", " ", text)
    text = re.sub(r"^[^a-zA-Z0-9]+", "", text)
    if len(text) > max_chars:
        text = text[:max_chars]
        if text.endswith(" "):
            text = text[:-1]
        last_period = text.rfind(".")
        last_exclaim = text.rfind("!")
        last_question = text.rfind("?")
        cut = max(last_period, last_exclaim, last_question)
        if cut > 0:
            text = text[: cut + 1]
    return text.strip()


def has_negation(text: str) -> bool:
    """Check if text contains negation."""
    if not text:
        return False
    lowered = text.lower()
    negation_patterns = (
        r"\bnot\b",
        r"\bno\b",
        r"\bnever\b",
        r"\bneither\b",
        r"\bnone\b",
        r"\bn't\b",
        r"\bwithout\b",
        r"\bdon'?t\b",
        r"\bdoesn'?t\b",
        r"\bdidn'?t\b",
        r"\bwon'?t\b",
        r"\bwouldn'?t\b",
        r"\bcannot\b",
        r"\bcan'?t\b",
        r"\bwasn'?t\b",
        r"\bisn'?t\b",
        r"\baren'?t\b",
    )
    return bool(re.search(negation_patterns, lowered))


def similarity_score(a: str, b: str) -> float:
    """Simple word overlap similarity score."""
    if not a or not b:
        return 0.0
    tokens_a = set(re.findall(r"[a-z0-9]{2,}", a.lower()))
    tokens_b = set(re.findall(r"[a-z0-9]{2,}", b.lower()))
    if not tokens_a or not tokens_b:
        return 0.0
    intersection = tokens_a & tokens_b
    union = tokens_a | tokens_b
    return len(intersection) / len(union) if union else 0.0


def _claim_key(text: str) -> str:
    """Generate a key for grouping similar claims."""
    tokens = re.findall(r"[a-z0-9]{3,}", (text or "").lower())
    return " ".join(tokens[:16])
