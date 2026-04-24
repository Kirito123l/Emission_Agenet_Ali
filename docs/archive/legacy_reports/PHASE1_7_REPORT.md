# Phase 1.7 Report

## 1. Diagnosis Summary
- incomplete 失败归类分布：I4_OTHER=4（v7 A->E 组间 session 污染）
- multi_step 失败归类分布：M4_OTHER=7（v7 A->E 组间 session 污染）
- 选择的修复方向和理由：
  - 保留 Phase 1.7 中对 AO complete / classifier / governed return payload 的修复
  - 增补 matrix runner 的组间 session 隔离，因为这是诊断出的主因

## 2. Implementation
修改文件：
- [core/ao_manager.py](/home/kirito/Agent1/emission_agent/core/ao_manager.py)
- [core/ao_classifier.py](/home/kirito/Agent1/emission_agent/core/ao_classifier.py)
- [core/governed_router.py](/home/kirito/Agent1/emission_agent/core/governed_router.py)
- [evaluation/run_oasc_matrix.py](/home/kirito/Agent1/emission_agent/evaluation/run_oasc_matrix.py)
- [tests/test_ao_manager.py](/home/kirito/Agent1/emission_agent/tests/test_ao_manager.py)
- [tests/test_ao_classifier.py](/home/kirito/Agent1/emission_agent/tests/test_ao_classifier.py)

具体修改点：
- `complete_ao()` 引入 `objective_satisfied` 检查，避免单步成功就过早 complete 多步 AO。
- classifier Layer 1 新增 `first_message_in_session` / `no_active_ao_no_revision_signal`。
- governed wrapper 对缺失的 `executed_tool_calls` 做 memory backfill。
- matrix runner 在 preflight 后和每组开始前清理 `eval_*.json`。

## 3. Smoke Verification
| Run | A completion | E completion | incomplete(E) | multi_step(E) |
|---|---:|---:|---:|---:|
| v8 smoke | 76.67% | 90.00% | 100.00% | 100.00% |

## 4. Full A+E Verification
- [A metrics](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_full_v8_fix_A/end2end_metrics.json)
- [E metrics](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_full_v8_fix_E/end2end_metrics.json)
| Group | completion_rate | tool_accuracy | parameter_legal | result_data | wall_clock_sec |
|---|---:|---:|---:|---:|---:|
| A | 0.7111 | 0.7778 | 0.7111 | 0.7667 | 341.13 |
| E | 0.7111 | 0.7667 | 0.7278 | 0.7222 | 387.54 |

## 5. Per-Category Breakdown
| Category | A | E | E-A (pp) |
|---|---:|---:|---:|
| ambiguous_colloquial | 50.00% | 35.00% | -15.0 |
| code_switch_typo | 80.00% | 65.00% | -15.0 |
| constraint_violation | 76.47% | 100.00% | 23.5 |
| incomplete | 94.44% | 94.44% | 0.0 |
| multi_step | 70.00% | 85.00% | 15.0 |
| multi_turn_clarification | 10.00% | 10.00% | 0.0 |
| parameter_ambiguous | 66.67% | 66.67% | 0.0 |
| simple | 95.24% | 90.48% | -4.8 |
| user_revision | 100.00% | 100.00% | 0.0 |

## 6. Hard Floor Verdict
| Metric | Hard Floor | v7 (Phase 1.6) | v8 (Phase 1.7) | 达标 |
|---|---:|---:|---:|---|
| E completion rate | >= 72% | 73.89 | 71.11 | NO |
| E vs A | >= +6 pp | 6.11 | 0.00 | NO |
| pass_to_fail | < 8 | 14.00 | 10.00 | NO |
| parameter_ambiguous | >= 50% | 66.67 | 66.67 | YES |
| incomplete | >= 85% | 77.78 | 94.44 | YES |
| multi_step | >= 70% | 65.00 | 85.00 | YES |

## 7. Pass/Fail Analysis
- pass_to_fail (10): ["e2e_ambiguous_032", "e2e_codeswitch_163", "e2e_codeswitch_166", "e2e_codeswitch_168", "e2e_codeswitch_175", "e2e_colloquial_150", "e2e_colloquial_153", "e2e_colloquial_156", "e2e_colloquial_160", "e2e_incomplete_009"]
- fail_to_pass (10): ["e2e_codeswitch_172", "e2e_colloquial_152", "e2e_constraint_005", "e2e_constraint_007", "e2e_constraint_011", "e2e_constraint_047", "e2e_incomplete_015", "e2e_multistep_009", "e2e_multistep_041", "e2e_multistep_042"]

## 8. Remaining Failures (Phase 2 target)
- E 组仍失败 52 条，按类别分布：{'parameter_ambiguous': 8, 'multi_turn_clarification': 18, 'code_switch_typo': 7, 'ambiguous_colloquial': 13, 'incomplete': 1, 'simple': 2, 'multi_step': 3}
- E 组仍失败 task_id：["e2e_ambiguous_003", "e2e_ambiguous_005", "e2e_ambiguous_020", "e2e_ambiguous_024", "e2e_ambiguous_026", "e2e_ambiguous_032", "e2e_ambiguous_039", "e2e_clarification_101", "e2e_clarification_102", "e2e_clarification_103", "e2e_clarification_104", "e2e_clarification_106", "e2e_clarification_107", "e2e_clarification_108", "e2e_clarification_109", "e2e_clarification_111", "e2e_clarification_112", "e2e_clarification_113", "e2e_clarification_114", "e2e_clarification_115", "e2e_clarification_116", "e2e_clarification_117", "e2e_clarification_118", "e2e_clarification_119", "e2e_clarification_120", "e2e_codeswitch_163", "e2e_codeswitch_166", "e2e_codeswitch_168", "e2e_codeswitch_169", "e2e_codeswitch_175", "e2e_codeswitch_177", "e2e_codeswitch_180", "e2e_colloquial_143", "e2e_colloquial_144", "e2e_colloquial_145", "e2e_colloquial_146", "e2e_colloquial_148", "e2e_colloquial_149", "e2e_colloquial_150", "e2e_colloquial_153", "e2e_colloquial_154", "e2e_colloquial_156", "e2e_colloquial_157", "e2e_colloquial_158", "e2e_colloquial_160", "e2e_constraint_013", "e2e_incomplete_002", "e2e_incomplete_009", "e2e_multistep_004", "e2e_multistep_043", "e2e_multistep_044", "e2e_simple_011"]

## 9. Classifier Telemetry
| Metric | v6 | v8 |
|---|---:|---:|
| Layer 1 命中率 | 26.2% | 80.7% |
| Layer 2 调用次数 | 242 | 64 |
| Layer 2 平均延迟 | 4719.8 ms | 4569.6 ms |

## 10. Final Verdict
READY FOR PHASE 2: NO
