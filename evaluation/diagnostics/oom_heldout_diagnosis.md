# Held-out has_file OOM Diagnosis

## 1. Root Cause

Root cause: held-out task `e2e_heldout_multistep_007` (`test_data/test_shanghai_full.xlsx`) reaches `calculate_dispersion`, where `calculators/dispersion.py:542-543` materializes full receptor-by-source matrices:

```python
x_hat = rx_rot[:, None] - sx_rot[None, :]
y_hat = ry_rot[:, None] - sy_rot[None, :]
```

For this task, the diagnostic stage probe recorded:

- `receptors=202154`
- `sources_shape=(1, 7506, 4)`
- receptor-source pairs: `202154 * 7506 = 1,517,367,924`
- one float64 matrix at that shape: `11.3 GiB`
- two matrices (`x_hat`, `y_hat`) plus masks/features exceed WSL memory.

This is not primarily a cross-task retained DataFrame/GeoDataFrame leak. The memory blow-up occurs inside one task during `predict_time_series_xgb`.

## 2. Evidence

### 2.1 Task A: 11 has_file tasks, A group, serial RSS

Command:

```bash
/home/kirito/miniconda3/bin/python scripts/oom_probe.py task-a --rss-limit-mb 8192 --task-timeout-sec 180
```

Artifacts:

- RSS samples: `/tmp/oom_rss.log`
- Per-task records: `evaluation/diagnostics/oom_task_a_records.jsonl`
- Generated subset: `/tmp/held_out_hasfile_only.jsonl`

Completed task-level RSS records before kill:

| # | task_id | fixture | rss_before_mb | rss_after_task_mb | rss_after_gc_mb | net_after_gc_mb |
|---:|---|---|---:|---:|---:|---:|
| 1 | e2e_heldout_multistep_001 | test_data/test_20links.zip | 241.1 | 658.3 | 658.3 | +417.2 |
| 2 | e2e_heldout_multistep_002 | test_data/test_6links.xlsx | 665.7 | 665.8 | 665.8 | +0.1 |
| 3 | e2e_heldout_multistep_003 | test_data/test_6links.xlsx | 665.8 | 672.8 | 672.8 | +7.0 |
| 4 | e2e_heldout_multistep_004 | test_data/test_20links.zip | 672.8 | 672.8 | 672.8 | +0.0 |
| 5 | e2e_heldout_multistep_005 | test_data/test_6links.xlsx | 672.8 | 672.8 | 672.8 | +0.0 |
| 6 | e2e_heldout_multistep_006 | evaluation/file_tasks/data/micro_full.csv | 672.8 | 672.8 | 672.8 | +0.0 |

RSS monitor tail:

```text
09:43:19 4885 672.8MB oom_probe
09:43:24 4885 5260.1MB oom_probe
09:43:39 4885 11750.8MB oom_probe
# RSS_LIMIT_EXCEEDED 11750.8MB >= 8192.0MB
```

Task #7 in `/tmp/held_out_hasfile_only.jsonl`:

```text
e2e_heldout_multistep_007 | multi_step | test_data/test_shanghai_full.xlsx | calculate_macro_emission, calculate_dispersion, render_spatial_map
```

### 2.2 GC baseline

For the first six completed tasks, `gc.collect()` after each task did not reduce RSS materially:

- Task 1: `658.3MB -> 658.3MB` after GC
- Tasks 2-6: RSS stayed around `665-673MB`

Interpretation:

- The first `+417MB` is retained process/library/model/runtime state, not a per-task accumulating leak.
- After the initial warm-up, tasks 2-6 did not show cumulative growth.
- The catastrophic growth happens within task 7 before task-level `finally` can run.

### 2.3 Task B: single-task stage probe

Command:

```bash
/home/kirito/miniconda3/bin/python scripts/oom_probe.py stage-task \
  --task-id e2e_heldout_multistep_007 \
  --rss-limit-mb 4096 \
  --task-timeout-sec 180
```

Artifacts:

- Stage report: `evaluation/diagnostics/oom_stage_task.json`
- RSS samples: `/tmp/oom_stage_rss.log`

Stage timeline:

| stage | rss_mb |
|---|---:|
| file_analyzer:after | 252.2 |
| tool:analyze_file:after | 257.3 |
| tool:calculate_dispersion:before | 266.0 |
| dispersion.calculate:before | 271.6 |
| dispersion._segment_roads:after | 276.5 |
| dispersion._generate_receptors:after | 364.2 |
| dispersion._build_source_arrays:after | 364.6 |
| dispersion._process_meteorology:after | 364.6 |
| dispersion._ensure_models_loaded:after | 364.6 |
| dispersion._get_or_load_model:after | 490.9 |
| dispersion.predict_time_series_xgb:before:receptors=202154,sources_shape=(1, 7506, 4),met_rows=1,batch=200000,track=True | 490.9 |

RSS monitor:

```text
09:59:37 3339 257.3MB tool:analyze_file:after
09:59:50 3339 490.9MB dispersion.predict_time_series_xgb:before
09:59:55 3339 5539.9MB dispersion.predict_time_series_xgb:before
# RSS_LIMIT_EXCEEDED 5539.9MB >= 4096.0MB
```

The Excel fixture itself is small and has normal dimensions:

```text
test_data/test_shanghai_full.xlsx: 30K
Sheet1 max_row 151, max_column 5, dimension A1:E151
```

## 3. Code Locations

Primary OOM allocation:

- `calculators/dispersion.py:431-443` defines `predict_time_series_xgb`.
- `calculators/dispersion.py:542-543` allocates full `x_hat` and `y_hat` receptor-source matrices.
- `calculators/dispersion.py:550-556` and `612-618` build boolean masks over those full matrices.
- `calculators/dispersion.py:561-585` and `623-647` build feature matrices for all matched receptor-source pairs.

Call path:

- `tools/dispersion.py:162-168` calls `calculator.calculate(...)`.
- `calculators/dispersion.py:1217-1229` calls `predict_time_series_xgb(...)` with `track_road_contributions=True`.

Scale amplifiers:

- `calculators/dispersion.py:48` sets road segmentation interval to `10m`, producing `7506` source segments for this fixture.
- `calculators/dispersion.py:52-53` uses receptor offset/background defaults, producing `202154` receptors.
- `calculators/dispersion.py:66` has `batch_size=200000`, but batching only applies after full `x_hat/y_hat` allocation, so it does not cap memory.

## 4. Fix Options

### Option A: Minimal Patch (2-5 lines)

Add a preflight guard before `predict_time_series_xgb` allocation:

- Estimate `n_receptors * n_sources`.
- If above a safe threshold, return a structured error such as `DISPERSION_GRID_TOO_LARGE` with counts and suggested coarser settings.

Candidate location:

- `calculators/dispersion.py:1217` before calling `predict_time_series_xgb`, or inside `predict_time_series_xgb` before `x_hat/y_hat`.

Expected work: 0.5 day.

Risk:

- Prevents OOM.
- Does not complete large held-out dispersion tasks.
- Evaluation will fail these tasks unless benchmark/eval accepts graceful refusal.

### Option B: Medium Refactor (recommended)

Chunk prediction by receptors and/or source segments before forming `x_hat/y_hat`.

Implementation shape:

- In `predict_time_series_xgb`, loop over receptor chunks, e.g. 2k-10k receptors.
- For each chunk, compute `x_hat/y_hat`, masks, features, predictions, and accumulate into `total_conc` for that chunk.
- Keep road contribution tracking sparse/top-k per chunk; avoid allocating receptor-source full matrices globally.

Candidate location:

- `calculators/dispersion.py:504-684`, especially replacing `x_hat = rx_rot[:, None] - sx_rot[None, :]` with chunk-local arrays.

Expected work: 1-2 days including numeric regression checks.

Risk:

- Moderate. Needs validation against existing small cases.
- Preserves ability to run large held-out files.
- Addresses the actual OOM root cause without changing benchmark semantics.

### Option C: Large Architectural Change

Introduce an adaptive dispersion execution planner:

- Estimate network size, road segment count, receptor count, and expected receptor-source pairs.
- Select one of several modes:
  - exact full-vector mode for small cases,
  - chunked exact mode for medium/large cases,
  - coarse preview mode for very large cases,
  - graceful refusal with remediation hints when beyond configured budget.
- Surface the budget/readiness decision through DependencyContract/ExecutionReadiness telemetry.

Expected work: 4-7 days.

Risk:

- Broad, touches execution policy and user-visible behavior.
- Best long-term shape, but too large for an immediate held-out baseline unblock.

## 5. Recommendation

Recommended: Option B.

Reason: the failure is not caused by retained file DataFrames; it is caused by one live vectorized allocation inside `predict_time_series_xgb`. Chunking preserves exact computation while bounding peak RSS. Option A is a safe emergency guard but would convert large held-out dispersion tasks into controlled failures. Option C is useful later, but not needed to stop this OOM.

