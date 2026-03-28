# HISTORY_RENDERING_AUDIT

## 1. 诊断过程与根因

### 1.1 实时聊天中的文件附件显示链路

1. 用户点击附件按钮，触发隐藏文件输入框：`attachButton` 绑定在 [web/app.js:230](/home/kirito/Agent1/emission_agent/web/app.js#L230)。
2. 文件选择后进入 `handleFileSelect()`：读取 `fileInput` 的 `change` 事件，调用文件预览 API，并显示输入区附件预览 chip，位置见 [web/app.js:755](/home/kirito/Agent1/emission_agent/web/app.js#L755) 和 [web/app.js:1500](/home/kirito/Agent1/emission_agent/web/app.js#L1500)。
3. 发送消息时，流式路径 `sendMessageStream()` 调用 `addUserMessage(message, file?.name)`，用户消息气泡顶部的附件标签由同一个 `addUserMessage()` 生成，位置见 [web/app.js:328](/home/kirito/Agent1/emission_agent/web/app.js#L328) 和 [web/app.js:1161](/home/kirito/Agent1/emission_agent/web/app.js#L1161)。
4. 附件标签 DOM 结构就在 `addUserMessage()` 内联模板中：
   - 容器 class: `inline-flex items-center gap-2 ... rounded-full shadow-sm`
   - 图标容器 class: `w-6 h-6 rounded-full bg-emerald-100 ...`
   - 文件名文本：`text-xs font-medium ... truncate`
   - 次级文案：`附件已上传`
5. 文件发送到后端时，通过 `FormData.append('file', file)` 附加在 `/api/chat/stream` 或 `/api/chat` 请求中，位置见 [web/app.js:353](/home/kirito/Agent1/emission_agent/web/app.js#L353)。

### 1.2 历史消息加载链路

1. 左侧会话点击后触发 `loadSession(session.session_id)`，入口见 [web/app.js:945](/home/kirito/Agent1/emission_agent/web/app.js#L945)。
2. `loadSession()` 请求历史接口 `GET /api/sessions/{session_id}/history`，位置见 [web/app.js:1093](/home/kirito/Agent1/emission_agent/web/app.js#L1093) 和 [api/routes.py:872](/home/kirito/Agent1/emission_agent/api/routes.py#L872)。
3. 响应返回后进入 `renderHistory(messages)`，逐条渲染消息，位置见 [web/app.js:1122](/home/kirito/Agent1/emission_agent/web/app.js#L1122)。
4. 原始缺陷点：
   - 历史用户消息只调用 `addUserMessage(msg.content)`，没有把 `file_name`/`file_path` 传进去。
   - 后端 `Session.save_turn()` 原先只给用户消息保存 `role/content/timestamp`，根本没有附件字段。
5. 结论：
   - 前端历史渲染缺少附件字段消费。
   - 后端用户消息历史缺少附件字段持久化。
   - 两端共同构成根因，不是单点前端 bug。

### 1.3 后端持久化检查

1. 当前会话持久化实现位于 [api/session.py:63](/home/kirito/Agent1/emission_agent/api/session.py#L63)。
2. 修复前：
   - 助手消息已保存 `chart_data`、`table_data`、`map_data`、`download_file`、`trace_friendly`。
   - 用户消息未保存 `file_name`、`file_path`、`file_size`。
3. 修复后：
   - 用户消息新增保存 `file_name`、`file_path`、`file_size`，见 [api/session.py:81](/home/kirito/Agent1/emission_agent/api/session.py#L81)。
   - 历史返回模型 `Message` 新增这些字段，见 [api/models.py:81](/home/kirito/Agent1/emission_agent/api/models.py#L81)。
4. 历史 API 还补做了两类归一化：
   - 旧消息里若把 `文件已上传，路径: ...` 直接拼进了 `content`，会拆回“纯文本 + 附件字段”，见 [api/routes.py:108](/home/kirito/Agent1/emission_agent/api/routes.py#L108)。
   - 旧消息下载元数据会统一重写成消息级下载 URL，并带 `user_id` 查询参数，见 [api/routes.py:898](/home/kirito/Agent1/emission_agent/api/routes.py#L898)。

### 1.4 额外发现并修复的历史一致性问题

1. `addAssistantMessage()` 原先只有在 `data_type === "table" | "table_and_map"` 时才渲染表格；这会让“同一条消息同时包含 chart + table”的历史消息漏掉表格，而实时流式路径会两者都渲染。已改为按 `table_data` 实际存在与否判断，见 [web/app.js:1199](/home/kirito/Agent1/emission_agent/web/app.js#L1199)。
2. 流式文本更新 `updateMessageContent()` 原先直接 `marked.parse(content)`，历史加载则走 `formatReplyText()` + `formatMarkdown()`，文本清洗路径不完全一致。现已统一，见 [web/app.js:498](/home/kirito/Agent1/emission_agent/web/app.js#L498)。
3. 非流式 `/api/chat` 路径原先会把“文件已上传，路径...”污染后的消息文本直接存进历史和标题，导致历史用户文本/会话标题与实时体验不一致。已改为只把原始用户文本入库，并为“仅上传文件”的首轮会话生成合理标题，见 [api/routes.py:193](/home/kirito/Agent1/emission_agent/api/routes.py#L193)。
4. 历史下载曾依赖历史里保存的绝对路径；旧数据若来自其他机器或旧工作区，按钮会失效。现在下载接口会优先回退到当前 `outputs/` 目录按文件名解析，见 [api/routes.py:163](/home/kirito/Agent1/emission_agent/api/routes.py#L163)、[api/routes.py:680](/home/kirito/Agent1/emission_agent/api/routes.py#L680)、[api/routes.py:707](/home/kirito/Agent1/emission_agent/api/routes.py#L707)。

## 2. 修复方案

1. 后端保存用户附件元数据，不改实时前端展示逻辑，只补历史所需字段。
2. 历史前端继续复用现有 `addUserMessage()`，只在 `renderHistory()` 把 `file_name/file_path` 传进去，见 [web/app.js:1128](/home/kirito/Agent1/emission_agent/web/app.js#L1128)。
3. 助手历史消息继续复用现有 `addAssistantMessage()`、`renderResultTable()`、`renderMapData()`、`attachTracePanelToMessage()`，不新增历史专用富媒体渲染路径。
4. 历史 API 对旧格式数据做最小归一化，避免前端背负多套兼容逻辑。

## 3. 历史渲染审查结果

| 项目 | 结果 | 结论 | 修复状态 |
|---|---|---|---|
| 3.1 纯文本用户消息 | ✅ | 实时与历史都走 `addUserMessage()` | 无需修改 |
| 3.1 文件附件标签 | ❌ | 历史缺少附件字段持久化，且 `renderHistory()` 未传文件名 | 已修复 |
| 3.1 用户头像/气泡样式 | ✅ | 实时与历史共用 `addUserMessage()` 模板 | 无需修改 |
| 3.2 Assistant Markdown | ⚠️ | 流式更新与历史加载的文本清洗入口不同 | 已修复为同一清洗/Markdown 逻辑 |
| 3.2 emoji 显示 | ✅ | 都来自同一文本内容渲染链路 | 无需修改 |
| 3.2 数值/单位格式 | ✅ | 文本与表格均由同一回复数据/格式化函数生成 | 无需修改 |
| 3.3 计算结果表格 | ✅ | 历史与实时都复用 `renderResultTable()` | 无需修改 |
| 3.3 表格标题 | ✅ | 同一 `renderResultTable()` 生成 | 无需修改 |
| 3.3 下载结果文件按钮 | ⚠️ | 旧历史的 `download.url`/绝对路径可能失效 | 已修复 URL 归一化和路径回退 |
| 3.3 “还有 N 行”提示 | ✅ | 同一 `renderResultTable()` 生成 | 无需修改 |
| 3.4 排放地图 | ✅ | 历史与实时都走 `renderMapData()` | 无需修改 |
| 3.4 浓度地图 | ✅ | 同一地图分发和 Leaflet 初始化逻辑 | 无需修改 |
| 3.4 热点地图 | ✅ | 同一地图分发和 Leaflet 初始化逻辑 | 无需修改 |
| 3.4 地图标题/图例 | ✅ | 同一地图渲染函数生成 | 无需修改 |
| 3.4 地图交互 | ✅ | 同一 Leaflet 初始化逻辑 | 无需修改 |
| 3.5 排放因子曲线图 | ⚠️ | 历史消息在 `chart + table` 组合时会漏表格 | 已修复为按 payload 存在判断 |
| 3.5 场景对比柱状图 | ✅ | 未发现独立历史分支；现有 chart payload 统一走同一渲染路径 | 无需修改 |
| 3.6 Trace 折叠面板 | ✅ | 历史与实时都走 `attachTracePanelToMessage()` | 无需修改 |
| 3.6 展开后的步骤详情 | ✅ | 同一 `renderTracePanel()` | 无需修改 |
| 3.6 工具选择/参数标准化/耗时 | ✅ | 前端直接消费同一 `trace_friendly` 数据结构 | 无需修改 |
| 3.7 会话标题 | ⚠️ | 非流式文件消息会话标题可能被污染或为空 | 已修复 |
| 3.7 消息顺序 | ✅ | 历史接口按 `session._history` 顺序返回，前端顺序渲染 | 无需修改 |
| 3.7 滚动位置 | ✅ | `renderHistory()` 结束后 `scrollToBottom()` | 无需修改 |
| 3.7 空会话处理 | ✅ | `renderHistory([])` 仅保留日期 chip，未见异常 | 无需修改 |

## 4. 后端数据持久化状态

| 字段/能力 | 状态 | 说明 |
|---|---|---|
| `file_name` | 已保存 | 用户消息历史新增字段 |
| `file_path` | 已保存 | 用户消息历史新增字段 |
| `file_size` | 已保存 | 用户消息历史新增字段 |
| `chart_data` | 已保存 | 助手消息原本已保存 |
| `table_data` | 已保存 | 助手消息原本已保存 |
| `map_data` | 已保存 | 助手消息原本已保存 |
| `download_file` | 已保存 | 助手消息原本已保存；历史接口补归一化 |
| `trace_friendly` | 已保存 | 前端 Trace 面板使用该字段 |
| 原始 `trace` | 未保存 | 当前前端不消费；继续只保存 `trace_friendly` 以控制存储体积 |

说明：

1. 这次没有改动后端主响应结构的既有字段，只为历史 `Message` 模型补了必需的附件字段。
2. 历史接口不会改写实时渲染协议；只对旧消息做清洗和下载链接归一化。

## 5. 测试结果

### 自动化

| 命令 | 结果 | 备注 |
|---|---|---|
| `node --check web/app.js` | ✅ 通过 | JS 语法正常 |
| `pytest -q tests/test_api_route_contracts.py` | ✅ 6 通过 | 覆盖附件历史返回、旧消息清洗、下载归一化 |
| `pytest -q tests/test_web_render_contracts.py` | ✅ 2 通过 | 更新为新的一致性契约 |
| `pytest -q` | ✅ 626 通过 | 全量通过 |
| `python scripts/utils/test_new_architecture.py` | ❌ 失败 | 沙箱网络受限，LLM 连接报 `httpx.ConnectError: [Errno 1] Operation not permitted` |
| `python scripts/utils/test_api_integration.py` | ❌ 失败 | 同上，受限于外部 LLM 网络连接 |

### 手动验证

1. 未在当前无浏览器、无外网的终端环境执行完整手动 UI 流程。
2. 建议按任务说明中的 1-6 步在本地浏览器复核。

## 6. 实际修改文件

1. `api/models.py`
2. `api/routes.py`
3. `api/session.py`
4. `web/app.js`
5. `tests/test_api_route_contracts.py`
6. `tests/test_web_render_contracts.py`
7. `HISTORY_RENDERING_AUDIT.md`
