import time

from workflow_primitives import (
    SCHEMA_VERSION,
    build_meta,
    classify_query_mode,
    cited_bullet_summary,
    make_claim_primitives,
    make_edges_from_claims,
    make_source_primitives,
    pick_evidence_quotes,
    rank_sources,
    split_consensus_disputed,
)


def test_rank_sources_orders_by_composite_score():
    rows = [
        {"url": "https://example.com/a", "title": "Alpha topic", "content": "topic alpha facts"},
        {"url": "https://example.com/b", "title": "Unrelated", "content": "noise only"},
    ]
    ranked = rank_sources("alpha topic", rows, target=2, default_intent="general")
    assert len(ranked) == 2
    assert ranked[0]["url"] == "https://example.com/a"


def test_split_consensus_disputed_flags_negation_conflicts():
    evidence_rows = [
        {"evidence_id": "ev_001", "source_id": "src_01", "exact_quote": "X does reduce failures.", "relevance_score": 0.8},
        {"evidence_id": "ev_002", "source_id": "src_02", "exact_quote": "X does not reduce failures.", "relevance_score": 0.8},
    ]
    claims = make_claim_primitives(evidence_rows, max_claims=10)
    consensus, disputed = split_consensus_disputed(claims)
    assert len(disputed) >= 1
    assert len(consensus) <= len(claims)


def test_make_edges_from_claims_builds_relationship_rows():
    claims = [
        {
            "claim_id": "clm_001",
            "statement": "System A improves throughput by 20 percent.",
            "support_evidence_ids": ["ev_001"],
            "refute_evidence_ids": [],
            "confidence_tier": "likely",
        },
        {
            "claim_id": "clm_002",
            "statement": "System A does not improve throughput in production.",
            "support_evidence_ids": ["ev_002"],
            "refute_evidence_ids": [],
            "confidence_tier": "likely",
        },
    ]
    edges = make_edges_from_claims(claims)
    assert len(edges) >= 1
    assert edges[0]["relationship"] in {"supports", "contradicts", "expands_upon"}


def test_build_meta_includes_schema_version_and_token_estimate():
    started = time.perf_counter()
    meta = build_meta(started, {"x": "hello", "y": [1, 2, 3]})
    assert meta["schema_version"] == SCHEMA_VERSION
    assert meta["token_estimate"] > 0
    assert meta["compute_ms"] >= 1


def test_rank_sources_demotes_social_hosts_for_fact_queries():
    rows = [
        {
            "url": "https://www.reddit.com/r/slugfacts/post/123",
            "title": "slug facts discussion",
            "content": "slug facts slug facts slug facts",
        },
        {
            "url": "https://extension.umn.edu/yard-and-garden-insects/slugs",
            "title": "slug facts and controls",
            "content": "slug facts slug facts slug facts",
        },
    ]
    ranked = rank_sources("slug facts", rows, target=2, default_intent="general")
    assert ranked[0]["url"] == "https://extension.umn.edu/yard-and-garden-insects/slugs"


def test_pick_evidence_quotes_filters_navigation_boilerplate():
    content = (
        "Reddit - The heart of the internet Skip to main content Open menu Open navigation. "
        "Slug facts: slugs have two pairs of tentacles and leave a mucus trail to help movement and reduce water loss."
    )
    quotes = pick_evidence_quotes("slug facts", content, limit=2)
    assert quotes
    top_quote = quotes[0][0].lower()
    assert "skip to main content" not in top_quote
    assert "tentacles" in top_quote


def test_rank_sources_disambiguates_slug_toward_animal_context():
    rows = [
        {
            "url": "https://example.com/biology/slug-facts",
            "title": "Slug facts",
            "content": "A slug is a shell-less gastropod mollusk closely related to snails.",
        },
        {
            "url": "https://example.com/hunting/shotgun-slug-loads",
            "title": "Shotgun slug loads",
            "content": "A shotgun slug is a single bullet fired from a shotgun cartridge.",
        },
        {
            "url": "https://example.com/oncology/slug-emt",
            "title": "SLUG and EMT",
            "content": "The transcription factor SLUG regulates EMT and binds mRNA targets.",
        },
    ]
    ranked = rank_sources("slug facts", rows, target=3, default_intent="general")
    assert ranked[0]["url"] == "https://example.com/biology/slug-facts"
    assert ranked[-1]["url"] in {
        "https://example.com/hunting/shotgun-slug-loads",
        "https://example.com/oncology/slug-emt",
    }


def test_rank_sources_keeps_non_animal_slug_queries_unpenalized():
    rows = [
        {
            "url": "https://example.com/hunting/shotgun-slug-loads",
            "title": "Shotgun slug loads",
            "content": "A shotgun slug is a single projectile used for short-range hunting.",
        },
        {
            "url": "https://example.com/biology/slug-facts",
            "title": "Slug facts",
            "content": "A slug is a shell-less gastropod mollusk.",
        },
    ]
    ranked = rank_sources("shotgun slug ballistics", rows, target=2, default_intent="general")
    assert ranked[0]["url"] == "https://example.com/hunting/shotgun-slug-loads"


def test_make_source_primitives_include_link_metadata_fields():
    ranked = rank_sources(
        "slug facts",
        [
            {
                "url": "https://www.example.com/slug-facts",
                "title": "Slug facts",
                "content": "Slug facts and habitat overview.",
            }
        ],
        target=1,
        default_intent="general",
    )
    sources = make_source_primitives(ranked)
    assert len(sources) == 1
    assert sources[0]["title"] == "Slug facts"
    assert sources[0]["domain"] == "example.com"
    assert 0.0 <= sources[0]["relevance_score"] <= 1.0


def test_pick_evidence_quotes_filters_pmc_header_noise():
    content = (
        "PMC Copyright notice PMCID: PMC10029789 PMID: 37363710. "
        "Slug facts: a slug is a shell-less gastropod that prefers moist habitats and is mostly nocturnal."
    )
    quotes = pick_evidence_quotes("slug facts", content, limit=2)
    assert quotes
    best = quotes[0][0].lower()
    assert "pmcid" not in best
    assert "gastropod" in best


def test_pick_evidence_quotes_filters_citation_listing_noise():
    content = (
        "by SM Joe · 2008 · Cited by 127 — Local slug control seems practical ...11 pages·360 KB. "
        "A slug is a shell-less gastropod mollusk that relies on moisture to avoid dehydration."
    )
    quotes = pick_evidence_quotes("slug facts", content, limit=2)
    assert quotes
    best = quotes[0][0].lower()
    assert "cited by" not in best
    assert "gastropod" in best


def test_make_claim_primitives_avoids_dangling_sentence_fragments():
    long_quote = (
        "Slug respiration occurs through a pneumostome on the right side of the mantle, "
        "and the opening supports gas exchange in moist habitats where dehydration pressure "
        "remains high across warm seasons and exposed soil conditions; this mechanism helps "
        "many terrestrial species maintain activity during humidity swings, while"
    )
    evidence_rows = [
        {
            "evidence_id": "ev_001",
            "source_id": "src_01",
            "exact_quote": long_quote,
            "relevance_score": 0.92,
        }
    ]
    claims = make_claim_primitives(evidence_rows, max_claims=5)
    assert claims
    statement = claims[0]["statement"]
    assert statement.endswith(".")
    assert not statement.lower().endswith(" and.")
    assert not statement.lower().endswith(" while.")


def test_pick_evidence_quotes_dedupes_near_duplicate_facts():
    content = (
        "Slug facts: slugs are shell-less gastropod mollusks that rely on moisture to avoid dehydration. "
        "Slugs are shell-less gastropod mollusks and rely on moisture to avoid dehydration during movement. "
        "Slug facts: slugs have two pairs of tentacles used for sensing and navigation."
    )
    quotes = pick_evidence_quotes("slug facts", content, limit=3)
    assert len(quotes) == 2
    lowered = [item[0].lower() for item in quotes]
    assert any("tentacles" in line for line in lowered)


def test_cited_bullet_summary_skips_uncited_claims_and_marks_disputed():
    claims = [
        {
            "claim_id": "clm_001",
            "statement": "Slugs are shell-less gastropods.",
            "support_evidence_ids": ["ev_missing"],
            "refute_evidence_ids": [],
            "confidence_tier": "likely",
        },
        {
            "claim_id": "clm_002",
            "statement": "Slugs are active mostly at night in moist habitats.",
            "support_evidence_ids": ["ev_001"],
            "refute_evidence_ids": [],
            "confidence_tier": "disputed",
        },
    ]
    evidence_rows = [
        {
            "evidence_id": "ev_001",
            "source_id": "src_01",
            "exact_quote": "Slugs are active mostly at night in moist habitats.",
            "relevance_score": 0.91,
        }
    ]

    text = cited_bullet_summary("slug facts", claims, evidence_rows, max_lines=3)
    assert "[src_01]" in text
    assert "Disputed:" in text
    assert "ev_missing" not in text


def test_cited_bullet_summary_falls_back_to_evidence_rows():
    text = cited_bullet_summary(
        "slug facts",
        claims=[],
        evidence_rows=[
            {
                "evidence_id": "ev_001",
                "source_id": "src_02",
                "exact_quote": "Slugs produce mucus that helps movement and reduces water loss.",
                "relevance_score": 0.83,
            }
        ],
        max_lines=3,
    )
    assert "mucus" in text.lower()
    assert "[src_02]" in text


def test_classify_query_mode_prioritizes_comparative_when_fact_words_present():
    query = "what is the best project management tool for small teams"
    assert classify_query_mode(query) == "comparative"
