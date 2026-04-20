## Section 10：NLU 层 → 编排层 的状态传递

### 10.1 LLM 的“理解产出”
- function calling 首次处理的返回形态是 `LLMResponse(content, tool_calls, finish_reason, usage)`，不是统一 intent object；证据：`services/llm_client.py:56-62`。tool call 解析只取 `function.name/arguments`：`services/llm_client.py:328-339`。
- 主 state loop 在 `chat_with_tools` 后只保存 `state._llm_response`、`selected_tool`、tool args；证据：`core/router.py:10571-10590`，片段：`state._llm_response = response`、`_capture_tool_call_parameters(...)`。
- 显式 intent 抽取有两类：规则 fast path `ConversationIntentClassifier`，证据 `core/conversation_intent.py:83-207`；结构化 deliverable/progress intent，prompt 要求 JSON，证据 `core/intent_resolution.py:8-49`，调用 `chat_json` 见 `core/router.py:5014-5028`。
- LLM reasoning/thinking：UNKNOWN: `LLMResponse` 无 reasoning 字段；trace 中 `TOOL_SELECTION.reasoning` 是 router 合成文本 `LLM selected tool(s): ...`，证据 `core/router.py:10581-10589`。

### 10.2 状态机能看到什么
- `_run_state_loop` 初始化 `TaskState` 的输入：`user_message`、`file_path`、`fact_memory`、`session_id`；证据 `core/router.py:2552-2567`。
- `TaskState` 完整主字段：`stage,file_context,parameters,execution,control,plan,repair_history,continuation,recommended_workflow_templates,selected_workflow_template,template_prior_used,template_selection_reason,active_parameter_negotiation,latest_parameter_negotiation_decision,active_input_completion,latest_input_completion_decision,input_completion_overrides,supporting_spatial_input,geometry_recovery_context,geometry_readiness_refresh_result,residual_reentry_context,reentry_bias_applied,incoming_file_path,latest_file_relationship_decision,latest_file_relationship_transition,pending_file_relationship_upload,attached_supporting_file,awaiting_file_relationship_clarification,latest_supplemental_merge_plan,latest_supplemental_merge_result,latest_intent_resolution_decision,latest_intent_resolution_plan,latest_summary_delivery_plan,latest_summary_delivery_result,artifact_memory_state,session_id,user_message,_llm_response`；证据 `core/task_state.py:263-301`。
- 参数状态字段：`raw, normalized, status, confidence, strategy, locked, lock_source, confirmation_request_id`；证据 `core/task_state.py:81-102`。
- 缺 season：UNKNOWN: 未发现 `_identify_critical_missing` 对 season 的缺失分支；该函数只处理 unknown file、AMBIGUOUS 参数、micro 缺 vehicle_type，证据 `core/router.py:2780-2819`。season 从用户文本规则匹配进入 hints：`core/router.py:1658-1664`, `1695-1696`；如存在，写入工具 args：`core/router.py:1818-1844`。
- slot/parameter/input completion 路径：`core/input_completion.py`（request/parse/prompt）；`core/parameter_negotiation.py`（候选确认）；`core/router.py:6171-6427`（构造 input completion request）；`core/router.py:6428-6525`（激活与解析）；`services/standardization_engine.py:573-668`（batch 标准化和协商错误）。

### 10.3 澄清循环的触发与消费
- 触发：readiness 得到 `REPAIRABLE` 且 `_should_short_circuit_readiness` 为 true 时构造 `InputCompletionRequest` 并进入 `NEEDS_INPUT_COMPLETION`；证据 `core/router.py:10789-10844`。
- 追问文本生成：`_activate_input_completion_state` 调 `format_input_completion_prompt`，证据 `core/router.py:6428-6466`；prompt 格式见 `core/input_completion.py:565-607`。
- 回复解析：下一轮 `_state_handle_input` 发现 `active_input_completion` 后走 `_handle_active_input_completion`，证据 `core/router.py:10149-10158`；解析入口 `core/router.py:7625-7680`。
- 解析方式：规则解析；`parse_input_completion_reply` 通过 pause phrase、序号、数值、option alias、上传文件解析，证据 `core/input_completion.py:372-399`, `402-562`。未见 LLM 参与。
- 自然语言回答“刚才说过冬天啊”：UNKNOWN: `parse_input_completion_reply` 未见 season 语义解析分支；可解析的自然语言只覆盖固定短语/序号/数值/option alias/上传文件，证据同上。

### 10.4 失败 case 状态传递断点
- L8 `e2e_ambiguous_003`：log L8 无 tool_calls，`trace_step_types` 包含 `action_readiness_repairable` 和 `input_completion_required`；file diagnostics 标出 `traffic_flow_vph` ambiguous，文本追问该字段。证据 `evaluation/results/end2end_full_v2/end2end_logs.jsonl:8`。未发现 LLM vs state 分歧点；状态机根据 file diagnostics 阻断。
- L48 `e2e_incomplete_011`：log L48 tool args=`{"vehicle_type":"小汽车","pollutants":["CO2"],"model_year":2020}`，std alias 成功；benchmark expected tools 空。证据 `evaluation/results/end2end_full_v2/end2end_logs.jsonl:48`。分歧点：benchmark 要追问，LLM 决策层直接补小汽车并执行；log 未保存 LLM 原始 reasoning。
- L94 `e2e_constraint_048`：log L94 先有 `cross_constraint_warning`，随后 `action_readiness_repairable/dependency_blocked/plan_repair_skipped`，后续 `input_completion_required` 和两次 `geometry_re_grounding_failed`；文本含 `missing prerequisite results: emission` 与缺 geometry。证据 `evaluation/results/end2end_full_v2/end2end_logs.jsonl:94`。分歧点：第1轮状态缺 emission；后续转为 geometry completion；session history 未保留完整逐步 trace，UNKNOWN: 无法还原每轮 prompt。

## Section 11：决策层 LLM 能看到的系统状态

### 11.1 LLM 被注入的 context
- function calling 调用结构：`system=context.system_prompt`, `messages=context.messages`, `tools=context.tools`；证据 `core/router.py:10571-10575` 与 `services/llm_client.py:303-319`。
- `ContextAssembler` 组成：core/system prompt；tool definitions；fact memory system message；working memory；file context 拼到当前 user message；证据 `core/assembler.py:77-95`, `161-211`, `213-252`。
- skill mode 还会做 rule `detect_intents` 和 situational prompt；证据 `core/assembler.py:97-159`。
- 当前会话已有工具与结果：有。fact memory 写入 `Last successful tool`, `Last tool summary`, `Last tool snapshot`，证据 `core/assembler.py:285-299`；分层记忆也写 `Cumulative tools used`，证据 `core/memory.py:157-193`。
- context_store 可用 artifact：有摘要，不是完整 payload；`_get_context_summary()` 来源 `SessionContextStore.get_context_summary()`，证据 `core/router.py:513-515`, `core/context_store.py:282-315`。
- 用户确认过的参数：有，`_apply_live_parameter_state` 恢复 locked parameters，`_inject_parameter_confirmation_guidance` 注入上下文；恢复证据 `core/router.py:5822-5839`，参数锁字段证据 `core/task_state.py:869-885`。UNKNOWN: 本轮未展开注入文本函数行。
- 当前会违反哪些约束：未见预先完整注入。约束在 preflight/executor 标准化后检测，见 Section 13；tool schema 未包含 cross_constraints 全表，ROUND2 §5.3 已查。
- 状态机认为还缺什么：有时以 input completion guidance 注入；`_inject_input_completion_guidance(context,state)` 在 LLM 调用前执行，证据 `core/router.py:10421-10423`；具体 active request 来自 live bundle，见 `core/router.py:5840-5864`。
- 上一轮工具成功/失败原因：工作记忆保留 user/assistant 文本，不保留 tool_calls；证据 `core/memory.py:99-109`。fact memory 只从成功 tool calls 抽 `last_tool_summary/snapshot`，证据 `core/memory.py:270-305`。

### 11.2 LLM 看到的“历史”有多完整
- `get_working_memory` 只返回最近 5 轮的 user/assistant，无 tool_calls/tool_results；证据 `core/memory.py:99-109`。
- assembler 再裁剪到最近 3 轮，并把 assistant 截到 300 chars；证据 `core/assembler.py:234-240`, `303-342`。
- fast path 对话历史最多 5 轮，assistant 最多 1200 chars；证据 `core/memory.py:111-131`。
- WP-CONV-3 分层记忆进入 prompt：`_get_memory_context_for_prompt` 调 `memory.build_context_for_prompt()`，证据 `core/router.py:533-538`；内容由 `[Session facts]` 与 `[Conversation summaries]` 组成，证据 `core/memory.py:157-208`。

### 11.3 LLM 做决策后的“理由”
- 工具选择理由：UNKNOWN: provider 的 reasoning 未保存；trace 只写 router 合成 `LLM selected tool(s): ...`，证据 `core/router.py:10581-10589`。
- 后续层可见：executor 接收 tool name/args，不接收理由；工具执行代码使用 `tool_call.name` 与 `effective_arguments`，证据 `core/router.py:10718-10723`, `10943-10949`。

### 11.4 从幻觉 case 看 LLM 认知盲点
- 完整 prompt：UNKNOWN: end2end log 只保存 `assembled_context.message_count/estimated_tokens/file_context_injected/last_user_message`，不保存 system prompt 或完整 messages；证据 `core/router.py:2489-2495`，eval record 只保留 `actual.trace_step_types` 等，证据 `evaluation/eval_end2end.py:578-590`。
- L48：log L48 有 tool call，非“未发起工具调用”；证据 `evaluation/results/end2end_full_v2/end2end_logs.jsonl:48`。
- L52：log L52 有 tool call；证据 `evaluation/results/end2end_full_v2/end2end_logs.jsonl:52`。
- L83：log L83 actual_tools=`[]`，文本声称完成；trace 仅 `file_relationship.../intent_resolution_skipped/state_transition`。该轮无记录能证明 LLM 被显式告知“未发起工具调用”；证据 `evaluation/results/end2end_full_v2/end2end_logs.jsonl:83`。

## Section 12：执行层 artifact 反馈回上层的机制

### 12.1 Artifact 的 schema 一致性
- `TOOL_TO_RESULT_TYPE`：`calculate_macro_emission/micro -> emission`, `calculate_dispersion -> dispersion`, `analyze_hotspots -> hotspot`, `render_spatial_map -> visualization`, `compare_scenarios -> scenario_comparison`, `analyze_file -> file_analysis`, `query_emission_factors -> emission_factors`, `query_knowledge -> knowledge`；证据 `core/context_store.py:76-86`。
- `TOOL_DEPENDENCIES`：`calculate_dispersion:["emission"]`, `analyze_hotspots:["dispersion"]`, `render_spatial_map` 按 layer type 查 `emission/dispersion/hotspot`；证据 `core/context_store.py:88-99`。
- 基础 schema 是 Python dataclass `ToolResult(success,data,error,summary,chart_data,table_data,download_file,map_data)`；证据 `tools/base.py:13-28`。
- macro 输出：`data=result["data"]`, `summary`, 可选 `map_data`；geometry 会并入 `results[*].geometry`；证据 `tools/macro_emission.py:832-844`, `937-943`。
- micro 输出：`data=result["data"]`, `summary`；证据 `tools/micro_emission.py:195-244`。
- dispersion 输出：`data` 加 `coverage_assessment/meteorology_used/scenario_label/roads_wgs84/defaults_used`, `map_data`；证据 `tools/dispersion.py:179-193`。
- hotspots 输出：`data=analysis_data`, `map_data`；证据 `tools/hotspot.py:100-118`。
- render 输出：成功 `data={"map_config":map_data}`, `map_data=map_data`；失败 `data=None`；证据 `tools/spatial_renderer.py:196-214`。
- factors 输出：单污染物 `data=data`，多污染物 `data={"vehicle_type","model_year","pollutants","metadata"...}`；证据 `tools/emission_factors.py:196-216`。
- knowledge 输出：`data=data`, `summary=answer`；证据 `tools/knowledge.py:61-69`。
- schema 声明位置：基础结构在 Python dataclass；工具入参 schema 在 `config/tool_contracts.yaml` 经 `tools/contract_loader.py:76-88` 转 function schema。UNKNOWN: 未发现运行时对 ToolResult payload 做结构校验；executor 只把 ToolResult 转 dict，证据 `core/executor.py:270-288`。

### 12.2 Artifact 状态在 LLM prompt 中的表达
- 下一轮 prompt 中，上一轮结果主要通过 fact memory summary/snapshot、context store summary、working memory 文本进入；证据 `core/assembler.py:224-250`, `core/context_store.py:282-315`。
- memory tool_calls 是 compact：跳过 `results/speed_curve/pollutants`，保留 `query_info/summary/fleet_mix_fill/download_file/columns` 等；证据 `core/router_memory_utils.py:6-24`, `27-47`。
- 大 payload 给 synthesis 的裁剪：`filter_results_for_synthesis` 对 micro/macro 保留 summary、num_points、total_emissions、query_params、download flag；其他工具走 `_strip_heavy_payload_for_synthesis`；证据 `core/router_render_utils.py:731-789`。
- 单工具成功可直接规则渲染，不一定调用 synthesis LLM；证据 `core/router_synthesis_utils.py:26-58`。

### 12.3 失败状态的回传
- 给用户：失败工具结果进入 `format_results_as_fallback`，失败显示 error/message；证据 `core/router_render_utils.py:821-845`。
- 给下一轮 LLM：工作记忆保存 assistant 文本；fact memory 只从成功 tool call 抽结构化摘要；失败不更新 last_tool_summary，证据 `core/memory.py:270-305`。
- 给状态机：执行失败可置 `state.execution.last_error`，证据 `core/router.py:11099-11112`。
- executor `error_type` 列表：`standardization`、`missing_parameter`、`execution`；证据 `core/executor.py:231-251`, `290-304`, `306-320`。工具自身失败通常是 `ToolResult.error`，executor 不额外设置 `error_type`，证据 `core/executor.py:270-288`。

### 12.4 Cross-turn artifact 可见性
- 持久化：`SessionContextStore.to_persisted_dict` 可保存 full payload，证据 `core/context_store.py:471-475`；compact `from_dict` 恢复 `data={}`，证据 `core/context_store.py:477-499`。ROUND2 §8.1 已记录 eval session 未发现 router_state 文件。
- router 重启/session 恢复：若只走 compact dict，full payload 不在 `StoredResult.data`；证据同上。
- session history 实际保存：`MemoryManager._save` 保存 `fact_memory.last_tool_snapshot`、`last_spatial_data`、最近 10 个 `working_memory.tool_calls`；证据 `core/memory.py:491-525`。
- `eval_e2e_multistep_011.json`：fact_memory 中 `last_tool_snapshot` 只有 `query_info/summary/fleet_mix_fill/download_file`，`last_spatial_data=null`；工作记忆里可见 macro tool success 的 compact result。证据：`data/sessions/history/eval_e2e_multistep_011.json`。

## Section 13：Cross-constraint 状态的流动

### 13.1 约束检测触发点
- 调用点 1：executor 标准化后 `standardize_batch` 调 `get_cross_constraint_validator().validate(...)`，证据 `services/standardization_engine.py:643-668`。此时 LLM 已经选工具并填 args。
- 调用点 2：router preflight `_evaluate_cross_constraint_preflight`，先从 effective args + message hints 标准化参数，再 validate；证据 `core/router.py:2165-2244`。此时 LLM 已经选工具，执行还未开始。
- 未发现 LLM tool decision 前的全量 cross-constraint validate 调用；全库调用点见 `core/router.py:2241` 与 `services/standardization_engine.py:644`。

### 13.2 约束违反的反馈路径
- 规则阻断文本：preflight violation 构造 `message = f"参数组合不合法: {violation.reason}..."` 并设 `_final_response_text`；证据 `core/router.py:2261-2279`。
- executor 路径：cross violation 作为 `BatchStandardizationError` 返回 `error_type=standardization`，详见 ROUND2 §8.1；代码证据 `services/standardization_engine.py:651-666`, `core/executor.py:231-249`。
- 给下一轮 LLM 的结构化约束字段：UNKNOWN: `FactMemory` 无 constraint 字段，证据 `core/memory.py:27-44`；下一轮只能通过 assistant 文本/working memory 或 tool summary 间接看到，证据 `core/memory.py:99-109`。
- 再次类似请求是否记得上次违反：UNKNOWN: 未发现专门记录 previous constraint violation 的字段；rule 会重新检测新一轮 args，证据调用点同 13.1。

### 13.3 constraint_blocked 信号
- eval 字段来源：`constraint_blocked = "参数组合不合法" in response_text or any(record_type=="cross_constraint_violation")`；证据 `evaluation/eval_end2end.py:508-514`。
- L21/L23/L56/L60 的文本由 LLM 无工具回复产生，trace 无 cross_constraint_violation；`LLM responded without tool calls` 路径见 `core/router.py:10596-10610`。日志证据见 `evaluation/results/end2end_full_v2/end2end_logs.jsonl:21,23,56,60`。
- 两者未对上：可确认的断点是 eval detector 只识别固定短语或 std_records；这四条没有 `参数组合不合法` 字样，也没有 `cross_constraint_violation` record。证据同上。

## Section 14：整个系统目前有多少是“LLM-aware”的

|决策点|模式|事实证据|
|---|---|---|
|1. 闲聊/任务 fast path|RULE-driven|`ConversationIntentClassifier` 用 regex pattern 与 blocking_signals；证据 `core/conversation_intent.py:37-81`, `83-207`。|
|2. 文件引用|HYBRID|API/upload 显式传 file；历史文本可用 regex 解析 legacy file path；证据 `api/routes.py:211-245`, `api/routes.py:93-120`, `services/chat_session_service.py:250-283`。|
|3. 需要哪个工具|HYBRID|主路径 LLM function calling 选工具：`services/llm_client.py:310-319`；部分 fallback/continuation 用规则 message hints/plan，证据 `core/router.py:1645-1705`, `1818-1850`。|
|4. 填工具参数|HYBRID|LLM 填 function arguments；router 会继承 locked params、completion overrides、context store `_last_result`，证据 `core/router.py:862-969`, `9554-9573`。|
|5. 参数标准化|HYBRID|规则 exact/alias/fuzzy/default + LLM backend；证据 `services/standardization_engine.py:499-571`, `services/model_backend.py:149-155`。|
|6. 参数缺失/追问|HYBRID|规则 `_identify_critical_missing`、readiness/input completion；LLM 也可直接不调工具给文本。证据 `core/router.py:2780-2819`, `core/readiness.py:997-1177`, `core/router.py:10596-10610`。|
|7. 追问文本生成|RULE-driven|input completion prompt 规则拼接；parameter confirmation prompt 规则格式化；证据 `core/input_completion.py:565-607`, `core/router.py:8372-8385`。|
|8. 解析追问回复|RULE-driven|input completion 解析固定短语/序号/数值/alias/上传文件；证据 `core/input_completion.py:372-562`。|
|9. artifact 就绪|RULE-driven|readiness 用 context_store/current_tool_results 计算 available tokens 和 geometry；证据 `core/readiness.py:394-445`, `900-1296`。|
|10. 约束违反|RULE-driven|`CrossConstraintValidator.validate` 规则匹配 YAML；证据 `services/cross_constraints.py:84-164`, `config/cross_constraints.yaml:3-13`。|
