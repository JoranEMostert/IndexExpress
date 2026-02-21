# Benchmark

Simple benchmark runner for collecting repeatable mode-level performance and payload data.

## What it does

- Runs all four search modes in sequence: `peek`, `skim`, `analyze`, `research`
- Captures latency, status, payload sizes, and key count fields per run
- Captures routing metadata (`requested_mode`, `executed_mode`, `route_reason`) to track analyze-to-research handoffs
- Writes three report formats into `benchmark/output_reports/`:
  - JSON (full raw benchmark data)
  - CSV (flat rows for quick spreadsheet/charting)
  - Markdown (human-readable summary)

## Usage

From repo root:

```bash
python benchmark/run_benchmark.py
```

Useful options:

```bash
python benchmark/run_benchmark.py \
  --mcp-url http://localhost:8000/mcp \
  --query "slug facts" \
  --runs 3 \
  --research-sub-queries 6 \
  --timeout-s 600
```

Mode-specific query overrides:

```bash
python benchmark/run_benchmark.py \
  --peek-query "best ai coding tools" \
  --skim-query "slug facts" \
  --analyze-query "best python web framework" \
  --research-query "vacation plan to aruba"
```

For pure link-discovery benchmarking of `peek`, leave content fetch disabled (default).
