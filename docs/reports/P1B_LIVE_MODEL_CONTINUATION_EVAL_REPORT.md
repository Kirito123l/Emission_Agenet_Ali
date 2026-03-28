# P1B: Live-Model Continuation Evaluation Mode

## 1. Summary

本轮没有新增 workflow 能力，也没有改 continuation / repair / dependency enforcement 的语义。实现重点是把现有 continuation evaluation harness 扩展成双 execution mode：

- `deterministic`
- `live_model`

两种 mode 现在共用同一套：

- case schema
- category grouping
- per-case result schema
- metrics surface
- Markdown summary structure

其中 `live_model` mode 复用真实的 continuation + first tool-selection 主路径，仍然通过 `core/router.py::_state_handle_input()` 完成：

- residual continuation decision
- continuation guidance injection
- first tool selection

最终目标已达到：continuation prompt variants 现在可以在同一 protocol 下分别跑 deterministic 和 live-model backend，并输出 mode-aware comparison artifacts，适合论文主实验与消融对照。

## 2. Files Changed

- `evaluation/eval_continuation.py`
  - 这是本轮核心文件。
  - 新增 `ContinuationExecutionMode`，把 case execution 拆成 `deterministic` 和 `live_model` 两条 backend。
  - 新增 `LiveModelContinuationLLM`，用受控 `temperature/seed` 包装真实 LLM client。
  - 新增 `_run_case_live_model()`、mode-aware aggregation、mode-aware Markdown/JSON comparison、failure recording、CLI filtering。
  - 保留单 mode 时的 legacy output path，避免破坏现有 deterministic 使用方式。

- `services/llm_client.py`
  - 给 async `chat()` / `chat_with_tools()` / `chat_json()` 增加可选 `seed` 参数。
  - 这样 live-model eval mode 可以在不改 router 主逻辑的前提下，尽量用更确定性的模型设置执行 first-step continuation evaluation。

- `tests/test_continuation_eval.py`
  - 扩展 mode-aware 测试。
  - 覆盖 deterministic/live_model mode switching、schema compatibility、mode comparison、live backend path、trace extraction、failure recording、no-tool/direct-answer failure。

- `evaluation/README.md`
  - 补充 continuation evaluation 的 mode-aware 使用方式、CLI 示例和输出目录结构。

- `P1B_LIVE_MODEL_CONTINUATION_EVAL_REPORT.md`
  - 本轮实现报告。

## 3. Execution Mode Design

本轮坚持 `same protocol / same metrics / same outputs`，没有新建平行 runner。

`evaluation/eval_continuation.py` 现在以 `execution_mode` 为正式维度：

- `ContinuationExecutionMode.DETERMINISTIC`
- `ContinuationExecutionMode.LIVE_MODEL`

实现方式是：

- 共用 `ContinuationEvalCase`
- 共用 `_collect_case_result()`
- 共用 `_aggregate_variant_metrics()`
- 共用 mode-aware comparison 渲染逻辑
- 只在 `_run_case()` 内部分流到：
  - `_run_case_deterministic()`
  - `_run_case_live_model()`

这样 deterministic 和 live-model 之间只有 execution backend 不同，评测协议本身不分叉。

## 4. Live-Model Backend

live-model mode 没有伪造 continuation path，而是走真实 state-loop 首步：

1. 构造 live residual continuation bundle
2. 构造 `TaskState`
3. 通过 `_build_router_for_case(...)` 注入 live-model LLM backend
4. 真实调用 `await router._state_handle_input(state, trace_obj=...)`
5. 从真实 state / trace 中提取：
   - continuation decided / skipped
   - first selected tool
   - trace markers
   - blocked-after-continuation
   - failure type / failure message

本轮故意只聚焦 first-step continuation behavior，而没有把 live-model mode 扩成 full workflow benchmark。原因是当前论文目标仍然是：

- continuation decision quality
- prompt-variant effect
- first-step next-tool alignment
- early blocked / override behavior

如果把 live mode 扩成多步 E2E benchmark，会把问题空间从 continuation evaluation 漂移到 full workflow execution benchmarking，这会削弱论文叙事聚焦。

## 5. Mode-Aware Outputs

mode-aware 结果目录现在是：

```text
<output_dir>/
  deterministic/
    <variant>/
      continuation_case_results.jsonl
      continuation_metrics.json
      continuation_summary.md
    continuation_variant_comparison.json
    continuation_variant_comparison.md
  live_model/
    <variant>/
      continuation_case_results.jsonl
      continuation_metrics.json
      continuation_summary.md
    continuation_variant_comparison.json
    continuation_variant_comparison.md
  continuation_mode_comparison.json
  continuation_mode_comparison.md
```

同时，为了不破坏现有 deterministic harness 使用方式，单 mode 运行时仍会保留 legacy 输出路径：

```text
<output_dir>/<variant>/...
```

per-case result 现在统一包含：

- `case_id`
- `category`
- `execution_mode`
- `prompt_variant`
- `expected_continuation_decision`
- `actual_continuation_decision`
- `expected_new_task_override`
- `actual_new_task_override`
- `expected_next_tool`
- `actual_next_tool`
- `next_step_alignment`
- `blocked_after_continuation`
- `trace_ok`
- `pass`
- `failure_type`
- `failure_message`
- `notes`

## 6. Metrics and Comparison

本轮没有推翻现有 metrics surface，继续沿用：

- `continuation_decision_accuracy`
- `new_task_override_precision`
- `safe_continuation_recall`
- `next_step_alignment_rate`
- `blocked_after_continuation_rate`
- `trace_completeness`
- `repair_aware_continuation_success_rate`

在此基础上，仅补充了 mode-friendly 失败聚合：

- `failure_count`
- `failure_counts`

聚合层现在支持：

- overall by variant
- category-level metrics
- variant comparison inside each execution mode
- deterministic vs live-model comparison across the same variant

`continuation_mode_comparison.json` / `.md` 额外给出：

- 同 variant 下 deterministic vs live-model 的 metric gaps
- category-level largest gap summary
- 当前最推荐的 live-model variant

这些 gap 对论文有意义，因为它们能把以下问题从“定性印象”变成“结构化对比”：

- mock-friendly trend 是否能迁移到 live-model mode
- 哪些 category 对真实模型更敏感
- 哪些 prompt variant 在 live-model 条件下更稳

## 7. Failure Handling

live-model mode 不再假设每个 case 都会像 deterministic backend 那样干净收敛。

per-case results 现在会正式记录：

- `llm_backend_init_failure`
- `llm_call_failure`
- `timeout`
- `runtime_failure`
- `unexpected_direct_answer`
- `no_tool_selected`
- `trace_missing`

记录方式不是脚本崩溃，而是：

- 继续生成该 case 的 result row
- 在 `failure_type` / `failure_message` / `mode_notes` 中记录失败细节
- 在 aggregate metrics 中累计 `failure_count` / `failure_counts`

这对论文实验很重要，因为 live-model runs 的失败来源必须可区分：

- framework failure
- model instability
- runner failure
- trace incompleteness

如果这些都混在一起，后续主实验结论会很难解释。

## 8. Tests

本轮运行了以下测试：

- `pytest -q tests/test_continuation_eval.py`
- `pytest -q tests/test_continuation_eval.py tests/test_router_state_loop.py tests/test_task_state.py tests/test_trace.py tests/test_config.py`

结果：

- `tests/test_continuation_eval.py`: `8 passed`
- combined regression suite: `71 passed, 4 warnings`

另外运行了两个 smoke commands：

- `python scripts/eval/run_continuation_eval.py --mode deterministic --variant balanced_repair_aware --max-cases 4 --output-dir /tmp/p1b_continuation_eval_det_smoke`
- `python scripts/eval/run_continuation_eval.py --mode-set deterministic,live_model --variant balanced_repair_aware --max-cases 2 --dry-run --output-dir /tmp/p1b_continuation_eval_dry_run`

还补跑了一个非 pytest 的 mode-comparison smoke，使用 fake live backend 调 `run_continuation_evaluation(...)`：

- deterministic 和 live_model 两个 mode 都成功产出
- `recommended_live_model_variant = balanced_repair_aware`
- fake live backend smoke 中：
  - `deterministic_alignment = 0.5`
  - `live_alignment = 1.0`
  - `live_failure_count = 0`

新增覆盖的关键行为包括：

- execution mode switching
- deterministic/live-model per-case schema compatibility
- mode-aware comparison output generation
- live backend 真实经过 `_state_handle_input()` 路径
- first selected tool extraction
- continuation trace extraction
- live-model failure recording
- live-model direct-answer / no-tool failure recording
- legacy deterministic output path compatibility

## 9. Known Limitations

- live-model mode still focuses on first-step continuation behavior
- not yet a full end-to-end workflow benchmark
- no new workflow capabilities were introduced
- still no persistence / scheduler / auto-completion
- live-model results may still have stochasticity, even under constrained settings
- this round does not change continuation policy semantics; it only makes them measurable under a second backend
- current live-model test coverage in repo is mock-backed; I did not run a real external-model benchmark in this environment

## 10. Suggested Next Step

最自然的下一步是做一轮 **small-budget real-model continuation sweep**：

- 固定现有 case schema
- 固定现有 metric surface
- 只选 `balanced_repair_aware` + 少量对照 variant
- 在真实模型上按 category 做小样本批跑
- 生成 deterministic vs live-model 的首版论文表格

这是当前代码现实下最直接把评测 harness 推向 paper-grade evidence 的一步，而且不会把系统拉向新的 workflow 功能开发。
