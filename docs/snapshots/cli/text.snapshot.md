# CLI Text Output Snapshot (Baseline)

Captured from `expressindex_cli.main` rendering helpers with deterministic fixture payloads.

## peek

```text
# Peek Result

## Top Sources
- src_01 https://example.com/one
- src_02 https://example.com/two
```

## skim

```text
# Skim Final Answer

Skim answer line one.
Skim answer line two.

## Uncertainties
- Date may vary by region.
```

## analyze

```text
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
```

## research

```text
# Research Final Synthesis

Research synthesis paragraph with citations [src_01].

## Open Questions
- Need 2026 data refresh.
```
