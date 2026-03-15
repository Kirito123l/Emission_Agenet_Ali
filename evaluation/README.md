# Evaluation and Reproducibility

This directory contains the current local benchmark and reproducibility paths.

For the overall repo status and current docs map, see [../ENGINEERING_STATUS.md](../ENGINEERING_STATUS.md). For current shareability/open-source sanity, see [../RELEASE_READINESS.md](../RELEASE_READINESS.md). For run-vs-validate guidance, see [../RUNNING.md](../RUNNING.md) and [../DEVELOPMENT.md](../DEVELOPMENT.md).

## Choose Your Goal

| Goal | Command | Expected result |
|---|---|---|
| Validate the installed app only | `python main.py health` then `pytest` | Use the runtime path in [../RUNNING.md](../RUNNING.md); no benchmark artifacts needed |
| Run the smallest meaningful evaluation | `python evaluation/run_smoke_suite.py` | Fresh directory under `evaluation/logs/` with `smoke_summary.json` |
| Inspect one benchmark family | `python evaluation/eval_normalization.py` or another single runner | Per-task metrics and logs only for that benchmark |
| Run the larger experiment matrix | `python evaluation/eval_ablation.py` | Combined summary across the three benchmark families |

This directory is for benchmark and reproducibility work, not the first-run app smoke check.

## Canonical Evaluation Entry Points

### Minimal smoke suite

`python evaluation/run_smoke_suite.py`

This is the recommended smallest meaningful evaluation run. It executes:

- normalization evaluation
- file-grounding evaluation
- end-to-end evaluation in `tool` mode

The default macro mapping modes are `direct,fuzzy` so the smoke path avoids depending on the AI-only macro column-mapping stage.

### Individual benchmark runners

- `python evaluation/eval_normalization.py`
- `python evaluation/eval_file_grounding.py`
- `python evaluation/eval_end2end.py`

Use these when you want per-task metrics or custom flags.

### Larger experiment matrix

- `python evaluation/eval_ablation.py`

This runs the current baseline/ablation matrix across the three benchmark families and writes a combined summary.

## Sample and Benchmark Assets

### Canonical sample sets

- `evaluation/normalization/samples.jsonl`
- `evaluation/file_tasks/samples.jsonl`
- `evaluation/end2end/samples.jsonl`

### File-task sample assets

- `evaluation/file_tasks/data/`

Contains the CSV/Excel fixtures used by file-grounding and some end-to-end samples.

### Additional human-comparison scaffold

- `evaluation/human_compare/samples.csv`

This is present as a future-facing/manual comparison asset, not a fully automated benchmark path.

### Checked-in example outputs

- `evaluation/logs/_smoke_*`

These are example artifacts from prior smoke runs. They are useful as reference outputs, but they are not the source of truth. Re-run the scripts above when validating the current codebase.

## Minimum Reproducible Validation Path

For the smallest meaningful benchmark pass:

```bash
python evaluation/run_smoke_suite.py
```

This writes a fresh output directory under `evaluation/logs/` and produces `smoke_summary.json`.

What to look for:

- a new run directory under `evaluation/logs/`
- subdirectories for `normalization/`, `file_grounding/`, and `end2end/`
- a top-level `smoke_summary.json` summarizing the run

## More Targeted Commands

### Normalization only

```bash
python evaluation/eval_normalization.py
```

### File grounding only

```bash
python evaluation/eval_file_grounding.py
```

### End-to-end only

```bash
python evaluation/eval_end2end.py --mode tool
```

### Router-based end-to-end evaluation

```bash
python evaluation/eval_end2end.py --mode router
```

Use router mode only when you intentionally want to exercise the full LLM routing loop.

## Outputs

Each evaluation run writes JSON metrics plus JSONL logs under `evaluation/logs/<run_name>/`.

Typical structure:

```text
evaluation/logs/<run_name>/
  normalization/
  file_grounding/
  end2end/
  smoke_summary.json
```

The exact files depend on the runner, but metrics are written as `*_metrics.json` and per-sample logs as `*_logs.jsonl`.

## Practical Notes

- The smoke suite is designed to be the least surprising local reproducibility path.
- If you only need to prove the app boots and the regression suite passes, use the validation path in [../RUNNING.md](../RUNNING.md) instead of this directory.
- `tool` mode is lower risk than `router` mode for local benchmarking because it bypasses the full chat routing loop.
- Some benchmark paths may still depend on configured LLM access depending on flags and task mix.
- The evaluation framework is usable now, but it is still evolving and should be treated as an engineering benchmark harness rather than a finalized paper package.
