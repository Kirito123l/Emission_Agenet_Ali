# FRONTEND_BACKEND_AUDIT

## 1. 多工具 `map_data` 传递验证

### 检查项
- 后端 `map_data` 收集链路
- 前端 `map_collection` 处理
- 路径 B（LLM 文字回复）中的前端 payload 提取
- API 层 JSON / SSE 透传

### 发现
- ✅ `core/router_payload_utils.py` 的 `_collect_map_payloads()` 会从 `result.map_data` 和 `result.data.map_data` 两层收集地图 payload，并在多图场景返回 `map_collection`。
- ✅ `core/router.py` 的 `_extract_frontend_payloads()` 同时被 `_state_build_response()` 和 legacy `_process_response()` 调用，所以单工具友好渲染路径和多工具 LLM 最终回复路径都会附带 `map_data` / `table_data` / `chart_data` / `download_file`。
- ✅ `api/routes.py` 在同步 JSON 和 SSE `map` event 中都直接透传 `map_data`。
- ✅ `web/app.js` 里的 `getMapPayloadItems()` / `renderMapData()` 已支持 `map_collection`，多张地图会逐个追加到同一条消息卡片，不会互相覆盖。

### 修复方案
- 本轮未发现后端 `map_collection` 链路缺口。
- 保留现有后端实现，重点补强前端组合消息场景和流式卡片样式一致性。

### 修复后验证
- `python3 verify_map_data_collection.py` 输出：

```text
Result type: <class 'dict'>
Map count: 2
  Item 0: type=emission, has_layers=True
  Item 1: type=raster, has_layers=True
Backend map_data collection: PASS
```


## 2. 地图 z-index / 滚动遮挡验证

### 检查项
- Leaflet stacking CSS 覆盖是否完整
- 地图容器样式
- 消息卡片 stacking context
- CSS 注入时机

### 发现
- ✅ `ensureLeafletStackingStyles()` 已覆盖 `.leaflet-pane`、`.leaflet-top`、`.leaflet-bottom`、`.leaflet-control`、`.leaflet-popup-pane`。
- ✅ 该函数在 `DOMContentLoaded` 和地图渲染前都会调用，注入时机足够早。
- ❌ 流式消息容器 `createAssistantMessageContainer()` 之前没有复用 `.assistant-message-row` / `.assistant-message-card`，导致地图卡片与普通助手消息卡片的 stacking context 不一致。

### 修复方案
- 在 `web/app.js` 中让流式消息容器也使用 `.assistant-message-row` / `.assistant-message-card`。
- 在 `createAssistantMessageContainer()` 内显式调用 `ensureLeafletStackingStyles()`，保证流式首张地图也使用统一的 Leaflet z-index 覆盖。

### 修复后验证
- `tests/test_web_render_contracts.py` 新增断言覆盖上述类名和注入调用。
- `node -c web/app.js` 通过。


## 3. 排放线图层视觉问题

### 检查项
- 线宽
- 色阶范围
- 低值可见性

### 发现
- ✅ 当前 `initLeafletMap()` 的自适应线宽已提升到 `2 / 2.5 / 3 / 3.5 / 4 px`。
- ✅ `getEmissionColor()` 使用对数归一化和高饱和色带，低值不会退化成近白色。
- ✅ 线透明度按路段数自适应，稀疏场景下为 `0.85`，可读性尚可。

### 修复方案
- 本轮无需继续修改排放线视觉参数。

### 修复后验证
- 代码审查确认 `weight`、`opacity`、色阶函数都已处于合理区间。


## 4. 栅格渲染完整性

### 检查项
- `raster` 类型识别
- 栅格方块渲染
- 栅格图例

### 发现
- ✅ `renderSingleMapData()` 会优先将 `type === "raster"` 或带 `raster_grid` 的 payload 送入 `renderRasterMap()`。
- ✅ `initRasterLeafletMap()` 使用 `stroke: false` 渲染无边框填色方块。
- ✅ `getRasterColor()` 对正值走对数映射，对低值/零值回退线性映射。
- ✅ `renderRasterLegend()` 包含标题、渐变条、min/max、单位和分辨率。

### 修复方案
- 本轮无需修改。

### 修复后验证
- 代码路径完整，无分支遗漏。


## 5. 热点渲染完整性

### 检查项
- 热点边框
- rank 标签
- popup 内容

### 发现
- ✅ `initHotspotLeafletMap()` 的热点区域边框为红色虚线 `dashArray: '8, 4'`。
- ✅ 热点中心使用 `L.divIcon()` 渲染 rank 标签。
- ✅ popup 会展示 Top Contributing Roads 和贡献比例。

### 修复方案
- 本轮无需修改。

### 修复后验证
- 代码路径完整，无分支遗漏。


## 6. Trace 面板和 Summary 展示

### 检查项
- 友好渲染模板覆盖
- `defaults_used` 展示
- `coverage_assessment` 展示

### 发现
- ✅ `TOOLS_NEEDING_RENDERING` 已覆盖：
  - `calculate_macro_emission`
  - `calculate_micro_emission`
  - `query_emission_factors`
  - `calculate_dispersion`
  - `analyze_hotspots`
  - `render_spatial_map`
  - `analyze_file`
- ✅ `query_knowledge` 走 summary-only 快捷路径，属于刻意设计，不是缺失。
- ✅ `core/router_render_utils.py` 中，宏观排放和扩散模板都消费了 `defaults_used`。
- ✅ 扩散和热点模板都展示了 `coverage_assessment` warning。

### 修复方案
- 本轮无需修改。

### 修复后验证
- 现有 `tests/test_render_defaults.py` 保持通过。


## 7. 前端代码整体审计

### 检查项
- JS 语法
- 未使用函数粗查
- `console.*` 残留
- 硬编码 URL/端口
- 文件规模

### 发现
- ✅ `node -c web/app.js` 通过。
- ✅ `web/app.js` 未发现 `localhost` / `127.0.0.1` / `8000` 的真实硬编码。
  - 说明：搜索 `8000` 时命中的其实是色阶颜色 `#800026`，不是端口。
- ⚠️ `web/app.js` 当前 3487 行，`console.log/error/warn` 共 95 处，调试噪音偏高。
- ❌ 非流式 `table_and_map` 响应之前不会渲染表格，因为 `addAssistantMessage()` 只接受 `data_type === 'table'`。

### 修复方案
- 在 `web/app.js` 中将表格渲染条件改为支持 `table` 和 `table_and_map`。
- 保留现有 `console.*`，但在报告中标记为后续维护项，不在本轮做大规模清理。

### 修复后验证
- 新增 `tests/test_web_render_contracts.py`，断言 `table_and_map` 也会触发表格渲染。


## 8. 后端代码审计

### 检查项
- 指定 Python 文件编译
- `print()` 残留
- imports 粗查
- 全量测试
- 健康检查

### 发现
- ✅ `python -m py_compile` 检查通过：
  - `core/router.py`
  - `core/router_payload_utils.py`
  - `core/router_render_utils.py`
  - `core/router_synthesis_utils.py`
  - `core/skill_injector.py`
  - `core/assembler.py`
  - `core/coverage_assessment.py`
  - `tools/dispersion.py`
  - `tools/hotspot.py`
  - `tools/spatial_renderer.py`
  - `calculators/dispersion.py`
  - `calculators/hotspot_analyzer.py`
- ✅ `core/router.py` / `core/router_payload_utils.py` / `core/router_render_utils.py` 未发现 `print(...)` 残留。
- ✅ `python main.py health` 通过，8 个工具均为 OK。
- ✅ `pytest -q` 通过，509 passed。

### 修复方案
- 本轮无需修改核心 router / payload / render 链路。

### 修复后验证
- 编译、全量测试、健康检查均通过。


## 9. 端到端数据流模拟

### 检查项
- “排放 → 可视化 → 扩散” Python 层模拟

### 发现
- ❌ 首次运行 `simulate_e2e.py` 时，`SpatialRendererTool.execute(data_source=result["data"])` 失败。
- 根因：
  - `MacroEmissionCalculator` 返回的 `results` 不保留 geometry。
  - `SpatialRendererTool._build_emission_map()` 之前只会从 tool result 自身读取 `geometry` / `coordinates`，无法从原始 source links 回填。
- 约束：
  - 按要求不能修改 `calculators/`。

### 修复方案
- 在允许修改的 `tools/spatial_renderer.py` 中新增 `source_links` 兼容入口。
- `_build_emission_map()` 会按 `link_id` 从 `source_links` 回填 geometry。
- `simulate_e2e.py` 改为把原始 source links 一起传给 `SpatialRendererTool.execute(...)`，更接近 router 实际持有空间上下文的行为。

### 修复后验证
- `tests/test_spatial_renderer.py` 新增两条测试：
  - `test_build_emission_map_can_reuse_source_links_geometry`
  - `test_execute_with_direct_data_and_source_links`
- `python3 simulate_e2e.py` 输出：

```text
--- Step 2: Spatial Renderer ---
Render success: True
Has map_data: True
Map type: macro_emission_map
Links: 2

--- Step 3: Map Data Collection ---
Collected map_data type: map_collection
Map items: 2
  Item 0: type=macro_emission_map
  Item 1: type=raster
```


## 10. 修复清单

### 修改的文件
- `web/app.js`
  - 修复 `table_and_map` 表格不渲染
  - 流式消息容器复用 `assistant-message-row` / `assistant-message-card`
  - 流式消息容器提前注入 Leaflet stacking styles
- `tools/spatial_renderer.py`
  - 新增 `source_links` geometry 回填兼容
- `tests/test_web_render_contracts.py`
  - 新增前端源代码契约测试
- `tests/test_spatial_renderer.py`
  - 新增 geometry 回填测试
- `simulate_e2e.py`
  - 新建无服务端链路模拟脚本
- `verify_map_data_collection.py`
  - 新建后端 `map_collection` 验证脚本

### 最终验证

```text
node -c web/app.js
PASS

python -m py_compile core/router.py core/router_payload_utils.py core/router_render_utils.py core/router_synthesis_utils.py core/skill_injector.py core/assembler.py core/coverage_assessment.py tools/dispersion.py tools/hotspot.py tools/spatial_renderer.py calculators/dispersion.py calculators/hotspot_analyzer.py
PASS

pytest tests/test_spatial_renderer.py tests/test_web_render_contracts.py tests/test_multi_tool_map_data.py tests/test_router_state_loop.py -q
64 passed

pytest -q
509 passed, 19 warnings

python main.py health
8 tools OK

python3 verify_map_data_collection.py
PASS

python3 simulate_e2e.py
PASS
```

### 结论
- 关键渲染链路当前可用。
- 多工具 `map_collection` 修复完整，路径 A / 路径 B / JSON / SSE 均已打通。
- 本轮新增修复的两个真实问题：
  - 非流式 `table_and_map` 表格丢失
  - `SpatialRendererTool` 直接消费宏观排放结果时无法回填 geometry
- 仍建议后续单独处理 `web/app.js` 中大量 `console.*` 调试输出，这是维护性问题，不是当前功能阻塞项。
