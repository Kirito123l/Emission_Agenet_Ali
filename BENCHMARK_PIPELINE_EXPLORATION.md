# BENCHMARK_PIPELINE_EXPLORATION

Read-only exploration completed on the current repository state.

Method:
- Read code and data under `evaluation/`, `core/`, `api/`, `tools/`, `services/`.
- Ran lightweight JSONL/JSON/CSV statistics and path comparisons.
- Did not modify existing code or run large benchmark jobs.

## Section 1: Benchmark 数据全貌

### 1.1 当前有哪些 benchmark / sample / candidate 数据文件

#### A. Canonical benchmark / eval sample sets

| file path | samples | schema / columns | role |
|---|---:|---|---|
| `evaluation/benchmarks/end2end_tasks.jsonl` | 180 | `id, category, description, user_message, has_file, test_file, expected_tool, expected_tool_chain, expected_params, success_criteria, follow_up_messages?, benchmark_metadata?` | 当前 full end-to-end benchmark；`eval_end2end.py` 默认读取它，`evaluation/eval_end2end.py:46`, `evaluation/run_e2e_stable.py:16`, `evaluation/run_phase1_5_benchmark.py:23`, `evaluation/run_oasc_matrix.py:15`, `evaluation/run_health.py:59` |
| `evaluation/benchmarks/standardization_benchmark.jsonl` | 825 | `id, dimension, difficulty, raw_input, expected_output, language, notes` | 当前 canonical standardization benchmark；`evaluation/eval_standardization_benchmark.py:24` |
| `evaluation/end2end/samples.jsonl` | 10 | `sample_id, user_query, file_path, expected_tool_name, tool_arguments, expected_success, expected_outputs` | legacy / smoke e2e sample set；`evaluation/run_smoke_suite.py:55-64`；`evaluation/eval_end2end.py:733-751` 兼容其旧 schema |
| `evaluation/normalization/samples.jsonl` | 10 | `sample_id, tool_name, raw_arguments, expected_standardized, focus_params, expected_success` | normalization eval sample set；`evaluation/eval_normalization.py:136-155` |
| `evaluation/file_tasks/samples.jsonl` | 10 | `sample_id, user_query, file_path, expected_task_type, expected_tool_name, expected_mapping, expected_required_present` | file-grounding eval sample set；`evaluation/eval_file_grounding.py:183-208` |
| `evaluation/continuation/samples.jsonl` | 8 | `case_id, category, description, prior_state, current_user_input, expected_continuation_decision, expected_new_task_override, expected_next_tool, expected_trace_markers, notes` | continuation eval sample set；`evaluation/eval_continuation.py:47-81` |
| `evaluation/human_compare/samples.csv` | 10 | `sample_id, task_type, user_query, file_path, manual_baseline, expected_tool_name, notes` | manual comparison scaffold；README 明确说不是 fully automated benchmark path，`evaluation/README.md:61-65` |

#### B. 旧生成链产物

| file path | samples | schema | role |
|---|---:|---|---|
| `evaluation/generated/e2e_tasks_simple.jsonl` | 10 | end2end candidate schema + `validation` | 旧 e2e 生成候选 |
| `evaluation/generated/e2e_tasks_parameter_ambiguous.jsonl` | 10 | same | 旧 e2e 生成候选 |
| `evaluation/generated/e2e_tasks_multi_step.jsonl` | 10 | same | 旧 e2e 生成候选 |
| `evaluation/generated/e2e_tasks_incomplete.jsonl` | 20 | same, but `expected_tool` may be absent | 旧 e2e 生成候选 |
| `evaluation/generated/e2e_tasks_constraint_violation.jsonl` | 10 | same | 旧 e2e 生成候选 |
| `evaluation/generated/e2e_tasks_summary.json` | n/a | `generated_at, model, categories, status_totals` | 旧 e2e 生成 summary；当前记录模型 `qwen3-max` |
| `evaluation/generated/hard_cases_{vehicle_type,pollutant,season,road_type,meteorology,stability_class}.jsonl` | 30/30/20/25/25/20 | standardization hard-case schema + `validation` | standardization hard-case 生成产物 |
| `evaluation/generated/hard_cases_summary.json` | n/a | `generated_at, model, dimensions, status_totals` | standardization hard-case summary；当前记录模型 `qwen3-max` |

#### C. `pipeline_v2` 数据资产

| file path | samples | schema | role |
|---|---:|---|---|
| `evaluation/pipeline_v2/gap_report.json` | n/a | coverage/gap report fields | coverage audit 输出 |
| `evaluation/pipeline_v2/phase0_coverage_report.json` | n/a | same family as `gap_report.json` | phase0 coverage snapshot |
| `evaluation/pipeline_v2/final_gap_report.json` | n/a | same family as `gap_report.json` | merge 后 final coverage snapshot |
| `evaluation/pipeline_v2/manual_candidates.jsonl` | 36 | benchmark-like schema + `candidate_metadata`, `review_decision` | manual candidate pool |
| `evaluation/pipeline_v2/validated_manual.jsonl` | 36 | above + `validation` | manual pool after validator |
| `evaluation/pipeline_v2/phase0_premerge_benchmark_100.jsonl` | 100 | benchmark schema | premerge 主 benchmark 100 条 |
| `evaluation/pipeline_v2/phase0_adversarial_candidates.jsonl` | 80 | benchmark schema + `follow_up_messages`, `benchmark_metadata` | adversarial / robustness candidate set |
| `evaluation/pipeline_v2/phase0_validated_adversarial.jsonl` | 80 | above + `validation` | validated adversarial set |
| `evaluation/pipeline_v2/phase0_reviewed_adversarial.jsonl` | 80 | above + `validation`, `review_decision` | reviewed adversarial set |

#### D. File-task fixture assets

These are not benchmark task rows, but they are benchmark input fixtures.

| file path | rows | columns | role |
|---|---:|---|---|
| `evaluation/file_tasks/data/macro_direct.csv` | 3 | `link_id,length,flow,speed` | macro canonical fixture |
| `evaluation/file_tasks/data/macro_fuzzy.csv` | 3 | `segment_name,road_length_km,traffic_volume_per_hour,avgVelocity` | macro fuzzy-column fixture |
| `evaluation/file_tasks/data/macro_cn_fleet.csv` | 3 | Chinese macro columns | macro Chinese/fleet fixture |
| `evaluation/file_tasks/data/micro_time_speed.csv` | 6 | `time,speed` | micro canonical fixture |
| `evaluation/file_tasks/data/micro_cn.csv` | 6 | Chinese micro columns | micro Chinese fixture |
| `evaluation/file_tasks/data/micro_full.csv` | 6 | `t,speed_kph,acceleration_mps2,grade_pct` | richer micro fixture |
| `evaluation/file_tasks/data/micro_speed_only.csv` | 6 | `speed_kmh` | intentionally incomplete micro fixture |
| `evaluation/file_tasks/data/micro_time_sec_speed_kmh.csv` | 6 | `time_sec,speed_kmh` | alternate micro fixture |

### 1.2 哪个更像当前主用 benchmark

结论：
- full benchmark 主用版本是 `evaluation/benchmarks/end2end_tasks.jsonl`。
- smoke / low-friction path 仍在用 `evaluation/end2end/samples.jsonl`。

依据：
- `eval_end2end.py` 默认样本路径是 `evaluation/benchmarks/end2end_tasks.jsonl`，`evaluation/eval_end2end.py:46`。
- 稳定跑分、Phase 1.5、OASC matrix、preflight 都默认指向同一个文件，`evaluation/run_e2e_stable.py:16`, `evaluation/run_phase1_5_benchmark.py:23`, `evaluation/run_oasc_matrix.py:15`, `evaluation/run_health.py:59`。
- `run_smoke_suite.py` 则显式使用 `evaluation/end2end/samples.jsonl`，而且是 `tool` mode，`evaluation/run_smoke_suite.py:55-64`。
- `evaluation/end2end/samples.jsonl` 还是 legacy schema；`eval_end2end.py` 需要 `_normalize_task()` 做兼容转换，`evaluation/eval_end2end.py:733-751`。

额外事实：
- 当前 `evaluation/benchmarks/end2end_tasks.jsonl` 的 180 条任务，和 `evaluation/pipeline_v2/phase0_premerge_benchmark_100.jsonl` 的 100 条 + `evaluation/pipeline_v2/phase0_validated_adversarial.jsonl` 的 80 条在 ID 集上完全相等；没有额外任务。
- 也就是说，当前 full benchmark 实际上就是 “phase0 premerge 100 + phase0 adversarial 80” 的并集。

关于“用户最近上传的 benchmark 文件”：
- 仓库里能看到较新的 `pipeline_v2/*.jsonl` 工件，且部分为未跟踪文件。
- 但没有任何 loader 默认指向这些文件，也没有 upload-specific 命名或 API 引用。
- 因此“最近上传的 benchmark 文件”是否存在，结论是 `UNKNOWN`。

### 1.3 当前 full benchmark（180 条）分布

#### Category 分布

| category | count |
|---|---:|
| `simple` | 21 |
| `parameter_ambiguous` | 24 |
| `multi_step` | 20 |
| `incomplete` | 18 |
| `constraint_violation` | 17 |
| `multi_turn_clarification` | 20 |
| `user_revision` | 20 |
| `ambiguous_colloquial` | 20 |
| `code_switch_typo` | 20 |

Category 枚举值来自数据本身，也与 `pipeline_v2` 支持类别一致，`evaluation/pipeline_v2/common.py:20-30`。

#### `expected_tool` 分布

| expected_tool | count |
|---|---:|
| `query_emission_factors` | 88 |
| `calculate_macro_emission` | 13 |
| `calculate_micro_emission` | 11 |
| `query_knowledge` | 1 |
| missing / null | 67 |

`expected_tool` 缺失主要对应：
- no-tool tasks
- multi-step tasks（只保留 `expected_tool_chain`）

#### `expected_tool_chain` 长度分布

| tool chain length | count |
|---|---:|
| 0 | 32 |
| 1 | 113 |
| 2 | 27 |
| 3 | 7 |
| 4 | 1 |

常见组合：

| expected_tool_chain | count |
|---|---:|
| `["query_emission_factors"]` | 88 |
| `[]` | 32 |
| `["calculate_macro_emission","calculate_dispersion"]` | 16 |
| `["calculate_macro_emission"]` | 13 |
| `["calculate_micro_emission"]` | 11 |
| `["calculate_macro_emission","render_spatial_map"]` | 5 |

#### `follow_up_messages` 分布

| follow_up_messages length | count |
|---|---:|
| 0 | 140 |
| 1 | 20 |
| 2 | 7 |
| 3 | 11 |
| 4 | 2 |

结论：
- 单轮 / 无 follow-up：140 / 180 = 77.8%
- 显式 scripted 多轮：40 / 180 = 22.2%

#### 按 category 看对话形态

| category | count | chain length pattern | follow-up pattern | judgement |
|---|---:|---|---|---|
| `simple` | 21 | 全是 1-step | 全是 0 | 单轮、单步 |
| `parameter_ambiguous` | 24 | 21 个 1-step，3 个 0-step | 全是 0 | 偏单轮参数标准化 / 局部澄清 |
| `multi_step` | 20 | 全是 2-4 step | 全是 0 | 多步工具链 |
| `incomplete` | 18 | 全是 0-step | 全是 0 | 等待补参 |
| `constraint_violation` | 17 | 8 个 0-step，9 个 1-2 step | 全是 0 | blocked / warning mixed |
| `multi_turn_clarification` | 20 | 16 个 1-step，4 个 2-step | 全是 2-4 个 follow-ups | 显式 scripted 多轮 |
| `user_revision` | 20 | 19 个 1-step，1 个 2-step | 全是 1 个 follow-up | 显式单次 revision |
| `ambiguous_colloquial` | 20 | 全是 1-step | 全是 0 | 单轮口语化解析 |
| `code_switch_typo` | 20 | 15 个 1-step，2 个 2-step，3 个 0-step | 全是 0 | 单轮 code-switch / typo |

#### 其他直接可见事实

| item | count / note |
|---|---|
| `geometry_gated_halt_acceptable=true` | 21 条，其中 `multi_step` 13 条，`constraint_violation` 8 条 |
| 有 `benchmark_metadata` 的任务 | 102 条 |
| 带 `phase0_adversarial=true` 的任务 | 80 条 |
| 最常见 `test_file` | `macro_direct.csv` 33 条，`micro_time_speed.csv` 18 条 |
| 具显式 geometry 的 fixture 覆盖 | 仅 `test_data/test_6links.xlsx`，被 6 条任务使用 |

### 1.4 是否存在指定类别

| requested class | count | basis |
|---|---:|---|
| simple execution | 21 | `category=simple` |
| parameter ambiguity | 24 | `category=parameter_ambiguous` |
| incomplete input | 18 | `category=incomplete` |
| constraint violation | 17 | `category=constraint_violation` |
| multi-step workflow | 35 | `category=multi_step` 20 条；按 chain length >1 统计是 35 条 |
| multi-turn clarification | 40 | `category=multi_turn_clarification` 20 条；按 `follow_up_messages` 非空统计是 40 条 |
| user revision / correction | 20 | `category=user_revision` |
| code-switch / typo / colloquial | 40 | `ambiguous_colloquial` 20 + `code_switch_typo` 20 |
| cross-session or task switching | 0 | 数据里没有相应 category，也没有 session-switch field |

`task_type` / `turn_count`：
- `task_type`: `UNKNOWN`，当前 full benchmark schema里没有这个字段。
- `turn_count`: `UNKNOWN`，当前 full benchmark schema里没有这个字段。

### 1.5 expected 设计风格：strict tool-chain / behavior-equivalent / mixed?

结论：`mixed, but path-heavy`。

证据：
- `expected_tool_chain` 仍是主骨架；默认要求 `actual == expected`，`evaluation/eval_end2end.py:377-388`。
- `success = geometry_gated_success or tool_match`，然后再与 `success_criteria` 求 AND，`evaluation/eval_end2end.py:856-877`。这说明 path match 仍是进入“成功”的主要门槛。
- 允许的“等价”只出现在少数特判：
  - 单工具时，若没抓到 tool call，但文本明显交付了 expected tool 结果，可算命中，`evaluation/eval_end2end.py:805-810`, `507-527`。
  - 参数比对允许 subset match、alias match、list subset match，`evaluation/utils.py:205-253`。
  - 参数还可从 tool result text 中补救匹配，`evaluation/eval_end2end.py:559-585`。
  - geometry 缺失导致 multi-step 合法停在前缀链时，可视作成功，但必须显式打 `geometry_gated_halt_acceptable=true`，`evaluation/eval_end2end.py:679-730`。
  - `user_revision` 允许只比对实际链的最后一段 suffix，`evaluation/eval_end2end.py:386-388`。

因此它不是纯 strict tool-chain matching，但也远不是“开放行为等价”；本质上仍然是“严格链路 + 少量白名单等价特判”。

### Section 1 小结

当前 full benchmark 主要在测：
- 工具链是否按预期发生
- 参数是否能被标准化到 canonical 值
- 缺参 / 约束 / geometry gating 下是否停在指定行为
- 少量 scripted 多轮澄清和单次 revision

当前 full benchmark 不主要测：
- 自由形态多轮对话
- 跨 session / task switching
- 开放式 artifact continuity
- 多种合理路径并存的行为等价
- 非脚本化、长上下文、自然补参对话

## Section 2: Benchmark 的构造 pipeline

### 2.1 旧生成链脚本

| file path | main entry / function | input | output | role | LLM | manual review |
|---|---|---|---|---|---|---|
| `evaluation/build_benchmark.py` | `load_mappings()`, `generate_*_cases()`, `main()` | `config/unified_mappings.yaml` | `evaluation/benchmarks/standardization_benchmark.jsonl` | deterministic 构建 standardization benchmark | no | no |
| `evaluation/context_extractor.py` | `extract_system_capabilities()`, `extract_tool_contracts()`, `load_existing_end2end_tasks()` | `config/unified_mappings.yaml`, `config/tool_contracts.yaml`, existing benchmark | in-memory prompt context | 给生成器提供 system capabilities / aliases / existing tasks | no | no |
| `evaluation/llm_generator.py` | `LLMGenerator.generate_json()` | system prompt + user prompt | parsed JSON object | 统一 LLM generation wrapper | yes (`qwen3-max` default, `evaluation/llm_generator.py:20`, `95-103`) | no |
| `evaluation/generate_e2e_tasks.py` | `main()` / generation loop | existing `evaluation/benchmarks/end2end_tasks.jsonl`, `config/cross_constraints.yaml`, context extractor output | `evaluation/generated/e2e_tasks_{category}.jsonl`, `evaluation/generated/e2e_tasks_summary.json` | 旧 e2e candidate 生成器；只覆盖 5 类，`evaluation/generate_e2e_tasks.py:36-43` | yes | implicit only via `validation.status`，无专门 CLI |
| `evaluation/merge_generated_e2e_tasks.py` | `main()` | `evaluation/generated/e2e_tasks_*.jsonl`, benchmark | 写回 `evaluation/benchmarks/end2end_tasks.jsonl` | 旧 e2e merge；只 merge `validation.status=valid`，`evaluation/merge_generated_e2e_tasks.py:118-155` | no | depends on preexisting `validation` |
| `evaluation/generate_hard_cases.py` | `main()` | standardization benchmark, mappings context | `evaluation/generated/hard_cases_{dimension}.jsonl`, summary | 生成 standardization hard cases | yes | no dedicated CLI; engine validation only |
| `evaluation/merge_generated_cases.py` | `main()` | `evaluation/generated/hard_cases_*.jsonl`, standardization benchmark | 写回 `evaluation/benchmarks/standardization_benchmark.jsonl` | merge standardization hard cases | no | yes/no 取决于 validation status |

旧 e2e 生成器的硬约束很强：
- prompt 里要求输出 `expected_tool` / `expected_tool_chain` / `expected_params` / `expected_behavior`，`evaluation/generate_e2e_tasks.py:70-108`。
- 类别只有 5 类：`simple`, `parameter_ambiguous`, `multi_step`, `incomplete`, `constraint_violation`，`evaluation/generate_e2e_tasks.py:36-43`。

### 2.2 `pipeline_v2` 脚本

| file path | main entry / function | input | output | role | LLM | manual review |
|---|---|---|---|---|---|---|
| `evaluation/pipeline_v2/coverage_audit.py` | `build_gap_report()` / `main()` | benchmark + mappings + constraints | `gap_report.json` family | 统计覆盖缺口、tool chain combo、language、constraint coverage | no | no |
| `evaluation/pipeline_v2/targeted_generator.py` | `generate_candidates()` / `main()` | `gap_report.json`, existing benchmark | candidates JSONL | 按 gap 定向生成候选任务 | yes | no |
| `evaluation/pipeline_v2/auto_validator.py` | `MultiLayerValidator.validate_all()` / `main()` | candidates + benchmark + mappings + constraints | validated candidates JSONL | 结构/参数/约束/去重/LLM review 五层校验 | layer5 yes | no dedicated human step here |
| `evaluation/pipeline_v2/review_cli.py` | `review()` / `main()` | validated candidates | reviewed candidates JSONL | 交互式人工 approve / reject / edit | no | yes, explicit TTY review |
| `evaluation/pipeline_v2/regression_check.py` | `main()` | reviewed candidates | regression input + `regression_report.json` + e2e logs | 对批准候选跑 full-system `eval_end2end` regression | no extra generation | no |
| `evaluation/pipeline_v2/merge_to_benchmark.py` | `merge_candidates()` / `main()` | reviewed candidates + benchmark | merged benchmark JSONL | 把 approved / auto-valid 候选并入 canonical benchmark | no | yes, consumes review decisions |
| `evaluation/pipeline_v2/curate_existing_benchmark.py` | `curate()` / `main()` | existing benchmark | curated benchmark JSONL | deterministic benchmark cleanup / relabel / metadata normalization | no | no |
| `evaluation/pipeline_v2/common.py` | helpers | mappings / constraints / task canonicalization | in-memory | shared schema, valid categories, default success criteria, ID generation | no | no |
| `evaluation/pipeline_v2/run_pipeline.sh` | shell stages | benchmark + gap report + candidates | full pipeline outputs | orchestrates coverage -> generation -> validation -> review -> regression -> merge | mixed | yes, at stage 4 |

`run_pipeline.sh` 的明确阶段链：
- Stage 1 coverage audit
- Stage 2 targeted generation
- Stage 3 auto validation
- Stage 4 human review
- Stage 5 regression check
- Stage 6 merge to benchmark
- final coverage report

证据：`evaluation/pipeline_v2/run_pipeline.sh:4-68`。

### 2.3 文字版流程链

#### 旧 end2end 生成链

`existing benchmark + mappings/contracts/constraints -> generate_e2e_tasks.py -> evaluation/generated/e2e_tasks_*.jsonl -> merge_generated_e2e_tasks.py -> evaluation/benchmarks/end2end_tasks.jsonl`

#### standardization 构建链

`unified_mappings.yaml -> build_benchmark.py -> standardization_benchmark.jsonl`

#### standardization hard-case 扩充链

`standardization benchmark + mappings context -> generate_hard_cases.py -> evaluation/generated/hard_cases_*.jsonl -> merge_generated_cases.py -> standardization_benchmark.jsonl`

#### pipeline_v2 主链

`end2end_tasks.jsonl -> coverage_audit.py -> gap_report.json -> targeted_generator.py -> candidates.jsonl -> auto_validator.py -> validated_candidates.jsonl -> review_cli.py -> reviewed_candidates.jsonl -> regression_check.py -> merge_to_benchmark.py -> end2end_tasks.jsonl`

### 2.4 clarification / colloquial / multi-step / revision 样本是怎么来的

#### `multi_step`

可确认来源：
- 旧 5 类生成链包含 `multi_step` 类，`evaluation/generate_e2e_tasks.py:36-43`。
- `pipeline_v2/phase0_premerge_benchmark_100.jsonl` 中已有 20 条 `multi_step`。
- 当前 180 条 benchmark 中前 100 条完全覆盖该 premerge 文件。

结论：
- `multi_step` 样本来源是“old generator / manual candidate / pipeline_v2 premerge”混合链，而不是只靠 adversarial phase。

#### `multi_turn_clarification` / `user_revision` / `ambiguous_colloquial` / `code_switch_typo`

可确认来源：
- 这些类别不在旧生成器的 5 类里，`evaluation/generate_e2e_tasks.py:36-43`。
- 它们在 `pipeline_v2/common.py` 被纳入有效类别，`evaluation/pipeline_v2/common.py:20-30`。
- 当前 benchmark 里对应任务都带 `benchmark_metadata.phase0_adversarial=true`，并写明 `generation_flow=pipeline_v2_coverage_audit_targeted_manual_review`、`human_review=manual_codex_reviewed`，例如 `evaluation/benchmarks/end2end_tasks.jsonl:101`, `:121`, `:141`, `:161`。
- `evaluation/pipeline_v2/phase0_adversarial_candidates.jsonl` 恰好提供这四类共 80 条，且主 benchmark 精确包含其全部 80 个 ID。

结论：
- 这四类显然来自 `phase0_adversarial` 数据资产。
- 但仓库内没有找到生成 `phase0_adversarial_candidates.jsonl` 的专门脚本。
- 因此“它们到底是手工写的、模板生成的、LLM 生成的，还是混合方式”的最终结论是 `UNKNOWN`。
- 只能确认：最终 checked-in 数据带有人审痕迹，且 review 后全部 `approved`，`phase0_reviewed_adversarial.jsonl` 中 80 条都是 `review_decision=approved`。

#### `user_revision`

额外事实：
- 数据层面只建模了一次 follow-up revision；所有 `user_revision` 样本都只有 1 条 `follow_up_messages`。
- 并且 `benchmark_metadata.expected_param_source=final_user_revision` 已写入样本，例如 `evaluation/benchmarks/end2end_tasks.jsonl:121-140`。

### 2.5 pipeline 中哪些环节天然把 benchmark 往“规整输入”方向拉

| stage / file | evidence | shaping effect |
|---|---|---|
| `evaluation/generate_e2e_tasks.py` | prompt 强制输出 `expected_tool_chain` / `expected_params` / `expected_behavior`，`evaluation/generate_e2e_tasks.py:70-108` | 生成时先有结构化 expected，再有用户文本，天然偏“可标注的规整任务” |
| `evaluation/pipeline_v2/targeted_generator.py` | prompt rule 4 要求 `expected_params` 使用标准值，`evaluation/pipeline_v2/targeted_generator.py:35-40` | 期望标签层先 canonicalize，弱化自然语言补参的原始形态 |
| `evaluation/pipeline_v2/targeted_generator.py` | `tool_chain_combo` gap 要求“严格覆盖该工具链顺序”，`evaluation/pipeline_v2/targeted_generator.py:62-64` | 强化唯一 expected path |
| `evaluation/pipeline_v2/auto_validator.py` | `layer2_params()` 只接受 MOVES / mappings 里的标准值，`evaluation/pipeline_v2/auto_validator.py:172-208` | 非标准 expected 值被过滤掉 |
| `evaluation/pipeline_v2/common.py` | `build_success_criteria()` 对 category 直接套默认模板，`evaluation/pipeline_v2/common.py:286-312` | success semantics 被归纳成固定几种布尔组合 |
| `evaluation/pipeline_v2/common.py` | `canonicalize_benchmark_task()` 只保留有限字段，`evaluation/pipeline_v2/common.py:315-340` | benchmark schema 收敛为评测友好的固定字段 |
| `phase0_adversarial` 数据本身 | `multi_turn_clarification` follow-ups 多是短槽位回答，如 `["乘用车","NOx","2022年"]`，`evaluation/benchmarks/end2end_tasks.jsonl:101-110` | 多轮澄清更像 scripted slot-filling，而不是自由对话 |
| `user_revision` 数据本身 | 每条只有 1 次 revision follow-up，`evaluation/benchmarks/end2end_tasks.jsonl:121-140` | revision 被压缩成单次覆盖，不测复杂反复修正 |

### Section 2 小结

当前 benchmark 构造 pipeline 的主要塑形作用是：
- 先 canonicalize expected path / expected params / expected criteria
- 再生成或筛选自然语言表层
- 最后用 validator / review / regression 把任务进一步收束成“可被当前 `eval_end2end.py` 稳定判定”的形式

这会自然强化：
- canonical 参数
- 固定工具链
- 短 follow-up
- 可布尔化的成功条件

## Section 3: Evaluation 逻辑与 benchmark 假设

### 3.1 Eval 脚本地图

| file path | role |
|---|---|
| `evaluation/eval_end2end.py` | full e2e benchmark runner；当前最关键 |
| `evaluation/eval_ablation.py` | 多 feature-flag ablation，底层调用 `eval_end2end.py` |
| `evaluation/eval_standardization_benchmark.py` | standardization benchmark runner |
| `evaluation/eval_standardization_ablation.py` | standardization mode ablation |
| `evaluation/eval_normalization.py` | executor-layer normalization eval |
| `evaluation/eval_file_grounding.py` | file task recognition + column grounding eval |
| `evaluation/eval_continuation.py` | residual-plan continuation eval |
| `evaluation/run_smoke_suite.py` | minimal smoke suite；e2e 部分走 legacy 10-sample tool-mode |
| `evaluation/run_e2e_stable.py` | 多次重复 full e2e run |
| `evaluation/run_health.py` | preflight health check，从 full benchmark 里抽前 5 个 simple |
| `evaluation/run_oasc_matrix.py` | OASC group matrix runner |
| `evaluation/run_phase1_5_benchmark.py` | Phase 1.5 matrix + report generator |

### 3.2 `eval_end2end.py` 的核心执行流程

1. 读取样本并统一 schema。
   - `load_jsonl()` -> `_normalize_task()`，`evaluation/eval_end2end.py:1083-1088`, `733-773`
2. 可选先跑 `FileAnalyzerTool` 分析 benchmark 里指向的 test file。
   - `evaluation/eval_end2end.py:1113-1118`
3. 根据 mode 选择执行面：
   - `router`: `_run_router_task()` -> `build_router()` -> `router.chat()`，`evaluation/eval_end2end.py:990-1068`, `1128-1134`
   - `naive`: `NaiveRouter.chat()`，`evaluation/eval_end2end.py:1135-1154`
   - `tool`: 直接 `ToolExecutor.execute()`，仅支持单步，`evaluation/eval_end2end.py:1155-1185`
4. `router` mode 会在同一 session 内做 bounded follow-ups。
   - 最多 `min(len(expected_chain)+scripted_follow_up_count+2, 8)` 轮，`evaluation/eval_end2end.py:997-1000`
   - 若 benchmark 自带 `follow_up_messages`，优先喂这些。
   - 否则根据 expected chain 自动伪造“继续执行下一步”消息，`evaluation/eval_end2end.py:1047`, `602-619`
5. 汇总 response / trace / tool_calls。
   - `_merge_response_payloads()` / `_merge_trace_payloads()`，`evaluation/eval_end2end.py:622-676`
6. `_build_task_result()` 计算 actual criteria、success、failure type。
   - `evaluation/eval_end2end.py:776-918`
7. 写 `end2end_logs.jsonl` 与 `end2end_metrics.json`。
   - `evaluation/eval_end2end.py:1238-1242`

### 3.3 success / failure criteria 实际定义

| criterion | actual meaning in code | refs |
|---|---|---|
| `tool_executed` | 抓到 tool call；或没有 tool call 但响应文本明显交付了单工具 expected 结果 | `evaluation/eval_end2end.py:805-810` |
| `params_legal` | `expected_params` 与实际 arguments 做 subset match；若 arguments 不匹配，可从 tool result text 再补救匹配 | `evaluation/eval_end2end.py:797-802`, `559-585`; `evaluation/utils.py:205-253` |
| `result_has_data` | response payload 里有 chart/table/map/download/data；或响应文本看起来交付了 expected tool result | `evaluation/eval_end2end.py:812-815`, `359-374`, `507-527` |
| `requires_user_response` | `final_stage` 属于 needs-user 类；或 trace step type 是 clarification / input completion / negotiation；或文本像在追问用户 | `evaluation/eval_end2end.py:817-821`, `442-459` |
| `constraint_blocked` | 文本有 constraint block cue，或标准化 trace 记录了 `cross_constraint_violation` | `evaluation/eval_end2end.py:822-829`, `470-478` |
| `constraint_warning` | 标准化 trace 记录了 `cross_constraint_warning`，或文本有 warning cue | `evaluation/eval_end2end.py:830-833`, `461-467` |
| `trace_has_error` | trace steps 出现 `error` 字段或 `step_type=error` | `evaluation/eval_end2end.py:834-836` |
| `geometry_gated_halt_acceptable` | 仅当 benchmark 显式允许、expected chain 在 geometry-required tool 之前停下、file 没 geometry、文本同时含 emission 完成 + 几何/后续提示等证据时成立 | `evaluation/eval_end2end.py:679-730` |
| `tool_chain_match` | 默认必须 `actual == expected`；`user_revision` 允许 suffix match；geometry-gated success 也能放行 | `evaluation/eval_end2end.py:377-388`, `856-860` |

### 3.4 成功判定到底更偏路径、结果还是行为

结论：`路径正确` 权重最高，`行为约束正确` 次之，`结果正确` 更像补充证据。

理由：
- `success` 默认先取 `geometry_gated_success or tool_match`，`evaluation/eval_end2end.py:871`。
- 然后才对 `success_criteria` 中的布尔项做 AND，`evaluation/eval_end2end.py:873-876`。
- `result_has_data`、`requires_user_response`、`constraint_warning` 等并不能替代 `tool_match`；它们只是额外门槛。
- 唯一显著的 path-exception 是 geometry-gated multi-step 以及单工具文本交付 fallback。

所以：
- 不是纯 result-based eval。
- 也不是纯 behavior contract eval。
- 本质仍是 path-backed eval。

### 3.5 是否要求 expected_tool_chain / expected_params 完全匹配

#### `expected_tool_chain`

大体上是“要求完全匹配”，只有少数例外：
- exact chain match：默认要求 `actual == expected`，`evaluation/eval_end2end.py:377-380`
- `user_revision`：允许实际链最后一段等于 expected，`evaluation/eval_end2end.py:386-388`
- 单步文本结果 fallback：没有 tool call 但文本看起来像完成 expected tool，`evaluation/eval_end2end.py:805-810`
- geometry-gated multi-step 特判，`evaluation/eval_end2end.py:848-860`

#### `expected_params`

不是 strict full equality，而是：
- subset match
- alias-aware flexible match
- list subset match
- 可从 tool result text 中兜底

证据：
- `evaluation/utils.py:170-253`
- `evaluation/eval_end2end.py:559-585`

### 3.6 是否有对 clarification / refusal / waiting-for-user 的正确行为判定

有，但比较有限：
- `incomplete` / no-tool / clarification 类任务可以通过 `requires_user_response=true`, `tool_executed=false`, `result_has_data=false` 来判定正确等待用户，见 `evaluation/eval_end2end.py:817-821`, `838-847`。
- `constraint_blocked=true` 也能判正确拒绝，`evaluation/eval_end2end.py:822-829`。
- 但这些判定严重依赖：
  - `final_stage`
  - trace step type
  - 文本 cue heuristics

没有看到的内容：
- 没有单独的 “clarification quality” 分数。
- 没有单独的 “state continuity” / “artifact continuity” criteria。
- 没有自由格式文本的语义等价判定。

### 3.7 当前 eval 最绑定旧系统的 5 个位置

| rank | code position | why it is binding |
|---|---|---|
| 1 | `evaluation/eval_end2end.py:377-388` | 把 expected tool chain 当成主成功骨架；只允许少量白名单例外 |
| 2 | `evaluation/eval_end2end.py:995-1056` | router-mode 评估会主动向 agent 注入 scripted / synthetic follow-up；这不是自然用户对话 |
| 3 | `evaluation/eval_end2end.py:817-821`, `442-478` | clarification / block / warning 依赖 stage + trace + 文本 cue heuristics |
| 4 | `evaluation/eval_end2end.py:679-730` | geometry-gated 合法中止依赖 benchmark 明确标 flag；agent 若走更细粒度 continuity path，eval 未必认 |
| 5 | `evaluation/eval_end2end.py:1155-1157` + `evaluation/run_smoke_suite.py:55-64` | smoke e2e 仍是 legacy 10-sample tool-mode 且只支持单步，和真实 router benchmark 已分叉 |

### Section 3 小结

当前 eval 的核心假设是：
- expected path 可以被提前枚举
- clarification 可以被布尔 criteria + 文本 cue 识别
- bounded same-session follow-up 足以代表多轮
- 多数正确行为最终仍要落到 expected tool chain 上

## Section 4: Agent 入口、状态机、澄清链路、artifact 链路

### 4.1 Agent / router 主入口

| layer | file / symbol | fact |
|---|---|---|
| API route | `api/routes.py:210`, `:270` | `/chat` 和 `/chat/stream` 接收 `mode=full|naive|governed_v2` |
| Session facade | `api/session.py:83-110` | `Session.chat()` 根据 mode 调 `router` / `naive_router` / `governed_router` |
| Default API router object | `api/session.py:49-58` | `Session.router` 用 `build_router(..., router_mode="full")` 懒加载 |
| Governed wrapper entry | `core/governed_router.py:16-48` | `GovernedRouter.chat()` 在 `UnifiedRouter` 外包了一层 AO-aware memory / classifier |
| Router factory | `core/governed_router.py:354-365` | `build_router()` 只有 `governed_v2` 或 `router + ENABLE_GOVERNED_ROUTER=true` 才返回 GovernedRouter；否则返回 UnifiedRouter |
| Unified main entry | `core/router.py:2372-2390` | `UnifiedRouter.chat()` 根据 `enable_state_orchestration` 选择 `_run_state_loop()` 或 `_run_legacy_loop()` |

对 benchmark 很重要的一点：
- `eval_end2end.py` 在 router mode 里调用 `build_router(session_id=..., router_mode="router")`，`evaluation/eval_end2end.py:996`。
- 这意味着 benchmark router mode 在某些 env 下会实际测到 `GovernedRouter`，而 API 默认 `full` 模式并不走同一分支。

### 4.2 多轮澄清最相关的模块

| concern | file / symbol | fact |
|---|---|---|
| 通用状态容器 | `core/task_state.py:263-300` | `TaskState` 同时保存 `active_parameter_negotiation`, `active_input_completion`, `continuation`, `geometry_recovery_context`, `artifact_memory_state` 等 |
| 参数确认 request / parse | `core/parameter_negotiation.py:59-130`, `:293-423` | 规则式 request schema + deterministic reply parser；不是 LLM 解析 |
| 输入补全 request / parse | `core/input_completion.py:74-160`, `:372`, `:402`, `:565` | 也是结构化 request + deterministic reply parser；不是 LLM 解析 |
| Router 恢复 active negotiation | `core/router.py:10020-10023`, `10149-10169` | 每轮开头先把 live bundles 应用回 `TaskState`，再优先处理 active input_completion / active negotiation |
| Router 构建并激活 input completion | `core/router.py:6171-6450` | readiness 缺失字段会被转成结构化 input completion 流 |
| Router 构建并激活 parameter negotiation | `core/router.py:5937-6078`, `8374-8394` | 标准化低置信/失败会进入 parameter confirmation 流 |
| 标准化失败后的澄清入口 | `core/router.py:11022-11049` | executor 返回 `error_type="standardization"` 时，先尝试 parameter negotiation，否则落到普通 clarification |
| dispersion 专项 clarification | `core/router.py:1481-1540` | 多污染物扩散前先问目标 pollutant；这是单独链路，不走 generic clarification |
| 缺关键信息的 deterministic clarification | `core/router.py:2780-2804`, `10621-10636` | 仍保留通用 missing-input clarification 分支 |

结论：
- 当前“用户补充回答如何被消费”主要是规则式 parser，不是 LLM free-form consume。
- 系统不是只有一个 clarification bucket，而是至少分成：
  - parameter negotiation
  - input completion
  - dispersion pollutant clarification
  - generic clarification
  - file relationship clarification

最容易出现“用户说清楚了但系统接不上”的位置：
- active request 没有正确恢复进 `TaskState`
- 用户回复不命中 deterministic parser 规则
- reply 进入了错误的 clarification lane
- live state bundle / persisted state 与当前 stage 不一致

### 4.3 状态机相关代码

核心 enum：
- `TaskStage.INPUT_RECEIVED`
- `TaskStage.GROUNDED`
- `TaskStage.NEEDS_CLARIFICATION`
- `TaskStage.NEEDS_PARAMETER_CONFIRMATION`
- `TaskStage.NEEDS_INPUT_COMPLETION`
- `TaskStage.EXECUTING`
- `TaskStage.DONE`

证据：`core/task_state.py:47-54`

terminal states：
- `DONE`
- `NEEDS_CLARIFICATION`
- `NEEDS_PARAMETER_CONFIRMATION`
- `NEEDS_INPUT_COMPLETION`

证据：`core/task_state.py:436-442`

valid transition map：
- `INPUT_RECEIVED -> GROUNDED / NEEDS_* / DONE`
- `GROUNDED -> EXECUTING / NEEDS_* / DONE`
- `EXECUTING -> DONE / NEEDS_*`

证据：`core/task_state.py:420-433`

state loop：
- `UnifiedRouter._run_state_loop()` 用 `while not state.is_terminal()` 驱动，`core/router.py:2552-2592`
- `INPUT_RECEIVED` 走 `_state_handle_input()`，`core/router.py:2574-2579`
- response 在 `_state_build_response()` 根据 stage 统一出文本，`core/router.py:11193-11280`

多轮对话与状态恢复实现位置：
- runtime live bundles 初始化：`core/router.py:357-417`
- persisted state 序列化/恢复：`core/router.py:744-806`
- API session 层持久化 router state：`api/session.py:112-167`

### 4.4 artifact / dependency / geometry / context 链路

| concern | file / symbol | benchmark impact |
|---|---|---|
| semantic result store | `core/context_store.py:65-220` | multi-step benchmark 不是只靠“上一工具结果”，而是按 `result_type + scenario label` 取依赖结果 |
| canonical dependency graph | `core/tool_dependencies.py:30-136`, `181-260` | dispersion / hotspot / render 是否可继续执行，取决于 canonical result tokens 是否可用 |
| action readiness / repairability | `core/readiness.py:78-243`, `900-1285` | benchmark 中的 blocked / repairable / geometry gating 实际由 readiness layer 决定 |
| geometry recovery context | `core/geometry_recovery.py:88-165`, `168-317` | supporting spatial file、re-grounding、resume hint 都在这里建模 |
| residual reentry | `core/residual_reentry.py:101-182`, `247-260` | geometry recovery 后能否无缝回到 residual workflow，在这里建模 |
| artifact memory | `core/artifact_memory.py:32-67`, `198-249`, `619-625`, `734-859` | 已交付 artifact 会影响 follow-up bias、去重、可交付物推荐 |
| TaskState hooks | `core/task_state.py:276-299`, `447-584` | artifact / geometry / reentry / continuation 状态都进 `TaskState`，也会被 trace / persisted state 暴露 |

对 benchmark 中不同任务类型的影响：
- `multi_step`: 直接受 `context_store + tool_dependencies + readiness` 影响
- `multi_turn_clarification`: 直接受 `active_input_completion` / `active_parameter_negotiation` / `dispersion_clarification` 影响
- `constraint_violation`: 受 standardization records + readiness / preflight 影响
- `render/map` / spatial multi-step: 受 geometry support / geometry recovery / residual reentry 强影响
- follow-up artifact continuity: 受 `artifact_memory` 与 `context_store` 双重影响

### 4.5 对 benchmark 最核心的 10 个 Python 文件

| priority | file path | why it matters for benchmark |
|---|---|---|
| P0 | `evaluation/eval_end2end.py` | 当前 full benchmark 的执行器和判分器；所有 path/criteria 假设都在这里 |
| P0 | `core/router.py` | 真实被测主流程；state loop、clarification、continuation、execution、readiness 全在这里 |
| P0 | `core/task_state.py` | benchmark 未来若要对齐 agent 升级，必须先理解它实际维护的 state surface |
| P0 | `evaluation/pipeline_v2/common.py` | benchmark canonical schema、valid categories、default success criteria、ID 规则都在这里 |
| P0 | `evaluation/pipeline_v2/auto_validator.py` | pipeline_v2 如何把任务“规整成可评测 benchmark”的关键入口 |
| P0 | `evaluation/pipeline_v2/targeted_generator.py` | pipeline_v2 如何按 gap 反推候选 benchmark 的关键入口 |
| P1 | `core/readiness.py` | 决定哪些 action ready / blocked / repairable；很多 multi-step 语义都受它约束 |
| P1 | `core/context_store.py` | artifact / dependency / scenario continuity 的底层存储 |
| P1 | `core/input_completion.py` | “缺字段后继续执行”是否可测，核心取决于它的 request/parse contract |
| P1 | `core/parameter_negotiation.py` | “自然语言补参后稳定解析”是否可测，核心取决于它的 request/parse contract |

### Section 4 小结

如果后续要让 benchmark 和 agent 升级对齐，最不能忽视的模块是：
- `core/router.py`
- `core/task_state.py`
- `core/readiness.py`
- `core/context_store.py`
- `evaluation/eval_end2end.py`

原因很直接：
- benchmark 不是只在测工具名
- 它实际上在测 router state loop 能否在 clarification / readiness / dependency / geometry / artifact continuity 下继续推进

## Section 5: Benchmark 与未来 agent 升级的对齐风险

### 5.1 当前 benchmark 隐含的旧假设

#### A 类：未来 agent 升级后大概率会失效

| assumption | benchmark field dependency | evaluation dependency | pipeline dependency | why risky |
|---|---|---|---|---|
| `expected_tool_chain` 基本是唯一正确路径 | `expected_tool_chain` | `evaluation/eval_end2end.py:377-388`, `856-877` | `evaluation/pipeline_v2/targeted_generator.py:62-64` | 更强 agent 可能走不同但合理的 action ordering / implicit result reuse / richer continuation path |
| scripted `follow_up_messages` 足以代表多轮澄清 | `follow_up_messages` | `evaluation/eval_end2end.py:995-1056` | `phase0_adversarial` 数据本身 | 未来 agent 的多轮会更自然、更长、更上下文化，不一定是短槽位回答 |
| user revision 可以压缩成 1 次 follow-up + 最终 expected params | `follow_up_messages`, `expected_params`, `benchmark_metadata.expected_param_source` | `evaluation/eval_end2end.py:386-388`, `791-794` | `phase0_adversarial` 数据 | 更强 agent 可能处理中途多次修正、撤销、引用已有结果；当前 benchmark 只测最末一次修正 |
| blocked / clarification 任务不应执行任何工具 | `success_criteria.tool_executed=false` | `evaluation/eval_end2end.py:838-877` | `evaluation/pipeline_v2/common.py:294-307`, `auto_validator.py:231-247` | 更强 agent 可能先做 harmless grounding / file analysis / knowledge lookup 再追问用户 |

#### B 类：未来 agent 升级后需要弱化

| assumption | benchmark field dependency | evaluation dependency | pipeline dependency | why risky |
|---|---|---|---|---|
| expected params 必须是 canonical 标准值而不是自然补参原文 | `expected_params` | `evaluation/utils.py:205-253` | `evaluation/pipeline_v2/targeted_generator.py:35-40`, `auto_validator.py:172-208` | 未来重点会变成“用户自然语言补参后的稳定解析”；只看 canonical label 会遮蔽解析难度 |
| clarification / waiting-for-user 的正确性可由文本 cue heuristics 识别 | `success_criteria.requires_user_response` | `evaluation/eval_end2end.py:817-821`, `442-459` | `common.build_success_criteria()` | agent 文本一旦更自然，这种 cue-based 判定容易误伤 |
| geometry-gated 合法中止必须由显式 flag 白名单控制 | `success_criteria.geometry_gated_halt_acceptable` | `evaluation/eval_end2end.py:679-730` | `evaluation/pipeline_v2/common.py:304-311` | 未来可能要测更细的 geometry recovery / artifact continuity，而不是简单 stop-before-tool |
| router mode 注入 synthetic continuation prompt 不影响 benchmark 语义 | `expected_tool_chain`, `follow_up_messages` | `evaluation/eval_end2end.py:602-619`, `995-1056` | current eval harness | 这会把“真实对话鲁棒性”部分替换成“评测器引导下的受控继续执行” |

#### C 类：未来 agent 升级后仍然有效

| assumption | why still valid |
|---|---|
| canonical domain parameter legality 仍重要 | 排放任务仍需要落到合法的 vehicle/pollutant/season/road/meteorology 组合；`evaluation/utils.py:205-253`, `auto_validator.py:172-208` |
| cross-constraint coverage 仍重要 | `constraint_violation` 仍对应领域规则，不会因 agent 更自然就失效；`auto_validator.py:212-247` |
| file-grounding / fixture 多样性仍重要 | benchmark 仍需要区分 macro/micro/fuzzy/Chinese/geometry fixtures；`evaluation/eval_file_grounding.py:68-178` |

### 5.2 后续人工重点复查清单

#### 最值得人工打开阅读的 Python 文件

- `evaluation/eval_end2end.py`
- `core/router.py`
- `core/task_state.py`
- `core/readiness.py`
- `core/context_store.py`
- `core/input_completion.py`
- `core/parameter_negotiation.py`
- `evaluation/pipeline_v2/common.py`
- `evaluation/pipeline_v2/targeted_generator.py`
- `evaluation/pipeline_v2/auto_validator.py`

#### 最值得人工打开阅读的 benchmark 文件

- `evaluation/benchmarks/end2end_tasks.jsonl`
- `evaluation/pipeline_v2/phase0_premerge_benchmark_100.jsonl`
- `evaluation/pipeline_v2/phase0_adversarial_candidates.jsonl`
- `evaluation/pipeline_v2/phase0_reviewed_adversarial.jsonl`
- `evaluation/pipeline_v2/validated_manual.jsonl`
- `evaluation/end2end/samples.jsonl`
- `evaluation/continuation/samples.jsonl`

#### 最值得人工复查的日志 / 结果目录

- `evaluation/results/end2end_pipeline_v2_full/`
- `evaluation/results/end2end_full_v5_oasc_E/`
- `evaluation/results/end2end_full_v4_state/`
- `evaluation/results/end2end_full_v4_state_off/`
- `evaluation/results/end2end_preflight_v5_oasc/`
- `evaluation/results/end2end_full_v3_rescored_v2/`

## Appendix A: File Map

### Benchmark / sample data

- `evaluation/benchmarks/end2end_tasks.jsonl`
- `evaluation/benchmarks/standardization_benchmark.jsonl`
- `evaluation/end2end/samples.jsonl`
- `evaluation/normalization/samples.jsonl`
- `evaluation/file_tasks/samples.jsonl`
- `evaluation/continuation/samples.jsonl`
- `evaluation/human_compare/samples.csv`
- `evaluation/file_tasks/data/macro_direct.csv`
- `evaluation/file_tasks/data/macro_fuzzy.csv`
- `evaluation/file_tasks/data/macro_cn_fleet.csv`
- `evaluation/file_tasks/data/micro_time_speed.csv`
- `evaluation/file_tasks/data/micro_cn.csv`
- `evaluation/file_tasks/data/micro_full.csv`
- `evaluation/file_tasks/data/micro_speed_only.csv`
- `evaluation/file_tasks/data/micro_time_sec_speed_kmh.csv`

### Generated / merge intermediates

- `evaluation/generated/e2e_tasks_simple.jsonl`
- `evaluation/generated/e2e_tasks_parameter_ambiguous.jsonl`
- `evaluation/generated/e2e_tasks_multi_step.jsonl`
- `evaluation/generated/e2e_tasks_incomplete.jsonl`
- `evaluation/generated/e2e_tasks_constraint_violation.jsonl`
- `evaluation/generated/e2e_tasks_summary.json`
- `evaluation/generated/hard_cases_vehicle_type.jsonl`
- `evaluation/generated/hard_cases_pollutant.jsonl`
- `evaluation/generated/hard_cases_season.jsonl`
- `evaluation/generated/hard_cases_road_type.jsonl`
- `evaluation/generated/hard_cases_meteorology.jsonl`
- `evaluation/generated/hard_cases_stability_class.jsonl`
- `evaluation/generated/hard_cases_summary.json`
- `evaluation/generated_backup_smoke/`

### Pipeline v2 data + scripts

- `evaluation/pipeline_v2/common.py`
- `evaluation/pipeline_v2/coverage_audit.py`
- `evaluation/pipeline_v2/targeted_generator.py`
- `evaluation/pipeline_v2/auto_validator.py`
- `evaluation/pipeline_v2/review_cli.py`
- `evaluation/pipeline_v2/regression_check.py`
- `evaluation/pipeline_v2/merge_to_benchmark.py`
- `evaluation/pipeline_v2/curate_existing_benchmark.py`
- `evaluation/pipeline_v2/run_pipeline.sh`
- `evaluation/pipeline_v2/gap_report.json`
- `evaluation/pipeline_v2/final_gap_report.json`
- `evaluation/pipeline_v2/phase0_coverage_report.json`
- `evaluation/pipeline_v2/manual_candidates.jsonl`
- `evaluation/pipeline_v2/validated_manual.jsonl`
- `evaluation/pipeline_v2/phase0_premerge_benchmark_100.jsonl`
- `evaluation/pipeline_v2/phase0_adversarial_candidates.jsonl`
- `evaluation/pipeline_v2/phase0_validated_adversarial.jsonl`
- `evaluation/pipeline_v2/phase0_reviewed_adversarial.jsonl`

### Evaluation scripts

- `evaluation/README.md`
- `evaluation/utils.py`
- `evaluation/eval_end2end.py`
- `evaluation/eval_ablation.py`
- `evaluation/eval_standardization_benchmark.py`
- `evaluation/eval_standardization_ablation.py`
- `evaluation/eval_normalization.py`
- `evaluation/eval_file_grounding.py`
- `evaluation/eval_continuation.py`
- `evaluation/run_smoke_suite.py`
- `evaluation/run_e2e_stable.py`
- `evaluation/run_health.py`
- `evaluation/run_oasc_matrix.py`
- `evaluation/run_phase1_5_benchmark.py`
- `evaluation/build_benchmark.py`
- `evaluation/context_extractor.py`
- `evaluation/llm_generator.py`
- `evaluation/generate_e2e_tasks.py`
- `evaluation/merge_generated_e2e_tasks.py`
- `evaluation/generate_hard_cases.py`
- `evaluation/merge_generated_cases.py`

### Agent / router / state / continuity

- `api/routes.py`
- `api/session.py`
- `core/governed_router.py`
- `core/router.py`
- `core/task_state.py`
- `core/readiness.py`
- `core/context_store.py`
- `core/tool_dependencies.py`
- `core/input_completion.py`
- `core/parameter_negotiation.py`
- `core/geometry_recovery.py`
- `core/residual_reentry.py`
- `core/file_relationship_resolution.py`
- `core/intent_resolution.py`
- `core/supplemental_merge.py`
- `core/summary_delivery.py`
- `core/plan.py`
- `core/plan_repair.py`
- `core/workflow_templates.py`
- `core/memory.py`
- `core/assembler.py`
- `core/executor.py`
- `core/trace.py`
- `core/naive_router.py`
- `core/analytical_objective.py`
- `core/ao_classifier.py`
- `core/ao_manager.py`
- `services/chat_session_service.py`
- `services/artifact_summary.py`
- `tools/file_analyzer.py`
- `config/tool_contracts.yaml`
- `config/unified_mappings.yaml`
- `config/cross_constraints.yaml`

## Appendix B: Open Questions

1. `phase0_adversarial_candidates.jsonl` 的精确生成方式是什么？仓库里没有对应生成脚本，只能从数据里的 `generation_flow` / `human_review` 元数据确认其经过人工审阅；原始 authoring path 是 `UNKNOWN`。
2. 当前 `evaluation/benchmarks/end2end_tasks.jsonl` 究竟是由 `phase0_reviewed_adversarial.jsonl` 还是 `phase0_validated_adversarial.jsonl` merge 进来的？按内容都能解释，最终写入路径在仓库内没有单独记录。
3. 用户是否“最近上传”了某个 benchmark 文件？仓库里没有 upload-specific 入口或命名，结论是 `UNKNOWN`。
4. `pipeline_v2/regression_check.py` 的结果是否真的参与人工筛选或 merge 决策？脚本会生成 `regression_report.json`，但 `merge_to_benchmark.py` 本身不读取该报告；人工是否据此筛选，仓库内无法确认。
5. 哪个 `evaluation/results/` 目录才是当前团队认定的“official baseline”结果目录？仓库里存在多个历史目录，但没有唯一指针文件。
