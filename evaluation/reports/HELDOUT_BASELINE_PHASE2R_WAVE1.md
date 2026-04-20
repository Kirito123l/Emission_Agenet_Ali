# Held-out Baseline: Phase 2R Wave 1

## 1. Run Health

Commands:

```bash
python evaluation/run_oasc_matrix.py --groups A,E \
  --samples evaluation/benchmarks/held_out_tasks.jsonl \
  --smoke --parallel 8 --qps-limit 15 --cache \
  --output-prefix heldout_smoke_phase2r_wave1

python evaluation/run_oasc_matrix.py --groups A,E \
  --samples evaluation/benchmarks/held_out_tasks.jsonl \
  --parallel 8 --qps-limit 15 --cache \
  --output-prefix heldout_full_phase2r_wave1
```

Smoke sanity:

| Group | tasks | completion_rate | data_integrity | infra_unknown | max RSS |
|---|---:|---:|---|---:|---:|
| A | 10 | 50.00% | clean | 0 | 1422.5 MB |
| E | 10 | 30.00% | clean | 0 | 1422.5 MB |

Full run health:

| Group | tasks | data_integrity | infra_ok | infra_unknown | max RSS |
|---|---:|---|---:|---:|---:|
| A | 75 | clean | 100.00% | 0 | 1306.2 MB |
| E | 75 | clean | 100.00% | 0 | 1306.2 MB |

Result files:

- `evaluation/results/heldout_smoke_phase2r_wave1_A/end2end_metrics.json`
- `evaluation/results/heldout_smoke_phase2r_wave1_E/end2end_metrics.json`
- `evaluation/results/heldout_full_phase2r_wave1_A/end2end_metrics.json`
- `evaluation/results/heldout_full_phase2r_wave1_E/end2end_metrics.json`

## 2. Overall

| Group | completion_rate | tool_accuracy | parameter_legal | result_data | infra_ok |
|---|---:|---:|---:|---:|---:|
| A | 54.67% | 66.67% | 69.33% | 73.33% | 100.00% |
| E | 18.67% | 32.00% | 28.00% | 29.33% | 100.00% |

## 3. Per-category Completion Rate

| category | A | E | E-A |
|---|---:|---:|---:|
| simple | 83.33% | 0.00% | -83.33 pp |
| ambiguous_colloquial | 30.00% | 0.00% | -30.00 pp |
| multi_step | 0.00% | 0.00% | +0.00 pp |
| multi_turn_clarification | 20.00% | 40.00% | +20.00 pp |
| user_revision | 87.50% | 50.00% | -37.50 pp |
| parameter_ambiguous | 71.43% | 0.00% | -71.43 pp |
| code_switch_typo | 62.50% | 0.00% | -62.50 pp |
| constraint_violation | 57.14% | 14.29% | -42.85 pp |
| incomplete | 100.00% | 100.00% | +0.00 pp |

## 4. Main Benchmark vs Held-out

Main benchmark reference: `evaluation/results/end2end_full_v8_fix_E/end2end_metrics.json`.

| category | main E | held-out E | gap |
|---|---:|---:|---:|
| simple | 90.48% | 0.00% | -90.48 pp |
| ambiguous_colloquial | 35.00% | 0.00% | -35.00 pp |
| multi_step | 85.00% | 0.00% | -85.00 pp |
| multi_turn_clarification | 10.00% | 40.00% | +30.00 pp |
| user_revision | 100.00% | 50.00% | -50.00 pp |
| parameter_ambiguous | 66.67% | 0.00% | -66.67 pp |
| code_switch_typo | 65.00% | 0.00% | -65.00 pp |
| constraint_violation | 100.00% | 14.29% | -85.71 pp |
| incomplete | 94.44% | 100.00% | +5.56 pp |

## 5. Stance Distribution

Source: `clarification_telemetry` from `evaluation/results/heldout_full_phase2r_wave1_E/end2end_logs.jsonl`.

Entry-level stance counts:

| category | directive | deliberative | exploratory | unknown/missing |
|---|---:|---:|---:|---:|
| simple | 12 | 0 | 0 | 0 |
| ambiguous_colloquial | 10 | 0 | 0 | 0 |
| multi_step | 16 | 0 | 0 | 0 |
| multi_turn_clarification | 17 | 16 | 0 | 0 |
| user_revision | 11 | 3 | 0 | 0 |
| parameter_ambiguous | 7 | 0 | 0 | 0 |
| code_switch_typo | 7 | 1 | 0 | 0 |
| constraint_violation | 10 | 0 | 0 | 0 |
| incomplete | 0 | 1 | 0 | 0 |

Task-level dominant stance:

| category | directive | deliberative | exploratory | no telemetry |
|---|---:|---:|---:|---:|
| simple | 12 | 0 | 0 | 0 |
| ambiguous_colloquial | 10 | 0 | 0 | 0 |
| multi_step | 8 | 0 | 0 | 0 |
| multi_turn_clarification | 5 | 5 | 0 | 0 |
| user_revision | 7 | 0 | 0 | 1 |
| parameter_ambiguous | 7 | 0 | 0 | 0 |
| code_switch_typo | 7 | 1 | 0 | 0 |
| constraint_violation | 7 | 0 | 0 | 0 |
| incomplete | 0 | 1 | 0 | 4 |

Sanity checks:

- `multi_turn_clarification`: 5/10 tasks had at least one `deliberative` stance signal = 50.00%, below the expected >=70%.
- `expected_stance` is not present in `held_out_tasks.jsonl`; using non-`multi_turn_clarification` tasks as a directive proxy gives 58/65 tasks with at least one `directive` stance signal = 89.23%, above the expected >=80%. The user-provided 64-task directive denominator cannot be reconstructed from current log schema without an explicit expected-stance field.
- No task emitted `exploratory` in this run.

## 6. Known Issues

- `DISPERSION_GRID_TOO_LARGE` did not trigger in smoke or full held-out logs after fixture downgrade.
- `execution_error` / `execution_traceback` were not populated in A or E full logs; all infrastructure statuses were `ok`.
- E underperforms A by 36.00 pp overall on held-out (`18.67%` vs `54.67%`). The largest held-out E drops are `simple`, `parameter_ambiguous`, `code_switch_typo`, and `constraint_violation`.
- `multi_turn_clarification` is the only major category where E improves over A in held-out (+20.00 pp).
