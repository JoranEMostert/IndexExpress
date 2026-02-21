import json
import re
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Literal
from urllib.parse import urlparse


SCHEMA_VERSION = "v2.0"

SOCIAL_HOST_MARKERS = (
    "reddit.com",
    "facebook.com",
    "instagram.com",
    "tiktok.com",
    "x.com",
    "twitter.com",
    "pinterest.com",
    "linkedin.com",
    "quora.com",
)

REFERENCE_HOST_MARKERS = (
    "wikipedia.org",
    "britannica.com",
    "nationalgeographic.com",
    "smithsonianmag.com",
    "who.int",
    "cdc.gov",
    "nih.gov",
    "nasa.gov",
    "noaa.gov",
    "extension.",
)

DOCUMENTATION_HOST_MARKERS = (
    "docs.",
    "developer.",
    "readthedocs",
    "mdn",
)

LOW_SIGNAL_SENTENCE_MARKERS = (
    "skip to content",
    "pmcid",
    "pmid",
    "did you know",
    "cited by",
    "doi:",
    "read more",
    "back to top",
    "advertisement",
)

FACT_QUERY_STOPWORDS = {
    "facts",
    "about",
    "what",
    "where",
    "when",
    "who",
    "why",
    "how",
}

SLUG_ANIMAL_MARKERS = (
    "gastropod",
    "mollusk",
    "snail",
)

SLUG_NON_ANIMAL_MARKERS = (
    "shotgun",
    "cartridge",
    "ammo",
    "bullet",
    "emt",
)

SLUG_NON_ANIMAL_QUERY_HINTS = (
    "shotgun",
    "cartridge",
    "ammo",
    "bullet",
)


ConfidenceTier = Literal["consensus", "likely", "disputed", "insufficient_data"]


@dataclass
class SourcePrimitive:
    source_id: str
    url: str
    title: str
    domain: str
    relevance_score: float
    domain_trust_score: float
    freshness_timestamp: str
    intent_category: str


@dataclass
class EvidencePrimitive:
    evidence_id: str
    source_id: str
    exact_quote: str
    relevance_score: float


@dataclass
class ClaimPrimitive:
    claim_id: str
    statement: str
    support_evidence_ids: list[str]
    refute_evidence_ids: list[str]
    confidence_tier: ConfidenceTier


def normalize_url(url: str) -> str:
    cleaned = (url or "").strip().lower()
    cleaned = re.sub(r"^https?://", "", cleaned)
    cleaned = cleaned.rstrip("/")
    return cleaned


def classify_query_intent(query: str) -> str:
    q = (query or "").strip().lower()
    if any(token in q for token in ("paper", "study", "meta-analysis", "journal", "peer reviewed")):
        return "academic"
    if any(token in q for token in ("latest", "news", "today", "breaking", "update")):
        return "news"
    if any(token in q for token in ("api", "docs", "documentation", "install", "tutorial", "sdk")):
        return "documentation"
    return "general"


def classify_query_mode(query: str) -> str:
    raw = (query or "").strip().lower()
    q = f" {raw} "

    comparative_markers = (
        " vs ",
        " versus ",
        " compare ",
        " comparison ",
        " better ",
        " best ",
        " pros and cons ",
        " tradeoff ",
        " trade-off ",
        " should i ",
        " recommend ",
        " worth it ",
        " choose ",
    )
    if any(token in q for token in comparative_markers):
        return "comparative"

    if any(token in q for token in (" error ", " fix ", " install ", " api ", " docs ", " tutorial ")):
        return "task"

    fact_markers = (
        " facts ",
        " fact ",
        " what is ",
        " who is ",
        " when ",
        " where ",
        " definition ",
        " explain ",
        " overview ",
        " history ",
    )
    if any(token in q for token in fact_markers):
        return "fact"

    if raw.endswith("?") and raw.startswith(("what", "who", "when", "where", "why", "how many", "how much")):
        return "fact"

    return "general"


def _query_focus_terms(query: str) -> set[str]:
    tokens = re.findall(r"[a-z0-9]{3,}", (query or "").lower())
    return {token for token in tokens if token not in FACT_QUERY_STOPWORDS}


def _topic_alignment_multiplier(query: str, title: str, url: str, body: str, mode: str) -> float:
    query_lc = (query or "").lower()
    if "slug" not in query_lc:
        return 1.0
    if any(hint in query_lc for hint in SLUG_NON_ANIMAL_QUERY_HINTS):
        return 1.0

    focus_terms = _query_focus_terms(query)
    if "slug" not in focus_terms and mode != "fact":
        return 1.0

    joined = f"{title} {url} {body}".lower()
    if any(marker in joined for marker in SLUG_NON_ANIMAL_MARKERS):
        return 0.12
    if any(marker in joined for marker in SLUG_ANIMAL_MARKERS):
        return 1.05
    return 0.55


def classify_source_intent(url: str, title: str, fallback: str) -> str:
    host = urlparse(url or "").netloc.lower()
    title_lc = (title or "").lower()
    if host.endswith(".edu") or "/scholar" in host or "arxiv" in host:
        return "academic"
    if host.endswith(".gov"):
        return "primary_source"
    if any(tag in host for tag in ("docs.", "developer", "readthedocs", "mdn")):
        return "documentation"
    if any(tag in title_lc for tag in ("opinion", "editorial", "commentary")):
        return "opinion"
    if any(tag in title_lc for tag in ("report", "analysis", "explainer")):
        return "analysis"
    return fallback or "general"


def domain_trust_score(url: str) -> float:
    host = urlparse(url or "").netloc.lower()
    if not host:
        return 0.2
    if any(marker in host for marker in SOCIAL_HOST_MARKERS):
        return 0.35
    if host.endswith(".gov"):
        return 0.96
    if host.endswith(".edu"):
        return 0.92
    if any(marker in host for marker in REFERENCE_HOST_MARKERS):
        return 0.9
    if any(marker in host for marker in DOCUMENTATION_HOST_MARKERS):
        return 0.88
    if host.endswith(".org"):
        return 0.82
    if any(tag in host for tag in ("wikipedia.org", "github.com", "arxiv.org", "nature.com", "science.org")):
        return 0.9
    if any(tag in host for tag in ("medium.com", "substack.com", "blog.")):
        return 0.58
    if host.endswith(".com"):
        return 0.72
    return 0.65


def parse_freshness_timestamp(url: str, content: str) -> str:
    joined = f"{url} {(content or '')[:300]}"
    match = re.search(r"(20\d{2})[-_/](\d{1,2})[-_/](\d{1,2})", joined)
    if match:
        try:
            dt = datetime(
                int(match.group(1)),
                int(match.group(2)),
                int(match.group(3)),
                tzinfo=timezone.utc,
            )
            return dt.isoformat().replace("+00:00", "Z")
        except ValueError:
            pass
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def freshness_score(timestamp: str) -> float:
    try:
        if timestamp.endswith("Z"):
            timestamp = timestamp[:-1] + "+00:00"
        dt = datetime.fromisoformat(timestamp)
    except Exception:
        return 0.5
    age_days = max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0)
    if age_days <= 30:
        return 1.0
    if age_days <= 180:
        return 0.85
    if age_days <= 365:
        return 0.7
    if age_days <= 730:
        return 0.55
    return 0.35


def lexical_relevance(query: str, text: str) -> float:
    query_terms = {t for t in re.findall(r"[a-z0-9]{3,}", (query or "").lower())}
    if not query_terms:
        return 0.0
    body_terms = set(re.findall(r"[a-z0-9]{3,}", (text or "").lower()))
    overlap = len(query_terms.intersection(body_terms))
    score = overlap / max(1, len(query_terms))
    return round(min(1.0, max(0.0, score)), 4)


def _normalize_terms(text: str) -> set[str]:
    terms = re.findall(r"[a-z0-9]{3,}", (text or "").lower())
    normalized: set[str] = set()
    for token in terms:
        stem = token
        if stem.endswith("ies") and len(stem) > 5:
            stem = stem[:-3] + "y"
        elif stem.endswith("ing") and len(stem) > 6:
            stem = stem[:-3]
        elif stem.endswith("es") and len(stem) > 5:
            stem = stem[:-2]
        elif stem.endswith("s") and len(stem) > 4:
            stem = stem[:-1]
        normalized.add(stem)
    return normalized


def similarity_score(text_a: str, text_b: str) -> float:
    a_terms = _normalize_terms(text_a)
    b_terms = _normalize_terms(text_b)
    if not a_terms or not b_terms:
        return 0.0
    inter = len(a_terms.intersection(b_terms))
    union = len(a_terms.union(b_terms))
    return round(inter / max(1, union), 4)


def has_negation(text: str) -> bool:
    return any(
        token in (text or "").lower()
        for token in (" not ", " no ", " never ", " cannot ", " can't ", " fails ", " false ", " wrong ")
    )


def _split_sentences(text: str) -> list[str]:
    compact = re.sub(r"\s+", " ", (text or "").strip())
    if not compact:
        return []
    parts = re.split(r"(?<=[.!?])\s+", compact)
    return [p.strip() for p in parts if len(p.strip()) >= 40]


def _clean_quote_text(text: str) -> str:
    cleaned = (text or "").strip()
    cleaned = re.sub(r"^[#>*\-\s]+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip(" -")


def _normalize_fact_statement(text: str, max_chars: int | None = None) -> str:
    cleaned = _clean_quote_text(text)
    cleaned = re.sub(r"^[A-Za-z][A-Za-z0-9\s]{0,24}:\s+", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)

    if max_chars and max_chars > 0 and len(cleaned) > max_chars:
        window = cleaned[: max_chars + 1]
        boundary = max(
            window.rfind(". "),
            window.rfind("! "),
            window.rfind("? "),
            window.rfind("; "),
        )
        if boundary >= int(max_chars * 0.55):
            cleaned = window[: boundary + 1]
        else:
            split = window.rfind(" ")
            cleaned = window[:split] if split >= int(max_chars * 0.55) else window[:max_chars]

    cleaned = cleaned.strip(" ,;:-")
    cleaned = re.sub(
        r"\b(and|or|but|because|while|although|which|that|with|without|including|than|to|of|for|from|in|on|at)$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip(" ,;:-")
    if len(re.findall(r"[a-z0-9]+", cleaned.lower())) < 4:
        return ""
    if cleaned and cleaned[-1] not in ".!?":
        cleaned += "."
    return cleaned


def _quote_signal_multiplier(sentence: str) -> float:
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


def _dedupe_scored_quotes(quotes: list[tuple[str, float]], threshold: float = 0.82) -> list[tuple[str, float]]:
    deduped: list[tuple[str, float]] = []
    for quote, score in quotes:
        if any(similarity_score(quote, existing[0]) >= threshold for existing in deduped):
            continue
        deduped.append((quote, score))
    return deduped


def _content_quality_score(text: str) -> float:
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


def _host_category(host: str) -> str:
    host = (host or "").lower()
    if any(marker in host for marker in SOCIAL_HOST_MARKERS):
        return "social"
    if any(marker in host for marker in DOCUMENTATION_HOST_MARKERS):
        return "docs"
    if host.endswith(".edu") or host.endswith(".gov") or any(marker in host for marker in REFERENCE_HOST_MARKERS):
        return "reference"
    if any(marker in host for marker in ("youtube.com", "youtu.be", "vimeo.com")):
        return "video"
    if any(marker in host for marker in ("news", "times", "post", "reuters", "apnews", "bbc")):
        return "news"
    return "other"


def _mode_weight_multiplier(mode: str, host_category: str) -> float:
    if mode == "fact":
        return {
            "social": 0.35,
            "video": 0.6,
            "docs": 1.1,
            "reference": 1.18,
            "news": 0.88,
            "other": 0.95,
        }.get(host_category, 1.0)
    if mode == "task":
        return {
            "social": 0.6,
            "video": 0.8,
            "docs": 1.22,
            "reference": 1.08,
            "news": 0.8,
            "other": 1.0,
        }.get(host_category, 1.0)
    if mode == "comparative":
        return {
            "social": 0.88,
            "video": 0.9,
            "docs": 1.02,
            "reference": 1.04,
            "news": 1.0,
            "other": 1.0,
        }.get(host_category, 1.0)
    return {
        "social": 0.82,
        "video": 0.9,
        "docs": 1.04,
        "reference": 1.08,
        "news": 1.0,
        "other": 1.0,
    }.get(host_category, 1.0)


def pick_evidence_quotes(query: str, content: str, limit: int = 2) -> list[tuple[str, float]]:
    scored: list[tuple[str, float]] = []
    for sentence in _split_sentences(content)[:80]:
        cleaned = _clean_quote_text(sentence)
        if _looks_like_boilerplate(cleaned):
            continue
        relevance = lexical_relevance(query, cleaned)
        if relevance <= 0:
            continue
        signal = _quote_signal_multiplier(cleaned)
        if signal <= 0:
            continue
        score = round(relevance * signal, 4)
        if score <= 0.15:
            continue
        scored.append((cleaned[:450], score))

    if not scored:
        for sentence in _split_sentences(content)[:80]:
            cleaned = _clean_quote_text(sentence)
            if _looks_like_boilerplate(cleaned):
                continue
            relevance = lexical_relevance(query, cleaned)
            if relevance <= 0:
                continue
            scored.append((cleaned[:450], max(0.1, relevance)))
            if len(scored) >= limit:
                break

    scored.sort(key=lambda item: item[1], reverse=True)
    deduped = _dedupe_scored_quotes(scored)
    return deduped[:limit]


def rank_sources(
    query: str,
    candidates: list[dict[str, Any]],
    target: int,
    default_intent: str,
) -> list[dict[str, Any]]:
    normalized_seen: set[str] = set()
    domain_counts: dict[str, int] = {}
    rows: list[dict[str, Any]] = []
    mode = classify_query_mode(query)

    for candidate in candidates:
        url = candidate.get("url", "")
        key = normalize_url(url)
        if not key or key in normalized_seen:
            continue
        normalized_seen.add(key)

        host = urlparse(url).netloc.lower()
        domain_counts[host] = domain_counts.get(host, 0) + 1

        title = candidate.get("title", "")
        body = candidate.get("fetched_markdown") or candidate.get("content") or ""
        relevance = lexical_relevance(query, f"{title} {body}")
        trust = domain_trust_score(url)
        freshness_ts = parse_freshness_timestamp(url, body)
        freshness = freshness_score(freshness_ts)
        intent = classify_source_intent(url, title, default_intent)
        quality = _content_quality_score(body)
        host_category = _host_category(host)
        mode_multiplier = _mode_weight_multiplier(mode, host_category)
        topic_alignment = _topic_alignment_multiplier(query, title, url, body[:2000], mode)

        rows.append(
            {
                **candidate,
                "_normalized": key,
                "_host": host,
                "_relevance": relevance,
                "_trust": trust,
                "_freshness": freshness,
                "_freshness_timestamp": freshness_ts,
                "_intent": intent,
                "_quality": quality,
                "_host_category": host_category,
                "_mode_multiplier": mode_multiplier,
                "_topic_alignment": topic_alignment,
            }
        )

    max_domain_count = max(domain_counts.values(), default=1)
    for row in rows:
        consensus = domain_counts.get(row.get("_host", ""), 0) / max_domain_count
        row["_consensus"] = round(consensus, 4)
        base_score = (
            (0.38 * row["_relevance"])
            + (0.2 * consensus)
            + (0.2 * row["_trust"])
            + (0.1 * row["_freshness"])
            + (0.12 * row.get("_quality", 0.4))
        )
        row["_score"] = round(
            base_score * row.get("_mode_multiplier", 1.0) * row.get("_topic_alignment", 1.0),
            4,
        )

    rows.sort(key=lambda item: item.get("_score", 0.0), reverse=True)
    return rows[:target]


def make_source_primitives(ranked_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for idx, row in enumerate(ranked_sources, start=1):
        url = row.get("url", "")
        host = (row.get("_host") or urlparse(url).netloc.lower()).strip()
        if host.startswith("www."):
            host = host[4:]
        src = SourcePrimitive(
            source_id=f"src_{idx:02d}",
            url=url,
            title=row.get("title", "") or "Untitled",
            domain=host,
            relevance_score=round(float(row.get("_relevance", 0.0)), 4),
            domain_trust_score=round(float(row.get("_trust", 0.0)), 4),
            freshness_timestamp=row.get("_freshness_timestamp", parse_freshness_timestamp(url, "")),
            intent_category=row.get("_intent", "general"),
        )
        out.append(asdict(src))
    return out


def make_evidence_primitives(query: str, ranked_sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    evidence_rows: list[dict[str, Any]] = []
    source_id_map = {item.get("url", ""): f"src_{idx:02d}" for idx, item in enumerate(ranked_sources, start=1)}
    counter = 1
    for source in ranked_sources:
        body = (source.get("fetched_markdown") or source.get("content") or "").strip()
        if not body:
            continue
        quotes = pick_evidence_quotes(query, body, limit=2)
        for quote, relevance in quotes:
            primitive = EvidencePrimitive(
                evidence_id=f"ev_{counter:03d}",
                source_id=source_id_map.get(source.get("url", ""), "src_00"),
                exact_quote=quote,
                relevance_score=round(relevance, 4),
            )
            evidence_rows.append(asdict(primitive))
            counter += 1
    return evidence_rows


def _claim_key(text: str) -> str:
    tokens = re.findall(r"[a-z0-9]{3,}", (text or "").lower())
    return " ".join(tokens[:16])


def make_claim_primitives(evidence_rows: list[dict[str, Any]], max_claims: int = 24) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    evidence_index = {row.get("evidence_id", ""): row for row in evidence_rows}

    for row in evidence_rows:
        quote = _normalize_fact_statement(row.get("exact_quote", ""))
        if not quote:
            continue
        if _looks_like_boilerplate(quote):
            continue
        statement = _normalize_fact_statement(quote, max_chars=220)
        if not statement:
            continue
        key = _claim_key(quote)
        if not key:
            continue
        bucket = grouped.setdefault(
            key,
            {
                "statement": statement,
                "support_evidence_ids": [],
                "source_ids": set(),
                "negated": has_negation(quote),
            },
        )
        bucket["support_evidence_ids"].append(row.get("evidence_id", ""))
        bucket["source_ids"].add(row.get("source_id", ""))

    merged_buckets: list[dict[str, Any]] = []
    for bucket in grouped.values():
        merged = False
        for existing in merged_buckets:
            if bool(bucket.get("negated")) != bool(existing.get("negated")):
                continue
            if similarity_score(bucket.get("statement", ""), existing.get("statement", "")) < 0.78:
                continue
            existing["support_evidence_ids"].extend(bucket.get("support_evidence_ids", []))
            existing["source_ids"].update(bucket.get("source_ids", set()))
            if len(bucket.get("statement", "")) > len(existing.get("statement", "")):
                existing["statement"] = bucket.get("statement", "")
            merged = True
            break
        if not merged:
            merged_buckets.append(
                {
                    "statement": bucket.get("statement", ""),
                    "support_evidence_ids": list(bucket.get("support_evidence_ids", [])),
                    "source_ids": set(bucket.get("source_ids", set())),
                    "negated": bool(bucket.get("negated", False)),
                }
            )

    merged_buckets.sort(
        key=lambda item: (len(item.get("source_ids", set())), len(item.get("support_evidence_ids", []))),
        reverse=True,
    )

    claims: list[dict[str, Any]] = []
    for idx, bucket in enumerate(merged_buckets, start=1):
        support_ids = [eid for eid in bucket["support_evidence_ids"] if eid in evidence_index]
        unique_sources = {evidence_index[eid].get("source_id", "") for eid in support_ids}
        tier: ConfidenceTier = "consensus" if len(unique_sources) >= 2 else "likely"
        primitive = ClaimPrimitive(
            claim_id=f"clm_{idx:03d}",
            statement=bucket["statement"],
            support_evidence_ids=support_ids[:6],
            refute_evidence_ids=[],
            confidence_tier=tier,
        )
        claims.append(asdict(primitive))
        if len(claims) >= max_claims:
            break

    return claims


def split_consensus_disputed(claims: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    disputed_ids: set[str] = set()
    for i, left in enumerate(claims):
        for right in claims[i + 1 :]:
            sim = similarity_score(left.get("statement", ""), right.get("statement", ""))
            if sim < 0.45:
                continue
            if has_negation(left.get("statement", "")) == has_negation(right.get("statement", "")):
                continue
            left_refute = left.setdefault("refute_evidence_ids", [])
            right_refute = right.setdefault("refute_evidence_ids", [])
            left_refute.extend(right.get("support_evidence_ids", [])[:2])
            right_refute.extend(left.get("support_evidence_ids", [])[:2])
            left["confidence_tier"] = "disputed"
            right["confidence_tier"] = "disputed"
            disputed_ids.add(left.get("claim_id", ""))
            disputed_ids.add(right.get("claim_id", ""))

    consensus: list[dict[str, Any]] = []
    disputed: list[dict[str, Any]] = []
    for claim in claims:
        if claim.get("claim_id", "") in disputed_ids or claim.get("confidence_tier") == "disputed":
            disputed.append(claim)
        else:
            consensus.append(claim)

    return consensus, disputed


def make_edges_from_claims(claims: list[dict[str, Any]], max_edges: int = 200) -> list[dict[str, str]]:
    edges: list[dict[str, str]] = []
    for i, left in enumerate(claims):
        for right in claims[i + 1 :]:
            sim = similarity_score(left.get("statement", ""), right.get("statement", ""))
            if sim < 0.22:
                continue
            if has_negation(left.get("statement", "")) != has_negation(right.get("statement", "")):
                relationship = "contradicts"
            elif sim >= 0.72:
                relationship = "supports"
            else:
                relationship = "expands_upon"
            edges.append(
                {
                    "source_claim_id": left.get("claim_id", ""),
                    "target_claim_id": right.get("claim_id", ""),
                    "relationship": relationship,
                }
            )
            if len(edges) >= max_edges:
                return edges
    return edges


def cited_bullet_summary(
    query: str,
    claims: list[dict[str, Any]],
    evidence_rows: list[dict[str, Any]],
    max_lines: int = 5,
) -> str:
    del query
    evidence_map = {item.get("evidence_id", ""): item for item in evidence_rows}
    lines: list[str] = []
    accepted_statements: list[str] = []

    def claim_priority(row: dict[str, Any]) -> tuple[int, int]:
        confidence = row.get("confidence_tier", "likely")
        confidence_score = {
            "consensus": 3,
            "likely": 2,
            "disputed": 1,
            "insufficient_data": 0,
        }.get(confidence, 1)
        return confidence_score, len(row.get("support_evidence_ids", []))

    for claim in sorted(claims, key=claim_priority, reverse=True):
        support_ids = claim.get("support_evidence_ids", [])
        source_ids: list[str] = []
        for evidence_id in support_ids:
            source_id = evidence_map.get(evidence_id, {}).get("source_id", "")
            if source_id and source_id not in source_ids:
                source_ids.append(source_id)
        citation = " ".join(f"[{source}]" for source in source_ids[:2])
        if not citation:
            continue
        statement = _normalize_fact_statement((claim.get("statement", "") or "").strip(), max_chars=240)
        if not statement:
            continue
        if _looks_like_boilerplate(statement):
            continue
        if any(similarity_score(statement, prior) >= 0.8 for prior in accepted_statements):
            continue
        if claim.get("confidence_tier") == "disputed":
            statement = f"Disputed: {statement}"
        lines.append(f"- {statement} {citation}".strip())
        accepted_statements.append(statement)
        if len(lines) >= max_lines:
            break
    if not lines:
        fallback_lines: list[str] = []
        for item in sorted(evidence_rows, key=lambda row: row.get("relevance_score", 0.0), reverse=True):
            source_id = item.get("source_id", "")
            if not source_id:
                continue
            quote = _normalize_fact_statement(item.get("exact_quote", ""), max_chars=240)
            if not quote or _looks_like_boilerplate(quote):
                continue
            if any(similarity_score(quote, prior) >= 0.8 for prior in accepted_statements):
                continue
            fallback_lines.append(f"- {quote} [{source_id}]")
            accepted_statements.append(quote)
            if len(fallback_lines) >= min(max_lines, 3):
                break
        if fallback_lines:
            return "\n".join(fallback_lines)
        return "- Insufficient high-confidence evidence extracted from retrieved sources."
    return "\n".join(lines)


def estimate_tokens(payload: dict[str, Any]) -> int:
    text = json.dumps(payload, ensure_ascii=True)
    return max(1, int(len(text) / 4))


def build_meta(start_time: float, payload: dict[str, Any]) -> dict[str, Any]:
    compute_ms = int((time.perf_counter() - start_time) * 1000)
    return {
        "token_estimate": estimate_tokens(payload),
        "compute_ms": max(1, compute_ms),
        "schema_version": SCHEMA_VERSION,
    }
