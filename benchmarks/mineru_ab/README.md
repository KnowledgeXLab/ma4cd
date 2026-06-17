# MinerU A/B Benchmark

This benchmark provides a reusable A/B test harness for:

1. `accuracy`
2. `latency`
3. `LLM call count`

It is designed to be repeatable by default (offline + deterministic).

## Files

- `run_mineru_ab.py`: benchmark runner
- `fixtures/aerospace_pages.json`: fixed fixture set

## Default run (recommended)

```bash
PYTHONPATH=/home/zhuyao/Documents/ma4cd \
/home/zhuyao/miniconda3/envs/ma4cd/bin/python \
benchmarks/mineru_ab/run_mineru_ab.py
```

Default behavior:

- `judge-mode=mock` (deterministic fallback judge)
- fixed fixture set
- fixed seed

## Output

By default, output goes to:

`reports/mineru_ab_<timestamp>/`

Generated files:

- `summary.json`: aggregated A/B metrics + delta
- `summary.csv`: one row per variant
- `runs.csv`: per-run metrics
- `details.csv`: per-sample predictions and timings

## Useful options

```bash
--runs 10
--seed 42
--shuffle
--limit 50
--output-dir reports/mineru_ab_manual
```

## Real LLM fallback mode

Use real project `MinerLLMClient` as fallback judge:

```bash
PYTHONPATH=/home/zhuyao/Documents/ma4cd \
/home/zhuyao/miniconda3/envs/ma4cd/bin/python \
benchmarks/mineru_ab/run_mineru_ab.py \
  --judge-mode real \
  --real-model deepseek-chat
```

## Real MinerU adapter hook

If you already have a MinerU adapter function, pass it as:

`module:function`

Function signature:

```python
def my_extractor(url: str, html: str) -> dict | str:
    # dict should include "text" and optional "title"
    return {"text": "...", "title": "..."}
```

Built-in real adapter added in this repo:

`benchmarks.mineru_ab.adapters.mineru_html_adapter:extract_with_mineru_html`

It uses `mineru-html` OpenAI backend and reads:

- `MA4CD_MINERU_HTML_API_KEY` (fallback to `OPENAI_API_KEY`)
- `MA4CD_MINERU_HTML_BASE_URL` (fallback to `OPENAI_BASE_URL`)
- `MA4CD_MINERU_HTML_MODEL` (fallback to `MA4CD_MINER_BIG_MODEL`, default `deepseek-chat`)

Run:

```bash
PYTHONPATH=/home/zhuyao/Documents/ma4cd \
/home/zhuyao/miniconda3/envs/ma4cd/bin/python \
benchmarks/mineru_ab/run_mineru_ab.py \
  --mineru-adapter benchmarks.mineru_ab.adapters.mineru_html_adapter:extract_with_mineru_html
```

When adapter is not provided (or fails), the benchmark uses an internal
boilerplate-removal heuristic for the MinerU branch.

## Notes

- This benchmark is intentionally isolated from the full pipeline for stability.
- It can be integrated into CI later by asserting thresholds on `summary.json`.
