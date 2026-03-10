# 内部设计文档：宏观排放地图可视化

> 生成时间: 2026-03-08
> 文档目的: 分析现有数据流，为地图可视化功能提供技术基础

---

## 目录

1. [现有数据流分析](#1-现有数据流分析)
2. [ToolResult 数据结构](#2-toolresult-数据结构)
3. [前端现有能力](#3-前端现有能力)
4. [关键接口定义](#4-关键接口定义)
5. [地图可视化设计](#5-地图可视化设计)

---

## 1. 现有数据流分析

### 1.1 宏观排放计算完整数据流

```
用户输入 Excel 文件
    ↓
/api/chat (routes.py:303-428)
    ↓ 调用
UnifiedRouter.chat() (core/router.py:65-166)
    ↓ 使用
ContextAssembler → ToolExecutor → MemoryManager
    ↓ 执行
MacroEmissionTool.execute() (tools/macro_emission.py:214-429)
    ↓ 调用
MacroEmissionCalculator.calculate() (calculators/macro_emission.py:75-118)
    ↓ 返回
ToolResult (success=True/False, data, summary, chart_data, table_data, download_file)
    ↓ 提取
RouterResponse (text, chart_data, table_data, download_file)
    ↓ 返回前端
ChatResponse (reply, session_id, data_type, chart_data, table_data, file_id, download_file, message_id)
```

### 1.2 关键数据转换点

| 位置 | 文件 | 行号 | 功能 |
|------|------|------|------|
| **Tool执行** | core/executor.py | 87-105 | 将ToolResult转为Dict |
| **数据提取** | core/router.py | 269-285 | 从tool_results提取chart_data/table_data |
| **表格提取** | core/router.py | 811-1010 | `_extract_table_data()` |
| **图表提取** | core/router.py | 746-809 | `_extract_chart_data()` |
| **API响应** | api/routes.py | 391-401 | 构建ChatResponse |
| **前端接收** | web/app.js | 864-885 | `renderHistory()` 处理历史消息 |

---

## 2. ToolResult 数据结构

### 2.1 定义位置

**文件**: `tools/base.py:14-27`

```python
@dataclass
class ToolResult:
    """Standardized tool execution result"""
    success: bool                      # 执行是否成功
    data: Optional[Dict[str, Any]]     # 工具返回的数据
    error: Optional[str]               # 错误信息
    summary: Optional[str]             # 人类可读摘要
    chart_data: Optional[Dict]         # 图表数据
    table_data: Optional[Dict]         # 表格数据
    download_file: Optional[str]       # 下载文件路径
```

### 2.2 宏观排放工具的返回值

**工具**: `MacroEmissionTool.execute()` (tools/macro_emission.py:417-422)

```python
return ToolResult(
    success=True,
    data=result["data"],           # 来自 calculator
    summary=summary,               # 格式化的文本摘要
    # 注意: 宏观排放工具目前不设置 chart_data 和 table_data
    # 这些字段由 Router 的 _extract_*_data() 方法从 data 中提取
)
```

### 2.3 Calculator 返回的 data 结构

**来源**: `MacroEmissionCalculator.calculate()` (calculators/macro_emission.py:99-111)

```python
{
    "status": "success",
    "data": {
        "query_info": {
            "model_year": 2020,
            "pollutants": ["CO2", "NOx"],
            "season": "夏季",
            "links_count": 3
        },
        "results": [
            {
                "link_id": "Link_1",
                "link_length_km": 2.5,
                "traffic_flow_vph": 5000,
                "avg_speed_kph": 60,
                "fleet_composition": {...},
                "emissions_by_vehicle": {...},
                "total_emissions_kg_per_hr": {"CO2": 123.45, "NOx": 2.34},
                "emission_rates_g_per_veh_km": {"CO2": 123.4, "NOx": 2.3}
            },
            # ...更多路段
        ],
        "summary": {
            "total_links": 3,
            "total_emissions_kg_per_hr": {"CO2": 370.35, "NOx": 7.02}
        },
        "download_file": {...},
        "fleet_mix_fill": {...}
    }
}
```

---

## 3. 前端现有能力

### 3.1 引入的JS库

**文件**: `web/index.html:22-25`

```html
<!-- Marked.js for Markdown -->
<script src="marked.min.js"></script>
<!-- ECharts -->
<script src="https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js"></script>
```

**重要**: 前端**没有引入地图库**（如 Leaflet, Mapbox GL JS, OpenLayers）

### 3.2 图表渲染实现

**函数**: `initEmissionChart()` (web/app.js:1321-1467)

- 使用 ECharts 渲染折线图
- 支持多污染物切换（Tab切换）
- 数据格式: `{pollutant: {curve: [{speed_kph, emission_rate}, ...], unit: "g/km"}}`

### 3.3 表格渲染实现

**函数**: `renderResultTable()` (web/app.js:1086-1211)

- 显示汇总表 + 详情表
- 支持下载按钮
- 数据格式: `{columns: [...], preview_rows: [...], total_rows, summary, download}`

### 3.4 前端 data_type 处理

**位置**: `web/app.js:922-997` (`addAssistantMessage()`)

```javascript
const hasValidChartData = data.data_type === 'chart' && data.chart_data && ...
const hasValidTableData = data.data_type === 'table' && data.table_data && ...
```

- **chart**: 显示排放因子曲线图
- **table**: 显示计算结果表格
- **无data_type**: 只显示文本回复

---

## 4. 关键接口定义

### 4.1 ChatResponse (API → Frontend)

**文件**: `api/models.py:47-58`

```python
class ChatResponse(BaseModel):
    reply: str                              # 文本回复
    session_id: str                          # 会话ID
    data_type: Optional[str] = None          # "chart" | "table"
    chart_data: Optional[Dict[str, Any]]     # 图表数据
    table_data: Optional[Dict[str, Any]]     # 表格数据
    file_id: Optional[str] = None            # 文件ID（下载）
    download_file: Optional[Dict[str, Any]]  # 下载元数据
    message_id: Optional[str] = None         # 消息ID
    success: bool = True
    error: Optional[str] = None
```

### 4.2 RouterResponse (Router → API)

**文件**: `core/router.py:34-42`

```python
@dataclass
class RouterResponse:
    text: str                               # 合成文本
    chart_data: Optional[Dict] = None       # 图表数据
    table_data: Optional[Dict] = None       # 表格数据
    download_file: Optional[str] = None     # 下载文件
    executed_tool_calls: Optional[List[Dict[str, Any]]] = None
```

### 4.3 table_data 格式 (Frontend 渲染)

**实际使用格式**: `core/router.py:1000-1008` 宏观排放表格生成

```python
{
    "type": "calculate_macro_emission",
    "columns": ["link_id", "CO2_kg_h", "CO2_g_veh_km", "NOx_kg_h"],
    "preview_rows": [
        {"link_id": "Link_1", "CO2_kg_h": "123.45", "CO2_g_veh_km": "123.40", "NOx_kg_h": "2.34"},
        # ... 最多4行
    ],
    "total_rows": 10,           # 总行数
    "total_columns": 4,         # 总列数
    "summary": {
        "total_links": 10,
        "total_emissions_kg_per_hr": {"CO2": 1234.5, "NOx": 23.4}
    },
    "total_emissions": {...}    # 前端用于汇总表
}
```

### 4.4 download_file 格式

**标准化函数**: `api/routes.py:116-152`

```python
{
    "path": "/path/to/file.xlsx",        # 文件路径
    "filename": "result_20250308.xlsx",   # 文件名
    "file_id": "session_id",              # 会话ID
    "url": "/api/file/download/message/session_id/msg_id?user_id=xxx",  # 下载URL
    "message_id": "msg_id"                # 消息ID（可选）
}
```

---

## 5. 地图可视化设计

### 5.1 目标功能

在宏观排放计算结果中，增加地图可视化能力：
- 在地图上显示路段位置（需要用户提供坐标）
- 使用颜色编码显示各路段排放强度
- 支持点击路段查看详情
- 图例 + 统计信息面板

### 5.2 数据需求

**新增输入字段**（可选）:
- `link_coordinates`: 路段坐标 `[[lon1, lat1], [lon2, lat2], ...]` 或 GeoJSON LineString
- 或 `link_geojson`: 完整 GeoJSON FeatureCollection

**现有可用数据**:
- `link_id`: 路段标识
- `link_length_km`: 路段长度
- `total_emissions_kg_per_hr`: 各路段排放量
- `emission_rates_g_per_veh_km`: 单位排放率

### 5.3 前端实现方案

#### 方案 A: 使用 Leaflet（推荐）

**优势**:
- 轻量级（~140KB JS）
- 开源免费
- 支持多种图层（OSM, Mapbox, 等）
- 易于集成

**需要修改**:
1. `web/index.html`: 添加 Leaflet CSS/JS
2. `web/app.js`: 新增 `renderMap()` 函数
3. `core/router.py`: 新增 `_extract_map_data()` 方法
4. `tools/macro_emission.py`: 返回 `map_data` 字段

#### 方案 B: 使用 ECharts Geo（现有库扩展）

**优势**:
- 无需引入新库
- 与现有图表风格统一

**限制**:
- 需要准备 GeoJSON 数据
- 交互性较弱

### 5.4 数据结构设计

#### 5.4.1 map_data 格式

```python
{
    "type": "macro_emission_map",
    "center": [116.4074, 39.9042],  # 地图中心 [lon, lat]
    "zoom": 12,                       # 缩放级别
    "pollutant": "CO2",               # 当前显示的污染物
    "unit": "kg/h",                   # 单位
    "color_scale": {                  # 颜色映射
        "min": 0,
        "max": 500,
        "colors": ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"]
    },
    "links": [
        {
            "link_id": "Link_1",
            "geometry": [[116.1, 39.9], [116.2, 39.95]],  # LineString坐标
            "emissions": {"CO2": 123.45, "NOx": 2.34},
            "emission_rate": {"CO2": 123.4, "NOx": 2.3}
        },
        # ... 更多路段
    ],
    "summary": {
        "total_links": 10,
        "total_emissions": {"CO2": 1234.5, "NOx": 23.4},
        "max_emission_link": {"id": "Link_5", "CO2": 234.5}
    }
}
```

#### 5.4.2 ToolResult 扩展

```python
return ToolResult(
    success=True,
    data=result["data"],
    summary=summary,
    map_data=map_data,  # 新增字段
    download_file=download_file
)
```

### 5.5 前端渲染逻辑

#### 新增函数: `renderMap(mapData, msgId)`

```javascript
function renderMap(mapData, msgId) {
    const container = document.getElementById(msgId);
    if (!container) return;

    const mapId = `emission-map-${Date.now()}`;
    const mapHtml = `
        <div class="w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm p-6 mt-4">
            <div class="flex justify-between items-center mb-4">
                <h3 class="text-lg font-bold">路段排放地图</h3>
                <select id="${mapId}-pollutant" class="px-3 py-1 rounded-md text-sm">
                    ${Object.keys(mapData.links[0].emissions).map(p =>
                        `<option value="${p}">${p}</option>`
                    ).join('')}
                </select>
            </div>
            <div id="${mapId}" style="height: 500px;"></div>
            <div class="mt-4 flex items-center gap-4 text-sm">
                <div class="flex items-center gap-2">
                    <span class="text-slate-600">低排放</span>
                    <div class="w-32 h-3 rounded" style="background: linear-gradient(to right, ${mapData.color_scale.colors.join(', ')})"></div>
                    <span class="text-slate-600">高排放</span>
                </div>
            </div>
        </div>
    `;

    container.querySelector('.message-content').insertAdjacentHTML('beforeend', mapHtml);

    // 初始化 Leaflet 地图
    setTimeout(() => initLeafletMap(mapData, mapId), 100);
}
```

### 5.6 Router 扩展

#### 新增方法: `core/router.py`

```python
def _extract_map_data(self, tool_results: list) -> Optional[Dict]:
    """从宏观排放计算结果提取地图数据"""
    for r in tool_results:
        if r["name"] == "calculate_macro_emission" and r["result"].get("success"):
            data = r["result"].get("data", {})
            results = data.get("results", [])

            # 检查是否有坐标数据
            has_coords = any(
                "link_coordinates" in link or "geometry" in link
                for link in results
            )

            if not has_coords:
                return None

            # 构建地图数据
            return self._format_macro_emission_map(data)

    return None

def _format_macro_emission_map(self, data: Dict) -> Dict:
    """格式化宏观排放数据为地图格式"""
    results = data.get("results", [])
    query_info = data.get("query_info", {})
    summary = data.get("summary", {})

    pollutants = query_info.get("pollutants", ["CO2"])
    main_pollutant = pollutants[0]

    # 提取所有路段的排放值，用于确定颜色范围
    emissions = [
        link["total_emissions_kg_per_hr"].get(main_pollutant, 0)
        for link in results
    ]
    min_emission = min(emissions) if emissions else 0
    max_emission = max(emissions) if emissions else 100

    return {
        "type": "macro_emission_map",
        "center": [116.4074, 39.9042],  # TODO: 从数据计算中心
        "zoom": 12,
        "pollutant": main_pollutant,
        "unit": "kg/h",
        "color_scale": {
            "min": min_emission,
            "max": max_emission,
            "colors": ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"]
        },
        "links": [
            {
                "link_id": link["link_id"],
                "geometry": link.get("link_coordinates", link.get("geometry", [])),
                "emissions": link["total_emissions_kg_per_hr"],
                "emission_rate": link["emission_rates_g_per_veh_km"]
            }
            for link in results
        ],
        "summary": summary
    }
```

### 5.7 更新 data_type 枚举

**文件**: `api/models.py`

```python
class ChatResponse(BaseModel):
    data_type: Optional[str] = None  # "chart" | "table" | "map" | "chart_and_table"
    map_data: Optional[Dict[str, Any]] = None  # 地图数据
```

### 5.8 实现优先级

| 优先级 | 任务 | 文件 | 估计时间 |
|--------|------|------|----------|
| P0 | 前端添加 Leaflet 库 | web/index.html | 5分钟 |
| P0 | 实现 `renderMap()` 函数 | web/app.js | 1小时 |
| P0 | 实现 `_extract_map_data()` | core/router.py | 30分钟 |
| P1 | Tool 层支持坐标数据 | tools/macro_emission.py | 30分钟 |
| P2 | Excel 导入支持坐标列 | skills/macro_emission/excel_handler.py | 1小时 |
| P2 | 地图交互优化 | web/app.js | 1小时 |

---

## 6. 测试数据准备

### 6.1 测试路段数据（含坐标）

```json
{
    "links_data": [
        {
            "link_id": "Link_1",
            "link_length_km": 2.5,
            "traffic_flow_vph": 5000,
            "avg_speed_kph": 60,
            "fleet_mix": {"Passenger Car": 70, "Passenger Truck": 20, "Transit Bus": 10},
            "link_coordinates": [[116.1, 39.9], [116.2, 39.95]]
        },
        {
            "link_id": "Link_2",
            "link_length_km": 1.8,
            "traffic_flow_vph": 3500,
            "avg_speed_kph": 45,
            "fleet_mix": {"Passenger Car": 60, "Light Commercial Truck": 30, "Transit Bus": 10},
            "link_coordinates": [[116.2, 39.95], [116.25, 39.92]]
        },
        {
            "link_id": "Link_3",
            "link_length_km": 3.2,
            "traffic_flow_vph": 6000,
            "avg_speed_kph": 80,
            "fleet_mix": {"Passenger Car": 80, "Passenger Truck": 15, "Refuse Truck": 5},
            "link_coordinates": [[116.25, 39.92], [116.3, 39.9]]
        }
    ],
    "pollutants": ["CO2", "NOx"],
    "model_year": 2020,
    "season": "夏季"
}
```

---

## 7. 参考资料

- **Leaflet 文档**: https://leafletjs.com/reference.html
- **ECharts GL 文档**: https://echarts.apache.org/zh/option-gl.html
- **GeoJSON 规范**: https://geojson.org/
- **现有宏排数据**: `calculators/macro_emission/data/`
