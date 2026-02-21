"""
Core utilities for workflow primitives.
"""
from core.url_utils import (
    normalize_url,
    domain_trust_score,
    host_category,
)
from core.query_mode import classify_query_mode
from core.evidence import (
    LOW_SIGNAL_SENTENCE_MARKERS,
    _split_sentences,
    _clean_quote_text,
    _quote_signal_multiplier,
    _looks_like_boilerplate,
    _content_quality_score,
)
from core.claims import (
    _normalize_fact_statement,
    has_negation,
    similarity_score,
    _claim_key,
)

__all__ = [
    "normalize_url",
    "domain_trust_score",
    "host_category",
    "classify_query_mode",
    "LOW_SIGNAL_SENTENCE_MARKERS",
    "_split_sentences",
    "_clean_quote_text",
    "_quote_signal_multiplier",
    "_looks_like_boilerplate",
    "_content_quality_score",
    "_normalize_fact_statement",
    "has_negation",
    "similarity_score",
    "_claim_key",
]
