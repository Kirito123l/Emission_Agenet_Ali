# P0H Workflow Templates Report

## 1. Summary

本轮实现了一个轻量的 `workflow template prior` 层，位置严格收束在 state loop 的 planning 前：

- `file grounding` 结果现在可以映射到有限的领域 workflow templates
- template recommendation 是规则优先、可解释、可 trace 的
- selected template 只作为 planner 的结构化 prior 注入，不直接生成最终 execution plan，也不接管 execution
- residual continuation / repair 路径仍然优先，不会被 fresh template recommendation 覆盖

目标已达到：系统现在形成了 `file-driven grounding -> workflow prior recommendation -> explicit planning` 这条更完整的方法链。

## 2. Files Changed

- [core/workflow_templates.py](/home/kirito/Agent1/emission_agent/core/workflow_templates.py)
  - 新增正式 template IR：`WorkflowTemplate`、`WorkflowTemplateStep`、`TemplateRecommendation`、`TemplateSelectionResult`
  - 定义有限模板集
  - 实现规则优先的 `recommend_workflow_templates(...)` 和 `select_primary_template(...)`

- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)
  - 在 `_state_handle_input()` 中接入 template recommendation
  - continuation 生效时显式 skip fresh template recommendation
  - 在 `_generate_execution_plan()` 的 planner payload 中注入 `workflow_template_prior`
  - 为 trace 补充 recommendation / selection / injection / skip 记录

- [core/task_state.py](/home/kirito/Agent1/emission_agent/core/task_state.py)
  - 增加 `recommended_workflow_templates`
  - 增加 `selected_workflow_template`
  - 增加 `template_prior_used`
  - 增加 `template_selection_reason`
  - 扩展 `to_dict()` 以暴露模板 prior 可观察状态

- [core/trace.py](/home/kirito/Agent1/emission_agent/core/trace.py)
  - 新增 template trace 类型
  - 扩展 formatter，保证 trace 对调试和论文 artifact 可读

- [config.py](/home/kirito/Agent1/emission_agent/config.py)
  - 新增 `ENABLE_WORKFLOW_TEMPLATES`
  - 新增 `WORKFLOW_TEMPLATE_MAX_RECOMMENDATIONS`
  - 新增 `WORKFLOW_TEMPLATE_MIN_CONFIDENCE`

- [tests/test_workflow_templates.py](/home/kirito/Agent1/emission_agent/tests/test_workflow_templates.py)
  - 新增模板推荐专项测试

- [tests/test_router_state_loop.py](/home/kirito/Agent1/emission_agent/tests/test_router_state_loop.py)
  - 覆盖 template prior 注入时序
  - 覆盖 continuation 下 skip template recommendation
  - 覆盖 parameter confirmation continuation 下 skip 行为

- [tests/test_task_state.py](/home/kirito/Agent1/emission_agent/tests/test_task_state.py)
  - 覆盖模板推荐和选中结果的序列化可观察性

- [tests/test_trace.py](/home/kirito/Agent1/emission_agent/tests/test_trace.py)
  - 覆盖新的 template trace formatter

- [tests/test_config.py](/home/kirito/Agent1/emission_agent/tests/test_config.py)
  - 覆盖 workflow template config 默认值

## 3. Template Design

本轮只定义了少量高价值模板，避免走向“大而全模板库”：

- `macro_emission_baseline`
  - `calculate_macro_emission`
  - optional `render_spatial_map`
  - 服务最小宏观排放工作流

- `macro_spatial_chain`
  - `calculate_macro_emission -> calculate_dispersion -> analyze_hotspots -> render_spatial_map`
  - 服务带空间上下文的排放-扩散-热点链

- `micro_emission_baseline`
  - `calculate_micro_emission`
  - 服务微观逐秒计算主线

- `macro_render_focus`
  - `calculate_macro_emission -> render_spatial_map`
  - 服务地图/渲染意图更强的宏观场景

- `micro_render_focus`
  - `calculate_micro_emission -> render_spatial_map`
  - 仅在 micro grounding 明确且存在空间上下文、同时用户有显式 render intent 时才可能被选中

只选这些模板，是因为它们直接对应当前论文主线里的核心 workflow regularities：宏观排放、微观排放、空间链、渲染导向。再扩更多边缘模板会削弱“bounded prior space”的叙事。

## 4. Recommendation Logic

模板推荐读取的 grounding signals 主要来自 file analysis：

- `task_type`
- `confidence`
- `missing_field_diagnostics.status`
- `dataset_roles`
- `dataset_role_summary`
- `selected_primary_table`
- `spatial_metadata`

同时只读取很少的用户意图信号：

- render / map / visualization
- dispersion / concentration
- hotspot

规则要点：

- `task_type` 是主信号
  - `macro_emission` 只进宏观模板候选
  - `micro_emission` 只进微观模板候选
  - `unknown` 直接 skip

- `missing_field_diagnostics.status` 是 gating signal
  - `complete`：正常提高推荐置信度
  - `partial`：仍可推荐，但在 `unmet_requirements` 中留下缺口
  - `insufficient`：可保留 recommendation 作为诊断信息，但 `is_applicable=False`，不会被选为 template prior

- `spatial_ready` 决定空间链/渲染导向模板是否进入候选

- `render_intent` 只用于 render-focus 模板，不会把所有 macro/micro 文件都推成渲染导向

这仍然是规则优先逻辑，不是 planner rewrite。planner 依然通过 `chat_json()` 生成正式 `ExecutionPlan`；模板只提供 bounded starting point。

## 5. Router / Planning Integration

集成点在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py) 的 `_state_handle_input()`：

1. 文件 grounding 完成
2. continuation / parameter confirmation 先按现有逻辑处理
3. 只有在：
   - `state.file_context.grounded == True`
   - 且不是 residual continuation authoritative path
   时，才做 template recommendation
4. recommendation 和 selection 写 trace
5. selected template prior 通过 `_generate_execution_plan()` 的 `planner_payload["workflow_template_prior"]` 注入 planning context
6. planner 再生成正式 `ExecutionPlan`

执行层没有改：

- 没有直接执行 template skeleton
- 没有从 template 自动补全缺失步骤
- 没有改 execution / repair / continuation 主语义

为了避免 taxonomy 膨胀，本轮没有额外引入 “template-plan deviation” 新 trace type；如果 planner 和 selected template 存在偏离，当前会在 `PLAN_CREATED` 的 reasoning 中附带对齐摘要。

## 6. Trace Extensions

新增 trace 类型：

- `WORKFLOW_TEMPLATE_RECOMMENDED`
  - 记录候选模板、confidence、matched signals、unmet requirements

- `WORKFLOW_TEMPLATE_SELECTED`
  - 记录 selected template id 和 selection reason

- `WORKFLOW_TEMPLATE_INJECTED`
  - 记录注入 planning payload 的 prior 摘要

- `WORKFLOW_TEMPLATE_SKIPPED`
  - 记录未推荐/未使用的原因
  - 典型原因包括：
    - `task_type=unknown`
    - file readiness 不足
    - residual continuation 仍然 authoritative

这些 trace 对论文有价值，因为它们把 “template prior exists” 变成了可审计 artifact，而不是 prompt 层隐含行为。

## 7. Tests

本轮运行了：

- `python -m py_compile core/workflow_templates.py core/router.py core/task_state.py core/trace.py config.py tests/test_workflow_templates.py tests/test_router_state_loop.py tests/test_task_state.py tests/test_trace.py tests/test_config.py`
- `pytest -q tests/test_workflow_templates.py tests/test_router_state_loop.py tests/test_task_state.py tests/test_trace.py tests/test_config.py`
- `pytest -q tests/test_file_grounding_enhanced.py`

结果：

- `86 passed, 4 warnings`
- `18 passed`
- `py_compile` 通过

关键新增覆盖：

- macro / micro / spatial-chain / insufficient / unknown 的模板推荐逻辑
- template prior 在 planning 前注入
- continuation path 不覆盖 residual workflow
- parameter confirmation continuation 不触发 fresh template recommendation
- template trace formatter
- TaskState 对 template recommendation / selection 的可观察性

## 8. Known Limitations

- templates are lightweight priors, not rigid execution plans
- no scheduler / auto-completion was introduced
- recommendation remains rule-first and bounded
- no UI/template editor was added
- continuation/residual workflow still takes precedence over fresh template recommendation

另外，本轮没有引入专门的 template-plan deviation trace taxonomy；当前偏离信息收在 `PLAN_CREATED` 的 reasoning 中。这样保持了 trace 集合的克制，但如果后续论文实验要单独量化 template adherence，仍需要专门 evaluation layer。

## 9. Suggested Next Step

最自然的下一步是做 **template-prior ablation / evaluation harness**：在现有 lightweight planning evaluation 面上，对比 `with template prior` vs `without template prior` 的 plan quality、next-step alignment 和 downstream deviation rate，而不是继续扩模板库或走向 scheduler。
