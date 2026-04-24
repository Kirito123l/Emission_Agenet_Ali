# PHASE1_DIAGNOSIS

源：v4 on/off logs + `data/sessions/history/eval_*.json`。prompt未保存；block按state-on首轮前FactMemory反推（`turn < final_turn-eval_router_turns+1`）。首轮action均`New task starts`；未列字段为空。

## Part 1: pass_to_fail 17条（分类名：DIAG_D=DIAG_D_BLOCK_CONFUSION；DIAG_B=DIAG_B_EMPTY_BLOCK_NOISE）
### Case e2e_ambiguous_006
- 原文：`查询2023年私家车在主干道的CO2排放因子`
- 行为：off T=query ok R=已成功查询；on T=[] fail R=已成功查询。
- block：log query@t11→EF。差异：tool→no_tool。分类：**DIAG_D**。
### Case e2e_ambiguous_007
- 原文：`查公交车高架NOx排放因子`
- 行为：off T=query ok R=已成功查询；on T=[] fail R=已成功查询。
- block：log query@t11→EF。差异：tool→no_tool。分类：**DIAG_D**。
### Case e2e_ambiguous_009
- 原文：`校车在支路上的NOx排放因子是多少？`
- 行为：off T=query ok；on T=[] fail R=已成功查询。
- block：log query@t11→EF。差异：tool→no_tool。分类：**DIAG_D**。
### Case e2e_ambiguous_010
- 原文：`公交车冬天在高架上的CO2因子`
- 行为：off T=query ok；on T=[] fail R=根据系统查询结果。
- block：log query@t11→EF。差异：tool→no_tool。分类：**DIAG_D**。
### Case e2e_ambiguous_011
- 原文：`分析这份家用车轨迹的CO2排放`
- 行为：off T=micro ok；on T=[] fail R=已完成排放计算。
- block：log micro@t12→emission。差异：tool→no_tool。分类：**DIAG_D**。
### Case e2e_ambiguous_024
- 原文：`长途大巴的NOx排放有多少？`
- 行为：off T=query ok；on T=[] fail R=根据查询结果。
- block：log query@t5→EF。差异：tool→no_tool。分类：**DIAG_D**。
### Case e2e_ambiguous_028
- 原文：`城配货车NOx排放因子查一下`
- 行为：off T=query ok；on T=[] fail R=已为您查询到/已锁定。
- block：log query@t5→EF; locked={} 。差异：tool→no_tool。分类：**DIAG_D**。
### Case e2e_clarification_104
- 原文：`帮我算一下这个路段的NOx；冬季；继续`
- 行为：off T=macro ok；on T=[macro,macro] fail。
- block：log macro@t4→emission。差异：单调→重复调。分类：**DIAG_D**。
### Case e2e_clarification_117
- 原文：`查一下车的NOx；组合长途货车/主干道/2022年`
- 行为：off T=query ok；on T=[query,query] fail。
- block：log query@t5→EF。差异：单调→重复调。分类：**DIAG_D**。
### Case e2e_codeswitch_168
- 原文：`passenger truck 在主干道 NOx fctor`
- 行为：off T=query ok；on T=[] fail R=已成功获取。
- block：log query@t2→EF。差异：tool→no_tool。分类：**DIAG_D**。
### Case e2e_codeswitch_177
- 原文：`NOx for light commerical truck on 支路`
- 行为：off T=query ok；on T=[] fail R=already retrieved。
- block：log query@t2→EF。差异：tool→no_tool。分类：**DIAG_D**。
### Case e2e_constraint_035
- 原文：`用这个路网文件算THC排放，然后做扩散分析`
- 行为：off T=macro ok R=THC完成+缺geometry；on T=[] fail R=几何补全阻断。
- block：log macro@t14→emission。差异：跳过排放。分类：**DIAG_D**。
### Case e2e_incomplete_052
- 原文：`对比一下两个情景的排放差异`
- 行为：off T=[] ok R=追问/举例；on T=[knowledge,macro,macro,macro] fail。
- block：四字段空; tok=121; action=New task starts。差异：no_tool→执行示例。分类：**DIAG_B**。
### Case e2e_multistep_008
- 原文：`用这个路网文件算CO2排放，然后做扩散`
- 行为：off T=macro ok；on T=[] fail R=默认气象表。
- block：log macro@t22→emission。差异：tool→no_tool。分类：**DIAG_D**。
### Case e2e_multistep_050
- 原文：`带坐标路网算完CO2后直接出一张排放地图`
- 行为：off T=[macro,render] ok；on T=[render] fail R=已生成地图。
- block：log macro@t5→emission; render@t6→visualization。差异：跳过macro。分类：**DIAG_D**。
### Case e2e_revision_137
- 原文：`查2020年组合长途货车CO排放因子；车辆改成单体长途货车`
- 行为：off T=[query,query] ok；on T=[query] fail。
- block：log query@t3/t4→EF。差异：未对修订车型再调工具。分类：**DIAG_D**。
### Case e2e_simple_001
- 原文：`查询2020年网约车的CO2排放因子`
- 行为：off T=query ok；on T=[] fail R=查询成功/已获取。
- block：log query@t16→EF。差异：tool→no_tool。分类：**DIAG_D**。

汇总：DIAG_D=16，DIAG_B=1，DIAG_A/C/E=0。16/17 的on首轮前block含同task既往tool_log；多条on转no_tool或跳过前置工具。

## Part 2: fail_to_pass 13 条共性
| task_id | category | 关键字段 | 事实作用 |
|---|---|---|---|
| e2e_clarification_103 | multi_turn_clarification | tool_log | 重复query→单次query |
| e2e_clarification_106 | multi_turn_clarification | tool_log | 3条micro历史→单次micro |
| e2e_clarification_109 | multi_turn_clarification | tool_log | 3条query历史→单次query |
| e2e_codeswitch_163 | code_switch_typo | tool_log | off调工具失败；on no_tool追问 |
| e2e_codeswitch_179 | code_switch_typo | tool_log | 失败dispersion历史；on no_tool |
| e2e_constraint_013 | parameter_ambiguous | tool_log | on no_tool满足追问 |
| e2e_incomplete_002 | incomplete | tool_log | on no_tool避免query |
| e2e_incomplete_006 | incomplete | tool_log | on no_tool避免query |
| e2e_incomplete_008 | parameter_ambiguous | tool_log | on no_tool满足negotiation |
| e2e_incomplete_010 | incomplete | action | 四字段空，仅New task starts；on追问 |
| e2e_incomplete_011 | incomplete | tool_log | on no_tool避免query |
| e2e_incomplete_018 | incomplete | tool_log | on no_tool避免query |
| e2e_multistep_040 | multi_step | tool_log | 有macro历史；on完成链，off no_tool |
统计：tool_log=12；action=1；其余=0。

## Part 3: Block 在单轮任务中的噪音
simple+parameter_ambiguous共45条：tool_log空10(22.2%)；artifacts空12(26.7%)；locked空45(100%)；constraints空45(100%)；action=New task starts 45(100%)；全无效10(22.2%)。平均token=220.2。77.8%首轮前已有同session_id既往tool_log。

## Part 4: Token 分布与失败相关性
| token bucket | cases | completion_rate |
|---|---:|---:|
| [0,100) | 0 | NA |
| [100,150) | 34 | 58.8% |
| [150,300) | 108 | 67.6% |
| [300,500) | 30 | 80.0% |
| [500,+) | 8 | 12.5% |
事实：300-500桶最高；500+最低。不能仅凭长度确认因果；500+主要来自多轮/重复tool_log。
