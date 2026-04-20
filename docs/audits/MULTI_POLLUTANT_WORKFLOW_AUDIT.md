# Multi-Pollutant Dispersion / Hotspot Workflow Audit

## 1. Executive Summary

本次审计结论：用户看到的“`热点空间地图`本轮已经提供过，不需要重复执行或重复建议。”不是扩散模型或热点工具本身的输出，也不是前端渲染错误；它来自 router 的 readiness / artifact dedup 层。该句是一个症状，真正根因是系统把“工具执行”和“交付物去重提示”混在了同一轮响应里。

当前最可能的实际链路是：

1. `calculate_dispersion` 成功执行，并返回 `map_data`，通常是 `type: contour` 或 `type: raster`。
2. `analyze_hotspots` 成功执行，并返回 `map_data`，`type: hotspot`。
3. LLM 或后续编排又尝试调用 `render_spatial_map(layer_type=hotspot)`。
4. readiness 发现热点地图已经由 `analyze_hotspots` 的 `map_data` 提供，于是把 `render_hotspot_map` 判定为 `ALREADY_PROVIDED`。
5. router 将这个 dedup 提示写入最终文本，但没有丢弃前面两个成功工具的 payload，于是同一回复既说“不需要重复执行”，又显示刚刚生成的 NOx / CO2 扩散图和热点图。

因此，奇怪句子本身不是根因；它说明 dedup 层正确发现了“第三个 render_spatial_map 是重复渲染”，但 response assembly 把这个内部阻断提示提升成了主回复，同时仍附带本轮新生成的工具结果。

此外，多污染物路径仍有两个系统级风险：

- dedup key 太粗：地图按 `map:hotspot` / `map:dispersion` / `map:any` 判重，不包含 `pollutant`、`scenario_label`、hotspot 参数或地图类型细节。
- pollutant 选择仍可能被默认 NOx 绕过：当前已有“多污染物且未指定时澄清”的代码，但只在 `pollutant` 参数缺失时生效；如果 LLM 因 tool schema 默认值或提示惯性显式传入 `pollutant: NOx`，router 会把它当成用户明确选择。

建议不要只改句子。推荐分两步修：第一步修 dedup / response assembly / redundant render 这一组强相关问题；第二步修 pollutant disambiguation、hotspot context keying 和 artifact memory scope。

## 2. Reproduction Path

### 2.1 用户可见路径

已知用户交互：

1. 已有宏观排放结果，包含 `CO2 + NOx`。
2. 用户说：“帮我查看污染物扩散情况并识别排放热点”。
3. 系统按 `config/skills/dispersion_skill.yaml` 的提示先要求确认气象条件。
4. 用户说：“开始”。
5. 系统最终回复中出现：
   - “`热点空间地图`本轮已经提供过，不需要重复执行或重复建议。”
   - 同时显示新的 NOx 扩散 contour 和 hotspot 结果。
6. 用户说：“CO2的呢？”。
7. 同样出现 dedup 句子，同时显示新的 CO2 扩散 contour 和 hotspot 结果。

### 2.2 代码级最小复现

下面的只读复现直接证明该句来自 readiness：

```bash
python -c "from core.readiness import build_readiness_assessment, build_action_already_provided_response; result={'success': True, 'map_data': {'type':'hotspot'}, 'data': {}}; a=build_readiness_assessment({}, None, [{'name':'analyze_hotspots','result':result}], current_response_payloads={'map_data': result['map_data']}); aff=a.get_action('render_hotspot_map'); print(aff.status.value); print(aff.provided_artifact.artifact_id); print(build_action_already_provided_response(aff,a))"
```

输出为：

```text
already_provided
map:hotspot
“热点空间地图”本轮已经提供过，不需要重复执行或重复建议。
说明：本次回复已经提供了对应的空间可视化结果。
```

这说明奇怪句子的触发条件是：当前轮或 artifact memory 中已经有热点地图交付物，而系统又评估到 `render_hotspot_map`。

## 3. Exact Root-Cause Locations

| 问题 | 文件 / 函数 | 代码位置 | 证据 | 结论 |
|---|---|---:|---|---|
| 奇怪句子来源 | `core/readiness.py::build_action_already_provided_response` | `core/readiness.py:1350` | 构造 `“{display_name}”本轮已经提供过，不需要重复执行或重复建议。` | 这是用户看到的原句来源 |
| `render_hotspot_map` 被判重 | `core/readiness.py::_collect_already_provided_artifacts` | `core/readiness.py:522` | 从本轮 `map_data` 提取 `map:hotspot`，display name 为“热点空间地图” | 不是 hotspot 工具报错，而是 artifact dedup |
| 地图 dedup key 粗粒度 | `core/readiness.py::_extract_map_kinds` | `core/readiness.py:316` | 只返回 `emission / dispersion / hotspot / any` | 不区分污染物、场景、hotspot 参数，也不完整区分 map 子类型 |
| `contour` 被降级为 `any` | `core/readiness.py::_extract_map_kinds` | `core/readiness.py:325` | `raster/concentration/points` 归为 dispersion，但没有 `contour` | contour 扩散图会变成 `map:any`，误伤所有地图 action |
| render action 冲突过宽 | `config/tool_contracts.yaml` | `config/tool_contracts.yaml:647` | `render_dispersion_map` 冲突包含 `map:dispersion` 和 `map:any` | 任意 map 都可能阻断后续不同地图 |
| hotspot render 冲突过宽 | `config/tool_contracts.yaml` | `config/tool_contracts.yaml:668` | `render_hotspot_map` 冲突包含 `map:hotspot` 和 `map:any` | 已有扩散图或任意图时，热点图也可能被判重复 |
| 工具成功结果仍保留 | `core/router.py::_state_handle_executing` | `core/router.py:10192` | 成功工具结果 append 到 `state.execution.tool_results` | 后续 dedup 阻断不会清空已成功结果 |
| dedup 文本成为最终回复 | `core/router.py::_state_handle_executing` | `core/router.py:10083` | `ALREADY_PROVIDED` 时设置 `_final_response_text` | 内部去重提示被提升为用户主文本 |
| dedup 文本与 payload 合并 | `core/router.py::_state_build_response` | `core/router.py:10475` | `blocked_info` 分支仍调用 `_extract_frontend_payloads(state.execution.tool_results)` | 可以同时返回“不要重复”和新地图 payload |
| 多地图 payload 聚合 | `core/router_payload_utils.py::extract_map_data` | `core/router_payload_utils.py:300` | 多个 map payload 包装为 `map_collection` | 前面成功的 contour + hotspot 会一起显示 |
| dispersion 工具自带地图 | `tools/dispersion.py::execute` | `tools/dispersion.py:187` | `ToolResult(..., map_data=self._build_map_data(...))` | 不一定需要额外 `render_spatial_map` |
| hotspot 工具自带地图 | `tools/hotspot.py::execute` | `tools/hotspot.py:111` | `map_data = self._build_map_data(...)` | `analyze_hotspots` 后再 render hotspot 多数是重复 |
| 气象确认来源 | `config/skills/dispersion_skill.yaml` | `config/skills/dispersion_skill.yaml:7` | 明确要求调用 `calculate_dispersion` 前先确认气象条件 | “开始”是 prompt-driven continuation，不是工具硬要求 |
| 隐式 NOx 默认 | `config/tool_contracts.yaml` / `tools/dispersion.py` | `config/tool_contracts.yaml:424`; `tools/dispersion.py:96` | tool schema 和工具执行层都默认 `NOx` | LLM 或执行层仍可能走 NOx 默认 |

## 4. Problem Classification

### 4.1 Dedup Key Too Coarse

当前 dedup 主要围绕 artifact id：

- `map:emission`
- `map:dispersion`
- `map:hotspot`
- `map:any`

这些 key 不包含：

- `pollutant`: NOx vs CO2。
- `scenario_label`: baseline vs scenario。
- `map subtype`: contour vs raster vs receptor scatter。
- `hotspot settings`: percentile / threshold / threshold_value / min_hotspot_area_m2。
- `source result identity`: 由哪个 dispersion result 生成。

更严重的是，`core/readiness.py::_extract_map_kinds` 没有把 `type: contour` 归为 dispersion。当前 `tools/dispersion.py::_build_map_data` 会在有有效 contour 时返回 `type: contour`，但 readiness 只把 `raster / concentration / points` 归为 dispersion。因此 contour 扩散图会落入 `any`，导致 `map:any` 参与冲突，误伤 emission / dispersion / hotspot 三类 render action。

只读验证显示：

```text
contour ['map:any'] -> render_emission_map / render_dispersion_map / render_hotspot_map 都 already_provided
raster ['map:any', 'map:dispersion'] -> hotspot render 也会被 map:any 误伤
hotspot ['map:any', 'map:hotspot'] -> dispersion render 也会被 map:any 误伤
```

这说明 dedup key 不只是缺少污染物维度，也存在 `map:any` 过度冲突和 contour 类型遗漏。

### 4.2 Router Pollutant Selection Issue

当前 router 已经有多污染物澄清逻辑：

- `core/router.py::_build_missing_input_clarification` 在 `calculate_dispersion` 且无 message pollutants 时，会检查可用 emission pollutants。
- `core/router.py::_evaluate_missing_parameter_preflight` 在 `calculate_dispersion` 且 `effective_arguments` 无 `pollutant` 时，也会要求选择污染物。
- `core/router.py::_expand_multi_pollutant_dispersion_calls` 支持“所有污染物/逐个污染物”。

但是这个保护只对“参数里没有 pollutant”的情况生效。仍有一个隐式 NOx 路径：

- `config/tool_contracts.yaml` 中 `calculate_dispersion.parameters.pollutant.default` 是 `NOx`。
- `tools/dispersion.py` 中 `pollutant = str(kwargs.get("pollutant") or "NOx")`。
- 如果 LLM 在用户没有指定污染物时，根据默认值显式传入 `{"pollutant": "NOx"}`，router 会把它视作显式用户选择，不再触发澄清。

因此，“为什么先算 NOx”并不一定来自 calculator；更可能来自 LLM/tool schema 默认值和“显式参数”判断不区分“用户显式选择”与“LLM/default 补全”。

### 4.3 Response Synthesis Conflict

存在一个明确的响应合并冲突：

1. 前面工具已成功执行，结果被保存到 `state.execution.tool_results`。
2. 后续 `render_spatial_map` 被 readiness 判为 `ALREADY_PROVIDED`。
3. `_state_handle_executing` 设置：
   - `state.execution.blocked_info`
   - `state.execution.last_error`
   - `state._final_response_text = build_action_already_provided_response(...)`
4. `_state_build_response` 进入 `state.execution.blocked_info` 分支。
5. 该分支的文本来自 `_final_response_text`，但 `map_data` 来自 `_extract_frontend_payloads(state.execution.tool_results)`。

这就是“说不要重复，但仍返回新结果”的直接原因。严格说，系统不是在 dedup 后又执行了新工具；更准确地说，是先执行了新工具，再阻断一个重复 render 工具，最后把阻断文案和已成功工具 payload 混在一起返回。

### 4.4 Other Findings

#### Hotspot Context 仍未按 pollutant keying

`core/context_store.py` 当前只对 `dispersion` 做了 pollutant keying。`_make_key` 只有 `result_type == "dispersion"` 时才加入 pollutant。`analyze_hotspots` 结果仍按 `hotspot:baseline` 存储，所以同一场景下 NOx hotspot 和 CO2 hotspot 不能长期共存。metadata 虽然记录了 `pollutant`，但 store key 不用它。

#### Artifact Memory 记录了 pollutant，但查重不用 pollutant

`core/artifact_memory.py::classify_artifacts_from_delivery` 会把 `related_pollutant` 写入 `ArtifactRecord`，但：

- `_dedupe_records` 只用 `(artifact_type, artifact_family, source_tool_name, related_scope)`。
- `build_artifact_availability_decision` 按 artifact type/family 找 latest，不用 pollutant。
- `_scan_repeated_available_actions` 也按 artifact type 查 latest，不用 pollutant。

这意味着“NOx hotspot map 已提供”可能影响“CO2 hotspot map”的建议或 render 判重。

## 5. Trace for the User Intent

目标消息：

```text
帮我查看污染物扩散情况并识别排放热点
```

上下文：

- 已有 `calculate_macro_emission` 结果，包含 `CO2 + NOx`。
- 用户没有指定目标污染物。
- 用户随后用“开始”确认气象条件。

### 5.1 气象确认

`config/skills/dispersion_skill.yaml` 要求在调用 `calculate_dispersion` 前先确认气象条件，并给出“直接说开始使用默认配置”的交互模式。这解释了为什么系统先问 meteorology。

### 5.2 任务分解

`core/router.py::_extract_message_execution_hints` 对该消息会识别：

- `wants_dispersion = True`，因为包含“扩散”。
- `wants_hotspot = True`，因为包含“热点”。
- `pollutants = []`，因为没有 CO2 / NOx / PM2.5 等明确污染物。

因此理想链路应该是：先澄清污染物，或在用户明确“所有污染物”时批量执行。

### 5.3 为什么仍可能选 NOx

当前已有“缺 pollutant 时澄清”的防线，但它只能拦截没有 `pollutant` 的 tool call。如果 LLM 根据 tool contract 默认值产生 `pollutant: NOx`，则 router 无法判断这个 NOx 是用户指定，还是模型按默认值补的。

因此，需要从“参数是否存在”升级为“用户是否显式指定 pollutant”。可以利用 `hints["pollutants"]` 或新增 `pollutant_source=user|inferred|default`，不能只看 tool call arguments。

### 5.4 “CO2的呢？”为什么仍出现怪句

“CO2的呢？”会被 pollutant extractor 识别为 CO2，因此 CO2 dispersion/hotspot 可以正常执行。怪句仍出现，是因为 CO2 的 `analyze_hotspots` 已经返回 hotspot `map_data`，后续冗余的 `render_spatial_map(layer_type=hotspot)` 被 dedup 阻断。也就是说，第二轮怪句的主要根因仍是 redundant render + response assembly，不是 CO2 计算失败。

## 6. Response Assembly Audit

### 6.1 Dedup warning is assembled separately

`build_action_already_provided_response` 只负责生成文本，不携带新工具结果。它是 readiness 层对某个 action 的状态说明。

### 6.2 Actual tool results are carried separately

`core/router_payload_utils.extract_map_data` 会从所有成功工具结果中收集 `map_data`。若有多个地图，会返回：

```json
{
  "type": "map_collection",
  "items": [...]
}
```

因此，`calculate_dispersion` 的 contour 和 `analyze_hotspots` 的 hotspot 可以同时进入前端。

### 6.3 两者在 blocked_info 分支合并

`core/router.py::_state_build_response` 的 `state.execution.blocked_info` 分支使用：

- 文本：`state._final_response_text`，即 “热点空间地图本轮已经提供过...”
- payload：`_extract_frontend_payloads(state.execution.tool_results)`，即前面已经成功的 contour/hotspot map

这正是用户感知不一致的直接原因。

## 7. Similar Issues Likely Elsewhere

### 7.1 `render_spatial_map`

所有 render action 都受 `map:any` 影响。当前配置：

- `render_emission_map` conflicts: `map:emission`, `map:any`
- `render_dispersion_map` conflicts: `map:dispersion`, `map:any`
- `render_hotspot_map` conflicts: `map:hotspot`, `map:any`

这会导致“已有任意地图”时，其他地图类型也可能被判重复。例如已有 contour 扩散图后，想看热点图可能被 `map:any` 阻断。

### 7.2 `analyze_hotspots`

`analyze_hotspots` action 本身没有 `provided_conflicts`，所以它不会因为已有 hotspot result 被 readiness 阻断。这有利于 CO2 等新污染物重算热点，但也意味着相同 pollutant / 相同 threshold / 相同 scenario 的重复热点分析没有去重 key。

### 7.3 `compare_scenarios`

`compare_scenario` readiness 只检查 scenario 数量，不区分 result type 细节和 pollutant。artifact memory 对 `COMPARISON_RESULT` 也是按 artifact type/family 查重，不按 pollutant 或 scenario pair 查重。未来如果比较 NOx 和 CO2 的不同结果，可能出现类似的“已有 comparison，抑制新 comparison 建议”的粗粒度问题。

### 7.4 Next-Step Suggestion Logic

`core/capability_summary.py` 会把 already provided artifacts 写进 “本次已提供的交付物（不要重复建议这些）”，并要求 LLM 不重复建议地图、图表、表格。但这个 summary 继承了 readiness/artifact memory 的粗粒度 key，因此可能把“已经提供 NOx hotspot map”解释成“不要建议 CO2 hotspot map”。

## 8. Recommended Fix Plan

### 8.1 不建议只改文案

只把“热点空间地图本轮已经提供过...”隐藏或改成更温和的句子，会掩盖真实问题：

- redundant `render_spatial_map` 仍会被 LLM 选中。
- `map:any` 仍会误伤其他地图。
- NOx 与 CO2 的 artifact memory 仍无法区分。
- blocked text 和 successful payload 仍可能在别的 action 上混合。

### 8.2 第一阶段：同一 pass 修 dedup / render / response assembly

建议把以下改动放在一个 pass，因为它们共同解释当前怪句：

1. 修正 map kind 识别：
   - 将 `contour` 归为 dispersion。
   - 明确处理 `dispersion` map type。
   - 不要让具体地图默认落入 `map:any`。

2. 收窄 render action conflicts：
   - `render_emission_map` 只冲突 `map:emission`。
   - `render_dispersion_map` 只冲突 `map:dispersion`。
   - `render_hotspot_map` 只冲突 `map:hotspot`。
   - `map:any` 只用于真正“任意地图都够了”的交付请求，不应作为所有地图互斥锁。

3. 对 artifact identity 增加 scope：
   - `artifact_type`
   - `map_kind`
   - `pollutant`
   - `scenario_label`
   - 可选：`method / threshold / percentile`

4. 调整 blocked response assembly：
   - 如果 `ALREADY_PROVIDED` 发生在已有成功 tool_results 之后，不应把 dedup 文本作为主回复。
   - 应把它作为内部 trace 或低优先级 note。
   - 用户主回复应基于已成功的 `calculate_dispersion` / `analyze_hotspots` 结果。

5. 避免冗余 render tool：
   - 当 `calculate_dispersion` 或 `analyze_hotspots` 已返回 `map_data` 时，后续 `render_spatial_map` 对同一 map kind 应跳过，而不是生成用户可见阻断文案。

### 8.3 第二阶段：pollutant workflow / hotspot context

建议单独做第二 pass：

1. 区分用户显式 pollutant 与默认 pollutant：
   - 如果 `hints["pollutants"]` 为空，而 emission result 有多个污染物，即使 tool call 中出现 `pollutant: NOx`，也应视作 default/inferred，触发澄清。
   - 后端仍可保留 NOx 默认以兼容旧调用，但 LLM-facing routing 不应把默认当用户选择。

2. 对 hotspot result 做 pollutant keying：
   - 类似 dispersion 的 `dispersion:baseline:co2`。
   - 建议 hotspot key 至少包含 `pollutant + scenario_label`，可选包含 `method + threshold/percentile`。

3. 明确多污染物任务策略：
   - “污染物扩散情况”且已有多个污染物：问用户选哪一个。
   - “所有污染物 / 各污染物”：顺序执行每个 pollutant 的 dispersion + hotspot。
   - “CO2 的呢”：继承上轮 workflow，只替换 pollutant。

## 9. Risk Assessment

### 9.1 如果只 patch 句子

风险高。用户不再看到奇怪句子，但系统内部仍可能：

- 执行冗余 render tool。
- 因 `map:any` 阻断错误地图。
- 把 NOx artifact 当作 CO2 artifact。
- 在其它 blocked action 上继续混合“阻断文本 + 成功 payload”。

这是典型 symptom patch。

### 9.2 如果只 patch orchestration

风险中等。减少 redundant render 可以缓解当前现象，但如果不修 dedup key：

- 后续建议仍会被 artifact memory 粗粒度抑制。
- 跨污染物地图/热点仍可能被判已经提供。
- compare/scenario 等其它 artifact flow 仍可能复现同类问题。

### 9.3 如果一次大范围重构全部 artifact memory

风险中等偏高。artifact memory 被 readiness、capability summary、intent bias、trace、summary delivery 多处使用。一次改太多容易影响下载、表格、图表、地图建议策略。

## 10. Concrete Recommendation

建议采用“两 pass 修复”，但第一 pass 必须同时包含 dedup key、redundant render 和 response assembly 三个点。

### Pass 1：修当前怪句的真实根因

目标：同一轮 `calculate_dispersion -> analyze_hotspots -> redundant render_spatial_map` 不再产生用户可见的“不要重复”主文本，同时不影响成功工具结果展示。

最小边界：

- `core/readiness.py`
- `core/router.py`
- `core/router_payload_utils.py` 仅在需要时调整 map kind/scope 提取
- `config/tool_contracts.yaml` 的 map action `provided_conflicts`
- 对应 tests：readiness gating、multi-step execution、multi-map payload

验收：

- NOx 首轮：显示 NOx dispersion + hotspot，文本总结对应成功结果，不出现“热点空间地图本轮已经提供过”。
- CO2 追问：显示 CO2 dispersion + hotspot，不受 NOx hotspot artifact 影响。
- 如果用户明确要求“再渲染同一个 hotspot map”，可以温和提示已展示，但不与新计算结果混合。

### Pass 2：修多污染物语义完整性

目标：污染物选择、hotspot context、artifact memory scope 完整支持多污染物。

最小边界：

- `core/router.py` pollutant source tracking。
- `core/context_store.py` hotspot keyed by pollutant/method/scenario。
- `core/artifact_memory.py` artifact scope 纳入 pollutant/scenario。
- `core/capability_summary.py` 显示 scope-aware already-provided 信息。

验收：

- 宏观结果包含 `CO2 + NOx`，用户只说“做扩散和热点”时先问污染物。
- 用户说“所有污染物”时顺序执行每个 pollutant。
- 用户说“CO2 的呢”时只替换 pollutant，不复用 NOx hotspot/map artifact。

## 11. Bottom Line

“热点空间地图本轮已经提供过...”是一个暴露出来的提示，不是根本问题。根本问题是：当前系统把 bounded artifact dedup 当成执行阻断，并在已有成功工具结果的同一轮里把阻断文案作为主回复返回；同时 dedup key 没有污染物/场景/地图 subtype 维度。

推荐先做一个聚焦修复 pass，解决 dedup scope、redundant render 和 response assembly 冲突；再做第二 pass，补齐 pollutant-aware workflow 和 hotspot/artifact memory keying。这样比一次性大重构风险更低，也比只改文案更接近真实根因。
