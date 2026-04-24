# EXPLORATION_ROUND2

## Section 7：F 类 11 条是否真的是 eval 假阴性

### Case e2e_simple_004
- 用户原文：`计算这个路段流量文件的CO2和NOx排放`
- benchmark expected：`evaluation/benchmarks/end2end_tasks.jsonl:4`；tools=`["calculate_macro_emission"]`；params=`{"pollutants":["CO2","NOx"],"season":"夏季"}`；criteria=`{"tool_executed":true,"params_legal":true,"result_has_data":true}`。
- 实际：`evaluation/results/end2end_full_v2/end2end_logs.jsonl:4`；actual_tools=`["calculate_macro_emission"]`；actual_params=`{"file_path":".../macro_direct.csv","pollutants":["CO2","NOx"]}`；tool success=`true`；文本片段：`已成功计算...CO₂ 318.90 kg/小时...NOₓ 67.40 g/小时...季节：夏季`。
- eval 失败字段：`params_legal=false`；`params_comparison.season.actual=null`，但 `result_has_data=true`。
- 人工判定：**EVAL_BUG**。证据：工具成功且回复/summary 明确季节为夏季；失败来自 eval 只看 args 缺 `season`。

### Case e2e_ambiguous_001
- benchmark：`evaluation/benchmarks/end2end_tasks.jsonl:6`；tools=`["query_emission_factors"]`；params=`{"vehicle_type":"Passenger Car","pollutants":["CO2"]}`；criteria 完整同 L6。
- 实际：`evaluation/results/end2end_full_v2/end2end_logs.jsonl:6`；args=`{"vehicle_type":"家用车","pollutants":["CO2"],"model_year":2020}`；tool success=`true`；std=`家用车 -> Passenger Car(llm)`；文本含 `家用车（Passenger Car）...CO₂ 排放因子曲线`。
- eval 失败字段：`params_legal=false`；vehicle actual raw=`家用车`。
- 判定：**EVAL_BUG**。证据：标准化记录成功且工具返回 Passenger Car 数据。

### Case e2e_incomplete_003
- benchmark：`evaluation/benchmarks/end2end_tasks.jsonl:18`；tools=`[]`；params=`{}`；criteria=`{"tool_executed":false,"requires_user_response":true,"result_has_data":false}`。
- 实际：`evaluation/results/end2end_full_v2/end2end_logs.jsonl:18`；actual_tools=`[]`；tool result=N/A；文本含 `直接说 “开始” 使用以上默认配置，或告诉我想调整的参数`。
- eval 失败字段：`requires_user_response=false`。
- 判定：**EVAL_BUG**。证据：无工具、无数据，文本要求用户继续确认。

### Case e2e_constraint_001
- benchmark：`evaluation/benchmarks/end2end_tasks.jsonl:21`；tools=`[]`；params=`Motorcycle/高速公路/CO2/2020`；criteria=`{"tool_executed":false,"constraint_blocked":true,"result_has_data":false}`。
- 实际：`evaluation/results/end2end_full_v2/end2end_logs.jsonl:21`；actual_tools=`[]`；文本含 `摩托车禁止在高速公路上行驶...无法为此非法场景提供排放因子`。
- eval 失败字段：`constraint_blocked=false`。
- 判定：**EVAL_BUG**。证据：系统文本实际执行阻断，但 log 未产生 `constraint_blocked=true`。

### Case e2e_constraint_003
- benchmark：`evaluation/benchmarks/end2end_tasks.jsonl:23`；tools=`[]`；params=`Motorcycle/高速公路/NOx/2020`；criteria 同约束阻断。
- 实际：`evaluation/results/end2end_full_v2/end2end_logs.jsonl:23`；actual_tools=`[]`；文本含 `摩托车禁止在高速公路上行驶...不存在...合法数据组合`。
- eval 失败字段：`constraint_blocked=false`。
- 判定：**EVAL_BUG**。证据同上。

### Case e2e_incomplete_014
- benchmark：`evaluation/benchmarks/end2end_tasks.jsonl:51`；tools=`[]`；params=`{"pollutant":"PM2.5"}`；criteria=`{"tool_executed":false,"requires_user_response":true,"result_has_data":false}`。
- 实际：`evaluation/results/end2end_full_v2/end2end_logs.jsonl:51`；actual_tools=`[]`；文本：`您已第三十七次提出...该请求已被系统永久终止，不再响应。`
- eval 失败字段：`requires_user_response=false`。
- 判定：**TRUE_POSITIVE_FAIL**。证据：未执行工具，也未给出可继续的补全问题。

### Case e2e_incomplete_018
- benchmark：`evaluation/benchmarks/end2end_tasks.jsonl:55`；tools=`[]`；params=`{"season":"冬季","pollutants":["CO2"]}`；criteria=`{"tool_executed":false,"requires_user_response":true,"result_has_data":false}`。
- 实际：`evaluation/results/end2end_full_v2/end2end_logs.jsonl:55`；actual_tools=`[]`；文本含 `已第27次成功查询...冬季小汽车...CO₂排放因子`。
- eval 失败字段：`requires_user_response=false`。
- 判定：**TRUE_POSITIVE_FAIL**。证据：未调用工具却声称成功查询，且未追问缺失车型。

### Case e2e_constraint_006
- benchmark：`evaluation/benchmarks/end2end_tasks.jsonl:56`；tools=`[]`；params=`Motorcycle/2022/CO2/高速公路`；criteria=`constraint_blocked=true`。
- 实际：`evaluation/results/end2end_full_v2/end2end_logs.jsonl:56`；actual_tools=`[]`；文本含 `摩托车是禁止在高速公路上行驶...无法提供`。
- eval 失败字段：`constraint_blocked=false`。
- 判定：**EVAL_BUG**。证据：文本阻断成立，detector 未置位。

### Case e2e_constraint_010
- benchmark：`evaluation/benchmarks/end2end_tasks.jsonl:60`；tools=`[]`；params=`Motorcycle/2023/PM2.5/高速公路`；criteria=`constraint_blocked=true`。
- 实际：`evaluation/results/end2end_full_v2/end2end_logs.jsonl:60`；actual_tools=`[]`；文本含 `摩托车...不允许在高速公路上行驶...参数组合不成立`。
- eval 失败字段：`constraint_blocked=false`; `requires_user_response=false`。
- 判定：**EVAL_BUG**。证据：文本阻断成立。

### Case e2e_simple_037
- benchmark：`evaluation/benchmarks/end2end_tasks.jsonl:83`；tools=`["calculate_macro_emission"]`；params=`{"pollutants":["NOx"]}`；criteria=`{"tool_executed":true,"params_legal":true,"result_has_data":true}`。
- 实际：`evaluation/results/end2end_full_v2/end2end_logs.jsonl:83`；actual_tools=`[]`；文本含 `已完成NOx排放计算...总排放量 67.40 g/小时`。
- eval 失败字段：`tool_executed=false`, `result_has_data=false`。
- 判定：**TRUE_POSITIVE_FAIL**。证据：无工具调用却声称完成。

### Case e2e_multistep_045
- benchmark：`evaluation/benchmarks/end2end_tasks.jsonl:91`；tools=`["query_knowledge","calculate_macro_emission"]`；params=`{"pollutants":["NOx"]}`；criteria=`{"tool_executed":true,"params_legal":true,"result_has_data":true}`。
- 实际：`evaluation/results/end2end_full_v2/end2end_logs.jsonl:91`；actual_tools 同 expected；query_knowledge success=true；macro args=`{"file_path":".../macro_direct.csv","pollutants":["NOx"]}` success=true；文本含 `已完成NOx排放知识查询和路段排放计算`。
- eval 失败字段：`params_legal=false`；`params_comparison.pollutants.actual=null`；`result_has_data=true`。
- 判定：**EVAL_BUG**。证据：第二个工具实际含 `pollutants:["NOx"]`，eval 比较未取到。

汇总：EVAL_BUG=8；TRUE_POSITIVE_FAIL=3；SPEC_AMBIGUOUS=0。

## Section 8：Artifact / Geometry 传递机制现状

### 8.1 Artifact 存储与查找

|问题|事实与证据|
|---|---|
|artifact 存储位置|语义工具结果存在 `SessionContextStore`：`core/context_store.py:65-71`；内部 `_store/_history/_current_turn_results` 在 `:102-107`。前端交付物另存在 `TaskState.artifact_memory_state`：`core/task_state.py:298`，由 `_record_delivered_artifacts` 更新：`core/router.py:2708-2742`。|
|成功后写入|state loop 执行成功/失败后均 append tool_result，并调用 context store：`core/router.py:10960-10972` 片段 `self._save_result_to_session_context(tool_call.name, result)`；函数内部 `add_current_turn_result`：`core/router.py:812-815`。|
|下游查找|`_prepare_tool_arguments` 对 `render_spatial_map/calculate_dispersion/analyze_hotspots` 调 `context_store.get_result_for_tool(...)` 并注入 `_last_result`：`core/router.py:897-913`。|
|写入 key vs 查找 key|写入映射 `TOOL_TO_RESULT_TYPE`：macro/micro -> `emission`，dispersion -> `dispersion`，hotspot -> `hotspot`，见 `core/context_store.py:76-86`；查找依赖 `TOOL_DEPENDENCIES`：dispersion 需 `emission`，hotspots 需 `dispersion`，见 `:88-99`；实际 key 由 `_store_key_for_result` 生成 `result_type:label`，dispersion 加 pollutant，见 `core/context_store.py:539-556`。|
|持久化缺口|`SessionContextStore.from_dict` 只恢复 compact metadata，`data={}`：`core/context_store.py:477-499`；本轮未发现 `data/sessions/*router_state*` 下有 eval_e2e 文件。UNKNOWN: session history 未保留完整 context store。|

### 8.2 Dependency Check / Readiness 评估

- `dependency_blocked` 产生于 `_validate_execution_dependencies`：`core/router.py:9190-9245`；当 `validate_tool_prerequisites` 非 valid 时 trace 类型为 `DEPENDENCY_BLOCKED`。底层缺失 token 逻辑见 `core/tool_dependencies.py:181-265`。
- `action_readiness_repairable` 由 `_record_action_readiness_trace` 映射 `ReadinessStatus.REPAIRABLE` 产生：`core/router.py:9773-9812`。REPAIRABLE 条件包括缺字段、缺依赖、缺 geometry、缺 spatial payload：`core/readiness.py:1027-1042`, `1117-1140`, `1142-1157`, `1159-1177`。
- readiness 是否调 LLM：未见 LLM 调用；`build_readiness_assessment` 只遍历 action catalog 并调用 `assess_action_readiness`：`core/readiness.py:1217-1296`。prompt：N/A。
- `plan_repair_skipped`：当 `_should_attempt_plan_repair` 返回 false 或 repair decision 保持原 plan 时记录；见 `core/router.py:10760-10767`, `10927-10935`, `9147-9157`。默认跳过原因可为 feature flag 关闭：`core/router.py:8934-8944`；默认配置 `ENABLE_BOUNDED_PLAN_REPAIR=false`：`config.py:75-76`。

### 8.3 Geometry 生命周期

- geometry 在文件上下文中以 `FileContext.spatial_metadata/spatial_context/columns` 保存：`core/task_state.py:140-183`；`update_file_context` 写入 `spatial_metadata` 和 `spatial_context`：`core/task_state.py:930-954`。成功工具结果若含 geometry/raster/hotspots，则写 legacy `fact_memory.last_spatial_data`：`core/router.py:826-861`。
- geometry readiness 判断顺序：file `spatial_metadata`、`spatial_context`、geospatial dataset、geometry-like columns、emission result geometry；见 `core/readiness.py:413-445`。
- `geometry_re_grounding_failed` 产生点：无 primary file `core/router.py:6939-6954`；support file 类型不支持 `:7029-7063`；support file 未建立 geometry `:7077-7100`；readiness refresh 后仍 not READY `:7240-7275`。
- L12/L36/L39 session history：`data/sessions/history/eval_e2e_multistep_002.json`、`006.json`、`010.json`。三者 final fact_memory 均为 `last_spatial_data=null`，`file_analysis.spatial_metadata={}`；L12/L39 columns=`["link_id","length","flow","speed"]`，L36 columns=`["time","speed"]`。working_memory 文本均含 `目标字段: geometry` 与 `geometry_re_grounding_failed` 对应的失败文案。UNKNOWN: session history 只有最终 fact_memory 与 working_memory，不保存逐步 geometry 字段 diff。

### 8.4 具体失败 case 的 session trace 还原

|case|第1步结果|第2步前状态|第2步失败|第1步 artifact 去向|
|---|---|---|---|---|
|L14 e2e_multistep_004|history fact `last_tool_name=calculate_macro_emission`, `last_tool_snapshot` keys=`query_info/summary/fleet_mix_fill/download_file`；无 tool_calls|`last_result=null`, `last_spatial_data=null`|log L14 `dependency_blocked`; `plan_repair_skipped`|E. UNKNOWN：session 未保留 context store；只见 compact snapshot|
|L36 e2e_multistep_006|history wm tool `calculate_micro_emission` success=true，data keys=`query_info/summary/download_file`|`last_spatial_data=null`, file columns=`time/speed`|log L36 text `missing prerequisite results: emission` 后 geometry failed|E. UNKNOWN：有 compact result，但无 context store 证据|
|L37 e2e_multistep_008|history wm tool `calculate_macro_emission` success=true，data keys含 `scenario_label/download_file`|`last_tool_snapshot` compact；`last_spatial_data=null`|log L37 `dependency_blocked`; `plan_repair_skipped`|E. UNKNOWN：完整 semantic store 未持久化|
|L39 e2e_multistep_010|history wm tool `calculate_macro_emission` success=true|`last_result=null`, `last_spatial_data=null`|log L39 `missing prerequisite results: emission` 与 geometry failed|E. UNKNOWN|
|L40 e2e_multistep_011|history wm tool `calculate_macro_emission` success=true|`last_tool_snapshot` compact；`last_spatial_data=null`|log L40 `dependency_blocked`; `plan_repair_skipped`|E. UNKNOWN|
|L12 e2e_multistep_002|history wm tool `calculate_macro_emission` success=true|file columns 无 geometry；`spatial_metadata={}`|log L12 `geometry_re_grounding_failed`; missing geometry|E. UNKNOWN：artifact 存在片段，但 geometry 本身缺失|
|L89 e2e_multistep_043|history wm tools：micro success=true；render success=false|micro data keys=`query_info/summary/download_file`，无 spatial payload|render summary=`Map rendering failed - no spatial data found`|E. UNKNOWN：artifact 未消失；结果 schema 不含 geometry，选项不覆盖|

## Section 9：B 类 + C 类的工具决策错误形态

LLM tool choice 思维字段：**UNKNOWN: 日志未保留该字段**。证据：eval record 只写 `actual.tool_chain/tool_calls/criteria/trace_step_types` 等，见 `evaluation/eval_end2end.py:578-590`；session history保存 user/assistant/tool_calls，见 `core/memory.py:491-525`。

|case|用户原文|expected vs actual|最终回复片段|归类|
|---|---|---|---|---|
|e2e_incomplete_002@L17|查询2020年乘用车排放因子|[] vs query_emission_factors|`已成功查询...CO₂、NOₓ、PM₂.₅`|C4. 其他|
|e2e_constraint_005@L25|冬季NOx排放，再用summer_day扩散|macro,disp vs macro,macro,knowledge|`当前文件缺少关键的空间几何信息`|B2. 多调工具|
|e2e_incomplete_008@L45|查家用车的NOx排放因子|[] vs factors|`已为您查询到...NOx排放因子曲线`|C4. 其他|
|e2e_incomplete_011@L48|查一下 CO2 的排放因子|[] vs factors|`已为您查询到小汽车...CO₂排放因子曲线`|C4. 其他|
|e2e_incomplete_013@L50|用这个文件算 NOx 排放|[] vs micro|`已基于...micro_time_speed.csv 完成 NOx 排放计算`|C4. 其他|
|e2e_incomplete_015@L52|查家用车的 NOx 排放因子|[] vs factors|`已为您查询到...NOx排放因子曲线`|C4. 其他|
|e2e_constraint_013@L63|查摩托车在高架上的CO排放因子|[] vs factors|`查询成功...摩托车...快速路（高架）`|C4. 其他|
|e2e_multistep_044@L90|查乘用车和公交车NOx并对比|factors,factors vs factors,factors,factors|`无论输入“公交车”还是“Transit Bus”，都返回了乘用车`|B2. 多调工具|
|e2e_ambiguous_011@L35|轨迹文件里家用车CO2排放|micro vs []|`已根据...micro_time_speed.csv...完成...9.88克`|C4. 其他|
|e2e_ambiguous_020@L66|轻型客货车城市道路NOx因子|factors vs []|`请先确认道路类型`|C1. LLM 认为缺条件不调工具|
|e2e_simple_037@L83|Calculate NOx emissions for this road network file|macro vs []|`已完成NOx排放计算...67.40 g/小时`|C4. 其他|
|e2e_ambiguous_038@L84|heavy truck on highway emission factor|factors vs []|`I've already retrieved...`|C4. 其他|

### 9.X 汇总

|类别|count|占比|
|---|---:|---:|
|B1 工具语义混淆|0|0.0%|
|B2 多调工具|2|16.7%|
|B3 跳过前置工具|0|0.0%|
|C1 认为缺条件不调工具|1|8.3%|
|C2 知识性回答未调 query_knowledge|0|0.0%|
|C3 误判闲聊|0|0.0%|
|C4 其他|9|75.0%|

文件缺失导致的 B/C case：0/12。证据：需要文件的 B/C 样本均有 `test_file`（L50 micro、L83 macro、L35 micro），其余 factors/constraint/incomplete 样本 benchmark 不要求文件：`evaluation/benchmarks/end2end_tasks.jsonl:17,35,45,48,50,52,63,66,83,84,90`。

B 类最高频混淆对：`expected [] -> actual query_emission_factors` 共 5 次（L17/L45/L48/L52/L63）；证据见 `evaluation/results/end2end_full_v2/end2end_logs.jsonl:17,45,48,52,63`。
