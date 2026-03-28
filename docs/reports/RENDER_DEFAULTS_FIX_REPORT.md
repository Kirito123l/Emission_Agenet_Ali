# RENDER_DEFAULTS_FIX_REPORT

## 1. 诊断结果

### 1.1 触发点与渲染链路

单工具结果的短路触发点在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1349)。

当前链路如下：

```text
router.chat
  -> _state_build_response(...)
    -> _synthesize_results(...)
      -> _maybe_short_circuit_synthesis(tool_results)
        -> 单工具 query_knowledge 且成功: 直接返回工具 summary
        -> 任一工具失败: format_results_as_fallback(...)
        -> 单工具成功:
           -> tool_name in TOOLS_NEEDING_RENDERING:
              render_single_tool_success(tool_name, result)
           -> elif result.summary:
              直接返回工具 summary
           -> else:
              render_single_tool_success(tool_name, result)
        -> 其余情况:
           -> build_synthesis_request(...)
           -> LLM synthesis
```

短路集合定义在 [core/router_synthesis_utils.py](/home/kirito/Agent1/emission_agent/core/router_synthesis_utils.py#L14)。

### 1.2 为什么宏观排放会走“友好渲染”

- `calculate_macro_emission` 一直在 `TOOLS_NEEDING_RENDERING` 集合里。
- 当这一轮只有一个成功工具结果时，router 不会再走 LLM synthesis，而是直接调用 `render_single_tool_success(...)`。
- 因此 skill 里的“展示默认参数”指令没有执行机会。

### 1.3 修复前哪些工具走模板渲染，哪些走 LLM synthesis

修复前：

- 模板渲染: `query_emission_factors`, `calculate_micro_emission`, `calculate_macro_emission`, `analyze_file`
- 直接返回 summary: `calculate_dispersion`, `analyze_hotspots` 等其他单工具成功场景
- LLM synthesis: 多工具成功场景，且不满足短路条件时

修复后：

- 模板渲染: `query_emission_factors`, `calculate_micro_emission`, `calculate_macro_emission`, `calculate_dispersion`, `analyze_hotspots`, `analyze_file`
- 直接返回 summary: 其他单工具成功场景
- LLM synthesis: 多工具成功场景，且不满足短路条件时

### 1.4 渲染函数位置与读取字段

- 宏观排放友好渲染: [core/router_render_utils.py](/home/kirito/Agent1/emission_agent/core/router_render_utils.py#L252)
  - 读取 `data.query_info`
  - 读取 `data.summary.total_emissions_kg_per_hr`
  - 现在还读取 `data.defaults_used`
  - 现在还检查 `data.results[*].geometry` 以决定是否注入后续建议

- 扩散友好渲染: [core/router_render_utils.py](/home/kirito/Agent1/emission_agent/core/router_render_utils.py#L312)
  - 读取 `data.query_info`
  - 读取 `data.summary`
  - 读取 `data.meteorology_used`
  - 读取 `data.coverage_assessment`
  - 读取 `data.defaults_used`
  - 读取 `data.raster_grid`

- 热点友好渲染: [core/router_render_utils.py](/home/kirito/Agent1/emission_agent/core/router_render_utils.py#L389)
  - 读取 `data.interpretation`
  - 读取 `data.summary`
  - 读取 `data.hotspots`
  - 读取 `data.coverage_assessment`

### 1.5 `defaults_used` 是否存在但被忽略

是。

- `calculate_macro_emission` tool 层会写入 `result["data"]["defaults_used"]`，见 [tools/macro_emission.py](/home/kirito/Agent1/emission_agent/tools/macro_emission.py#L579) 和 [tools/macro_emission.py](/home/kirito/Agent1/emission_agent/tools/macro_emission.py#L671)
- `calculate_dispersion` tool 层也会写入 `data["defaults_used"]`，见 [tools/dispersion.py](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L96) 和 [tools/dispersion.py](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L149)
- 修复前的宏观排放模板只读 `query_info` 和 `summary`，没有消费 `defaults_used`
- 修复前的扩散/热点单工具场景甚至没有专门模板，直接返回 summary

## 2. defaults_used 数据存在性确认

### 2.1 Calculator 层

快速验证结果：

```text
Calculator result keys: ['query_info', 'results', 'summary']
Has defaults_used: False
```

结论：

- `MacroEmissionCalculator.calculate()` 本身不产出 `defaults_used`
- `defaults_used` 是在 tool 层补进去的，不在 calculator 层

### 2.2 Macro tool 层

实际验证结果：

```text
success= True
data_keys= ['defaults_used', 'fleet_mix_fill', 'query_info', 'results', 'summary']
defaults_used= {
  'pollutants': ['CO2', 'NOx'],
  'model_year': 2020,
  'season': '夏季',
  'fleet_mix': {
    'Passenger Car': 70.0,
    'Passenger Truck': 20.0,
    'Light Commercial Truck': 5.0,
    'Transit Bus': 3.0,
    'Combination Long-haul Truck': 2.0
  }
}
```

结论：

- `defaults_used` 在最终 `ToolResult.data` 中真实存在
- 丢失点不在 tool 层，而在 router 的模板渲染链路

### 2.3 Dispersion tool 层

`calculate_dispersion` 在 tool 层会同时补这些关键字段：

- `defaults_used`
- `meteorology_used`
- `coverage_assessment`

对应代码见 [tools/dispersion.py](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L96) 和 [tools/dispersion.py](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L149)

## 3. 修改内容

### 3.1 修改文件

- [core/router_render_utils.py](/home/kirito/Agent1/emission_agent/core/router_render_utils.py)
- [core/router_synthesis_utils.py](/home/kirito/Agent1/emission_agent/core/router_synthesis_utils.py)
- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)
- [tests/test_render_defaults.py](/home/kirito/Agent1/emission_agent/tests/test_render_defaults.py)

### 3.2 具体改动

#### A. 直接在友好渲染模板中消费 `defaults_used`

在 [core/router_render_utils.py](/home/kirito/Agent1/emission_agent/core/router_render_utils.py#L8) 新增了几个 helper：

- `_format_default_value(...)`
- `_normalize_default_items(...)`
- `_append_defaults_section(...)`
- `_append_follow_up_section(...)`
- `_describe_meteorology_source(...)`
- `_format_meteorology_overrides(...)`
- `_format_hotspot_summary_line(...)`

这些 helper 实现了：

- `defaults_used` 的 dict / list-of-dicts 双格式兼容
- 车队组成默认值的动态摘要化展示
- 参数标签映射与 how-to-customize 文案拼接
- 扩散气象来源与覆盖参数说明
- 热点 top 摘要行拼接

#### B. 宏观排放模板补默认参数和后续建议

在 [core/router_render_utils.py](/home/kirito/Agent1/emission_agent/core/router_render_utils.py#L252)：

- 新增一行自然语言总览
- 新增“以下参数使用了系统默认值”段落
- 动态展示 `fleet_mix / model_year / season / pollutants`
- 检测到空间几何时，直接在首轮模板里加入：
  - 可视化排放分布
  - 做大气扩散分析

#### C. 扩散和热点也纳入友好渲染

在 [core/router_synthesis_utils.py](/home/kirito/Agent1/emission_agent/core/router_synthesis_utils.py#L14)：

- 将 `calculate_dispersion`
- 将 `analyze_hotspots`

加入 `TOOLS_NEEDING_RENDERING`，保持单工具场景零额外 LLM 调用，但不再只返回裸 summary。

#### D. 扩散模板补充关键信息

在 [core/router_render_utils.py](/home/kirito/Agent1/emission_agent/core/router_render_utils.py#L312)：

- 展示气象条件来源: 预设 / 预设覆盖 / 用户指定 / SFC 文件
- 展示覆盖参数详情
- 展示 `coverage_assessment.result_semantics`
- 展示 `coverage_assessment.warnings`
- 展示 `defaults_used`
- 直接加入热点分析和浓度地图的下一步建议

#### E. 热点模板补充 interpretation 和 top 摘要

在 [core/router_render_utils.py](/home/kirito/Agent1/emission_agent/core/router_render_utils.py#L389)：

- 展示 `interpretation`
- 展示热点数量、总面积、top 热点摘要
- 展示主要贡献路段
- 展示 coverage warnings
- 直接加入热点地图和阈值调整建议

#### F. 避免宏观排放重复拼接通用地图提示

在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1042)：

- 维持原有 `_visualization_available` 检测逻辑
- 但若单工具就是 `calculate_macro_emission`，且模板里已给出后续建议，则不再额外追加一段通用地图提示，避免重复

## 4. 修复前后输出对比

### 4.1 修复前

```text
宏观排放计算结果
计算参数
- 路段数: 20
- 年份: 2020
- 季节: 夏季
- 污染物: CO2, NOx
汇总结果
- 总排放量 (kg/h):
  - CO2: 1134.8827
  - NOx: 0.2396
```

### 4.2 修复后

```text
## 宏观排放计算结果

计算了 20 条路段的排放，总 CO2 排放 1134.88 kg/h，NOx 排放 0.24 kg/h。

**计算参数**
- 路段数: 20
- 年份: 2020
- 季节: 夏季
- 污染物: CO2, NOx

**汇总结果**
- 总排放量 (kg/h):
  - CO2: 1134.8827
  - NOx: 0.2396

**以下参数使用了系统默认值**
- 车队组成: 默认配置（Passenger Car 为主），如需自定义可在文件中添加 fleet_mix 列
- 模型年份: 2020，如需修改可告诉我"用 2015 年的排放因子"
- 季节: 夏季，如需修改可说"用冬季条件"
- 污染物: CO2, NOx，如需添加可说"加上 PM2.5"

**您可以进一步**
- “帮我可视化排放分布” - 在地图上查看各路段排放强度
- “帮我做扩散分析” - 了解污染物如何在大气中扩散
```

## 5. 测试结果

### 5.1 新增测试

新增 [tests/test_render_defaults.py](/home/kirito/Agent1/emission_agent/tests/test_render_defaults.py)，覆盖：

- macro friendly render 包含 `defaults_used`
- 无默认参数时不展示默认段落
- dispersion render 包含 `meteorology_used`
- hotspot render 包含 `interpretation` 和 top 热点摘要
- 上下文下一步建议注入
- `defaults_used` 的 dict / list-of-dicts 双格式兼容
- 单工具短路路径对 dispersion / hotspot 使用友好渲染

### 5.2 命令结果

```text
pytest tests/ -v -k "default"
-> 21 passed

pytest tests/test_router_contracts.py -q
-> 18 passed

pytest tests/test_router_state_loop.py -q
-> 8 passed

pytest -q
-> 488 passed, 19 warnings

python main.py health
-> 8 tools OK
```

## 6. 全量回归测试数

全量 `pytest -q` 结果：

- Passed: 488
- Warnings: 19
- Failed: 0

## 7. 约束检查

本次修复满足约束：

- 未修改 `calculators/`
- 未修改 `config/skills/`
- 未修改 `tools/definitions.py`
- 未修改前端文件
- 未增加额外 LLM 调用
- 默认参数文案从 `defaults_used` 动态取值
- `defaults_used` 为空时不展示默认参数段落
