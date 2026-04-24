# Phase 2 Baseline

## Scope

Step 0 rerun completed with the Phase 1.7 clean runner:

```bash
python evaluation/run_oasc_matrix.py \
  --groups A,B --parallel 8 --qps-limit 15 --cache \
  --results-root evaluation/results \
  --output-prefix clean_baseline_v8
```

Note: the current runner exposes `--results-root` + `--output-prefix`, not `--output-dir`.

Artifacts:

- `evaluation/results/clean_baseline_v8_A/end2end_metrics.json`
- `evaluation/results/clean_baseline_v8_B/end2end_metrics.json`
- `evaluation/results/end2end_full_v8_fix_E/end2end_metrics.json` (existing Phase 1.7 clean E)

All three runs are `data_integrity=clean`.

## Overall Metrics

| Group | Meaning | completion | tool_accuracy | parameter_legal | result_data | wall_clock_sec |
|---|---|---:|---:|---:|---:|---:|
| A | No OASC | 70.56% | 77.22% | 72.22% | 76.11% | 323.32 |
| B | Phase 1 SessionState only | 69.44% | 77.22% | 72.78% | 78.89% | 338.05 |
| E | Phase 1.7 OASC Hybrid | 71.11% | 76.67% | 72.78% | 72.22% | 387.54 |

## Per-Category Completion

| Category | A | B | E |
|---|---:|---:|---:|
| simple | 95.24% | 95.24% | 90.48% |
| parameter_ambiguous | 66.67% | 70.83% | 66.67% |
| multi_step | 75.00% | 65.00% | 85.00% |
| multi_turn_clarification | 5.00% | 10.00% | 10.00% |
| user_revision | 100.00% | 100.00% | 100.00% |
| ambiguous_colloquial | 45.00% | 45.00% | 35.00% |
| code_switch_typo | 80.00% | 75.00% | 65.00% |
| incomplete | 94.44% | 94.44% | 94.44% |
| constraint_violation | 76.47% | 70.59% | 100.00% |

## Baseline Readout

- Phase 2 real starting gap is still concentrated in `multi_turn_clarification` and `ambiguous_colloquial`.
- `multi_turn_clarification` remains low in all three baselines: A `5%`, B `10%`, E `10%`.
- `ambiguous_colloquial` remains low in all three baselines: A `45%`, B `45%`, E `35%`.
- OASC E is already strong on `multi_step` (`85%`) and `constraint_violation` (`100%`), so Phase 2 should avoid regressing those categories.
- B remains strictly worse than A overall (`69.44%` vs `70.56%`), so SessionState-only is not a useful target baseline for Phase 2 behavior.

## Source Paths

- `evaluation/results/clean_baseline_v8_A/end2end_metrics.json`
- `evaluation/results/clean_baseline_v8_B/end2end_metrics.json`
- `evaluation/results/end2end_full_v8_fix_E/end2end_metrics.json`
