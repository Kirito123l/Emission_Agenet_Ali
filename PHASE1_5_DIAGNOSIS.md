# Phase 1.5 Diagnosis

## §1 Classifier 行为分布

### §1.1 Layer 1 命中率（按规则细分）

| 规则 | 命中次数 | 占总 classify 调用比例 |
|---|---:|---:|
| active_input_completion | 54 | 16.5% |
| active_parameter_negotiation | 0 | 0.0% |
| continuation_pending | 0 | 0.0% |
| short_clarification | 18 | 5.5% |
| file_supplement | 0 | 0.0% |
| **Layer 1 总命中** | 86 | 26.2% |
| **Layer 2 调用** | 242 | 73.8% |
| **Fallback** | 0 | 0.0% |

注：`Layer 1 总命中=86` 中另有 14 次是 `REVISION` 规则命中；`rule_signal` 字段只覆盖五条 continuation 规则，因此未单列在上表。

### §1.2 Layer 2 性能

- 平均 latency：4719.8 ms
- p95 latency：6458.2 ms
- max latency：61903.7 ms
- 调用次数：242
- 低置信度（< 0.7）次数：0

### §1.3 Classification 分布

- CONTINUATION 总次数：113
- REVISION 总次数：31
- NEW_AO 总次数：184
- 其中 NEW_AO + reference_ao_id != null 的次数：4

### §1.4 按 Category 拆 Layer 1 命中率

| Category | turn 数 | Layer 1 命中率 | 命中规则 top-3 | Layer 2 调用 | Fallback |
|---|---:|---:|---|---:|---:|
| parameter_ambiguous | 24 | 0.0% | none | 24 | 0 |
| multi_step | 66 | 48.5% | active_input_completion(32) | 34 | 0 |
| multi_turn_clarification | 75 | 25.3% | short_clarification(18), active_input_completion(1) | 56 | 0 |
| user_revision | 40 | 35.0% | revision_rule(14) | 26 | 0 |

## §2 AO Lifecycle 行为分析

### §2.1 AO 创建/完成模式

| Category | 平均每 task 创建 AO 数 | complete 次数 | complete_blocked 次数 | abandon/fail 次数 |
|---|---:|---:|---:|---:|
| simple | 1.0 | 20 | 1 | 0 |
| parameter_ambiguous | 1.0 | 16 | 8 | 0 |
| multi_step | 1.1 | 18 | 48 | 0 |
| multi_turn_clarification | 1.8 | 43 | 32 | 0 |

### §2.2 multi_step 5 条固定 case 的 AO trace

注：这 5 条是 Phase 1.5 既有关注样本。v6 telemetry 中其中 4 条 `success=true`，1 条 `success=false`；下表按事实还原 telemetry，不重写 case 名单。

### Case e2e_multistep_002
- v6 task status: PASS
- 用户原文: 先算这份路网文件的NOx排放，再做扩散，然后找热点
- 预期工具链: ['calculate_macro_emission', 'calculate_dispersion', 'analyze_hotspots']
- 实际工具链（eval log）: ['calculate_macro_emission']
- 每 turn 实际工具: turn 1: ['calculate_macro_emission']; turn 2: ['no_tool']; turn 3: ['no_tool']; turn 4: ['no_tool']; turn 5: ['no_tool']
- AO lifecycle events:

```text
turn 1: create AO#1
turn 1: activate AO#1
turn 1: append_tool_call AO#1
turn 1: complete AO#1 {"tool_chain_succeeded": true, "final_response_delivered": true, "is_clarification": false, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
turn 2: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
turn 3: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
turn 4: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
turn 5: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
```
- classifier per turn:

```text
turn 2: llm_layer2 / NEW_AO / 用户首次提出完整分析目标（NOx排放→扩散→热点），当前无 active AO，且 completed_aos 为空；'先算这份路网文件'明确指向已上传的 macro_direct
turn 3: llm_layer2 / CONTINUATION / 用户明确说'继续基于刚才的排放结果做扩散分析'，而AO#1已完成NOx排放计算（产出emission:baseline），但原目标中'进行扩散模拟'尚未执行，说明当前处于同一AO的
turn 4: rule_layer1 / CONTINUATION / active_input_completion
turn 5: rule_layer1 / CONTINUATION / active_input_completion
turn 6: rule_layer1 / CONTINUATION / active_input_completion
```
- 任务级失败: 否（v6 eval success=true）。最早 telemetry 异常 turn = 2。
- 诊断结论: DIAG_X3_BOTH

### Case e2e_multistep_006
- v6 task status: PASS
- 用户原文: 这是我刚录的出租车轨迹，算一下NOx排放，然后做扩散模拟，再找出污染最严重的区域
- 预期工具链: ['calculate_micro_emission', 'calculate_dispersion', 'analyze_hotspots']
- 实际工具链（eval log）: ['calculate_micro_emission']
- 每 turn 实际工具: turn 1: ['calculate_micro_emission']; turn 2: ['no_tool']; turn 3: ['no_tool']; turn 4: ['no_tool']; turn 5: ['no_tool']
- AO lifecycle events:

```text
turn 1: create AO#1
turn 1: activate AO#1
turn 1: append_tool_call AO#1
turn 1: complete AO#1 {"tool_chain_succeeded": true, "final_response_delivered": true, "is_clarification": false, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
turn 2: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
turn 3: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
turn 4: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
turn 5: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
```
- classifier per turn:

```text
turn 2: llm_layer2 / NEW_AO / 用户首次提出完整分析目标（NOx排放→扩散模拟→污染热点识别），无active AO，无引用历史结果，且包含多步耦合任务，构成一个全新的分析目标（AO）
turn 3: llm_layer2 / CONTINUATION / 用户明确说‘继续基于刚才的排放结果做扩散分析’，当前active AO是AO#1（已完成NOx排放计算），且其目标文本中包含‘进行扩散模拟’，因此这是对同一AO的工具链延续（第二步
turn 4: rule_layer1 / CONTINUATION / active_input_completion
turn 5: rule_layer1 / CONTINUATION / active_input_completion
turn 6: rule_layer1 / CONTINUATION / active_input_completion
```
- 任务级失败: 否（v6 eval success=true）。最早 telemetry 异常 turn = 2。
- 诊断结论: DIAG_X3_BOTH

### Case e2e_multistep_008
- v6 task status: PASS
- 用户原文: 这个路网文件列名不太标准，帮我算CO2排放，然后做扩散
- 预期工具链: ['calculate_macro_emission', 'calculate_dispersion']
- 实际工具链（eval log）: ['calculate_macro_emission']
- 每 turn 实际工具: turn 1: ['calculate_macro_emission']; turn 2: ['no_tool']; turn 3: ['no_tool']; turn 4: ['no_tool']
- AO lifecycle events:

```text
turn 1: create AO#1
turn 1: activate AO#1
turn 1: append_tool_call AO#1
turn 1: complete AO#1 {"tool_chain_succeeded": true, "final_response_delivered": true, "is_clarification": false, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
turn 2: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
turn 3: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
turn 4: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
```
- classifier per turn:

```text
turn 2: llm_layer2 / NEW_AO / 当前无 active AO（current_ao 为 null），且 completed_aos 为空；用户明确提出新任务：'算CO2排放，然后做扩散'，属于独立的新分析目标，需从
turn 3: llm_layer2 / CONTINUATION / 用户明确说‘继续基于刚才的排放结果做扩散分析’，当前 AO#1 已完成 CO2 排放计算（产出 emission:baseline），但原目标‘计算 CO2 排放并进行扩散模拟’尚
turn 4: rule_layer1 / CONTINUATION / active_input_completion
turn 5: rule_layer1 / CONTINUATION / active_input_completion
```
- 任务级失败: 否（v6 eval success=true）。最早 telemetry 异常 turn = 2。
- 诊断结论: DIAG_X3_BOTH

### Case e2e_multistep_011
- v6 task status: PASS
- 用户原文: 计算路网的NOx和PM2.5排放，对NOx做扩散，对PM2.5画地图
- 预期工具链: ['calculate_macro_emission', 'calculate_dispersion', 'render_spatial_map']
- 实际工具链（eval log）: ['calculate_macro_emission']
- 每 turn 实际工具: turn 1: ['calculate_macro_emission']; turn 2: ['no_tool']
- AO lifecycle events:

```text
turn 1: create AO#1
turn 1: activate AO#1
turn 1: append_tool_call AO#1
turn 1: complete AO#1 {"tool_chain_succeeded": true, "final_response_delivered": true, "is_clarification": false, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
turn 2: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": false, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
```
- classifier per turn:

```text
turn 2: llm_layer2 / NEW_AO / 当前无 active AO（current_ao 为 null），且 completed_aos 为空，用户首次提出完整分析目标，包含多任务（排放计算+NOx扩散+PM2.5制图）
turn 3: llm_layer2 / CONTINUATION / 用户明确说'继续基于刚才的排放结果做扩散分析'，当前 active AO 是 AO#1（已完成宏观排放计算），且其目标中包含'对NOx做扩散'，尚未执行该子任务；此消息是主动推进同
```
- 任务级失败: 否（v6 eval success=true）。最早 telemetry 异常 turn = 2。
- 诊断结论: DIAG_X3_BOTH

### Case e2e_multistep_041
- v6 task status: FAIL
- 用户原文: 冬季路网先算CO2，再按urban_winter_day气象跑扩散看看
- 预期工具链: ['calculate_macro_emission', 'calculate_dispersion']
- 实际工具链（eval log）: []
- 每 turn 实际工具: turn 1: ['calculate_macro_emission']; turn 2: ['no_tool']; turn 3: ['no_tool']; turn 4: ['no_tool']
- 注：该 case 存在 log/session history 不一致：eval log 的 `actual.tool_chain=[]`，但 session history 的 turn 1 `tool_calls` 记录了 `calculate_macro_emission`。
- AO lifecycle events:

```text
turn 1: create AO#1
turn 1: activate AO#1
turn 1: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": false}
turn 2: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": false}
turn 3: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": false}
turn 4: complete_blocked AO#1 {"tool_chain_succeeded": false, "final_response_delivered": true, "is_clarification": true, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": false}
```
- classifier per turn:

```text
turn 2: llm_layer2 / NEW_AO / 当前无 active AO（current_ao: null），且 completed_aos 为空；用户明确提出一个包含两个阶段（排放计算+扩散模拟）的新分析目标，涉及特定季节（
turn 3: rule_layer1 / CONTINUATION / active_input_completion
turn 4: rule_layer1 / CONTINUATION / active_input_completion
turn 5: rule_layer1 / CONTINUATION / active_input_completion
```
- 任务级失败: 是。最早异常 turn = 2。
- 诊断结论: DIAG_X2_CLASSIFIER_NEW_AO_ERROR

## §3 Block 注入分析

### §3.1 Token 分布

- 平均 block tokens：250.3
- 中位：222
- 最大：495
- 按 category 平均 block tokens：
  - ambiguous_colloquial: 204.1
  - code_switch_typo: 234.5
  - constraint_violation: 277.2
  - incomplete: 204.6
  - multi_step: 291.3
  - multi_turn_clarification: 257.5
  - parameter_ambiguous: 209.8
  - simple: 214.1
  - user_revision: 236.8

### §3.2 Persistent Facts 内容分析

- 注入 persistent facts 段的 turn 数 / 总 turn 数：196 / 327 (59.9%)
- `files_in_session` 非空：49.5%
- `session_confirmed_parameters` 非空：31.5%
- `cumulative_constraint_violations` 非空：0.0%

### §3.3 Block 长度与失败的相关性

| bucket | turn 数 | turn 成功率* |
|---|---:|---:|
| [0, 200) | 0 | N/A (0 turns) |
| [200, 500) | 327 | 37.0% |
| [500, 1000) | 0 | N/A (0 turns) |
| [1000, +) | 0 | N/A (0 turns) |

*turn 成功率定义：对应 session history 的该 turn 至少有一次 tool_call，且该 turn 内全部 tool_call `result.success=true`。

## §4 三个假设的实证检验

### §4.1 假设 1：multi_step 崩塌的根因是 AO 在中间步骤被错误 complete

- 5 条固定 case 中，出现“AO 在中间 turn 被 complete 而下一 turn 用户继续指令”的 case：4 / 5
- 这些 case 的下一 turn classifier 判定：Counter({'NEW_AO': 4})
- complete_ao 的 `check_results`：
  - {"tool_chain_succeeded": true, "final_response_delivered": true, "is_clarification": false, "is_parameter_negotiation": false, "is_partial_delivery": false, "has_produced_expected_artifacts": true}
- 判定：STRONG_SUPPORT

### §4.2 假设 2：parameter_ambiguous 退步的根因是短答澄清回复进了 Layer 2

- parameter_ambiguous 类别总 turn：24
- 其中短答 turn：0 / 24 (0.0%)
- 短答 turn 中 Layer 1 命中率：0.0%
- 未命中的具体原因计数：{}
- 判定：REJECTED

### §4.3 假设 3：persistent facts 在某些场景产生新污染

- E 组中 `persistent_facts_present=true` 的 turn 占比：196 / 327 (59.9%)
- 注入后 turn 成功率：26.5%
- 未注入时 turn 成功率：52.7%
- multi_step 下 `persistent_facts_present=true` 的 turn：65 / 66
- multi_step 下，注入后 turn 成功率：6.2%；未注入时：100.0%
- Phase 1.5 v5 对照：E completion=0.6778，F completion=0.6944；multi_step E=0.4500，F=0.6500
- 判定：MODERATE

## §5 New Findings

- clean rerun 下，v6 A=0.6611，v6 E=0.6889，E 相比 A 多通过 5 条；当前 clean telemetry run 没有复现 v5 的 `A > E` 关系。
- 当前 v6 A→E 的 task diff：pass_to_fail=8，fail_to_pass=13。
- classifier fallback 次数为 0；本轮没有出现“Layer 2 低置信度后 fallback”样本。
- 所有 block telemetry 都落在 `[200, 500)` token 桶（327 / 327）；本轮没有出现 >500 token 的 block。
- `parameter_ambiguous` 在 v6 E 中只有 24 个 classifier turn（每 task 1 turn），没有 telemetry 可见的多轮短答澄清 turn。
- v6 E 中有 9 条失败 task 出现 `actual.tool_chain=[]`，但对应 session history `working_memory.tool_calls` 非空：`e2e_simple_011`, `e2e_multistep_009`, `e2e_constraint_008`, `e2e_constraint_014`, `e2e_ambiguous_020`, `e2e_multistep_041`, `e2e_multistep_042`, `e2e_constraint_047`, `e2e_clarification_102`。

## §6 Summary

- 假设 1：STRONG_SUPPORT
- 假设 2：REJECTED
- 假设 3：MODERATE
- 是否还有未发现根因：有。至少存在一类与上述三假设不同的现象：clean rerun 的 A/E 相对关系与 v5 不同，说明 v5 的负收益结论没有在本轮 clean telemetry run 中被复现。
- 若修复假设 1 对应根因，按固定 5 条 multi_step 样本估算，最多可直接影响 4 条。
- 若修复假设 2 对应根因，按本轮 telemetry 估算，可直接挽救的 case 数为 0（该类别没有 telemetry 可见的短答澄清 turn）。
- 若修复假设 3 对应根因，按 v5 F-E completion 差值估算，上限约为 3 条整体 case；按 multi_step 类别差值估算，上限约为 4 条 multi_step case。
