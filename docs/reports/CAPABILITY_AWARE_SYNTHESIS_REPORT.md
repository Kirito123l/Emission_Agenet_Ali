# Capability-Aware Result Synthesis Report

## 1. Summary

本轮实现了一个 synthesis-only 的定向修复：在结果综合阶段引入 capability-aware 约束，避免 LLM 和单工具短路渲染给出当前数据并不支持的后续建议。

修复覆盖了两条路径：

- LLM synthesis：在 `core/router.py::_synthesize_results()` 之前构建 capability summary，并注入到 synthesis prompt
- 单工具短路渲染：在 `core/router_render_utils.py::render_single_tool_success()` 中复用同一份 capability summary 过滤 follow-up 建议

解决的核心问题：

- 无空间几何的 CSV 在排放计算后，不再建议空间可视化或扩散分析
- 本轮已经提供 `download_file` / `map_data` / `chart_data` / `table_data` 时，不再在 LLM synthesis 中重复建议这些交付物
- follow-up 建议不再只看“系统有啥工具”，而是会看“当前数据和已有结果真正支持什么”

## 2. Files Changed

- [core/capability_summary.py](/home/kirito/Agent1/emission_agent/core/capability_summary.py)
  - 新增 synthesis-only helper
  - 负责汇总 `file_context`、`context_store`、当前 tool results、frontend payloads
  - 输出 `available_next_actions`、`unavailable_actions_with_reasons`、`already_provided`、`guidance_hints`
  - 提供 prompt 格式化和 deterministic follow-up 过滤

- [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)
  - 新增 `_get_file_context_for_synthesis()` 和 `_build_capability_summary_for_synthesis()`
  - 在 state-loop response 构建路径和 legacy `_process_response()` 中，都在 synthesis 前构建 capability summary
  - 给 `_synthesize_results()`、`_maybe_short_circuit_synthesis()`、`_build_synthesis_request()` 传入 capability summary

- [core/router_synthesis_utils.py](/home/kirito/Agent1/emission_agent/core/router_synthesis_utils.py)
  - `build_synthesis_request()` 支持追加 capability-aware prompt section
  - `maybe_short_circuit_synthesis()` 支持把 capability summary 传给单工具渲染

- [core/router_render_utils.py](/home/kirito/Agent1/emission_agent/core/router_render_utils.py)
  - `render_single_tool_success()` 新增可选 `capability_summary`
  - 宏观排放 / 扩散 / 热点三个短路渲染路径改为用 capability-aware follow-up 过滤
  - 在必要时输出“能力边界提示”，例如提示补充坐标/WKT/GeoJSON

- [tests/test_capability_aware_synthesis.py](/home/kirito/Agent1/emission_agent/tests/test_capability_aware_synthesis.py)
  - 新增 capability-aware synthesis 专项测试

## 3. Capability Summary Design

信息来源：

- `file_context` / `_file_analysis_cache`
  - `task_type`
  - `columns`
  - `column_mapping`
  - `spatial_metadata`
  - `dataset_roles`
  - `missing_field_diagnostics`

- `context_store`
  - `get_available_types(include_stale=False)`
  - `get_by_type(...)`
  - 结合 `tool_dependencies.validate_tool_prerequisites(...)` 做工具依赖判断

- 当前 tool results / frontend payloads
  - `download_file`
  - `map_data`
  - `chart_data`
  - `table_data`

构建逻辑：

- 先收集当前可用 result tokens：`emission / dispersion / hotspot`
- 再判断空间支持：
  - 优先看 `spatial_metadata`
  - 再看 `dataset_roles` 中的 geospatial / spatial_context 信号
  - 再看列名和 mapping 中是否有 `geometry / wkt / geojson / lon / lat ...`
  - 最后回退到当前结果里是否已经带 geometry / raster / hotspot spatial payload

- 之后按有限 action catalog 逐项评估：
  - `render_emission_map`
  - `calculate_dispersion`
  - `analyze_hotspots`
  - `render_dispersion_map`
  - `render_hotspot_map`

每个 action 都结合两类条件：

- 依赖条件：复用 `tool_dependencies.validate_tool_prerequisites(...)`
- 空间条件：只对空间类建议额外检查 geometry / spatial payload

输出格式：

- `available_next_actions`
  - 当前真正可建议的动作
- `unavailable_actions_with_reasons`
  - 当前不能建议的动作和原因
- `already_provided`
  - 本轮已经附带的交付物
- `guidance_hints`
  - 边界提示，如“如需空间分析，请补充路段坐标、WKT、GeoJSON 或其他几何信息”

这个设计的关键点是：没有重造一套 execution graph，而是复用了现有 `tool_dependencies.py` 和 `context_store`，只在 synthesis 层补足“当前数据能力边界”的表达。

## 4. Synthesis Integration

### LLM synthesis prompt

接入点在 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py) 的 `_synthesize_results()` 调用前。

控制流现在是：

1. 先从 `tool_results` 提取 `chart_data / table_data / map_data / download_file`
2. 再调用 `build_capability_summary(...)`
3. 把 summary 传入 `build_synthesis_request(...)`
4. `core/router_synthesis_utils.py` 追加 capability-aware prompt section：
   - 当前可执行的操作
   - 当前不可执行的操作
   - 本次已提供的交付物
   - “不要发明未列出的导出、可视化或分析步骤”

这意味着 LLM synthesis 现在拿到的是“结果 + 当前能力边界”，而不是只有结果。

### 短路渲染路径

接入点在 [core/router_render_utils.py](/home/kirito/Agent1/emission_agent/core/router_render_utils.py) 的 `render_single_tool_success()`。

现在不再无条件输出固定建议模板，而是：

1. 用同一份 capability summary 取对应 tool 的相关 action 子集
2. 只渲染当前可执行的 follow-up
3. 若关键空间 action 被挡住，则输出边界提示而不是错误引导

这样单工具成功和多工具 synthesis 两条路径使用的是同一套能力判断，不会再出现一边收敛、一边继续过度引导。

## 5. Tests

运行了：

```bash
python -m py_compile core/capability_summary.py core/router_synthesis_utils.py core/router_render_utils.py core/router.py tests/test_capability_aware_synthesis.py
pytest -q tests/test_capability_aware_synthesis.py tests/test_router_contracts.py tests/test_render_defaults.py
pytest -q tests/test_router_state_loop.py
```

结果：

- `py_compile` 通过
- `tests/test_capability_aware_synthesis.py tests/test_router_contracts.py tests/test_render_defaults.py`: `32 passed`
- `tests/test_router_state_loop.py`: `31 passed`

新增覆盖的关键行为：

- 无几何 CSV 的排放结果不会再建议空间可视化 / 扩散
- 有几何数据时会正常建议空间可视化 / 扩散
- 已提供 `download_file` 时 capability summary 会把它标记为 `already_provided`
- 已提供 emission map 时不会再建议重复的 emission map action
- 扩散结果存在时会建议热点分析；若扩散结果缺少空间 payload，则不建议浓度地图渲染
- synthesis prompt 确实注入了 capability constraints
- 单工具短路渲染会遵守 capability summary

## 6. Known Limitations

- 这轮仍然是 rule/helper 驱动的 synthesis 约束，不是新的框架层
- capability-aware 主要覆盖当前高价值 follow-up actions，不是通用“所有未来动作”的开放式推理器
- `already_provided` 目前按 `download_file / map_data / chart_data / table_data` 和 map kind 做 bounded 判断，不是更细粒度的 artifact ontology
- 对空间支持的判断仍依赖现有 `file_context` 和结果 payload 质量；如果上游 grounding 没暴露足够信号，synthesis 侧也只能保守收敛
- 没有引入新的 persistence / scheduler / auto-completion / planning 改动

## 7. Before/After

### 场景 A：无几何 CSV，宏观排放计算完成

Before:

- 建议“可视化排放空间分布”
- 建议“模拟 NOx 扩散浓度”
- 建议“导出详细路段排放表格”

After:

- 不再建议空间可视化
- 不再建议扩散分析
- 不再重复建议已提供的下载文件
- 会保留一条能力边界提示，例如：
  - “如需空间分析，请补充路段坐标、WKT、GeoJSON 或其他几何信息。”

### 场景 B：有几何数据，宏观排放计算完成

Before:

- 可以建议空间可视化和扩散，但没有显式说明为什么当前可行

After:

- 仍然建议空间可视化和扩散
- 但这些建议现在是 capability summary 明确允许后的结果，不再只是“工具表面可用”

### 场景 C：扩散结果已生成，但当前回复已经带了地图

Before:

- synthesis 或模板化建议仍可能继续说“在地图上展示浓度分布”

After:

- `already_provided` 会抑制重复的地图建议
- 还可继续建议热点分析这类当前依赖已经满足、且尚未提供的下一步

## 8. Debugging & Fix

这次回查的重点不是再扩机制，而是确认 capability-aware synthesis 为什么在真实场景里看起来“没生效”。

### 排查结论

1. **原先没有独立 feature flag**
   - `config.py` 里原先没有单独的 capability-aware synthesis 开关
   - 所以不存在“旧开关默认是 False 导致功能被关掉”的情况
   - 为了后续排障更直接，这次新增了：
     - `ENABLE_CAPABILITY_AWARE_SYNTHESIS`
   - 默认值设为 `true`

2. **state loop 和 legacy loop 实际都已经接了 capability summary**
   - state loop：
     - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py) `_state_build_response()` 会在 `_synthesize_results()` 前构建 capability summary
   - legacy loop：
     - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py) `_process_response()` 也会在 `_synthesize_results()` 前构建 capability summary
   - 这次又补了一点：
     - `_get_file_context_for_synthesis()` 在 `state` 上拿不到 grounded file context 时，会继续回退到 `memory.file_analysis`

3. **真正的短板在可观测性和 prompt 强度**
   - 之前 capability summary 虽然会拼进 prompt，但没有把构建出的 summary 和最终 prompt 打出来，排查时看不到“到底注没注进去”
   - 同时 prompt 约束文本偏软，属于“建议遵守”，不是“硬性禁止”

### 这次修复

1. **新增显式开关，默认开启**
   - [config.py](/home/kirito/Agent1/emission_agent/config.py)
   - `enable_capability_aware_synthesis = True` by default

2. **增加 capability summary 和完整 synthesis prompt 日志**
   - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)
   - `_build_capability_summary_for_synthesis()` 现在会输出：
     - 是否拿到 file context
     - 完整 capability summary JSON
   - `_synthesize_results()` 现在会输出：
     - 发给 LLM 的完整 `system_prompt`

3. **把 capability constraints 放到 prompt 最末尾，并改成硬约束措辞**
   - [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py)
     - `SYNTHESIS_PROMPT` 现在只到 `{results}` 为止
   - [core/router_synthesis_utils.py](/home/kirito/Agent1/emission_agent/core/router_synthesis_utils.py)
     - 如果存在 capability summary，就把 capability constraint section 放在最终 prompt 的最后
   - [core/capability_summary.py](/home/kirito/Agent1/emission_agent/core/capability_summary.py)
     - prompt section 改为：
       - `后续建议硬约束`
       - `当前不可执行的操作（严禁将这些列为推荐选项）`
       - `最终硬性要求`
       - 明确写出：
         - 只能建议允许列表中的操作
         - 严禁把不可执行动作写成建议项
         - 严禁重复建议已提供交付物
         - 如果没有安全后续操作，就明确说没有

### 场景验证

针对你指出的场景，这次补了同构测试：

- 标准无几何 CSV 列集：
  - `segment_id, highway, length_km, daily_traffic, avg_speed`
- 宏观排放完成后：
  - capability summary 会把
    - `可视化排放空间分布`
    - `模拟污染物扩散浓度`
    标记为 unavailable
  - deterministic render 不再输出这两项
  - 同时输出：
    - `如需空间分析，请补充路段坐标、WKT、GeoJSON 或其他几何信息。`

### 这次新增验证结果

运行了：

```bash
python -m py_compile config.py core/capability_summary.py core/router_synthesis_utils.py core/router_render_utils.py core/router.py tests/test_capability_aware_synthesis.py tests/test_config.py
pytest -q tests/test_capability_aware_synthesis.py tests/test_router_contracts.py tests/test_render_defaults.py tests/test_config.py
pytest -q tests/test_router_state_loop.py
```

结果：

- `43 passed, 4 warnings`
- `31 passed`

这次回查后的最终判断是：

- **capability-aware synthesis 并不是完全没接上**
- 真正的问题是：
  - 缺少显式开关和日志，排障不可见
  - prompt 约束不够硬，留给 LLM 过多自由发挥空间
- 这次修复把这两点补齐了，同时保持改动仍然只在 synthesis 层，没有动 planning / execution / continuation 主逻辑
