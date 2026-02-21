# CLI Markdown Output Snapshot (Baseline)

Captured from `markdown_from_result(...)` with deterministic fixture payloads.

## peek

```markdown
# ExpressIndex Peek Report

Query: example peek query

# Peek Result

## Top Sources
- src_01 https://example.com/one
- src_02 https://example.com/two

Compute time: 48ms
Token estimate: 0
```

## skim

```markdown
# ExpressIndex Skim Report

Query: example skim query

# Skim Final Answer

Skim answer line one.
Skim answer line two.

## Uncertainties
- Date may vary by region.

Compute time: 220ms
Token estimate: 950
```

## analyze

```markdown
# ExpressIndex Analyze Report

Query: example analyze query

# Analyze Recommendation

Choose Option A for cost and maintainability.

Options compared: Option A, Option B
Recommended option: Option A (medium)

## Tradeoffs
- Option B has higher operating cost.

Consensus claims: 1
Disputed claims: 0

## Sensitivity Factors
- If growth exceeds 3x, re-check cost assumptions.

Compute time: 340ms
Token estimate: 1300
```

## research

```markdown
# ExpressIndex Research Report

Query: example research query

# Research Final Synthesis

Research synthesis paragraph with citations [src_01].

## Open Questions
- Need 2026 data refresh.

Compute time: 510ms
Token estimate: 2100
```
