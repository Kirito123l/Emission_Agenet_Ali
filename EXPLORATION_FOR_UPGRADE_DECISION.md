# Contract-First Governance 升级前代码库探索

## Section 1：现有五级参数标准化流水线的事实

1.1 入口与层级：executor 在工具执行前调用标准化，`core/executor.py:219-224` 片段：`standardized_args, std_records = self._standardize_arguments(...)`；`core/executor.py:340-346` 片段：`self._std_engine.standardize_batch(params=arguments, tool_name=tool_name)`。总流水线写在 `services/standardization_engine.py:10-11`：`exact -> alias -> fuzzy -> LLM -> default -> abstain`。

五级对应函数与阈值：

|层级|函数/位置|命中阈值|
|---|---|---|
|exact/alias|`RuleBackend.standardize` 分发到 `standardize_vehicle_detailed` 等；`services/standardization_engine.py:207-214`|exact `confidence=1.0`，alias `0.95`；如 `services/standardizer.py:252-255`|
|fuzzy|vehicle/pollutant/season/road/meteorology/stability 的 fuzzy 分支；`services/standardizer.py:273`, `342`, `413`, `462`, `523`, `574`|vehicle 70；pollutant 80；season/road 60；meteorology/stability 75。配置表见 `services/standardization_engine.py:47-54`|
|LLM|`StandardizationEngine.standardize` 调用 model backend；`services/standardization_engine.py:546-558`|model 返回候选且 success；`services/model_backend.py:149-155` 片段：`strategy="llm"`，confidence 上限 `0.95`|
|default|season/road 空值或不匹配默认；`services/standardizer.py:384-390`, `422-428`, `433-439`, `471-477`|season=`夏季`，road_type=`快速路`；默认置信度空值 1.0，不匹配 fallback 0.5|
|abstain|不能标准化时返回失败；`services/standardization_engine.py:563-570`|`success=False`, `strategy="abstain"`|

1.2 失败路径：`standardize_batch` 在低置信或失败时抛 `BatchStandardizationError`：`services/standardization_engine.py:610-620`, `627-641`。executor 捕获后返回 `success=False`, `error_type="standardization"`, `negotiation_eligible`：`core/executor.py:231-249`。router 若可协商则进入参数确认：`core/router.py:11007-11017`；否则进入 clarification：`core/router.py:11019-11044`。低置信触发条件：`services/standardization_engine.py:943-956`，片段：`result.confidence < self._parameter_negotiation_threshold()`；阈值来自 `config.py:215-217`，默认 `0.85`。

1.3 `unified_mappings.yaml` 统计口径：仅统计 `aliases` 字段；中文=含 CJK 字符，英文=无 CJK 且含 A-Z。YAML 证据入口：`vehicle_types:` `config/unified_mappings.yaml:9`，`pollutants:` `:213`，`seasons:` `:263`，`road_types:` `:289`，`meteorology:` `:326`，`stability_classes:` `:375`。

|维度|标准名数|aliases min/median/max|中文/英文 aliases|aliases 最少样本|
|---|---:|---:|---:|---|
|vehicle_type|13|2/4/13|42/17|Combination Short-haul Truck=2；Refuse Truck=2|
|pollutant|6|2/3.0/4|5/13|CO=2；PM10=2|
|season|4|3/3.0/4|8/5|冬季=3；夏季=3|
|road_type|5|4/5/6|9/15|快速路=4；次干道=4|
|meteorology|6|5/5.5/7|19/15|urban_summer_night=5；urban_winter_day=5|
|stability_class|6|6/6.0/7|7/31|N1=6；N2=6|

1.4 `cross_constraints.yaml`：constraint 条目 4；具体组合规则 9，其中 blocked 1、warning 8。证据：`config/cross_constraints.yaml:3-8` 定义 constraints；`services/cross_constraints.py:123-158` 将 `blocked_combinations` 放入 violations，将 `consistency_warning`/`conditional_warning` 放入 warnings。

|constraint|type|具体组合数|覆盖维度|
|---|---|---:|---|
|vehicle_road_compatibility|blocked_combinations|1|vehicle_type, road_type|
|vehicle_pollutant_relevance|conditional_warning|2|vehicle_type, pollutants|
|pollutant_task_applicability|conditional_warning|2|pollutant, tool_name|
|season_meteorology_consistency|consistency_warning|4|season, meteorology|

引用文件：`core/executor.py`; `services/standardization_engine.py`; `services/standardizer.py`; `services/model_backend.py`; `core/router.py`; `config.py`; `config/unified_mappings.yaml`; `config/cross_constraints.yaml`; `services/cross_constraints.py`。

## Section 2：Full System benchmark 失败的实际分布

2.1 `evaluation/results/end2end_full_v2/end2end_logs.jsonl` 共 100 条，失败 41。失败分布：parameter_ambiguous=10，multi_step=10，constraint_violation=10，incomplete=7，simple=4。证据：metrics 文件 `evaluation/results/end2end_full_v2/end2end_metrics.json:1-18` 片段：`"tasks": 100`, `"completion_rate": 0.59`；失败行见下表。

2.2 失败 case 提取。状态规则：`error` 非空=errored；`final_stage=DONE`=completed；其他=incomplete。阶段证据为 `eval_router_turns/final_stage`；UNKNOWN：该 JSONL 只保留 `trace_step_types`，不保留每步 `stage_before/stage_after`。

|case|status|expected->actual|std|turn/stage|类|user|
|---|---|---|---|---|---|---|
|e2e_simple_004@L4|completed|macro->macro|pollutants exact ok|1/DONE|F|计算这个路段流量文件的CO2和NOx排放|
|e2e_ambiguous_001@L6|completed|factors->factors|vehicle 家用车->Passenger Car(llm)|1/DONE|F|查询2020年家用车的CO2排放因子|
|e2e_ambiguous_003@L8|incomplete|macro->[]|无记录|1/NEEDS_INPUT_COMPLETION|E|请分析这份路网文件里重卡的CO2排放|
|e2e_ambiguous_005@L10|incomplete|macro->[]|无记录|1/NEEDS_INPUT_COMPLETION|E|分析这个非标准列名路段文件的细颗粒物排放|
|e2e_multistep_002@L12|incomplete|macro,disp,hotspots->[]|NOx exact ok|5/NEEDS_INPUT_COMPLETION|E|先算这份路网文件的NOx排放，再做扩散，然后找热点|
|e2e_multistep_004@L14|completed|macro,disp->[]|CO2+disp warning|2/DONE|E|先算这个非标准列名路网文件的CO2排放，再做扩散图|
|e2e_incomplete_002@L17|completed|[]->factors|vehicle/pollutants exact ok|1/DONE|B|查询2020年乘用车排放因子|
|e2e_incomplete_003@L18|completed|[]->[]|无记录|1/DONE|F|帮我做扩散分析|
|e2e_constraint_001@L21|completed|[]->[]|无记录|1/DONE|F|查询2020年摩托车在高速公路上的CO2排放因子|
|e2e_constraint_003@L23|completed|[]->[]|无记录|1/DONE|F|查询2020年motorcycle在motorway上的NOx排放因子|
|e2e_constraint_005@L25|completed|macro,disp->macro,macro,knowledge|NOx/season/met exact ok|1/DONE|B|请计算这个路网文件冬季条件下的NOx排放，再用urban_summer_day做扩散|
|e2e_simple_011@L29|incomplete|factors->[]|vehicle fuzzy 0.80 -> confirmation|1/NEEDS_PARAMETER_CONFIRMATION|A|查询2022年长途货运卡车在秋季主干道的NOx排放因子|
|e2e_ambiguous_011@L35|completed|micro->[]|无记录|1/DONE|C|帮我算一下这个轨迹文件里家用车的CO2排放|
|e2e_multistep_006@L36|incomplete|micro,disp,hotspots->[]|Taxi->Passenger Car(llm)|5/NEEDS_INPUT_COMPLETION|E|这是我刚录的出租车轨迹，算一下NOx排放，然后做扩散模拟，再找出污染最严重的区域|
|e2e_multistep_008@L37|completed|macro,disp->[]|CO2+disp warning|2/DONE|E|这个路网文件列名不太标准，帮我算CO2排放，然后做扩散|
|e2e_multistep_010@L39|incomplete|macro,disp,hotspots->[]|NOx exact ok|5/NEEDS_INPUT_COMPLETION|E|用这个路网算NOx排放，做扩散，再找热点|
|e2e_multistep_011@L40|completed|macro,disp,map->[]|无记录|2/DONE|E|计算路网的NOx和PM2.5排放，对NOx做扩散，对PM2.5画地图|
|e2e_incomplete_008@L45|completed|[]->factors|家用车->Passenger Car(llm)|1/DONE|B|查家用车的NOx排放因子|
|e2e_incomplete_011@L48|completed|[]->factors|小汽车 alias ok|1/DONE|B|查一下 CO2 的排放因子|
|e2e_incomplete_013@L50|completed|[]->micro|小汽车 alias ok|1/DONE|B|用这个文件算 NOx 排放|
|e2e_incomplete_014@L51|completed|[]->[]|无记录|1/DONE|F|做一次 PM2.5 的扩散模拟|
|e2e_incomplete_015@L52|completed|[]->factors|家用车->Passenger Car(llm)|1/DONE|B|查家用车的 NOx 排放因子|
|e2e_incomplete_017@L54|errored|[]->[]|无记录|None/None|D|用 urban_summer_day 做一次扩散|
|e2e_incomplete_018@L55|completed|[]->[]|无记录|1/DONE|F|查冬季的 CO2 排放因子|
|e2e_constraint_006@L56|completed|[]->[]|无记录|1/DONE|F|查询2022年摩托车在高速公路的CO2排放因子|
|e2e_constraint_007@L57|incomplete|macro,disp->[]|NOx/season/met exact ok|4/NEEDS_INPUT_COMPLETION|E|计算这份路网冬季的NOx排放，并用urban_summer_day气象做扩散|
|e2e_constraint_008@L58|incomplete|micro,disp->[]|Taxi->Passenger Car(llm); warning|4/NEEDS_INPUT_COMPLETION|E|用我上传的夏季出租车轨迹算CO2排放，再用urban_winter_night做扩散|
|e2e_constraint_010@L60|completed|[]->[]|无记录|1/DONE|F|查一下2023年摩托车在高速公路的PM2.5排放因子|
|e2e_constraint_013@L63|completed|[]->factors|all exact ok|1/DONE|B|查摩托车在高架上的CO排放因子|
|e2e_constraint_014@L64|incomplete|micro,disp->[]|vehicle/pollutant/season/met exact ok|4/NEEDS_INPUT_COMPLETION|E|用夏天录的出租车轨迹算PM2.5排放，再用urban_winter_night做扩散|
|e2e_ambiguous_020@L66|completed|factors->[]|无记录|1/DONE|C|轻型客货车在城市道路跑的NOx排放因子多少？|
|e2e_ambiguous_028@L74|incomplete|factors->[]|road 地面道路->支路(fuzzy 0.75)|1/NEEDS_PARAMETER_CONFIRMATION|A|城配货车NOx排放因子查一下|
|e2e_simple_031@L77|completed|factors->factors|exact ok|1/DONE|F|查询2022年半挂短途货车的NOx排放因子|
|e2e_constraint_035@L81|incomplete|macro,disp->[]|THC+disp warning|4/NEEDS_INPUT_COMPLETION|E|用这个路网文件算THC排放，然后做扩散分析|
|e2e_simple_037@L83|completed|macro->[]|无记录|1/DONE|C|Calculate NOx emissions for this road network file|
|e2e_ambiguous_038@L84|completed|factors->[]|无记录|1/DONE|C|What's the emission factor for a heavy truck on the highway?|
|e2e_multistep_043@L89|completed|micro,map->micro,map|小汽车 alias ok; render failed|2/DONE|D|用这个轨迹文件算CO2排放，然后画个地图|
|e2e_multistep_044@L90|completed|factors,factors->factors,factors,factors|exact ok|1/DONE|B|查一下乘用车和公交车的NOx排放因子，帮我对比|
|e2e_multistep_045@L91|completed|knowledge,macro->knowledge,macro|NOx exact ok|1/DONE|F|先查一下NOx相关的排放知识，再用这个文件算排放|
|e2e_constraint_048@L94|incomplete|macro,disp->[]|CO2+disp warning|4/NEEDS_INPUT_COMPLETION|E|用这个路网文件算CO2排放，然后做扩散|
|e2e_multistep_049@L95|completed|macro,disp,hotspots->disp,hotspots|pollutant/met exact ok|1/DONE|E|这个带geometry的6条路网，算NOx后继续扩散并筛热点|

2.3 机械归因规则顺序：D=error 或 tool result success false；A=parameter_negotiation_required 或非 cross 单参失败；E=input_completion/dependency_blocked/geometry_re_grounding_failed/action_readiness_repairable；B=expected empty 但执行工具，或 actual 非空且 tool_chain_match=false；C=expected 非空、actual 空、DONE；F=DONE 后仍 eval fail；否则 G。计数：A=2（e2e_simple_011/e2e_ambiguous_028），B=8（e2e_incomplete_002/e2e_constraint_005/e2e_incomplete_008），C=4（e2e_ambiguous_011/e2e_ambiguous_020/e2e_simple_037），D=2（e2e_incomplete_017/e2e_multistep_043），E=14（e2e_ambiguous_003/e2e_multistep_002/e2e_constraint_048），F=11（e2e_simple_004/e2e_ambiguous_001/e2e_multistep_045），G=0。

2.4 聚焦：
- Simple 4：L4 缺 `season` 于 actual args，result_has_data=true；L29 fuzzy 0.80 触发 confirmation；L77 actual raw `半挂短途货车` 与 expected standard 比较失败但工具成功；L83 无 tool_calls 但文本声称已完成。
- Parameter Ambiguous 10：L6 家用车→LLM 填 `家用车`→Passenger Car(llm)；L8 重卡→无调用/无 std；L10 细颗粒物→无调用/无 std；L35 家用车→无调用/无 std；L45 家用车→Passenger Car(llm) 且执行；L52 同 L45；L63 摩托车/高架→Motorcycle/快速路 exact 且执行；L66 轻型客货车→无调用/无 std；L74 城配货车→vehicle exact，road `地面道路`→`支路` fuzzy 0.75 confirmation；L84 heavy truck/highway→无调用/无 std。
- Multi-Step 10 原始数据见 Section 4。

引用文件：`evaluation/results/end2end_full_v2/end2end_logs.jsonl`; `evaluation/results/end2end_full_v2/end2end_metrics.json`; `evaluation/eval_end2end.py`。

## Section 3：现有标准化在“合法化”这件事上真正漏了什么

3.1 Full System 日志中，去重后单参数标准化最终失败为 0。cross-constraint 失败记录为 4：L22/L24/L59/L62，均为 `vehicle_type+road_type`，original=`Motorcycle | 高速公路`，strategy=`cross_constraint_violation`。证据片段见 `evaluation/results/end2end_full_v2/end2end_logs.jsonl:22`：`"constraint_name":"vehicle_road_compatibility","reason":"摩托车不允许上高速公路"`。

3.2 对这些失败值查 YAML：`Motorcycle` 是标准名，证据 `config/unified_mappings.yaml:10-17`；`高速公路` 是标准名，证据 `config/unified_mappings.yaml:296-302`。分类：不是“别名缺失”；不是“别名有但 fuzzy 不够”；该失败来自 cross constraint，N/A 于单值 enum/alias 分类。

3.3 Full System `standardization_records` 去重统计，排除 cross_constraint 记录，共 204 个参数记录：标准名 exact=194/204=95.1%；合法别名 alias=3/204=1.5%；fuzzy=2/204=1.0%；LLM fallback=5/204=2.5%；单参最终失败=0/204=0.0%。证据：记录字段由 `core/router.py:10979-11005` 写入 trace；日志样本 L6 `vehicle_type 家用车 -> Passenger Car(llm)`，L29 `长途货运卡车 -> Single Unit Long-haul Truck(fuzzy,0.8)`，L48 `小汽车 -> Passenger Car(alias)`。

引用文件：`evaluation/results/end2end_full_v2/end2end_logs.jsonl`; `config/unified_mappings.yaml`; `core/router.py`。

## Section 4：multi_step 失败的逐个解剖

|case|用户原文|期望链|实际链|失败步|类型|证据片段|
|---|---|---|---|---:|---|---|
|e2e_multistep_002@L12|先算这份路网文件的NOx排放，再做扩散，然后找热点|macro,disp,hotspots|[]|2|M6|`final=NEEDS_INPUT_COMPLETION`; `geometry_re_grounding_failed`; 文本含“没有可用于空间分析的几何信息”|
|e2e_multistep_004@L14|先算这个非标准列名路网文件的CO2排放，再做扩散图|macro,disp|[]|2|M3|`action_readiness_repairable`; `dependency_blocked`; `plan_repair_skipped`|
|e2e_multistep_006@L36|出租车轨迹算NOx，再扩散，再找污染最严重区域|micro,disp,hotspots|[]|2|M3|文本含 `missing prerequisite results: emission`; `geometry_re_grounding_failed`|
|e2e_multistep_008@L37|路网文件算CO2排放，然后做扩散|macro,disp|[]|2|M3|`dependency_blocked`; `cross_constraint_warning`; final DONE|
|e2e_multistep_010@L39|路网算NOx排放，做扩散，再找热点|macro,disp,hotspots|[]|2|M3|文本含 `missing prerequisite results: emission`; `geometry_re_grounding_failed`|
|e2e_multistep_011@L40|算NOx/PM2.5，对NOx扩散，对PM2.5画地图|macro,disp,map|[]|2|M3|`intent_resolution_applied`; `dependency_blocked`; final DONE|
|e2e_multistep_043@L89|轨迹文件算CO2，然后画地图|micro,map|micro,map|2|M6|第二工具 `render_spatial_map` result success=false；summary=`Map rendering failed - no spatial data found`|
|e2e_multistep_044@L90|查乘用车和公交车NOx因子并对比|factors,factors|factors,factors,factors|2|M5|实际 3 次 factors；文本含“公交车…返回了乘用车 Passenger Car”|
|e2e_multistep_045@L91|先查NOx知识，再用文件算排放|knowledge,macro|knowledge,macro|N/A|M7|链匹配且 result_has_data=true；criteria `params_legal=false`, `requires_user_response=true`|
|e2e_multistep_049@L95|带 geometry 6 路网，算NOx后继续扩散并筛热点|macro,disp,hotspots|disp,hotspots|1|M4|actual chain 以 `calculate_dispersion` 开始，跳过 `calculate_macro_emission`|

汇总：M3=5/10=50.0%；M4=1/10=10.0%；M5=1/10=10.0%；M6=2/10=20.0%；M7=1/10=10.0%；M1=0；M2=0。

引用文件：`evaluation/results/end2end_full_v2/end2end_logs.jsonl`; `data/sessions/history/eval_e2e_multistep_002.json`; `data/sessions/history/eval_e2e_multistep_004.json`; `data/sessions/history/eval_e2e_multistep_006.json`; `data/sessions/history/eval_e2e_multistep_008.json`; `data/sessions/history/eval_e2e_multistep_010.json`; `data/sessions/history/eval_e2e_multistep_011.json`; `data/sessions/history/eval_e2e_multistep_043.json`; `data/sessions/history/eval_e2e_multistep_044.json`; `data/sessions/history/eval_e2e_multistep_045.json`; `data/sessions/history/eval_e2e_multistep_049.json`。

## Section 5：qwen3-max 的 function calling 行为观察

5.1 Naive Baseline 有日志：`evaluation/results/end2end_naive_full/end2end_logs.jsonl` 100 条，没调用任何工具 17 条，占 17.0%。类别：incomplete=12，parameter_ambiguous=3，simple=2。样本：L16 `e2e_incomplete_001`，L46 `e2e_incomplete_009`，L85 `e2e_ambiguous_039`。

5.2 Full System 中 LLM 工具参数出现不在 `standard_name + aliases + display_name_zh` 的陌生词 4 次、distinct=2：L6 `家用车`，L45 `家用车`，L77 `半挂短途货车`。证据：`家用车` 不在 Passenger Car aliases `config/unified_mappings.yaml:28-41`；`半挂短途货车` 不在 Combination Short-haul aliases `config/unified_mappings.yaml:181-186`。

5.3 注入方式：Full Router 在 `ContextAssembler` 中全量暴露工具：`core/assembler.py:133-139` 片段 `tools = list(self.all_tool_definitions)`；调用 function calling：`core/router.py:2483-2487` 与 `services/llm_client.py:310-315`，片段 `tools=tools`, `tool_choice="auto"`。工具定义来自 YAML 转 OpenAI schema：`tools/contract_loader.py:76-88`。Naive Router 使用 7 个工具，不是 9 个：`core/naive_router.py:28-36`；同样通过 `chat_with_tools(... tools=self.tool_definitions ...)`，`core/naive_router.py:130-135`。

当前 `vehicle_type` schema description 没有合法值 enum/完整别名表。`config/tool_contracts.yaml:30-35` 实际文本：`Vehicle type. Pass user's original expression (e.g., '小汽车', '公交车', 'SUV'). System will automatically recognize it.`；micro 工具为 `config/tool_contracts.yaml:97-102`：`Vehicle type. Pass user's original expression. REQUIRED.`

引用文件：`evaluation/results/end2end_naive_full/end2end_logs.jsonl`; `evaluation/results/end2end_full_v2/end2end_logs.jsonl`; `config/unified_mappings.yaml`; `core/assembler.py`; `core/router.py`; `services/llm_client.py`; `tools/contract_loader.py`; `core/naive_router.py`; `config/tool_contracts.yaml`。

## Section 6：benchmark 任务设计的潜在偏差

6.1 生成者/流程：`evaluation/llm_generator.py:20` 默认模型 `qwen3-max`；`evaluation/llm_generator.py:95-103` 用 chat completion 且 `response_format={"type":"json_object"}`。初代任务生成 prompt 在 `evaluation/generate_e2e_tasks.py:59-78`，类别定义在 `:36-43`。Pipeline v2：coverage audit -> targeted generation -> auto validation -> human review -> regression -> merge，证据 `evaluation/pipeline_v2/run_pipeline.sh:4-60`。Targeted generator 明确要求 expected_params 使用标准值，证据 `evaluation/pipeline_v2/targeted_generator.py:35-40`。

Full System 是否用于筛选：脚本确实在 merge 前跑 Full System regression，`evaluation/pipeline_v2/run_pipeline.sh:50-54`；`evaluation/pipeline_v2/regression_check.py:72-79` 调用 `run_end2end_evaluation` 并保存分析。UNKNOWN: 是否人工依据 regression 结果筛选无法从仓库确认；自动 merge 代码 `evaluation/pipeline_v2/merge_to_benchmark.py:33-45,81` 只看 review/validation status，不读取 regression report。

6.2 当前 100 条 benchmark 的 expected standardizable 参数出现 194 次，全部是 unified_mappings 标准名：pollutant 93、vehicle_type 50、road_type 24、season 15、meteorology 12；非标准 alias/other=0。证据：validator 规则要求标准值，`evaluation/pipeline_v2/auto_validator.py:166-192`；最终覆盖报告 `evaluation/pipeline_v2/final_gap_report.json:1-23` 记录 task_count=100 且 vehicle_type coverage=1.0，`:39-58` pollutant coverage=1.0。

6.3 parameter_ambiguous 24 条中，用户表达包含目标参数别名列表命中 20 条，占 83.3%；未命中 4 条，均为 `家用车`：L6 `e2e_ambiguous_001`，L35 `e2e_ambiguous_011`，L45 `e2e_incomplete_008`，L52 `e2e_incomplete_015`。命中样本：L8 `重卡`→Combination Long-haul Truck；L66 `轻型客货车`→Passenger Truck；L84 `heavy truck/highway`→Combination Long-haul Truck/高速公路。证据：benchmark 行见 `evaluation/benchmarks/end2end_tasks.jsonl:6,8,35,45,52,66,84`；aliases 源见 `config/unified_mappings.yaml:28-41`, `:196-204`, `:52-56`, `:296-302`。

引用文件：`evaluation/llm_generator.py`; `evaluation/generate_e2e_tasks.py`; `evaluation/pipeline_v2/run_pipeline.sh`; `evaluation/pipeline_v2/targeted_generator.py`; `evaluation/pipeline_v2/regression_check.py`; `evaluation/pipeline_v2/merge_to_benchmark.py`; `evaluation/pipeline_v2/auto_validator.py`; `evaluation/pipeline_v2/final_gap_report.json`; `evaluation/benchmarks/end2end_tasks.jsonl`; `config/unified_mappings.yaml`。
