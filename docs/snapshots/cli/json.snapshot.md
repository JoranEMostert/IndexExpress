# CLI JSON Output Snapshot (Baseline)

Captured from `json.dumps(payload, indent=2)` with deterministic fixture payloads.

## peek

```json
{
  "sources": [
    {
      "source_id": "src_01",
      "title": "Example One",
      "url": "https://example.com/one"
    },
    {
      "source_id": "src_02",
      "title": "Example Two",
      "url": "https://example.com/two"
    }
  ],
  "_meta": {
    "compute_ms": 48,
    "token_estimate": 0
  }
}
```

## skim

```json
{
  "final_answer": "Skim answer line one.\nSkim answer line two.",
  "claims": [
    {
      "claim_id": "clm_001",
      "statement": "Claim A",
      "confidence_tier": "high"
    },
    {
      "claim_id": "clm_002",
      "statement": "Claim B",
      "confidence_tier": "medium"
    }
  ],
  "key_evidence": [
    {
      "claim_id": "clm_001",
      "source_id": "src_01"
    }
  ],
  "sources": [
    {
      "source_id": "src_01",
      "title": "Evidence Source",
      "url": "https://example.com/evidence"
    }
  ],
  "uncertainties": [
    "Date may vary by region."
  ],
  "_meta": {
    "compute_ms": 220,
    "token_estimate": 950
  }
}
```

## analyze

```json
{
  "recommended_position": "Choose Option A for cost and maintainability.",
  "options_compared": [
    "Option A",
    "Option B"
  ],
  "recommended_option": "Option A",
  "confidence": "medium",
  "why_not": [
    "Option B has higher operating cost."
  ],
  "decision_matrix": [
    {
      "dimension": "Cost",
      "options": [
        {
          "option_name": "Option A",
          "score": 8,
          "rationale": "Lower monthly spend."
        },
        {
          "option_name": "Option B",
          "score": 5,
          "rationale": "Higher infra spend."
        }
      ]
    }
  ],
  "consensus_claims": [
    {
      "claim_id": "clm_010"
    }
  ],
  "disputed_claims": [],
  "sensitivity_factors": [
    "If growth exceeds 3x, re-check cost assumptions."
  ],
  "sources": [
    {
      "source_id": "src_10",
      "title": "Benchmark",
      "url": "https://example.com/bench"
    }
  ],
  "_meta": {
    "compute_ms": 340,
    "token_estimate": 1300
  }
}
```

## research

```json
{
  "final_synthesis": "Research synthesis paragraph with citations [src_01].",
  "open_questions": [
    "Need 2026 data refresh."
  ],
  "evidence_graph": {
    "nodes": [
      {
        "id": "n1"
      }
    ],
    "edges": []
  },
  "coverage_report": {
    "stopping_reason": "coverage_satisfied",
    "nodes_explored": 1
  },
  "trace_log": [
    "cycle_1 complete"
  ],
  "key_evidence": [
    {
      "claim_id": "clm_200",
      "source_id": "src_01"
    }
  ],
  "sources": [
    {
      "source_id": "src_01",
      "title": "Primary Source",
      "url": "https://example.com/primary"
    }
  ],
  "_meta": {
    "compute_ms": 510,
    "token_estimate": 2100
  }
}
```
