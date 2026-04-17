# Phase 2.4 Turn-1 Resolver Summary

| category | total | resolver=None | resolver=expected | resolver=wrong | none_rate |
|---|---:|---:|---:|---:|---:|
| ambiguous_colloquial | 20 | 10 | 10 | 0 | 50.0% |
| code_switch_typo | 20 | 12 | 8 | 0 | 60.0% |
| constraint_violation | 17 | 0 | 9 | 8 | 0.0% |
| incomplete | 18 | 3 | 0 | 15 | 16.7% |
| multi_step | 20 | 0 | 19 | 1 | 0.0% |
| multi_turn_clarification | 20 | 8 | 12 | 0 | 40.0% |
| parameter_ambiguous | 24 | 4 | 17 | 3 | 16.7% |
| simple | 21 | 4 | 17 | 0 | 19.0% |
| user_revision | 20 | 11 | 9 | 0 | 55.0% |

## Miss Breakdown

| expected_tool | 因子 | 排放因子 | 排放 | factor | emission | confirm_first | micro_kw | macro_kw | file_task_type | count |
|---|---|---|---|---|---|---|---|---|---|---:|
| query_emission_factors | 因子 | - | - | - | - | - | - | - | no_file | 24 |
| query_emission_factors | - | - | - | - | - | - | - | - | no_file | 9 |
| query_emission_factors | - | - | 排放 | - | - | - | - | - | no_file | 7 |
| query_emission_factors | - | - | - | factor | - | - | - | - | no_file | 4 |
| - | - | - | 排放 | - | - | - | - | - | no_file | 3 |
| - | - | - | - | - | - | - | - | - | no_file | 2 |
| query_knowledge | - | - | - | - | - | - | - | - | no_file | 1 |
| - | - | - | 排放 | - | - | confirm_first | - | - | no_file | 1 |
| query_emission_factors | 因子 | - | - | - | - | confirm_first | - | - | no_file | 1 |

## Decision Questions

- `query_emission_factors` resolver=None misses: 45
- Of those, messages containing `因子`: 25
- Expected != `query_emission_factors` tasks containing `因子` but not `排放因子`: 0
- Expected micro/macro resolver=None tasks with `file_task_type=no_file`: 0

## Analyzer Errors

No analyzer errors.
