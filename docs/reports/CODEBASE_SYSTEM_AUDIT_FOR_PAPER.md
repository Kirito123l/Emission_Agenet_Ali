# CODEBASE_SYSTEM_AUDIT_FOR_PAPER

> 审计范围说明：本报告基于对本地代码库的实际扫描与阅读，覆盖了 `core/`、`tools/`、`calculators/`、`services/`、`api/`、`web/`、`config/`、`skills/`、`shared/`、`llm/`、`scripts/`、`docs/`、`test_data/`、`LOCAL_STANDARDIZER_MODEL/`、`static_gis/`、`GIS文件/` 等目录。  
> 判断依据优先级：运行入口、路由、工具注册、调用链、前后端接口、持久化路径、测试脚本、配置与依赖。  
> 本报告不是 README 改写；对 README / docs 与当前代码不一致之处，已在文中明确指出。

# 1. 项目总体定位

这个系统当前并不是一个单纯的“聊天机器人”，也不是一个纯粹的“排放计算库”。从代码实际形态看，它是一个以自然语言交互为入口、以工具调用和数值计算为核心、并带有文件处理、会话记忆、结果可视化和知识检索能力的领域智能体系统。

它主要服务于机动车排放分析相关任务，包括：排放因子查询、基于轨迹的微观排放计算、基于路段/路网数据的宏观排放计算、文件驱动的数据分析、以及与排放法规/知识相关的 RAG 问答。系统既有 Web 前端、FastAPI 接口和登录会话管理，也有 CLI 入口，因此更接近“分析平台 + 领域智能体 + 轻量产品化界面”的组合体。

如果从论文包装角度看，它当前最像一个“已经产品化到一定程度的领域智能体原型”，而不是从零开始为论文写的最小方法验证代码。优点是功能链条完整；缺点是工程分层中仍保留多套旧架构、旧文档和旁路实现，需要在论文抽象时做明显收束。

# 2. 当前代码库的真实功能清单

下面按“功能模块”而非按文件罗列。每个模块的完成度分为：

- `已完成`：代码、调用链、接口基本打通，且能在主系统中被触发。
- `部分完成`：已有核心实现，但存在接入不完整、依赖外部条件、前端展示不完整、或旧新架构并存的问题。
- `预留`：存在接口、设计稿或资源，但主流程中没有真实闭环。

## 2.1 对话入口与会话系统

- 模块名称：自然语言对话入口
- 主要作用：接收用户文本/文件请求，进入统一路由，并返回文本、图表、表格、地图、下载文件元数据。
- 相关核心文件/目录：`main.py`、`run_api.py`、`api/main.py`、`api/routes.py`、`api/session.py`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`
- 输入输出：
  - 输入：文本消息、可选文件、会话 ID、用户标识/JWT
  - 输出：`ChatResponse`，包含 `reply`、`chart_data`、`table_data`、`map_data`、`download_file`、`message_id`
- 与其他模块关系：
  - 下游调用 `SessionRegistry -> Session -> UnifiedRouter`
  - 与前端 `web/app.js`、认证 `api/auth.py`、数据库 `api/database.py`、日志中间件绑定

补充判断：

- Web 默认走 `/api/chat/stream`，采用“换行分隔 JSON 流”的方式逐步返回状态、文本、表格、地图，不是单独的 planner/progress API。
- CLI 的 `main.py chat` 直接创建 `UnifiedRouter`，绕过 API 层。

## 2.2 LLM 路由 / assembler / executor 主链

- 模块名称：统一智能体主链
- 主要作用：把用户输入、记忆、文件上下文和工具定义组装给 LLM；让 LLM 决定是否调用工具；在执行层透明做参数标准化；再综合结果返回。
- 相关核心文件/目录：`core/router.py`、`core/assembler.py`、`core/executor.py`、`services/llm_client.py`、`tools/definitions.py`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`
- 输入输出：
  - 输入：`user_message`、`file_path`、记忆上下文、工具 schema
  - 输出：`RouterResponse(text/chart_data/table_data/map_data/download_file)`
- 与其他模块关系：
  - 上承 API / CLI
  - 下接工具注册表与具体工具
  - 与记忆系统、标准化服务、前端渲染格式强耦合

关键事实：

- 当前没有独立 planner JSON 层；`UnifiedRouter` 直接调用 `llm.chat_with_tools(...)`。
- `ContextAssembler` 负责拼接系统提示词、工具定义、事实记忆、工作记忆、文件摘要。
- `ToolExecutor` 在执行前透明标准化 `vehicle_type` / `pollutant(s)`，而不是让 LLM 输出标准名。
- `UnifiedRouter` 在工具执行后还会做二次 synthesis，并抽取 chart/table/map/download 结构给前端。

## 2.3 排放因子查询

- 模块名称：排放因子查询
- 主要作用：从本地 MOVES CSV 快照中按车型、污染物、年份、季节、道路类型查询速度-排放曲线。
- 相关核心文件/目录：`tools/emission_factors.py`、`calculators/emission_factors.py`、`calculators/data/emission_factors/`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`，工具名为 `query_emission_factors`
- 输入输出：
  - 输入：`vehicle_type`、`pollutant(s)`、`model_year`、`season`、`road_type`、`return_curve`
  - 输出：文本总结、曲线数据、关键速度点表格、可选 Excel 下载文件
- 与其他模块关系：
  - 由 `ToolExecutor` 做车型/污染物标准化
  - 由 `core/router.py` 格式化为前端 ECharts 所需数据
  - 前端通过 `renderEmissionChart()` 渲染曲线

代码层面的真实情况：

- 数据源不是数据库，而是本地 CSV 文件。
- `Speed` 字段编码中同时包含速度和道路类型，查询时在计算器内部做解析。
- 单污染物查询会尝试生成 Excel 下载文件；多污染物查询主要返回内存数据，不一定带下载文件。

## 2.4 微观排放计算

- 模块名称：微观排放计算
- 主要作用：根据逐秒轨迹数据（时间、速度、可选加速度/坡度），计算 VSP、opMode 和逐秒排放。
- 相关核心文件/目录：`tools/micro_emission.py`、`calculators/micro_emission.py`、`calculators/vsp.py`、`skills/micro_emission/excel_handler.py`、`calculators/data/micro_emission/`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`，工具名为 `calculate_micro_emission`
- 输入输出：
  - 输入：`trajectory_data` 或上传文件、`vehicle_type`、`pollutants`、`model_year`、`season`
  - 输出：逐点排放结果、汇总统计、表格预览、Excel 下载文件、自然语言摘要
- 与其他模块关系：
  - 文件读取依赖 `skills/micro_emission/excel_handler.py`
  - 核心数值由 `VSPCalculator` 和 `MicroEmissionCalculator` 执行
  - 路由层把 `results` 压缩成前端预览表格

需要特别说明的真实完成度判断：

- 微观计算主链是打通的。
- 但“智能列名映射”在微观路径中并没有真正做成 LLM 语义映射。`MicroEmissionTool` 初始化时会打印“Intelligent column mapping enabled”，但 `skills/micro_emission/excel_handler.py` 实际只用了硬编码候选列名，没有调用 LLM 做语义映射。因此：
  - 微观文件处理：`已完成`
  - 微观智能列名映射：`部分完成`

## 2.5 宏观排放计算

- 模块名称：宏观排放计算
- 主要作用：根据路段长度、流量、平均速度、车队组成计算路段级排放，并汇总为路段清单与总量。
- 相关核心文件/目录：`tools/macro_emission.py`、`calculators/macro_emission.py`、`skills/macro_emission/excel_handler.py`、`calculators/data/macro_emission/`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`，工具名为 `calculate_macro_emission`
- 输入输出：
  - 输入：`links_data` 或上传文件/ZIP、`pollutants`、`model_year`、`season`、`fleet_mix`、`default_fleet_mix`
  - 输出：路段级结果、总排放量、表格预览、Excel 下载文件、可选地图数据
- 与其他模块关系：
  - 读取 Excel/CSV/ZIP（Shapefile）依赖 `skills/macro_emission/excel_handler.py`
  - 数值由 `MacroEmissionCalculator` 执行
  - 如果存在几何信息，则在工具层直接组装 `map_data`

客观判断：

- 它本质上是“路段级/路网级批量宏观排放计算”，而不是独立的交通网络分配模型。
- 大规模路网能力主要来自“同一个宏观排放工具可处理很多 link”，并配套了 `test_data/test_shanghai_allroads.*` 这类大数据样本。
- 车队组成处理较完整：支持顶层 `fleet_mix` 下发、列名解析、默认车队回填、缺失行填补记录。

## 2.6 路网排放计算

- 模块名称：路网排放批量分析
- 主要作用：对整批路段数据执行宏观排放计算，并支持全路网结果可视化。
- 相关核心文件/目录：`tools/macro_emission.py`、`test_data/test_shanghai_allroads.*`、`test_data/ALLROADS_README.md`
- 当前完成度：`部分完成`
- 是否已经接入主流程：`是`，但作为宏观排放工具的“大规模使用场景”接入，而非独立工具
- 输入输出：
  - 输入：大量 link 记录（Excel/CSV/ZIP）
  - 输出：全路段排放表、地图线段渲染数据、下载文件
- 与其他模块关系：
  - 依赖宏观排放工具、地图前端、GIS 底图接口

为什么判断为“部分完成”而不是“已完成”：

- 代码确实支持大批量 link 计算与地图输出。
- 但没有专门的“路网排放”独立方法层、基准评测、性能工程或网络分析算法；本质仍是宏观排放工具的批量化使用。
- 从论文视角，这更像“应用场景扩展”而不是已经抽象成独立方法模块。

## 2.7 GIS / 地图可视化

- 模块名称：GIS 底图与排放地图可视化
- 主要作用：提供上海市行政区与路网底图 GeoJSON，并把宏观排放结果叠加为着色线段地图。
- 相关核心文件/目录：`api/routes.py`、`web/app.js`、`preprocess_gis.py`、`static_gis/`、`GIS文件/`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`
- 输入输出：
  - 输入：`map_data`（来自宏观排放工具） + `/api/gis/basemap`、`/api/gis/roadnetwork`
  - 输出：Leaflet 地图、污染物切换、路段 popup、底图叠加
- 与其他模块关系：
  - 地图本体由前端 Leaflet 渲染
  - 底图由 API 直接读取 `static_gis/*.geojson`
  - 路段几何来自上传文件或 ZIP Shapefile，而不是来自底图本身

需要区分的边界：

- 当前系统有“GIS 可视化”，但没有真正复杂的 GIS 空间分析流程。
- `static_gis/` 是预处理后的底图资源；`preprocess_gis.py` 只是把原始 Shapefile 简化成 GeoJSON。
- 地图中实际显示的排放值是 `kg/(h·km)` 的排放强度，不是单纯的路段总量。

## 2.8 文件上传与解析

- 模块名称：文件上传、预览与解析
- 主要作用：支持用户上传 Excel/CSV/ZIP，预览结构，分析任务类型，并将文件导入微观/宏观计算。
- 相关核心文件/目录：`api/routes.py`、`tools/file_analyzer.py`、`skills/micro_emission/excel_handler.py`、`skills/macro_emission/excel_handler.py`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`
- 输入输出：
  - 输入：`.xlsx/.xls/.csv/.zip`
  - 输出：文件预览、文件结构摘要、`task_type`、样例行、内部结构化数据
- 与其他模块关系：
  - API `/file/preview` 提供发送前预览
  - `UnifiedRouter` 上传文件后会自动调用 `analyze_file`
  - 微观/宏观工具各自读取具体内容

真实完成情况：

- 预览层可识别 trajectory / links / shapefile / unknown。
- `FileAnalyzerTool` 能分析 ZIP 中的 Shapefile 或表格文件。
- 宏观工具可直接吃 ZIP Shapefile；微观工具目前只处理表格文件，不处理 ZIP。

## 2.9 智能列名映射 / 参数标准化

- 模块名称：参数标准化与列语义映射
- 主要作用：把用户自然语言中的车型、污染物、表头列名等映射成系统标准格式。
- 相关核心文件/目录：`core/executor.py`、`services/standardizer.py`、`shared/standardizer/`、`skills/macro_emission/excel_handler.py`、`skills/micro_emission/excel_handler.py`、`config/unified_mappings.yaml`
- 当前完成度：`部分完成`
- 是否已经接入主流程：`部分接入`
- 输入输出：
  - 输入：自然语言车型/污染物、原始列名、文件样例
  - 输出：标准车型名、标准污染物名、标准字段映射、标准车队组成
- 与其他模块关系：
  - 车型/污染物标准化：主流程已接入 `ToolExecutor`
  - 列名映射：分散在 file analyzer / macro ExcelHandler / micro ExcelHandler 内部

必须明确的细分判断：

- 车型标准化：`已完成并接入主流程`
  - 由 `services/standardizer.py` 在执行层统一完成。
- 污染物标准化：`已完成并接入主流程`
  - 同上。
- 宏观列语义映射：`已完成但实现分散`
  - `skills/macro_emission/excel_handler.py` 使用 direct match + AI JSON 映射 + fuzzy fallback。
- 微观列语义映射：`部分完成`
  - 只有候选列名匹配，没有真正的 LLM 语义映射。
- 全局统一列映射架构：`未完全统一`
  - `services.standardizer.map_columns()`、`shared/standardizer/`、`skills/*/excel_handler.py` 是并存的三套路径。

## 2.10 多轮对话记忆

- 模块名称：多轮记忆与上下文保持
- 主要作用：保存最近对话、提取关键事实、缓存文件分析结果，支持后续追问。
- 相关核心文件/目录：`core/memory.py`、`api/session.py`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`
- 输入输出：
  - 输入：用户消息、助手回复、工具调用、文件路径与分析结果
  - 输出：working memory、fact memory、压缩记忆、会话历史
- 与其他模块关系：
  - `ContextAssembler` 读取记忆
  - API 会话历史接口读取 `Session._history`

但这里存在一个重要工程事实：

- 系统实际上有两套持久化：
  - `MemoryManager` 写入 `data/sessions/history/{session_id}.json`
  - `SessionManager` 写入 `data/sessions/{user_id}/history/{session_id}.json`
- 这说明“对话 UI 历史”和“Router 内部记忆”是两套并行状态，不是完全单源。
- 从功能上可用，但从论文方法或工程一致性上看，这是一个需要收敛的点。

## 2.11 工具调用 / function calling / tool registry

- 模块名称：工具注册与 function calling
- 主要作用：注册可被 LLM 调用的工具，并以 OpenAI function schema 暴露给主模型。
- 相关核心文件/目录：`tools/registry.py`、`tools/definitions.py`、`tools/base.py`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`
- 输入输出：
  - 输入：工具名、参数 JSON
  - 输出：`ToolResult`
- 与其他模块关系：
  - `ContextAssembler` 将 schema 暴露给 LLM
  - `ToolExecutor` 从 registry 获取工具执行

实测辅助信息：

- 本地执行 `python main.py health` 能成功注册并列出 5 个工具：
  - `query_emission_factors`
  - `calculate_micro_emission`
  - `calculate_macro_emission`
  - `analyze_file`
  - `query_knowledge`

## 2.12 RAG / 知识检索 / 文档问答

- 模块名称：知识检索问答
- 主要作用：基于本地索引做检索，再用 LLM 精炼答案并附上来源文档。
- 相关核心文件/目录：`tools/knowledge.py`、`skills/knowledge/skill.py`、`skills/knowledge/retriever.py`、`skills/knowledge/reranker.py`、`skills/knowledge/index/`
- 当前完成度：`部分完成`
- 是否已经接入主流程：`是`，工具名为 `query_knowledge`
- 输入输出：
  - 输入：`query`、`top_k`、`expectation`
  - 输出：检索结果、精炼答案、来源列表
- 与其他模块关系：
  - 通过 tool registry 接入主链
  - 使用旧版 `llm/client.py` 做答案精炼
  - 依赖本地 FAISS 索引和 embedding/rerank 配置

为什么判断为“部分完成”：

- 好的一面：
  - 索引文件真实存在，`chunks.jsonl` 约 13,860 条，`dense_index.faiss` 等本地资源齐全。
  - 工具已注册进主系统。
- 不完整的一面：
  - 检索代码实际只用了 dense FAISS；仓库中的 `sparse_embeddings.pkl` 没有接入主流程。
  - 索引构建流水线不在当前仓库中；只有 `scripts/migrate_knowledge.py` 用于从外部项目迁移索引，复现实验链条不完整。
  - 运行时依赖 DashScope API 或本地 BGE-M3；如果环境没配好，工具会在执行期失败。
  - `scripts/utils/test_rag_integration.py` 当前自身路径假设有问题，不能作为可靠回归脚本。

## 2.13 API 接口

- 模块名称：FastAPI 服务接口
- 主要作用：提供聊天、流式响应、文件预览、下载、GIS 数据、会话、认证等接口。
- 相关核心文件/目录：`api/main.py`、`api/routes.py`、`api/models.py`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`
- 输入输出：
  - 输入：HTTP 请求、multipart 文件、JWT、X-User-ID
  - 输出：JSON / 流式 JSON 行 / 文件 / GeoJSON 响应
- 与其他模块关系：
  - 上连 Web
  - 下连 Session、Router、数据库、日志中间件

主要接口族：

- 聊天：`/api/chat`、`/api/chat/stream`
- 文件：`/api/file/preview`、`/api/file/download/...`、`/api/file/template/...`
- GIS：`/api/gis/basemap`、`/api/gis/roadnetwork`
- 会话：`/api/sessions*`
- 认证：`/api/register`、`/api/login`、`/api/me`

## 2.14 Web 前端 / 聊天界面 / 图表界面

- 模块名称：Web 前端
- 主要作用：提供聊天 UI、流式输出、文件上传、历史会话、图表表格地图渲染、登录注册页。
- 相关核心文件/目录：`web/index.html`、`web/app.js`、`web/login.html`、`web/diagnostic.html`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`
- 输入输出：
  - 输入：文本、文件、会话切换、登录
  - 输出：聊天消息、ECharts 图、结果表、Leaflet 地图、下载按钮
- 与其他模块关系：
  - 通过 `fetchWithUser()` 访问 API
  - 依赖 ECharts、Leaflet、Marked、Tailwind CDN

但前端也存在“功能已做但并非完全一致”的地方：

- 流式路径对 `table`、`map`、`chart` 的渲染更完整。
- 非流式 / 历史回放路径中，`addAssistantMessage()` 对 `table_and_map` 的处理不完全一致，容易出现地图能显示但表格不显示的情况。
- 因此从“系统有这个能力”角度可记为已接入；从“所有入口展示完全一致”角度应记为部分打磨不足。

## 2.15 结果可视化（图表、表格、地图）

- 模块名称：结果可视化
- 主要作用：将后端结构化结果转为可交互可读的图、表、地图。
- 相关核心文件/目录：`core/router.py`、`api/routes.py`、`web/app.js`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`
- 输入输出：
  - 图表输入：排放因子曲线
  - 表格输入：微观/宏观结果预览与摘要
  - 地图输入：带几何和排放强度的路段列表
- 与其他模块关系：
  - 后端在 `Router` 中做数据抽取和轻量格式转换
  - 前端负责最终渲染

当前真实支持：

- 图表：ECharts 折线图，支持污染物切换
- 表格：汇总表 + 预览表 + 下载按钮
- 地图：Leaflet 折线着色图 + 污染物切换 + popup + GIS 底图叠加

## 2.16 本地模型 / 云端模型适配

- 模块名称：模型适配层
- 主要作用：适配云端大模型、本地 LLM、本地标准化模型、RAG embedding/rerank 模式。
- 相关核心文件/目录：`config.py`、`services/llm_client.py`、`llm/client.py`、`shared/standardizer/local_client.py`、`LOCAL_STANDARDIZER_MODEL/`
- 当前完成度：`部分完成`
- 是否已经接入主流程：`部分接入`
- 输入输出：
  - 输入：purpose、provider、API key、本地模型开关
  - 输出：统一聊天/JSON 调用能力、标准化能力
- 与其他模块关系：
  - 新主链使用 `services/llm_client.py`
  - 旧 skill / ExcelHandler / RAG refine 仍使用 `llm/client.py`
  - 本地标准化模型由 `shared/standardizer/local_client.py` 适配

真实情况：

- 云端模型适配：`已完成`
  - `config.py` 已支持 qwen / deepseek / local provider 配置。
- 本地标准化模型推理代码：`部分完成`
  - 客户端、配置、训练数据、LoRA 训练脚本都在。
  - 但 `LOCAL_STANDARDIZER_MODEL/models/` 目录下当前没有实际模型权重文件，仓库里只有训练/集成脚本，没有可直接运行的模型产物。
- LLM 适配架构：`未完全统一`
  - 新旧两套客户端并存：`services/llm_client.py` 与 `llm/client.py`。

## 2.17 日志、缓存、错误处理、配置系统

- 模块名称：日志/缓存/配置/错误处理
- 主要作用：记录访问日志、缓存请求体与 GIS 数据、缓存文件分析、管理配置和友好错误提示。
- 相关核心文件/目录：`api/logging_config.py`、`config.py`、`services/config_loader.py`、`core/memory.py`、`api/routes.py`
- 当前完成度：`已完成`
- 是否已经接入主流程：`是`
- 输入输出：
  - 输入：请求、异常、配置文件、环境变量
  - 输出：结构化日志、缓存命中、友好错误、目录初始化
- 与其他模块关系：
  - API 中间件负责访问日志
  - Router 负责文件分析缓存
  - GIS 接口有进程内缓存

比较有价值的工程特征：

- `api/logging_config.py` 会缓存 request body 并输出结构化访问日志。
- `UnifiedRouter` 对文件分析结果做了“路径 + mtime”缓存，避免同一路径被新文件覆盖时误用旧分析结果。
- `services/llm_client.py` 和 `llm/client.py` 都实现了代理失败时 proxy/direct failover。

# 3. 系统主流程梳理

## 3.1 总体主流程

当前真实主流程可以概括为：

`用户输入/上传文件 -> API 或 CLI 入口 -> Session/Router -> ContextAssembler -> LLM(tool use) -> ToolExecutor -> 具体工具/计算器/RAG -> Router 综合结果 -> API 规范化响应 -> Web 渲染`

更细的链路如下：

```text
Web / CLI
  -> api/routes.py 或 main.py
  -> api/session.py::Session.chat()
  -> core/router.py::UnifiedRouter.chat()
  -> 若有文件：先调用 analyze_file
  -> core/assembler.py::assemble()
  -> services/llm_client.py::chat_with_tools()
  -> core/executor.py::execute()
  -> tools/*.py
  -> calculators/*.py 或 skills/knowledge/*
  -> core/router.py::_synthesize_results() + _extract_*
  -> api/routes.py 规范化 download/map/table/chart
  -> web/app.js 渲染
```

## 3.2 主入口文件

- CLI 主入口：`main.py`
- API 启动入口：`run_api.py`
- FastAPI 应用入口：`api/main.py`
- 前端入口：`web/index.html`

## 3.3 主 API 路由

- 非流式聊天：`POST /api/chat`
- 流式聊天：`POST /api/chat/stream`
- 文件预览：`POST /api/file/preview`
- GIS 资源：`GET /api/gis/basemap`、`GET /api/gis/roadnetwork`
- 历史会话：`GET /api/sessions/{session_id}/history`

## 3.4 核心 orchestrator / router / executor

- orchestrator：`core/router.py::UnifiedRouter`
- context assembler：`core/assembler.py::ContextAssembler`
- executor：`core/executor.py::ToolExecutor`
- tool registry：`tools/registry.py`

## 3.5 前后端交互链路

### 自然语言问答路径

1. 用户在 `web/app.js` 输入文本。
2. 前端把请求发往 `/api/chat/stream` 或 `/api/chat`。
3. API 取出 `user_id/session_id`，找到或创建 `Session`。
4. `Session.chat()` 调用 `UnifiedRouter.chat()`。
5. Router 组装上下文给主 LLM。
6. LLM 决定直接回答，或者调用 `query_emission_factors` / `query_knowledge` 等工具。
7. 工具执行完后，Router 做 synthesis。
8. API 返回文本和结构化数据；前端将其渲染为 Markdown、图表、表格或地图。

### 文件驱动分析路径

1. 用户上传文件，前端先调用 `/api/file/preview`。
2. 发送正式消息时，API 将文件保存到临时目录，并把文件路径附加进 prompt，同时把 `file_path` 单独传给 Router。
3. Router 先执行 `analyze_file`，得到 `task_type`、列名、样例行等。
4. `ContextAssembler` 把文件摘要插入当前 user message 上方。
5. LLM 基于文件类型选择 `calculate_micro_emission` 或 `calculate_macro_emission`，或继续追问缺失参数。
6. 结果返回后，API 保存历史并为下载文件补 URL。

### RAG 路径

1. 用户提出法规、标准、概念性问题。
2. LLM 在 tool use 阶段可调用 `query_knowledge`。
3. `tools/knowledge.py` 包装 `KnowledgeSkill.execute()`。
4. `KnowledgeRetriever.search()` 使用 dense FAISS 检索。
5. `KnowledgeReranker.rerank()` 进行 API 或本地重排。
6. `KnowledgeSkill._refine_answer()` 再调用旧版 `llm/client.py` 做答案精炼。
7. Router 对单一知识工具结果直接返回 summary，跳过额外 synthesis。

### GIS 可视化路径

1. 宏观排放工具在读取到几何字段或 ZIP Shapefile 后，调用 `_build_map_data()`。
2. `map_data` 被 Router 抽出并经 API 返回。
3. 前端 `renderEmissionMap()` / `initLeafletMap()` 使用 Leaflet 绘制排放线段。
4. 同时前端调用 `/api/gis/basemap` 和 `/api/gis/roadnetwork` 加载上海底图与路网 GeoJSON 作为背景层。

### 路网排放分析路径

1. 用户上传大量路段文件，或发送“大规模路网排放”指令。
2. 文件预分析识别为 `macro_emission`。
3. LLM 调用 `calculate_macro_emission`。
4. 宏观工具读取全量 link 数据，执行逐 link 计算。
5. 同时返回路网级表格数据和地图数据。
6. 前端渲染为路段排放地图和路段预览表。

### 微观排放路径

1. 用户提供轨迹文件或轨迹数组。
2. LLM 调用 `calculate_micro_emission`。
3. 工具读取轨迹数据，缺失加速度时自动估算，缺失坡度时默认 0。
4. `VSPCalculator` 计算 VSP、opMode。
5. `MicroEmissionCalculator` 查询 MOVES 矩阵并生成逐秒排放。
6. Router 抽出摘要和前几行结果表。

### 宏观排放路径

1. 用户提供 link 文件、Shapefile ZIP 或 link 数据数组。
2. LLM 调用 `calculate_macro_emission`。
3. 工具进行列映射、字段修复、车队组成修复与缺失回填。
4. `MacroEmissionCalculator` 用平均 opMode=300 的矩阵计算每条路段排放。
5. 工具返回表格预览、总量摘要、下载文件、可选地图数据。

# 4. 代码架构与模块关系

## 4.1 架构类型判断

这个系统最接近：

- 一个单体式代码仓中的模块化系统
- 运行时采用 agent workflow / tool-use 风格
- 工具层具备一定插件式特征

它不是严格意义上的“通用 agent 框架”，而是“围绕机动车排放任务定制的单仓智能体应用”。

## 4.2 模块关系（简化 ASCII 图）

```text
                +--------------------+
                |  Web / CLI / API   |
                +---------+----------+
                          |
                          v
                +--------------------+
                |  Session / Router  |
                | UnifiedRouter      |
                +----+---------+-----+
                     |         |
                     |         +-------------------+
                     v                             v
           +-------------------+         +-------------------+
           | ContextAssembler  |         | MemoryManager     |
           +-------------------+         +-------------------+
                     |
                     v
           +-------------------+
           | LLM Tool Use      |
           +-------------------+
                     |
                     v
           +-------------------+
           | ToolExecutor      |
           | 标准化 + 执行      |
           +----+----+----+----+
                |    |    |    |
                v    v    v    v
             EF   Micro Macro  RAG
                \    |    /     |
                 \   |   /      |
                  v  v  v       v
              calculators    skills/knowledge
                     |
                     v
              chart / table / map / file
                     |
                     v
                 Web Render
```

## 4.3 工具模块与 LLM 模块如何耦合

- 新主链中，LLM 与工具通过 OpenAI function schema 耦合，耦合点集中在：
  - `tools/definitions.py`
  - `services/llm_client.py`
  - `core/router.py`
- 这是一种相对清晰的耦合方式。
- 但仓库内仍有旧 skill/LLM 路径：
  - RAG 精炼和部分 ExcelHandler 仍依赖 `llm/client.py`
  - 新旧 LLM 客户端并存

结论：主链耦合方式较清楚，但全仓还没有完成统一收束。

## 4.4 参数标准化是在 LLM 前、LLM 后还是执行层完成

按代码实际：

- 车型 / 污染物标准化：在 `ToolExecutor` 中执行，属于“LLM 后、执行前”的透明标准化。
- 文件列名映射：不统一。
  - `FileAnalyzerTool` 中是 heuristics/config-first
  - 宏观 ExcelHandler 中是“启发式 + LLM JSON 映射 + fuzzy fallback”
  - 微观 ExcelHandler 中是硬编码列名匹配

因此，这个系统的“参数标准化”其实是分层的：

- 用户自然语言实体：执行层透明标准化
- 表格结构语义：工具内部文件处理阶段标准化

## 4.5 RAG 与数值计算的关系

当前 RAG 与数值计算是并列工具，而不是深度融合方法：

- `query_knowledge` 主要回答法规/知识问题。
- 微观/宏观/因子工具主要处理数值计算。
- Router 会根据 LLM 的 tool use 决策选择其一。
- 没有看到“先检索知识再约束数值计算参数”的强绑定机制。

换言之，系统是“双路径共存”，不是“知识约束数值计算”的统一算法框架。

## 4.6 GIS 可视化与排放结果的关系

- GIS 底图只是背景参考层。
- 真正的排放地图数据来自宏观排放工具输出的 `map_data`。
- 上传 Shapefile 或带 geometry 的表格文件，会把几何随计算结果一起送到前端。
- 因此 GIS 与排放结果的关系是“结果承载和展示”，而不是“GIS 先验驱动计算”。

## 4.7 哪些设计比较有特色

- 以自然语言作为统一入口，把数值计算、文件分析、RAG、结果可视化串成一个闭环。
- Router 对文件分析做了 mtime 缓存，避免同路径文件覆盖导致误用旧分析结果。
- 宏观排放文件处理里，列语义映射、车队组成识别、缺失车队组成回填和结果回写做得比较工程化、但也比较完整。
- 宏观计算结果直接在工具层转换成 `map_data`，前端可立即渲染，不需要额外地图服务。

## 4.8 哪些地方偏工程实现，哪些地方接近“方法框架”

更偏工程实现的部分：

- FastAPI、登录注册、SQLite 用户表、前端页面、下载接口、日志中间件、会话管理
- GIS 静态底图预处理与 Leaflet 渲染
- Excel/ZIP/Shapefile 的文件兼容与下载导出

更接近“方法框架”的部分：

- Tool-use 驱动的领域分析主链
- 执行层透明参数标准化
- 文件分析 + 文件任务类型识别 + 自动选工具
- 数值计算路径与知识检索路径并存的双通道架构

# 5. 已实现能力 vs 未完成能力

## 5.1 已经完整可用的能力

- 基于自然语言的排放因子查询，含图表和表格输出
- 基于轨迹文件/数组的微观排放计算
- 基于路段文件/数组的宏观排放计算
- 宏观排放结果导出为 Excel
- 文件上传、预览、任务类型识别
- 会话创建、历史保存、下载链接回填
- Web 聊天界面与流式响应
- 上海 GIS 底图与路网底图加载
- 宏观排放地图可视化
- JWT 登录注册与游客模式
- 工具注册、统一 Router 主链、执行层车型/污染物标准化

## 5.2 已有雏形但还不稳定 / 未完全打通的能力

- RAG / 知识检索
  - 已接主流程，但运行依赖外部 embedding/rerank 配置，索引构建流程不在仓库内，测试脚本也有路径问题。
- 路网级大规模排放分析
  - 可通过宏观工具处理大规模 link，但缺少独立性能基准与稳定性说明。
- 智能列名映射
  - 宏观路径较强，微观路径较弱；系统层并未统一。
- 前端“表格 + 地图”一体渲染
  - 流式路径较完整，非流式/历史回放仍有展示不一致。
- 本地标准化模型
  - 训练与接入脚手架完整，但仓库缺实际模型权重。
- 新旧架构统一
  - 主流程已切到 `core/ + tools/`，但 `skills/`、`shared/standardizer/`、`llm/` 仍有遗留并行逻辑。

## 5.3 仅有接口或计划中的能力

- 完整可复现的 RAG 索引构建流水线
  - 当前仓库只有索引迁移脚本，没有完整构建流程。
- 稳定可复现的本地标准化模型推理产物
  - 只有训练/集成脚本，模型文件缺失。
- 独立的 planner / task decomposition 层
  - 当前没有。
- 更复杂的 GIS 空间分析能力
  - 当前只有底图叠加和结果可视化，没有空间统计、空间联动分析、网络分析。
- 一套真正统一的新技能/新 LLM/新标准化基础设施
  - 仍在过渡状态。

# 6. 从学术论文角度看，这个系统已经具备哪些潜在贡献点

下面只提“从代码里可以成立”的潜在点，不做夸大。

## 6.1 面向机动车排放分析的自然语言智能体

- 代码体现在哪里：
  - `core/router.py`
  - `tools/definitions.py`
  - `web/app.js`
- 更偏工程实现还是方法点：介于两者之间，更偏“领域智能体系统方法”
- 是否足以作为独立贡献：`可以作为主贡献之一`

成立原因：

- 它不是通用聊天壳，而是把排放因子、微观排放、宏观排放、文件分析和知识检索组织成统一工具生态。
- 这条主线很适合包装成“领域特化 agent for emission analysis”。

## 6.2 数值计算路径 + 文档知识路径的双路径系统

- 代码体现在哪里：
  - 数值路径：`tools/emission_factors.py`、`tools/micro_emission.py`、`tools/macro_emission.py`
  - 知识路径：`tools/knowledge.py`、`skills/knowledge/`
- 更偏工程实现还是方法点：偏系统方法点
- 是否足以作为独立贡献：`可作为辅贡献，不建议单独撑全文`

价值在于：

- 同一入口下既能做 deterministic numeric workflow，也能做 RAG-based knowledge QA。
- 这对专业领域用户体验有意义。

但要注意：

- 目前两条路径是“并列”而不是“深融合”，因此论文中不宜把它夸成统一推理范式。

## 6.3 高约束领域的透明参数标准化机制

- 代码体现在哪里：
  - `core/executor.py`
  - `services/standardizer.py`
  - `config/unified_mappings.yaml`
- 更偏工程实现还是方法点：偏方法框架，可抽象
- 是否足以作为独立贡献：`有潜力，但需要补实验`

这个点比较适合论文化：

- LLM 不需要学会输出 MOVES 标准名；
- 执行层负责把用户自然语言实体映射成受控标准参数；
- 这样减少了 prompt 负担，也降低了 tool argument 不规范导致的失败。

如果补上实验，可以做：

- 无标准化 vs 规则标准化 vs 透明标准化 的工具调用成功率比较。

## 6.4 文件驱动的排放分析工作流

- 代码体现在哪里：
  - `tools/file_analyzer.py`
  - `core/router.py`
  - `skills/macro_emission/excel_handler.py`
  - `skills/micro_emission/excel_handler.py`
- 更偏工程实现还是方法点：偏系统实现，但论文里很有展示价值
- 是否足以作为独立贡献：`更适合作为系统亮点，不建议单独做核心贡献`

理由：

- 上传任意表格/ZIP 后，系统能先识别任务类型，再进入相应分析链路。
- 对实际科研和业务用户很重要，因为他们往往先有文件，再提问题。

## 6.5 路网排放与 GIS 可视化联动

- 代码体现在哪里：
  - `tools/macro_emission.py::_build_map_data`
  - `api/routes.py` GIS 接口
  - `web/app.js` Leaflet 渲染
  - `preprocess_gis.py`
- 更偏工程实现还是方法点：偏应用型系统贡献
- 是否足以作为独立贡献：`适合作为应用系统论文的亮点，不适合作为纯方法贡献`

成立点：

- 不是只给数字表格，而是把路段结果转成可视化地图。
- 对交通/排放领域评审来说，这比单纯聊天结果更接近决策支持系统。

## 6.6 多轮上下文支持的专业分析系统

- 代码体现在哪里：
  - `core/memory.py`
  - `api/session.py`
- 更偏工程实现还是方法点：偏工程实现
- 是否足以作为独立贡献：`不宜单独作为贡献，但可作为必要系统能力`

原因：

- 记忆系统可以支持“NOx 呢”“换成公交车”之类追问。
- 但当前记忆设计还没有抽象成特别新的研究点，而且存在双持久化路径。

# 7. 从学术论文角度看，目前最缺什么

## 7.1 明确任务定义

现在代码能做很多事，但论文需要收敛成 1 到 2 个明确任务，而不是“什么都能做”。当前最缺的是：

- 任务边界定义
- 输入输出规范
- 典型用户问题集合
- 成功标准

## 7.2 benchmark / baseline / 消融

这是当前最明显的短板。

缺失项包括：

- benchmark 数据集
- baseline 方法
- 消融实验
- 量化指标

尤其是如果你想突出“透明标准化”“文件驱动工作流”“双路径系统”，都需要配套实验，否则只能写成系统介绍。

## 7.3 可重复实验脚本

仓库里有测试脚本，但它们更多是工程 smoke test，不是论文实验脚本。

目前缺：

- 批量运行实验脚本
- 标准输入集合
- 自动评估输出质量
- 环境依赖锁定
- RAG 索引构建与本地模型复现流程

## 7.4 错误分析支持

系统代码有错误处理，但没有论文所需的 error analysis 资产，例如：

- tool selection 失败案例
- 参数标准化失败案例
- 文件列映射失败案例
- RAG 误检/漏检案例
- 微观/宏观计算参数不一致造成的偏差分析

## 7.5 方法抽象还不够统一

最关键的问题不是“功能不够多”，而是“方法叙事还不够统一”。

目前仓库的实际情况是：

- 新主链：`core/ + tools/ + services/`
- 旧支线：`skills/ + llm/ + shared/standardizer/`

论文里如果直接照搬，会显得方法边界模糊。因此需要你们后续把论文主线收束成：

- 一个统一系统框架
- 若干关键方法模块
- 清楚的输入输出关系

## 7.6 用户研究 / 专家评估 / 真实案例

这类领域系统论文很适合补：

- 交通/排放领域专家评审
- 若干真实案例工作流
- 与传统手工流程的时间/错误率对比

当前代码本身还没有内置这部分证据。

# 8. 这个项目最适合包装成哪一类论文

基于当前代码现状，我认为最适合的是：

- `应用型系统论文`
- `领域智能体论文`
- `交通/排放领域 AI 应用论文`

不太适合直接包装成：

- 纯 RAG 方法论文
- 纯 tool-use 方法论文
- 纯可视化论文

理由如下：

1. 代码最强的地方是完整系统闭环，而不是单一算法创新。
2. 它对机动车排放这个高约束领域做了比较深的任务化定制。
3. 数值计算、文件输入、可视化、记忆、RAG 都有，但都更适合作为“系统模块”而不是各自一篇方法论文。
4. GIS 和路网能力是亮点，但仍以“系统应用价值”更强。

如果要更具体一点，最合适的题型会是：

`面向机动车排放分析的多工具自然语言智能体系统`

或者

`A domain-specific agent system for vehicle emission analysis with file-driven computation and map-based result exploration`

# 9. 论文包装建议（务实版）

## 9.1 如果只给 1 到 2 个月补实验，最值得优先补什么

优先级建议：

1. 先把论文主线收成“自然语言 + 文件驱动 + 排放计算 + 可视化”这一条
2. 补透明标准化和文件工作流的量化实验
3. 补 3 到 5 个真实案例

具体可执行项：

- 实验 1：工具调用成功率
  - 比较：无标准化 / 规则标准化 / 执行层透明标准化
- 实验 2：文件理解成功率
  - 比较：固定列名文件 vs 变体列名文件
- 实验 3：端到端案例效率
  - 比较：人工分析流程 vs 系统辅助流程

## 9.2 哪些功能虽然炫，但对论文帮助不大

- 登录注册、游客模式、会话重命名
- 过多前端 UI 细节
- 诊断页面
- 多 provider 细节
- 旧架构兼容层

这些是产品化加分项，不是论文核心。

## 9.3 哪些模块最值得作为论文主线

最值得抓住的主线是：

- 自然语言入口
- 透明参数标准化
- 文件驱动任务识别与数据导入
- 双数值计算链（微观 + 宏观）
- 路网结果可视化

这条线最完整，也最符合你项目的真实优势。

## 9.4 哪些内容应该放进论文方法部分

- 系统总框架
- tool-use 驱动的路由机制
- 执行层透明标准化
- 文件分析与任务类型识别
- 微观/宏观双计算链的统一封装方式
- 结果结构化抽取与多模态输出（文本/表/图/图层）

## 9.5 哪些内容更适合放到系统实现部分

- FastAPI、JWT、SQLite、SessionRegistry
- 前端 ECharts / Leaflet 实现
- 下载接口和模板接口
- 日志中间件
- GIS 底图预处理脚本
- 本地模型训练脚手架

## 9.6 哪些内容适合作为实验案例

- 排放因子查询案例
  - 用来展示自然语言到曲线查询的轻量分析流程
- 轨迹文件微观排放案例
  - 用来展示文件驱动 + VSP 计算
- 路段/路网文件宏观排放案例
  - 用来展示大规模 link 计算 + 地图联动
- 法规/标准问答案例
  - 作为附加能力，不建议放成主实验

# 10. 附录：关键文件索引

## 10.1 主流程入口

- `main.py`
- `run_api.py`
- `api/main.py`
- `core/router.py`

## 10.2 API 层

- `api/routes.py`
- `api/models.py`
- `api/session.py`
- `api/auth.py`
- `api/database.py`
- `api/logging_config.py`

## 10.3 LLM / router / assembler / executor

- `core/router.py`
- `core/assembler.py`
- `core/executor.py`
- `core/memory.py`
- `services/llm_client.py`
- `llm/client.py`（旧路径，RAG refine 和部分旧组件仍在用）

## 10.4 tool registry / tool definitions

- `tools/base.py`
- `tools/registry.py`
- `tools/definitions.py`

## 10.5 排放计算

- `tools/emission_factors.py`
- `tools/micro_emission.py`
- `tools/macro_emission.py`
- `calculators/emission_factors.py`
- `calculators/micro_emission.py`
- `calculators/macro_emission.py`
- `calculators/vsp.py`
- `calculators/data/`

## 10.6 文件处理与列映射

- `tools/file_analyzer.py`
- `skills/micro_emission/excel_handler.py`
- `skills/macro_emission/excel_handler.py`
- `services/standardizer.py`
- `config/unified_mappings.yaml`

## 10.7 RAG / 检索

- `tools/knowledge.py`
- `skills/knowledge/skill.py`
- `skills/knowledge/retriever.py`
- `skills/knowledge/reranker.py`
- `skills/knowledge/index/`
- `scripts/migrate_knowledge.py`

## 10.8 GIS / 地图可视化

- `tools/macro_emission.py`
- `api/routes.py`
- `web/app.js`
- `preprocess_gis.py`
- `static_gis/`
- `GIS文件/`
- `test_data/test_shanghai_allroads.*`

## 10.9 前端页面

- `web/index.html`
- `web/app.js`
- `web/login.html`
- `web/diagnostic.html`

## 10.10 配置文件

- `config.py`
- `config/prompts/core.yaml`
- `config/unified_mappings.yaml`
- `.env.example`
- `requirements.txt`

## 10.11 文档说明

- `README.md`
- `docs/ARCHITECTURE.md`
- `docs/INTERNAL_emission_calculation_guide.md`
- `docs/INTERNAL_map_viz_design.md`
- `docs/RAG_UPGRADE_SUMMARY.md`
- `docs/RAG_CONFIGURATION_GUIDE.md`
- `docs/designs/smart_column_mapping_design.md`
- `LOCAL_STANDARDIZER_MODEL/README.md`

## 10.12 与当前代码现状不一致、需要谨慎对待的文档/脚本

- `README.md`
  - 架构概述大体对，但对 GIS、认证、旧新并行结构、部分文件名和细节描述不够准确。
- `docs/ARCHITECTURE.md`
  - 仍把知识检索写成“预留”，但当前代码里 `query_knowledge` 已经注册进主流程。
- `docs/guides/WEB_STARTUP_GUIDE.md`
  - 明显偏旧，仍描述“会话仅内存存储、后续再做认证/持久化”，与当前代码的 JSON 持久化 + SQLite 认证不一致。
- `docs/INTERNAL_map_viz_design.md`
  - 文中提到前端“没有引入地图库”，但当前 `web/index.html` 已引入 Leaflet。
- `scripts/query_emission_factors_cli.py`
  - 引用了当前仓库不存在的 `skills.emission_factors.skill`，属于旧脚本。
- `scripts/utils/test_rag_integration.py`
  - 不是当前可直接用的可靠回归测试，路径与导入假设已过时。

# 一句话判断

- 这个项目当前更像：`产品化程度较高的领域智能体系统`，而不是“为了论文专门写的最小原型”。
- 如果要写论文，最值得抓住的主线是：`面向机动车排放分析的自然语言智能体：把文件驱动的数据导入、透明参数标准化、微观/宏观排放计算与地图化结果展示串成一个统一工作流`。
- 当前最需要补的三件事是：
  - `把论文任务定义收窄并统一方法叙事`
  - `补 benchmark / baseline / 消融 / 真实案例实验`
  - `清理旧新并行实现，至少在论文口径上统一主链与可复现流程`
