# PHASE0_REPORT

## 1. Eval 修复前后对比

| 数据集/口径 | tasks | completion_rate | 通过数 | 说明 |
|---|---:|---:|---:|---|
| v2 原日志原判定 | 100 | 0.5900 | 59 | evaluation/results/end2end_full_v2 |
| v2 原日志用修复后 evaluator 重评分 | 100 | 0.7000 | 70 | evaluation/results/end2end_full_v3_rescored_v2 |
| 原 100 条真实重跑 | 100 | 0.6900 | 69 | evaluation/results/end2end_full_v3_original100 |

- 指定 8 条 eval_bug 重评分结果：8/8 通过。
- 旧 v2 日志重评分 pass_to_fail：0。

| task_id | 修复前 | 修复后重评分 |
|---|---:|---:|
| e2e_simple_004 | False | True |
| e2e_ambiguous_001 | False | True |
| e2e_incomplete_003 | False | True |
| e2e_constraint_001 | False | True |
| e2e_constraint_003 | False | True |
| e2e_constraint_006 | False | True |
| e2e_constraint_010 | False | True |
| e2e_multistep_045 | False | True |

## 2. 新增 80 条任务分布

| category | count | bar |
|---|---:|---|
| multi_turn_clarification | 20 | ████████████████████ |
| user_revision | 20 | ████████████████████ |
| ambiguous_colloquial | 20 | ████████████████████ |
| code_switch_typo | 20 | ████████████████████ |

- benchmark 总数：180；新增 80 条 validator status：{'valid': 80}。
- coverage audit：vehicle_type 13/13，pollutant 6/6，meteorology 6/6。

## 3. 180 条 Full vs Naive

| mode | tasks | completion_rate | tool_accuracy | parameter_legal_rate | result_data_rate |
|---|---:|---:|---:|---:|---:|
| Full | 180 | 0.6611 | 0.7778 | 0.7167 | 0.7778 |
| Naive | 180 | 0.1556 | 0.6500 | 0.5444 | 0.4222 |

| category | tasks | Full completion | Full tool_accuracy | Naive completion | Naive tool_accuracy |
|---|---:|---:|---:|---:|---:|
| ambiguous_colloquial | 20 | 0.4000 | 0.6500 | 0.0000 | 0.9500 |
| code_switch_typo | 20 | 0.8000 | 0.8500 | 0.2000 | 0.7000 |
| constraint_violation | 17 | 0.8235 | 0.8235 | 0.0000 | 0.5294 |
| incomplete | 18 | 0.5556 | 1.0000 | 0.7222 | 1.0000 |
| multi_step | 20 | 0.8500 | 0.9000 | 0.1000 | 0.1000 |
| multi_turn_clarification | 20 | 0.1500 | 0.1500 | 0.0000 | 0.2500 |
| parameter_ambiguous | 24 | 0.5000 | 0.7500 | 0.0833 | 0.5000 |
| simple | 21 | 0.9524 | 0.9524 | 0.2857 | 0.9048 |
| user_revision | 20 | 0.9500 | 0.9500 | 0.0500 | 0.9500 |

## 4. Full 180 修复后仍失败 case 归因

- Full 失败数：61/180。按 category：{'parameter_ambiguous': 12, 'multi_step': 3, 'incomplete': 8, 'simple': 1, 'constraint_violation': 3, 'multi_turn_clarification': 17, 'user_revision': 1, 'ambiguous_colloquial': 12, 'code_switch_typo': 4}。

| bucket | count | task_ids |
|---|---:|---|
| NO_TOOL_OR_TEXT_PATH | 19 | e2e_simple_011, e2e_multistep_010, e2e_constraint_008, e2e_ambiguous_020, e2e_ambiguous_026, e2e_ambiguous_028, e2e_ambiguous_032, e2e_ambiguous_038, e2e_ambiguous_039, e2e_clarification_102, e2e_colloquial_148, e2e_colloquial_150, e2e_colloquial_153, e2e_colloquial_154, e2e_colloquial_157, e2e_colloquial_158, e2e_colloquial_160, e2e_codeswitch_177, e2e_codeswitch_180 |
| WRONG_TOOL_CHAIN | 19 | e2e_multistep_004, e2e_clarification_101, e2e_clarification_103, e2e_clarification_104, e2e_clarification_106, e2e_clarification_107, e2e_clarification_109, e2e_clarification_111, e2e_clarification_112, e2e_clarification_113, e2e_clarification_114, e2e_clarification_115, e2e_clarification_116, e2e_clarification_117, e2e_clarification_118, e2e_clarification_119, e2e_clarification_120, e2e_revision_135, e2e_codeswitch_169 |
| TOOL_EXECUTED_MISMATCH | 11 | e2e_incomplete_003, e2e_incomplete_005, e2e_incomplete_006, e2e_incomplete_008, e2e_incomplete_011, e2e_incomplete_013, e2e_incomplete_015, e2e_incomplete_017, e2e_incomplete_018, e2e_constraint_013, e2e_codeswitch_163 |
| PARAMS_LEGAL_FAIL | 8 | e2e_ambiguous_003, e2e_ambiguous_005, e2e_ambiguous_034, e2e_colloquial_143, e2e_colloquial_144, e2e_colloquial_145, e2e_colloquial_146, e2e_colloquial_149 |
| CONSTRAINT_WARNING_MISSED | 2 | e2e_constraint_007, e2e_constraint_047 |
| OTHER | 1 | e2e_multistep_043 |
| USER_RESPONSE_MISMATCH | 1 | e2e_incomplete_014 |

## 5. 产物

- `evaluation/eval_end2end.py`
- `evaluation/benchmarks/end2end_tasks.jsonl`
- `evaluation/pipeline_v2/phase0_adversarial_candidates.jsonl`
- `evaluation/pipeline_v2/phase0_validated_adversarial.jsonl`
- `evaluation/pipeline_v2/phase0_reviewed_adversarial.jsonl`
- `evaluation/pipeline_v2/phase0_coverage_report.json`
- `evaluation/results/end2end_full_v3/end2end_metrics.json`
- `evaluation/results/end2end_naive_v3/end2end_metrics.json`

## 6. 运行备注

- Full/Naive 运行中出现 DashScope proxy/direct 切换、embedding/rerank 连接错误；进程未中断，相关任务按当次实际结果计入 logs。
- 未修改 core/、services/、tools/ 下文件。
