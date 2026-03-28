# P0G File Analysis LLM Fallback Report

## 1. Summary

本轮实现的是一个 state-loop 内的 file grounding 增强层，而不是重写 `FileAnalyzerTool`。

最终落地的是一条明确的混合控制流：

1. `tools/file_analyzer.py` 继续先做规则分析。
2. `core/router.py::_state_handle_input()` 在 file grounding 节点拿到规则结果后，调用正式 trigger helper 判断是否需要 fallback。
3. 只有低置信度、列映射不足、ZIP/GIS 结构复杂、或非标准列名风险较高时，才调用 `llm.chat_json()` 做 bounded semantic fallback。
4. fallback 输出经过 deterministic schema validation 和 merge。
5. 最终结果仍然写回 canonical file analysis dict，并继续走既有 `FileContext -> assembler -> planning / continuation / tool selection` 路径。

目标已达到：

- rule-first file grounding 仍然是主路径
- low-confidence cases 会触发 bounded LLM fallback
- fallback 输出保持结构化和 canonical
- merge 不会随意覆盖高置信度规则映射
- ZIP/GIS 至少支持候选主表/属性表语义兜底
- 全程有 trace、测试和安全回退

## 2. Files Changed

### `core/file_analysis_fallback.py`
- 新增正式 fallback IR 和 deterministic helper。
- 定义了：
  - `FallbackReason`
  - `FileAnalysisFallbackDecision`
  - `LLMFileAnalysisResult`
  - `MergedFileAnalysisResult`
- 提供了：
  - `should_use_llm_fallback(...)`
  - `build_file_analysis_fallback_payload(...)`
  - `parse_llm_file_analysis_result(...)`
  - `merge_rule_and_fallback_analysis(...)`

### `tools/file_analyzer.py`
- 保留原有规则分析主路径。
- 为 tabular / shapefile / ZIP 场景补充 fallback 所需 metadata：
  - `format`
  - `column_mapping`
  - `unresolved_columns`
  - `analysis_strategy`
  - `fallback_used`
  - `selected_primary_table`
  - `zip_contents`
  - `candidate_tables`
- Shapefile 分析不再只给固定 `macro_emission`，而是也输出规则映射、置信度、evidence 和 sample rows。

### `core/router.py`
- 在 `_state_handle_input()` 的 file grounding 节点接入 fallback。
- 新增：
  - `FILE_ANALYSIS_FALLBACK_PROMPT`
  - `_build_file_analysis_fallback_messages(...)`
  - `_maybe_apply_file_analysis_fallback(...)`
- 控制流是：
  - 先 `_analyze_file()`
  - 再 fallback decision / optional `chat_json()` / merge / trace
  - 再 `state.update_file_context(...)`

### `core/trace.py`
- 新增 trace step types：
  - `FILE_ANALYSIS_FALLBACK_TRIGGERED`
  - `FILE_ANALYSIS_FALLBACK_APPLIED`
  - `FILE_ANALYSIS_FALLBACK_SKIPPED`
  - `FILE_ANALYSIS_FALLBACK_FAILED`
- 扩展了 friendly formatter，确保 file grounding fallback 可以直接作为论文 case artifact 展示。

### `config.py`
- 新增独立开关和参数：
  - `ENABLE_FILE_ANALYSIS_LLM_FALLBACK`
  - `FILE_ANALYSIS_FALLBACK_CONFIDENCE_THRESHOLD`
  - `FILE_ANALYSIS_FALLBACK_MAX_SAMPLE_ROWS`
  - `FILE_ANALYSIS_FALLBACK_MAX_COLUMNS`
  - `FILE_ANALYSIS_FALLBACK_ALLOW_ZIP_TABLE_SELECTION`

### Tests
- `tests/test_file_analysis_fallback.py`
- `tests/test_router_state_loop.py`
- `tests/test_trace.py`
- `tests/test_config.py`

## 3. Fallback Design

### Trigger Policy

fallback trigger 不是“规则失败就调 LLM”，而是正式的 decision helper：

- `should_use_llm_fallback(...)`

当前 trigger 原因受限于以下集合：

- `low_task_confidence`
- `task_type_unknown`
- `insufficient_column_mapping`
- `zip_gis_structure_complex`
- `nonstandard_column_names`

典型触发条件：

- `task_type == "unknown"`
- `confidence < FILE_ANALYSIS_FALLBACK_CONFIDENCE_THRESHOLD` 且规则映射不完整
- 关键字段映射不足，`macro_has_required / micro_has_required` 未满足
- ZIP 包中有多个候选主表 / Shapefile component，规则结果仍偏保守
- unresolved columns 大量表现为拼音/缩写/内部简称

明确不触发：

- 标准 CSV/Excel 且规则高置信度命中
- required fields 已由规则稳定识别
- 仅仅因为“可以调用 LLM”

### Fallback Schema

LLM fallback 不返回自由文本，而是 bounded JSON，对应 `LLMFileAnalysisResult`：

- `task_type`
- `confidence`
- `column_mapping`，方向固定为 `{canonical_field: source_column}`
- `reasoning_summary`
- `evidence`
- `unresolved_columns`
- `candidate_task_types`
- `selected_primary_table`

canonical task type 仍然只允许：

- `macro_emission`
- `micro_emission`
- `unknown`

canonical semantic fields 仍然只允许来自标准化器当前 vocabulary：

- macro: `link_id`, `link_length_km`, `traffic_flow_vph`, `avg_speed_kph`
- micro: `time`, `speed_kph`, `acceleration_mps2`, `grade_pct`

### Merge Policy

merge 由 `merge_rule_and_fallback_analysis(...)` 负责，策略是受控的：

1. 规则高置信度时直接保留规则结果。
2. fallback 合法且足够可信时才进入 merge。
3. merge 优先保留规则已经稳定识别的字段。
4. fallback 只补 unresolved canonical fields，或在规则 `task_type == unknown` 时提升 task type。
5. fallback 置信度过低时，不覆盖规则结果，router 记录 `FILE_ANALYSIS_FALLBACK_FAILED` 并保留 rule result。

这个设计支持论文里的“规则优先 + LLM 兜底”叙事，因为：

- 规则层仍然先裁决标准 case
- LLM 只在不确定时参与
- 参与结果仍然受 canonical schema 和 deterministic merge 约束
- fallback 不是 primary analyzer，而是 bounded semantic repair layer for grounding

## 4. Router / File Grounding Integration

### 接入节点

fallback 接在：

- `core/router.py::_state_handle_input()`

具体顺序是：

1. 检查文件上传和 file grounding cache
2. 调用 `_analyze_file(...)` 得到 rule analysis
3. 调用 `_maybe_apply_file_analysis_fallback(...)`
4. 将最终 analysis 写入：
   - `state.update_file_context(...)`
   - `state._file_analysis_cache`
5. 继续既有：
   - `assembler.assemble(...)`
   - planning
   - continuation
   - tool selection

### 最终结果如何进入 `FileContext`

本轮没有改后续模块接口。最终 file grounding 结果仍然是一个 canonical analysis dict，继续被：

- `TaskState.update_file_context(...)`
- `router._build_state_file_context(...)`
- `memory.update(..., file_analysis=...)`

消费。

另外，router 仍然通过 `_file_analysis_cache` 保留 richer metadata，所以像：

- `fallback_used`
- `file_analysis_fallback_decision`
- `selected_primary_table`

这些额外字段不会破坏既有 `FileContext` 主字段，但在 assembler 和 memory surface 上仍可见。

### 为什么后续 planning / continuation 不需要重写

因为本轮没有改变 file grounding 的输出协议，只提高了它的鲁棒性。  
后续模块仍然看到同样的核心字段：

- `task_type`
- `confidence`
- `column_mapping`
- `sample_rows`
- `columns`
- `evidence`

区别只是这些字段在低置信度 case 上更稳，不再完全依赖规则列名匹配。

## 5. ZIP/GIS Handling

### 这轮支持了什么

这一轮对 ZIP/GIS 的支持是轻量但正式的：

- ZIP 场景会暴露：
  - `zip_contents`
  - `candidate_tables`
  - `selected_primary_table`
- Shapefile 场景会暴露：
  - `geometry_types`
  - attribute columns
  - sample rows
  - rule mappings / unresolved columns
- fallback prompt 能看到 ZIP contents 和 candidate tables，从而给出：
  - `selected_primary_table`
  - semantic field mapping
  - bounded task type guess

### 明确不支持什么

这一轮没有实现：

- general GIS semantic agent
- geometry-level open-ended inference
- 多表深度探索和自动切换执行表
- 基于 fallback 自动重读另一张候选表

### 为什么这样足够服务论文主线

因为这一轮论文要证明的是：

- input grounding 也遵循 rule-first + bounded LLM fallback
- ZIP/GIS 非标准结构不会直接把系统推入“全靠 LLM 自由理解”

当前支持的“候选主表 + 字段语义 fallback”已经足以支撑这一点，不需要把 scope 扩成 GIS agent。

## 6. Trace Extensions

新增 trace 类型：

- `FILE_ANALYSIS_FALLBACK_TRIGGERED`
- `FILE_ANALYSIS_FALLBACK_APPLIED`
- `FILE_ANALYSIS_FALLBACK_SKIPPED`
- `FILE_ANALYSIS_FALLBACK_FAILED`

### 写入路径

全部在 `core/router.py::_maybe_apply_file_analysis_fallback(...)` 中写入：

- `TRIGGERED`
  - 记录 rule confidence、trigger reasons、unresolved columns、candidate tables
- `APPLIED`
  - 记录 merge 后的 `task_type`、`confidence`、`column_mapping`、`selected_primary_table`
- `SKIPPED`
  - 记录为什么 rule analysis 足够强，不需要 fallback
- `FAILED`
  - 记录 LLM call failure、schema validation failure、或 low-confidence fallback rejected

### 为什么这些 trace 对论文有用

这些 trace 让 file grounding fallback 不再只是“prompt 技巧”，而是一个正式可审计层：

- 可以展示什么时候 fallback 被触发
- 可以展示 fallback 给出了什么 bounded结构化结果
- 可以展示最终是 merge 了，还是安全回退到规则结果
- 可以直接作为 case-study / ablation artifact 截图

## 7. Tests

### 运行的测试

我跑了：

```bash
pytest -q tests/test_file_analysis_fallback.py tests/test_trace.py tests/test_config.py
python -m py_compile core/file_analysis_fallback.py tools/file_analyzer.py core/router.py core/trace.py config.py
pytest -q tests/test_router_state_loop.py
pytest -q tests/test_file_analysis_fallback.py tests/test_file_grounding_enhanced.py tests/test_router_state_loop.py tests/test_trace.py tests/test_config.py
```

### 结果

- `33 passed, 4 warnings`
- `28 passed`
- `79 passed, 4 warnings`

warnings 都是现有 FastAPI `on_event` deprecation warning，不是本轮引入。

### 新增覆盖的关键行为

`tests/test_file_analysis_fallback.py`

- 标准高置信度文件不触发 fallback
- 非标准缩写列会触发 fallback
- merge 保留规则已可靠映射的字段
- 非法 fallback 结果会被 reject，不覆盖规则结果
- ZIP candidate table selection 在 bounded schema 内可用

`tests/test_router_state_loop.py`

- 低置信度 file grounding 会在 state loop 中触发 fallback
- fallback applied 后，最终 `file_context` 进入 assembler 的是 merged canonical result
- fallback 失败不会让 router 崩溃，而是安全回退并走既有保守路径

`tests/test_trace.py`

- 四类 file analysis fallback trace 的 friendly formatting 都可读

`tests/test_config.py`

- 新增 flag 和阈值默认值覆盖

## 8. Known Limitations

- rule-first remains the primary path
- fallback only applies to low-confidence cases
- no general GIS semantic agent
- no new workflow execution capability was introduced
- no persistence / scheduler / auto-completion was added
- fallback still depends on bounded prompt/schema quality

另外还有一个代码现实上的限制需要明确：

- ZIP fallback 目前能帮助判断 `selected_primary_table`，但不会因为 LLM 选择了另一张候选表就自动重读并替换整个底层数据分析对象。这是刻意保守的边界，否则会把本轮拉向 general table-selection executor。

## 9. Suggested Next Step

最推荐的下一步是：

### 建一套 file grounding evaluation harness

理由很直接：

- continuation 侧已经有 evaluation harness
- file grounding fallback 现在已经有 formal trigger / merge / trace
- 最自然的论文下一步就是把它也做成 rule-only vs fallback-enabled 的受控评测

这个方向能直接回答：

- fallback 到底提升了哪些低置信度 case
- ZIP/GIS / 非标准列名 / 拼音缩写场景的 gain 在哪里
- trigger policy 是否足够保守
- merge 是否真的避免了破坏高置信度规则映射

这比继续堆新 workflow 功能更符合当前代码现实，也更有利于论文主实验。
