# Phase 1.7 Diagnosis

## Incomplete Failures (v7 source)

### Case e2e_incomplete_001
- 用户原文: 查询2020年CO2排放因子
- 预期 criteria: {"tool_executed": false, "requires_user_response": true, "result_has_data": false}
- 实际行为:
  - actual_tools: ['query_emission_factors']
  - 最终回复前 200 字: 已查询到2020年小汽车的CO2排放因子数据（基于夏季、快速路条件）：

- **最低排放**：约168 g/km（在速度约55 km/h时）
- **典型城市工况**（30 km/h）：约195 g/km
- **高速工况**（100 km/h）：约185 g/km

该结果使用了默认的季节（夏季）和道路类型（快速路）参数。如果您需要其他车辆类型（如公交车、货车）、不同季节或道路类型的排放因子，
  - turn 数: 1
- AO lifecycle events: [(2, 'create', 'AO#1'), (1, 'activate', 'AO#1'), (2, 'append_tool_call', 'AO#1'), (2, 'complete', 'AO#1')]
- Classifier 每 turn 判定: [(2, 'rule_layer1', 'NEW_AO', 'first_message_in_session')]
- 失败原因归类: I4_OTHER
  - 说明: v7 log 中单轮 incomplete task 出现 `create AO#2` / classifier turn>1（如 turn=2/3），说明 E 组并不是干净首轮；结合 matrix runner 当时未清空 `eval_*.json`，归因为 A->E 组间 session 复用。

### Case e2e_incomplete_002
- 用户原文: 查询2020年乘用车排放因子
- 预期 criteria: {"tool_executed": false, "requires_user_response": true, "result_has_data": false}
- 实际行为:
  - actual_tools: ['query_emission_factors']
  - 最终回复前 200 字: 已成功查询到2020年乘用车的排放因子数据，包含CO2、NOx和PM2.5三种污染物。

**查询条件：**
- 车辆类型：乘用车
- 车型年份：2020年  
- 季节：夏季（系统默认）
- 道路类型：快速路（系统默认）

数据显示了各污染物排放因子随车速变化的完整曲线。如需查看具体数值表格、切换为地面道路条件、更改季节，或查询其他污染物（如CO、THC等），请随时告诉我。

您也可以基于这些排
  - turn 数: 1
- AO lifecycle events: [(2, 'create', 'AO#2'), (1, 'activate', 'AO#2'), (2, 'append_tool_call', 'AO#2'), (2, 'complete', 'AO#2')]
- Classifier 每 turn 判定: [(2, 'rule_layer1', 'NEW_AO', 'no_active_ao_no_revision_signal')]
- 失败原因归类: I4_OTHER
  - 说明: v7 log 中单轮 incomplete task 出现 `create AO#2` / classifier turn>1（如 turn=2/3），说明 E 组并不是干净首轮；结合 matrix runner 当时未清空 `eval_*.json`，归因为 A->E 组间 session 复用。

### Case e2e_incomplete_011
- 用户原文: 查一下 CO2 的排放因子
- 预期 criteria: {"tool_executed": false, "requires_user_response": true, "result_has_data": false}
- 实际行为:
  - actual_tools: ['query_emission_factors']
  - 最终回复前 200 字: 已查询到 **小汽车（2020年款）** 在 **夏季、快速路** 条件下的 **CO₂ 排放因子曲线**：

- CO₂ 排放随车速变化，在 **中等车速（约 40–70 km/h）** 时排放最低；
- 车速过低（<20 km/h）或过高（>90 km/h）时，单位距离 CO₂ 排放量上升。

📊 您可以通过下方图表查看详细的速度-排放关系，数据表也已生成。

> 💡 **说明**：本次查询使
  - turn 数: 1
- AO lifecycle events: [(2, 'create', 'AO#1'), (1, 'activate', 'AO#1'), (2, 'append_tool_call', 'AO#1'), (2, 'complete', 'AO#1')]
- Classifier 每 turn 判定: [(2, 'rule_layer1', 'NEW_AO', 'first_message_in_session')]
- 失败原因归类: I4_OTHER
  - 说明: v7 log 中单轮 incomplete task 出现 `create AO#2` / classifier turn>1（如 turn=2/3），说明 E 组并不是干净首轮；结合 matrix runner 当时未清空 `eval_*.json`，归因为 A->E 组间 session 复用。

### Case e2e_incomplete_013
- 用户原文: 用这个文件算 NOx 排放
- 预期 criteria: {"tool_executed": false, "requires_user_response": true, "result_has_data": false}
- 实际行为:
  - actual_tools: ['calculate_micro_emission']
  - 最终回复前 200 字: 已基于您提供的微观轨迹文件计算了 NOx 排放，结果如下：

**总排放量：**  
- **NOx: 0.00 克**

**运行统计：**  
- 总距离：0.03 公里  
- 总时间：6 秒  
- 平均速度：18.6 km/h  

**说明：**  
本次计算使用了以下默认参数（如需调整请告知）：
- 车辆类型：小汽车
- 车型年份：2020 年
- 季节：夏季

由于轨迹时间很短（仅
  - turn 数: 1
- AO lifecycle events: [(2, 'create', 'AO#1'), (2, 'activate', 'AO#1'), (2, 'append_tool_call', 'AO#1'), (2, 'complete', 'AO#1')]
- Classifier 每 turn 判定: [(3, 'rule_layer1', 'NEW_AO', 'first_message_in_session')]
- 失败原因归类: I4_OTHER
  - 说明: v7 log 中单轮 incomplete task 出现 `create AO#2` / classifier turn>1（如 turn=2/3），说明 E 组并不是干净首轮；结合 matrix runner 当时未清空 `eval_*.json`，归因为 A->E 组间 session 复用。

## Multi-step Failures (v7 source)

### Case e2e_multistep_001
- 用户原文: 请先计算这个路网文件的CO2排放，再做扩散分析
- 预期工具链: ['calculate_macro_emission', 'calculate_dispersion']
- 实际工具链: []
- 最终回复前 200 字: 🌤 **扩散气象条件 — 当前默认配置**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 风向 | 西南风（SW） | 典型城市夏季主导风向 |
| 风速 | 2.5 m/s | 中等强度 |
| 大气稳定度 | 强不稳定（A类） | 白天强对流，扩散快 |
| 混合层高度 | 1000 m | 夏季白天典型值 |
| 适用场景 | 城市夏季白天 | 
- turn 数: 2
- AO lifecycle events: [(5, 'create', 'AO#2'), (5, 'activate', 'AO#2'), (5, 'complete_blocked', 'AO#2'), (6, 'complete_blocked', 'AO#2')]
- Classifier 每 turn 判定: [(6, 'rule_layer1', 'NEW_AO', 'no_active_ao_no_revision_signal'), (7, 'llm_layer2', 'CONTINUATION', "用户当前消息明确指向 active 的 AO#2（'请先计算这个路网文件的CO2排放，再做扩散分析'），且使用'开始，按默认参数继续执行这个完整流程：calculate_macro_emission -> calculate_dispersion'，属于对当前 active AO 的确认与执行指令，补全此前因缺失 geometry 而中断的工具链。无参数修改、无新目标引入、未引用已完成 AO#legacy 的结果，故非 REVISION 或 NEW_AO。")]
- 失败原因归类: M4_OTHER
  - 说明: v7 log 中存在 `AO#2`、classifier turn>6、以及 continuation 基于已存在 active AO 的判定；这些都要求 session 已有历史，不符合干净 benchmark 首轮。主因归为 A->E 组间 session 复用。

### Case e2e_multistep_002
- 用户原文: 先算这份路网文件的NOx排放，再做扩散，然后找热点
- 预期工具链: ['calculate_macro_emission', 'calculate_dispersion', 'analyze_hotspots']
- 实际工具链: []
- 最终回复前 200 字: 🌤 **扩散气象条件 — 当前默认配置**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 风向 | 西南风（SW） | 典型城市夏季主导风向 |
| 风速 | 2.5 m/s | 中等强度 |
| 大气稳定度 | 强不稳定（A类） | 白天强对流，扩散快 |
| 混合层高度 | 1000 m | 夏季白天典型值 |
| 适用场景 | 城市夏季白天 | 
- turn 数: 2
- AO lifecycle events: [(6, 'create', 'AO#2'), (6, 'activate', 'AO#2'), (6, 'complete_blocked', 'AO#2'), (7, 'complete_blocked', 'AO#2')]
- Classifier 每 turn 判定: [(7, 'rule_layer1', 'NEW_AO', 'no_active_ao_no_revision_signal'), (8, 'llm_layer2', 'CONTINUATION', "用户明确指向当前 active 的 AO#2（'先算这份路网文件的NOx排放，再做扩散，然后找热点'），且当前 AO 处于等待扩散气象确认后的执行阶段；'开始，按默认参数继续执行这个完整流程' 是对已激活 AO 的工具链推进指令，属于补全执行动作，而非修改或新建目标。")]
- 失败原因归类: M4_OTHER
  - 说明: v7 log 中存在 `AO#2`、classifier turn>6、以及 continuation 基于已存在 active AO 的判定；这些都要求 session 已有历史，不符合干净 benchmark 首轮。主因归为 A->E 组间 session 复用。

### Case e2e_multistep_003
- 用户原文: 计算这个中文路网文件的CO2排放并在地图上展示
- 预期工具链: ['calculate_macro_emission', 'render_spatial_map']
- 实际工具链: ['calculate_macro_emission']
- 最终回复前 200 字: 输入补全 / Input Completion
当前动作 `run_macro_emission` 还不能直接执行。
原因: 当前还不能安全执行macro_emission计算，因为关键输入字段尚未齐备：交通流量(traffic_flow_vph)。
目标字段: `traffic_flow_vph`
任务类型: `macro_emission`
文件上下文: task_type=macro_emi
- turn 数: 4
- AO lifecycle events: [(5, 'create', 'AO#2'), (5, 'activate', 'AO#2'), (5, 'complete_blocked', 'AO#2'), (6, 'append_tool_call', 'AO#2'), (6, 'complete_blocked', 'AO#2'), (7, 'complete_blocked', 'AO#2'), (8, 'complete_blocked', 'AO#2')]
- Classifier 每 turn 判定: [(6, 'rule_layer1', 'NEW_AO', 'no_active_ao_no_revision_signal'), (7, 'rule_layer1', 'CONTINUATION', 'active_input_completion'), (8, 'llm_layer2', 'CONTINUATION', "用户说'继续把刚才的结果渲染成地图'，当前active AO#2的目标是'计算CO2排放并在地图上展示'，且已成功完成calculate_macro_emission（产出emission:baseline），但render_spatial_map因缺失geometry被阻断；此消息明确要求推进同一AO的后续步骤（即执行render_spatial_map），属于对active AO的工具链延续，而非修改参数或开启新目标。"), (9, 'llm_layer2', 'CONTINUATION', "用户当前消息'继续把刚才的结果渲染成地图'明确指向 active 的 AO#2（其 objective_text 是'计算这个中文路网文件的CO2排放并在地图上展示'），且该 AO 已完成 calculate_macro_emission，但 render_spatial_map 尚未执行（因此前提示缺少地理坐标）。用户意图是补全工具链，继续执行缺失的可视化步骤，属于对当前 active AO 的流程延续，而非修改参数（非 REVISION）或启动新目标（非 NEW_AO）。")]
- 失败原因归类: M4_OTHER
  - 说明: v7 log 中存在 `AO#2`、classifier turn>6、以及 continuation 基于已存在 active AO 的判定；这些都要求 session 已有历史，不符合干净 benchmark 首轮。主因归为 A->E 组间 session 复用。

### Case e2e_multistep_004
- 用户原文: 先算这个非标准列名路网文件的CO2排放，再做扩散图
- 预期工具链: ['calculate_macro_emission', 'calculate_dispersion']
- 实际工具链: ['calculate_macro_emission']
- 最终回复前 200 字: Cannot execute calculate_dispersion because missing prerequisite results: emission. This turn stops before tool execution.

输入补全 / Input Completion
当前动作 `run_macro_emission` 还不能直接执行。
原因: 当前还不能安全执行macr
- turn 数: 4
- AO lifecycle events: [(5, 'create', 'AO#2'), (5, 'activate', 'AO#2'), (5, 'complete_blocked', 'AO#2'), (6, 'complete_blocked', 'AO#2'), (7, 'append_tool_call', 'AO#2'), (7, 'complete_blocked', 'AO#2'), (8, 'complete_blocked', 'AO#2')]
- Classifier 每 turn 判定: [(6, 'rule_layer1', 'NEW_AO', 'no_active_ao_no_revision_signal'), (7, 'llm_layer2', 'CONTINUATION', "用户当前消息明确指向 active 的 AO#2（'先算这个非标准列名路网文件的CO2排放，再做扩散图'），且指令'按默认参数继续执行这个完整流程：calculate_macro_emission -> calculate_dispersion' is a direct continuation of the pending AO — it reiterates intent to complete the two-step chain, acknowledges missing prerequisites (emission result), and authorizes executing the first tool (calculate_macro_emission) to unblock the chain. No parameter revision or new objective is introduced."), (8, 'rule_layer1', 'CONTINUATION', 'active_input_completion'), (9, 'llm_layer2', 'CONTINUATION', "用户当前消息'继续基于刚才的排放结果做扩散分析'明确指向 active 的 AO#2（其 objective_text 包含'再做扩散图'，且已成功完成 calculate_macro_emission），当前处于工具链第二步（calculate_dispersion）等待触发状态；无参数修改、无新目标引入，纯属推进已有 active AO 的后续步骤。")]
- 失败原因归类: M4_OTHER
  - 说明: v7 log 中存在 `AO#2`、classifier turn>6、以及 continuation 基于已存在 active AO 的判定；这些都要求 session 已有历史，不符合干净 benchmark 首轮。主因归为 A->E 组间 session 复用。

### Case e2e_multistep_010
- 用户原文: 用这个路网算NOx排放，做扩散，再找热点
- 预期工具链: ['calculate_macro_emission', 'calculate_dispersion', 'analyze_hotspots']
- 实际工具链: []
- 最终回复前 200 字: 🌤 **扩散气象条件 — 当前默认配置**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 风向 | 西南风（SW） | 典型城市夏季主导风向 |
| 风速 | 2.5 m/s | 中等强度 |
| 大气稳定度 | 强不稳定（A类） | 白天强对流，扩散快 |
| 混合层高度 | 1000 m | 夏季白天典型值 |
| 适用场景 | 城市夏季白天 | 
- turn 数: 2
- AO lifecycle events: [(6, 'create', 'AO#2'), (6, 'activate', 'AO#2'), (6, 'complete_blocked', 'AO#2'), (7, 'complete_blocked', 'AO#2')]
- Classifier 每 turn 判定: [(7, 'rule_layer1', 'NEW_AO', 'no_active_ao_no_revision_signal'), (8, 'llm_layer2', 'CONTINUATION', "用户明确指向当前 active 的 AO#2（'用这个路网算NOx排放，做扩散，再找热点'），且当前状态为 active、未完成；新消息'开始，按默认参数继续执行这个完整流程...' 是对已启动分析链的确认与推进，属于补全执行意图、触发工具链调用，无参数修改或新目标引入。")]
- 失败原因归类: M4_OTHER
  - 说明: v7 log 中存在 `AO#2`、classifier turn>6、以及 continuation 基于已存在 active AO 的判定；这些都要求 session 已有历史，不符合干净 benchmark 首轮。主因归为 A->E 组间 session 复用。

### Case e2e_multistep_041
- 用户原文: 冬季路网先算CO2，再按urban_winter_day气象跑扩散看看
- 预期工具链: ['calculate_macro_emission', 'calculate_dispersion']
- 实际工具链: []
- 最终回复前 200 字: 🌤 **扩散气象条件 — 当前默认配置**

| 参数 | 默认值 | 说明 |
|------|--------|------|
| 风向 | 西北风（315°） | 城市冬季白天主导风向 |
| 风速 | 3.0 m/s | 中等偏强 |
| 大气稳定度 | 不稳定（U类） | 冬季白天对流较强，扩散条件较好 |
| 混合层高度 | 800 m | 冬季白天典型值 |
| 适用场景 | 城市冬
- turn 数: 2
- AO lifecycle events: [(5, 'create', 'AO#2'), (5, 'activate', 'AO#2'), (5, 'complete_blocked', 'AO#2'), (6, 'complete_blocked', 'AO#2')]
- Classifier 每 turn 判定: [(6, 'rule_layer1', 'NEW_AO', 'no_active_ao_no_revision_signal'), (7, 'llm_layer2', 'CONTINUATION', "当前存在 active AO#2（'冬季路网先算CO2，再按urban_winter_day气象跑扩散看看'），且用户最新消息明确要求'按默认参数继续执行 calculate_macro_emission -> calculate_dispersion'，属于对同一分析目标的流程推进；虽此前因 geometry 缺失被阻塞，但用户未修改目标、未切换参数、未放弃当前 AO，而是重申执行意图，符合 CONTINUATION 定义。")]
- 失败原因归类: M4_OTHER
  - 说明: v7 log 中存在 `AO#2`、classifier turn>6、以及 continuation 基于已存在 active AO 的判定；这些都要求 session 已有历史，不符合干净 benchmark 首轮。主因归为 A->E 组间 session 复用。

### Case e2e_multistep_044
- 用户原文: 查一下乘用车和公交车的NOx排放因子，帮我对比
- 预期工具链: ['query_emission_factors', 'query_emission_factors']
- 实际工具链: ['query_emission_factors', 'query_emission_factors', 'query_emission_factors', 'query_emission_factors']
- 最终回复前 200 字: 我发现系统在查询“Transit Bus”（公交车）时，仍然返回了“Passenger Car”（乘用车）的排放因子数据，这表明当前数据库可能对公交车类型的识别存在限制。

不过，基于已获取的数据，我可以为您总结**2020年乘用车在夏季快速路上的NOx排放特性**，并说明与公交车的典型差异：

### 乘用车（Passenger Car, 2020年）NOx排放因子特征：
- **最低排放速度*
- turn 数: 1
- AO lifecycle events: [(2, 'create', 'AO#2'), (1, 'activate', 'AO#2'), (2, 'append_tool_call', 'AO#2'), (2, 'append_tool_call', 'AO#2'), (2, 'append_tool_call', 'AO#2'), (2, 'append_tool_call', 'AO#2'), (2, 'complete', 'AO#2')]
- Classifier 每 turn 判定: [(2, 'rule_layer1', 'NEW_AO', 'no_active_ao_no_revision_signal')]
- 失败原因归类: M4_OTHER
  - 说明: v7 log 中存在 `AO#2`、classifier turn>6、以及 continuation 基于已存在 active AO 的判定；这些都要求 session 已有历史，不符合干净 benchmark 首轮。主因归为 A->E 组间 session 复用。

## Distribution Summary

| 类型 | Count | 代表 task_id |
|---|---:|---|
| I4_OTHER | 4 | e2e_incomplete_001, e2e_incomplete_002, e2e_incomplete_011 |
| M4_OTHER | 7 | e2e_multistep_001, e2e_multistep_002, e2e_multistep_003 |

结论：v7 的 incomplete / multi_step regression 主因是 matrix runner 在 A 组和 E 组之间复用了相同 `eval_<task_id>` session history。
