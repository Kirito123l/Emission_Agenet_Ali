# Codebase Snapshot

生成时间: 2026-04-04  
工作区: `~/Agent1/emission_agent`

## 1. 前端关键函数位置表

| 函数名 | 文件 | 行号 | 简述 |
| --- | --- | ---: | --- |
| `fetchWithUser(url, options = {})` | `web/app.js` | 55 | 所有前端请求的统一包装，注入 `X-User-ID` 和可选 `Authorization` 头。 |
| `sendMessage()` | `web/app.js` | 243 | 非流式聊天入口，`POST /api/chat`，发送 `FormData`。 |
| `sendMessageStream(message, file)` | `web/app.js` | 331 | 流式聊天入口，`POST /api/chat/stream`，按行解析 JSON 事件流。 |
| `renderMapData(mapData, msgContainer)` | `web/app.js` | 1885 | 地图类型分发器，根据 `mapData.type` 进入 contour / hotspot / emission / raster 渲染。 |
| `renderMapExportButton(resultType, scenarioLabel)` | `web/app.js` | 2133 | 生成“导出结果图”按钮 HTML，内联调用 `exportMapImage(...)`。 |
| `renderContourMap(mapData, msgContainer)` | `web/app.js` | 2987 | 渲染 contour 卡片、统计信息、Leaflet 容器和图例。 |
| `initHotspotLeafletMap(mapData, mapId)` | `web/app.js` | 3043 | 热点地图初始化；这里绑定热点 polygon popup、标签和高亮道路层。 |
| `renderHotspotMap(mapData, msgContainer)` | `web/app.js` | 3254 | 渲染热点分析卡片、解释 banner、Leaflet 容器和图例。 |
| `readErrorDetail(response)` | `web/app.js` | 4039 | 导出失败时读取后端错误正文。 |
| `exportMapImage(buttonEl, resultType, scenarioLabel)` | `web/app.js` | 4055 | `POST /api/export_map`，下载导出的 PNG/SVG/PDF。 |

热点点击/弹窗绑定位置:

- `web/app.js:3112-3136` 在 `initHotspotLeafletMap()` 的 `onEachFeature` 中调用 `layer.bindPopup(...)`
- `web/app.js:3143-3171` 在同一函数中创建热点编号 `L.divIcon(...)`

## 2. chat/stream 请求流程

当前前端默认 `USE_STREAMING = true`，实际主路径是 `sendMessageStream()`，请求目标为 `/api/chat/stream`。非流式备用路径是 `sendMessage()`，请求目标为 `/api/chat`。

请求代码片段，来自 `web/app.js:349-369`:

```javascript
try {
    const formData = new FormData();
    formData.append('message', message);
    if (currentSessionId) {
        formData.append('session_id', currentSessionId);
    }
    if (file) {
        formData.append('file', file);
    }

    console.log('🌐 发送流式请求到:', `${API_BASE}/chat/stream`);

    const response = await fetchWithUser(`${API_BASE}/chat/stream`, {
        method: 'POST',
        body: formData
    });

    if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`);
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
```

错误处理位置:

- `web/app.js:467-468`: 单条流式事件 JSON 解析失败时只记录日志，不中断整个流。
- `web/app.js:473-476`: 整个流式请求失败时进入 `catch`，更新消息内容为 `抱歉，请求失败: ...`。
- `web/app.js:318-327`: 非流式 `sendMessage()` 的 `catch`，会移除 loading 并插入失败消息。
- 没有看到针对 `502`、超时、重试、退避的专门分支，当前都是通用错误处理。

## 3. API 路由列表

路由注册入口:

- `api/main.py:51` `app.include_router(router, prefix="/api")`
- `api/main.py:52` `app.include_router(map_export_router, prefix="/api")`

关键处理函数:

- `/api/chat` -> `api/routes.py:176` `async def chat(...)`
- `/api/chat/stream` -> `api/routes.py:318` `async def chat_stream(...)`
- `/api/export_map` -> `api/map_export.py:102` `async def export_map(payload: ExportMapRequest, request: Request)`

注册到应用中的路由清单:

| Method | Path | Handler |
| --- | --- | --- |
| `GET,HEAD` | `/openapi.json` | `openapi` |
| `GET,HEAD` | `/docs` | `swagger_ui_html` |
| `GET,HEAD` | `/docs/oauth2-redirect` | `swagger_ui_redirect` |
| `GET,HEAD` | `/redoc` | `redoc_html` |
| `POST` | `/api/chat` | `chat` |
| `POST` | `/api/chat/stream` | `chat_stream` |
| `POST` | `/api/file/preview` | `preview_file` |
| `GET` | `/api/gis/basemap` | `get_gis_basemap` |
| `GET` | `/api/gis/roadnetwork` | `get_gis_roadnetwork` |
| `GET` | `/api/file/download/{file_id}` | `download_file` |
| `GET` | `/api/file/download/message/{session_id}/{message_id}` | `download_file_by_message` |
| `GET` | `/api/download/{filename}` | `download_result_file` |
| `GET` | `/api/file/template/{template_type}` | `download_template` |
| `GET` | `/api/sessions` | `list_sessions` |
| `POST` | `/api/sessions/new` | `create_session` |
| `DELETE` | `/api/sessions/{session_id}` | `delete_session` |
| `PATCH` | `/api/sessions/{session_id}/title` | `update_session_title` |
| `GET` | `/api/sessions/{session_id}/history` | `get_session_history` |
| `GET` | `/api/health` | `health_check` |
| `GET` | `/api/test` | `test_endpoint` |
| `POST` | `/api/register` | `register` |
| `POST` | `/api/login` | `login` |
| `GET` | `/api/me` | `get_current_user` |
| `POST` | `/api/export_map` | `export_map` |
| `GET` | `/test` | `root_test` |
| `GET` | `/login` | `login_page` |
| `MOUNT` | `/` | `web` |

`ExportMapRequest` 字段定义，来自 `api/models.py:112-122`:

```python
class ExportMapRequest(BaseModel):
    session_id: Optional[str] = None
    result_type: str = "dispersion"  # "dispersion" | "hotspot" | "emission"
    scenario_label: str = "baseline"
    format: str = "png"              # "png" | "svg" | "pdf"
    dpi: int = 300
    add_basemap: bool = True
    add_roads: bool = True
    language: str = "zh"
```

## 4. hotspot road_contributions 数据结构

`tools/hotspot.py` 中的 `HotspotTool.execute()` 不自己构造 `road_contributions`，而是从上一轮 dispersion 结果透传:

- `tools/hotspot.py:62` 读取 `dispersion_data.get("road_contributions")`
- `tools/hotspot.py:91-92` 将其挂回 `analysis_data["road_contributions"]`

从测试和 `calculators/hotspot_analyzer.py:441-512` 可以确认 `road_contributions` 的输入结构大致是:

```python
{
    "receptor_top_roads": {
        "0": [(0, 3.5), (1, 1.5)],
        "1": [(0, 2.0), (1, 3.0)],
        "2": [(1, 4.0), (0, 2.0)],
        "3": [(0, 1.0), (1, 5.0)],
    },
    "road_id_map": ["road_A", "road_B"],
    "tracking_mode": "dense_exact",
}
```

含义推断:

- `receptor_top_roads`: `receptor_idx -> [(road_idx, contribution_value), ...]`
- `road_id_map`: `road_idx -> link_id`
- `tracking_mode`: road contribution 的跟踪模式元信息

`HotspotAnalyzer` 会把上面的 receptor-level 贡献汇总为每个热点里的 `contributing_roads`，输出结构见 `calculators/hotspot_analyzer.py:503-512`:

```python
{
    "link_id": "road_A",
    "contribution_pct": 60.0,
    "contribution_value": 1.5,
}
```

单个 hotspot 的完整字段，来自 `calculators/hotspot_analyzer.py:34-45`:

```python
{
    "hotspot_id": 1,
    "rank": 1,
    "center": {"lon": 121.404, "lat": 31.203},
    "bbox": [121.403, 31.202, 121.405, 31.204],
    "area_m2": 5000.0,
    "grid_cells": 2,
    "max_conc": 2.5,
    "mean_conc": 1.75,
    "cell_keys": ["0_2", "1_2"],
    "contributing_roads": [
        {"link_id": "road_A", "contribution_pct": 60.0, "contribution_value": 1.5},
        {"link_id": "road_B", "contribution_pct": 40.0, "contribution_value": 1.0},
    ],
}
```

`HotspotTool` 的 `result.data` 最终会包含:

- 分析器原始字段: `method`, `threshold_value`, `percentile`, `coverage_level`, `interpretation`, `hotspot_count`, `hotspots`, `summary`
- 工具补充字段: `raster_grid`, `road_contributions`, `coverage_assessment`, `contour_bands`, `roads_wgs84`, `query_info`, `meteorology_used`, `scenario_label`

`tools/spatial_renderer.py:890-901` 输出到前端的 hotspot `map_data` 则裁剪成:

```python
{
    "type": "hotspot",
    "title": "...",
    "scenario_label": "...",
    "center": [...],
    "zoom": 12,
    "interpretation": "...",
    "layers": [...],
    "hotspots_detail": hotspots,
    "contributing_road_ids": ["road_A", "road_B"],
    "coverage_assessment": {...},
    "summary": {...},
}
```

注意:

- 原始 `road_contributions` 会保留在 `ToolResult.data` 中
- 前端实际消费的是 `hotspots_detail[].contributing_roads` 和 `contributing_road_ids`
- `map_data` 本身不直接暴露 `road_contributions`

## 5. MapExporter 缓存现状

`services/map_exporter.py` 中 `MapExporter` 的 public 方法签名:

- `services/map_exporter.py:100` `__init__(self, runtime_config: Optional[Any] = None)`
- `services/map_exporter.py:110` `cleanup_expired_exports(self, output_dir: Optional[Path | str] = None, ttl_hours: Optional[int] = None) -> None`
- `services/map_exporter.py:135` `export_dispersion_map(self, dispersion_result: dict, output_path: str | Path, format: str = "png", dpi: int = 300, figsize: tuple[float, float] = (12, 10), add_basemap: bool = True, add_roads: bool = True, add_colorbar: bool = True, add_title: bool = True, add_scalebar: bool = True, title: str | None = None, language: str = "zh") -> str`
- `services/map_exporter.py:174` `export_hotspot_map(self, hotspot_result: dict, output_path: str | Path, format: str = "png", dpi: int = 300, figsize: tuple[float, float] = (12, 10), add_basemap: bool = True, add_roads: bool = True, add_colorbar: bool = True, add_title: bool = True, add_scalebar: bool = True, title: str | None = None, language: str = "zh") -> str`
- `services/map_exporter.py:215` `export_emission_map(self, emission_result: dict, output_path: str | Path, format: str = "png", dpi: int = 300, figsize: tuple[float, float] = (12, 10), add_basemap: bool = True, add_roads: bool = False, add_colorbar: bool = True, add_title: bool = True, add_scalebar: bool = True, title: str | None = None, language: str = "zh") -> str`

补充:

- `MapExporter` 类里没有通用的 `export_map()` 方法
- 通用分发发生在 `api/map_export.py:57-99` 的 `_export_map_sync(...)`
- API handler `export_map(payload, request)` 在 `api/map_export.py:102`

当前缓存现状:

- 没有看到导出结果缓存
- 没有文件内容 hash
- 没有“同参数命中已有导出图”的 `exists` 复用逻辑
- 当前唯一与“缓存”接近的行为是:
  - `cleanup_expired_exports(...)` 删除旧文件，不是缓存命中
  - `self._tile_server_reachable` 只缓存一次瓦片服务器可达性判断，见 `services/map_exporter.py:100-102` 和 `733-743`
- 导出文件名在 `api/map_export.py:136-139` 带时间戳，所以同一结果重复导出会生成新文件

如果以后要做 cache，现有入参里适合作为 cache key 的字段有:

- `result_type`
- `scenario_label`
- `stored.data` 的内容指纹或稳定 hash
- `format`
- `dpi`
- `figsize`
- `add_basemap`
- `add_roads`
- `add_colorbar`
- `add_title`
- `add_scalebar`
- `title`
- `language`
- 运行时配置中影响输出的值，如 `map_export_basemap_enabled`

## 6. 发现的潜在问题

1. 前端没有针对 `502`、超时、网络中断的专项处理。
   - `web/app.js` 的聊天和导出路径都只有通用 `catch`
   - 这意味着用户看到的错误文案会比较粗糙，也没有重试/退避

2. `MapExporter` 没有缓存，重复导出必定重新绘图。
   - 这在高 DPI、热点/contour 场景下会重复消耗 CPU
   - 现状更像“导出文件临时目录 + TTL 清理”，不是 cache

3. `MapExporter` 没有统一的 `export_map()` 方法。
   - 现在由 `api/map_export.py::_export_map_sync()` 负责按 `result_type` 分发
   - 如果未来增加新的导出类型，需要同时改 API 分发和服务层调用点

4. hotspot 原始 `road_contributions` 没有进入前端 `map_data`。
   - 前端当前足够展示 `contributing_roads`
   - 但如果以后需要做 receptor-level attribution drill-down，需要从 `ToolResult.data` 取，不是从 `map_data` 取

5. 应用里同时存在 `/test` 和 `/api/test`。
   - 两者都可用于测试可达性，但职责有些重复
   - 交接时容易混淆监控或 smoke test 使用哪个端点

6. 静态文件挂载是根路径 `/`。
   - `api/main.py:72` 通过 `app.mount("/", StaticFiles(...), name="web")`
   - 这对 SPA 是方便的，但后续若继续增加顶层非 `/api` 路由，需要注意与静态资源路由的关系

