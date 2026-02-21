"""
Evidence extraction utilities.
"""
import re
from typing import Final


LOW_SIGNAL_SENTENCE_MARKERS: Final[tuple] = (
    "skip to content",
    "jump to content",
    "open menu",
    "open navigation",
    "log in",
    "sign in",
    "sign up",
    "privacy policy",
    "terms of service",
    "cookie",
    "javascript",
    "go to reddit home",
    "reddit - the heart of the internet",
    "expand user menu",
    "select citation style",
    "thank you for your feedback",
    "external websites",
    "related articles",
    "written and fact-check",
    "pmc copyright notice",
    "pmcid",
    "pmid",
    "for other uses, see",
    "disambiguation",
    "did you know",
    "what if we told you",
    "want to know your way around",
    "photo by",
    "cited by",
    "save article failed to save article",
    "made possible by",
    "doi:",
    "all rights reserved",
    "read more",
    "back to top",
    "table of contents",
    "advertisement",
    "subscribe to",
    "newsletter",
)


def _split_sentences(text: str) -> list[str]:
    """Split text into sentences."""
    text = (text or "").replace("\n", " ").replace("\r", " ")
    parts = re.split(r"(?<=[.!?])\s+", text)
    sentences = [s.strip() for s in parts if s.strip()]
    return sentences


def _clean_quote_text(text: str) -> str:
    """Clean extracted quote text."""
    if not text:
        return ""
    cleaned = re.sub(r"<[^>]+>", "", text)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = cleaned.strip()
    if len(re.findall(r"[a-z0-9]+", cleaned.lower())) < 4:
        return ""
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def _quote_signal_multiplier(sentence: str) -> float:
    """Calculate signal multiplier for a quote."""
    lowered = (sentence or "").lower()
    if not lowered:
        return 0.0
    if lowered.endswith("?"):
        return 0.25
    if "..." in sentence:
        return 0.45
    if re.search(r"\bcited by\s+\d+", lowered):
        return 0.15
    if re.search(r"\b\d+\s*pages?\b", lowered) and re.search(r"\b\d+\s*kb\b", lowered):
        return 0.15
    if any(marker in lowered for marker in ("did you know", "what if we told you", "in the spirit of")):
        return 0.35
    return 1.0


def _looks_like_boilerplate(sentence: str) -> bool:
    """Check if sentence is likely boilerplate."""
    lowered = (sentence or "").lower()
    if not lowered:
        return True
    if any(marker in lowered for marker in LOW_SIGNAL_SENTENCE_MARKERS):
        return True
    if lowered.endswith("?") and len(sentence) <= 160:
        return True
    if lowered.startswith("(from "):
        return True
    if sentence.lstrip().startswith("#"):
        return True
    if sentence.count("|") >= 4:
        return True
    if len(re.findall(r"https?://|www\.", lowered)) >= 1:
        return True
    if sentence.count(" - ") >= 3:
        return True
    if lowered.startswith("(http") or ".jpg" in lowered or ".png" in lowered or ".svg" in lowered:
        return True
    if re.search(r"\b(read more|click here|back to top|follow us|share this)\b", lowered):
        return True
    if re.search(r"\bcited by\s+\d+", lowered):
        return True
    if re.search(r"\b\d+\s*pages?\b", lowered) and re.search(r"\b\d+\s*kb\b", lowered):
        return True
    url_count = len(re.findall(r"https?://", lowered))
    slash_count = lowered.count("/")
    hash_count = lowered.count("#")
    if url_count >= 2 or slash_count >= 12 or hash_count >= 5:
        return True
    letters = sum(1 for ch in sentence if ch.isalpha())
    symbols = sum(1 for ch in sentence if ch in "#/|[]()<>-")
    if letters > 0 and (symbols / letters) > 0.35:
        return True
    digits = sum(1 for ch in sentence if ch.isdigit())
    if letters > 0 and (digits / letters) > 0.45:
        return True
    return False


def _content_quality_score(text: str) -> float:
    """Calculate content quality score."""
    compact = (text or "").strip()
    if not compact:
        return 0.2
    sentences = _split_sentences(compact)
    if not sentences:
        return 0.4
    noisy = sum(1 for sentence in sentences[:40] if _looks_like_boilerplate(sentence))
    noise_ratio = noisy / max(1, min(len(sentences), 40))
    quality = 1.0 - noise_ratio
    return round(max(0.15, min(1.0, quality)), 4)
