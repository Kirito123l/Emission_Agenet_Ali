# Phase 1.55 Report

## Summary

Changed files:
- [evaluation/eval_end2end.py](/home/kirito/Agent1/emission_agent/evaluation/eval_end2end.py)
- [evaluation/run_oasc_matrix.py](/home/kirito/Agent1/emission_agent/evaluation/run_oasc_matrix.py)
- [evaluation/tool_cache.py](/home/kirito/Agent1/emission_agent/evaluation/tool_cache.py)
- [evaluation/benchmarks/end2end_tasks.jsonl](/home/kirito/Agent1/emission_agent/evaluation/benchmarks/end2end_tasks.jsonl)
- [tests/test_benchmark_acceleration.py](/home/kirito/Agent1/emission_agent/tests/test_benchmark_acceleration.py)

Implemented in `evaluation/` only:
- task-level parallel execution with `--parallel`
- LLM request rate limiting with `--qps-limit`
- smoke subset with `--smoke`
- group selection in matrix runner with `--groups`
- deterministic tool cache with `--cache` / `--no-cache` / `--clear-cache`
- per-task cache-hit and rate-limit telemetry in logs and metrics

## Measured Runs

Measured artifacts:
- [serial_metrics.json](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_acceleration_test/serial_metrics.json)
- [parallel_metrics.json](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_acceleration_test/parallel_metrics.json)
- [parallel_cached_metrics.json](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_acceleration_test/parallel_cached_metrics.json)
- [smoke_metrics.json](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_acceleration_test/smoke_metrics.json)
- [consistency_report.json](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_acceleration_test/consistency_report.json)

Wall-clock:
- Smoke subset, A config, `--smoke --parallel 8 --cache`: `78.83s`
- Full 180, A config, first run, `--parallel 8 --cache`: `341.40s`
- Full 180, A config, warm cache, `--parallel 8 --cache`: `305.05s`
- Full 180, serial current runner: `UNKNOWN: not re-run in this task`

Observed speed facts:
- Smoke mode is under 3 minutes.
- Full parallel first run is about 5.7 minutes.
- Warm cache improves full parallel wall-clock by about 36.35s (`341.40s -> 305.05s`).

## Consistency

Consistency source pairing:
- Serial baseline source: [end2end_full_v6_telemetry_A/end2end_metrics.json](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_full_v6_telemetry_A/end2end_metrics.json)
- Parallel source: [parallel_A_first/end2end_metrics.json](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_acceleration_test/parallel_A_first/end2end_metrics.json)

Results:
- serial completion rate: `0.6611`
- parallel completion rate: `0.6889`
- completion rate diff: `0.0278` (`2.78 pp`)
- per-task exact tool-chain match rate: `0.9000`
- warm-cache hit rate: `0.8053`
- verdict: `INCONSISTENT`

This does not meet the requested `<= 0.5 pp` consistency bound.

## Matrix Runner

`run_oasc_matrix.py` now supports:
- `--groups A,E`
- `--parallel N`
- `--qps-limit N`
- `--smoke`
- `--cache` / `--no-cache`

Example:

```bash
python evaluation/run_oasc_matrix.py --groups E --parallel 8 --qps-limit 15 --cache
python evaluation/run_oasc_matrix.py --groups A,E --smoke --parallel 8
```

## Daily / Final Runs

Daily development run:

```bash
python evaluation/eval_end2end.py \
  --samples evaluation/benchmarks/end2end_tasks.jsonl \
  --output-dir evaluation/results/end2end_smoke_dev \
  --smoke --parallel 8 --qps-limit 15 --cache
```

Full validation run:

```bash
python evaluation/eval_end2end.py \
  --samples evaluation/benchmarks/end2end_tasks.jsonl \
  --output-dir evaluation/results/end2end_full_fast \
  --parallel 8 --qps-limit 15 --cache
```

Strict serial fallback:

```bash
python evaluation/eval_end2end.py \
  --samples evaluation/benchmarks/end2end_tasks.jsonl \
  --output-dir evaluation/results/end2end_full_serial \
  --parallel 1 --no-cache
```

## Verification

Executed:
- `python -m py_compile evaluation/eval_end2end.py evaluation/run_oasc_matrix.py evaluation/tool_cache.py tests/test_benchmark_acceleration.py`
- `pytest -q tests/test_benchmark_acceleration.py tests/test_eval_failsafe.py`
- Real smoke benchmark run
- Real full 180 parallel first-run benchmark run
- Real full 180 parallel warm-cache benchmark run

## Simplifications Made

- The cache wrapper is injected at runtime around `core.executor.ToolExecutor.execute()` from `evaluation/`; no system source files were modified.
- Cache keys use raw eval-time tool args plus file-content hash. They do not wait for executor-side standardized args.
- The consistency baseline reuses the clean serial A run from v6 instead of re-running a fresh full serial pass inside this task.

## Remaining Risks

- Consistency acceptance is not met: `2.78 pp` completion-rate drift between serial baseline and parallel run.
- Warm-cache speedup is modest because LLM latency still dominates end-to-end wall-clock.
- Full serial wall-clock for the current accelerated runner was not measured in this task.
