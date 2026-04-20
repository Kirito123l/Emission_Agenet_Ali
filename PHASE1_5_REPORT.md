# Phase 1.5 OASC Final Report

## 1. Run Health Status
- A: `data_integrity=clean`, `run_status=completed`, health=`ok:179, unknown:1`
- B: `data_integrity=clean`, `run_status=completed`, health=`ok:180`
- C: `data_integrity=clean`, `run_status=completed`, health=`ok:180`
- D: `data_integrity=clean`, `run_status=completed`, health=`ok:180`
- E: `data_integrity=clean`, `run_status=completed`, health=`ok:176, unknown:4`
- F: `data_integrity=clean`, `run_status=completed`, health=`ok:179, unknown:1`
- 6 组均为 `data_integrity=clean`
- Preflight: [end2end_preflight_v5_oasc/end2end_metrics.json](/home/kirito/Agent1/emission_agent/evaluation/results/end2end_preflight_v5_oasc/end2end_metrics.json) => `5/5 ok`, `run_status=completed`, `data_integrity=clean`

## 2. Implementation Summary
- OASC code: [core/analytical_objective.py](/home/kirito/Agent1/emission_agent/core/analytical_objective.py), [core/ao_manager.py](/home/kirito/Agent1/emission_agent/core/ao_manager.py), [core/ao_classifier.py](/home/kirito/Agent1/emission_agent/core/ao_classifier.py), [core/governed_router.py](/home/kirito/Agent1/emission_agent/core/governed_router.py)
- Refactor/injection: [core/memory.py](/home/kirito/Agent1/emission_agent/core/memory.py), [core/assembler.py](/home/kirito/Agent1/emission_agent/core/assembler.py), [config.py](/home/kirito/Agent1/emission_agent/config.py), [api/session.py](/home/kirito/Agent1/emission_agent/api/session.py), [api/routes.py](/home/kirito/Agent1/emission_agent/api/routes.py)
- Eval fail-safe and runners: [evaluation/eval_end2end.py](/home/kirito/Agent1/emission_agent/evaluation/eval_end2end.py), [evaluation/run_health.py](/home/kirito/Agent1/emission_agent/evaluation/run_health.py), [evaluation/run_oasc_matrix.py](/home/kirito/Agent1/emission_agent/evaluation/run_oasc_matrix.py)

## 3. Test Results
- Focused pytest:
  - OASC/core/API subset: `63 passed`
  - eval fail-safe: `5 passed`
- Manual classifier validation: `15/15`
- Full pytest: `1050 passed, 8 failed`
- Out-of-scope failures remain in [calculators/scenario_comparator.py](/home/kirito/Agent1/emission_agent/calculators/scenario_comparator.py), [calculators/hotspot_analyzer.py](/home/kirito/Agent1/emission_agent/calculators/hotspot_analyzer.py), [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)

## 4. Main Benchmark Results

| Group | completion_rate | tool_accuracy | parameter_legal | result_data | data_integrity |
|---|---:|---:|---:|---:|:-:|
| A (Phase 0 baseline) | 0.7000 | 0.8167 | 0.7444 | 0.7944 | clean |
| B (Phase 1 regression) | 0.6111 | 0.7389 | 0.6722 | 0.7056 | clean |
| C (Rule-only) | 0.6833 | 0.8222 | 0.7389 | 0.8222 | clean |
| D (LLM-only) | 0.6778 | 0.8167 | 0.7167 | 0.8056 | clean |
| E (Hybrid, main) | 0.6778 | 0.8222 | 0.7222 | 0.8000 | clean |
| F (Hybrid w/o persistent facts) | 0.6944 | 0.8333 | 0.7333 | 0.7944 | clean |

## 5. Per-Category Breakdown for E vs A

| Category | A | E | Delta |
|---|---:|---:|---:|
| ambiguous_colloquial | 0.6500 | 0.5500 | -0.1000 |
| code_switch_typo | 0.8000 | 0.8000 | 0.0000 |
| constraint_violation | 0.8824 | 0.8824 | 0.0000 |
| incomplete | 0.5000 | 0.4444 | -0.0556 |
| multi_step | 0.7000 | 0.4500 | -0.2500 |
| multi_turn_clarification | 0.3000 | 0.6000 | +0.3000 |
| parameter_ambiguous | 0.5417 | 0.4583 | -0.0834 |
| simple | 0.9524 | 0.9524 | 0.0000 |
| user_revision | 1.0000 | 1.0000 | 0.0000 |

## 6. Hard Floor 验收

| 指标 | Hard Floor | E 组实际 | 是否通过 |
|---|---:|---:|:-:|
| Hybrid completion rate | ≥ 72% | 67.78% | NO |
| E vs A | ≥ +6 pp | -2.22 pp | NO |
| pass_to_fail (E vs A) | < 8 | 16 | NO |
| parameter_ambiguous category | ≥ 50% | 45.83% | NO |
| Feature flag 全关时 | Phase 0 ± 1pp | 70.00% vs 66.10% | NO |

**HARD FLOOR NOT MET**

## 7. Pass/Fail Analysis (E vs A)
- `pass_to_fail=16`
  - `e2e_multistep_002, e2e_incomplete_001, e2e_ambiguous_009, e2e_ambiguous_010, e2e_ambiguous_011, e2e_multistep_006, e2e_multistep_008, e2e_multistep_011, e2e_incomplete_011, e2e_incomplete_017, e2e_incomplete_018, e2e_ambiguous_034, e2e_multistep_041, e2e_colloquial_144, e2e_colloquial_158, e2e_colloquial_160`
- `fail_to_pass=12`
  - `e2e_incomplete_004, e2e_ambiguous_022, e2e_ambiguous_032, e2e_incomplete_051, e2e_incomplete_053, e2e_clarification_106, e2e_clarification_107, e2e_clarification_108, e2e_clarification_109, e2e_clarification_116, e2e_clarification_117, e2e_colloquial_147`
- pass_to_fail category split: `multi_step=5, incomplete=4, parameter_ambiguous=4, ambiguous_colloquial=3`
- fail_to_pass category split: `multi_turn_clarification=6, incomplete=3, parameter_ambiguous=2, ambiguous_colloquial=1`
- E failure bucket distribution: `输出不完整=58`

## 8. Classifier Performance
- Layer 1 命中率: `UNKNOWN: end2end_logs.jsonl 与 session history 未持久化 classifier layer 命中 telemetry`
- Layer 2 调用次数和平均延迟: `UNKNOWN: evaluator/logs 未保留 classifier 调用计数与 latency_ms`
- Fallback 触发次数: `UNKNOWN: evaluator/logs 未保留 classifier fallback telemetry`
- Manual case 准确率: `15/15`

## 9. Token Statistics
- Block 平均/中位/最大 tokens: `UNKNOWN: end2end logs 与 session history 未持久化 per-call block token telemetry`
- 按场景分桶（empty/single AO/multi AO/with revision）: `UNKNOWN: only final FactMemory snapshot is persisted; per-call block telemetry unavailable`

## 10. Pass/Fail per Category

| Category | A | B | C | D | E | F |
|---|---:|---:|---:|---:|---:|---:|
| ambiguous_colloquial | 0.6500 | 0.5000 | 0.5500 | 0.5000 | 0.5500 | 0.5000 |
| code_switch_typo | 0.8000 | 0.6500 | 0.8500 | 0.8000 | 0.8000 | 0.6500 |
| constraint_violation | 0.8824 | 0.7059 | 0.8824 | 0.6471 | 0.8824 | 0.8824 |
| incomplete | 0.5000 | 0.7222 | 0.4444 | 0.4444 | 0.4444 | 0.5000 |
| multi_step | 0.7000 | 0.7500 | 0.5500 | 0.5500 | 0.4500 | 0.6500 |
| multi_turn_clarification | 0.3000 | 0.2500 | 0.3500 | 0.6500 | 0.6000 | 0.5500 |
| parameter_ambiguous | 0.5417 | 0.2917 | 0.5833 | 0.5833 | 0.4583 | 0.5833 |
| simple | 0.9524 | 0.8095 | 0.9524 | 0.9524 | 0.9524 | 0.9524 |
| user_revision | 1.0000 | 0.9000 | 1.0000 | 0.9500 | 1.0000 | 1.0000 |

## 11. Phase 2 Goal Cases
- Bucket `输出不完整`:
  - `e2e_ambiguous_003, e2e_ambiguous_005, e2e_multistep_002, e2e_multistep_004, e2e_incomplete_001, e2e_incomplete_002, e2e_incomplete_003, e2e_simple_011, e2e_ambiguous_009, e2e_ambiguous_010, e2e_ambiguous_011, e2e_multistep_006, e2e_multistep_008, e2e_multistep_009, e2e_multistep_010, e2e_multistep_011, e2e_incomplete_006, e2e_incomplete_008, e2e_incomplete_010, e2e_incomplete_011, e2e_incomplete_013, e2e_incomplete_014, e2e_incomplete_015, e2e_incomplete_017, e2e_incomplete_018, e2e_constraint_008, e2e_constraint_013, e2e_ambiguous_020, e2e_ambiguous_026, e2e_ambiguous_034, e2e_constraint_035, e2e_ambiguous_038, e2e_ambiguous_039, e2e_multistep_040, e2e_multistep_041, e2e_multistep_043, e2e_multistep_050, e2e_clarification_101, e2e_clarification_111, e2e_clarification_112, e2e_clarification_113, e2e_clarification_114, e2e_clarification_115, e2e_clarification_119, e2e_clarification_120, e2e_colloquial_143, e2e_colloquial_144, e2e_colloquial_145, e2e_colloquial_146, e2e_colloquial_148, e2e_colloquial_149, e2e_colloquial_157, e2e_colloquial_158, e2e_colloquial_160, e2e_codeswitch_163, e2e_codeswitch_169, e2e_codeswitch_178, e2e_codeswitch_179`

READY FOR PHASE 2: NO
