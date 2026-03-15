# 面向论文写作的第二轮深度代码审计

本报告不重复第一轮“功能盘点”，而是聚焦论文定位、方法主线和实验设计。判断依据来自主调用链、工具注册、配置、测试脚本、数据样例与局部运行验证，重点参考：

- `core/router.py` `UnifiedRouter.chat/_process_response/_extract_*`
- `core/executor.py` `ToolExecutor.execute/_standardize_arguments`
- `core/assembler.py` `ContextAssembler.assemble/_format_file_context`
- `tools/file_analyzer.py` `FileAnalyzerTool._identify_task_type/_analyze_structure`
- `tools/micro_emission.py` `MicroEmissionTool.execute`
- `tools/macro_emission.py` `MacroEmissionTool.execute/_standardize_fleet_mix/_apply_global_fleet_mix`
- `skills/macro_emission/excel_handler.py` `ExcelHandler._resolve_column_mapping/_parse_fleet_mix`
- `skills/micro_emission/excel_handler.py` `ExcelHandler.read_trajectory_from_excel`
- `calculators/micro_emission.py` / `calculators/macro_emission.py`
- `api/routes.py` `/chat` `/chat/stream` `/file/preview`
- `tools/definitions.py` / `tools/registry.py`
- `config/unified_mappings.yaml` / `config/prompts/core.yaml`

---

## 1. 透明参数标准化机制到底覆盖了哪些参数

### 1.1 结论先行

当前“统一透明标准化”在主流程里真正稳定覆盖的只有两类：

1. `vehicle_type`
2. `pollutant / pollutants`

其它很多参数虽然在配置文件、旧模块或工具内部存在“映射/默认/修补”逻辑，但并没有被 `core/executor.py` 的统一执行层透明处理。

尤其要注意：

- `model_year` 没有标准化，只是直接透传。
- `season` 没有统一标准化，英文别名在主流程里并不可靠。
- `road_type` 没有统一标准化，只在排放因子计算器内部做有限中文映射。
- `fuel_type` 不在主计算主链里。
- `fleet_mix` 只在宏观工具内部局部标准化。
- 文件列名映射并不统一：`file_analyzer`、宏观 Excel 处理器、微观 Excel 处理器是三套实现。

### 1.2 参数覆盖表

| 参数名 | 实现位置 | 是否接入主流程 | 稳定性判断 | 适合做论文实验吗 |
| --- | --- | --- | --- | --- |
| `vehicle_type` | `core/executor.py` `ToolExecutor._standardize_arguments()` 调 `services/standardizer.py` `standardize_vehicle()`；宏观 `fleet_mix` 还会在 `tools/macro_emission.py` `_standardize_fleet_mix()` 二次处理 | 是 | 高 | 适合 |
| `pollutant` / `pollutants` | `core/executor.py` `ToolExecutor._standardize_arguments()` 调 `services/standardizer.py` `standardize_pollutant()` | 是 | 中高 | 适合 |
| `model_year` | 主流程无标准化；微观在 `calculators/micro_emission.py` `_year_to_age_group()` 中把年份转年龄组；宏观在 `calculators/macro_emission.py` `_query_emission_rate()` 直接按 `modelYearID == model_year` 查 | 是，但非统一标准化 | 中低 | 适合做“限制分析”，不适合吹成主方法 |
| `season` | 主流程无标准化；各工具只做默认值；微/宏计算器内部 `SEASON_CODES.get(season, 7)` | 是，但非统一标准化 | 低到中 | 可做负例实验，不适合当主贡献 |
| `road_type` | 主流程无标准化；仅 `calculators/emission_factors.py` `ROAD_TYPE_MAPPING` 做有限中文映射 | 仅排放因子链接入 | 中低 | 可做局部实验，不适合主贡献 |
| `fuel_type` | 主计算工具定义中没有；仅 RAG 索引元数据里出现，如 `skills/knowledge/index/chunks.jsonl` 的 `business_filters.fuel_type` | 否 | 低 | 不适合 |
| `fleet_mix` | `tools/macro_emission.py` `_standardize_fleet_mix/_apply_global_fleet_mix/_fill_missing_link_fleet_mix()`；文件导入侧在 `skills/macro_emission/excel_handler.py` `_parse_fleet_mix()` | 仅宏观链接入 | 中高 | 适合，尤其适合做宏观链辅实验 |
| 文件列名映射 | `tools/file_analyzer.py` 调 `services/standardizer.py` `map_columns()`；宏观实际执行用 `skills/macro_emission/excel_handler.py` `_resolve_column_mapping()`；微观实际执行用 `skills/micro_emission/excel_handler.py` `_find_column()` | 是，但实现分裂 | 宏观中高，微观中低 | 适合，但建议聚焦宏观 |

### 1.3 关键证据与具体判断

#### `vehicle_type`

- 执行层统一入口在 `core/executor.py:145-155`。
- 标准化服务在 `services/standardizer.py:74-128`，流程是 exact match -> fuzzy -> local model fallback。
- 本地模型 fallback 逻辑存在，但当前仓库没有可直接使用的权重目录；`config.py:61-72` 只是配置入口。
- 宏观链还有一层额外标准化：`tools/macro_emission.py:136-159` 会把 `fleet_mix` 里的车型名再次规整。

判断：

- 这是当前最像“透明标准化机制”的部分。
- 可以做 alias 覆盖实验、执行成功率实验。

#### `pollutant(s)`

- 执行层统一入口在 `core/executor.py:157-180`。
- 服务实现于 `services/standardizer.py:130-178`。
- 单污染物失败会抛标准化错误；多污染物列表里无法识别的项会保留原值继续下传，见 `core/executor.py:168-179`。

判断：

- 功能是真实接入主流程的。
- 但列表模式容错策略不完全一致，适合做“严格成功率”与“宽松成功率”两个指标。

#### `model_year`

- `core/executor.py` 没有任何年份标准化逻辑。
- 微观计算在 `calculators/micro_emission.py:68-89` 把真实年份转换为年龄组，再查表。
- 宏观计算在 `calculators/macro_emission.py:248-262` 直接拿 `model_year` 和矩阵中的 `modelYearID` 精确比较。

判断：

- 两条计算链对 `model_year` 的语义并不统一。
- 论文里不能写成“统一参数标准化覆盖到年份”，最多写成“年份参数在后端计算层被任务特定地解释”。

#### `season`

- `config/unified_mappings.yaml:263-287` 虽然定义了季节别名，但 `services/standardizer.py` 并没有对应的 `standardize_season()`。
- 实测 `ToolExecutor._standardize_arguments()` 对 `season='winter'` 直接透传，未转换为 `冬季`。
- 微/宏计算器都用 `SEASON_CODES.get(season, 7)`，见 `calculators/micro_emission.py:168-178` 与 `calculators/macro_emission.py:120-135`。这意味着英文 `"winter"` 在主流程里大概率会回落到默认夏季，而不是冬季。

判断：

- 这是当前一个很明确的“配置存在但主流程未真正调用”的例子。
- 可以作为论文里的负面分析或局限性，而不是贡献点。

#### `road_type`

- `tools/definitions.py:32-35` 把 `road_type` 暴露给 LLM。
- 但执行层不做标准化。
- 只有 `calculators/emission_factors.py:58-65` 内部维护了有限中文映射。

判断：

- 排放因子链可用，但不能说成统一标准化。
- 适合作为排放因子单链的局部输入约束，不适合作为论文主方法。

#### `fuel_type`

- 主工具定义没有 `fuel_type` 参数。
- 当前主要出现在知识库元数据中，例如 `skills/knowledge/index/chunks.jsonl` 的 `business_filters.fuel_type`。

判断：

- 不在当前数值计算主链。
- 不建议写进论文主线。

#### `fleet_mix`

- 顶层 `fleet_mix` 由 `tools/macro_emission.py:161-189` 分发到各 link。
- link 内部或顶层车型名通过 `tools/macro_emission.py:136-159` 标准化。
- 对缺失的车队组成，`tools/macro_emission.py:191-230` 用默认车队组成显式补齐，并把补齐信息写入结果 `fleet_mix_fill`。
- 文件导入时，`skills/macro_emission/excel_handler.py:517-557` 会解析并归一化车队比例。

判断：

- 这是宏观链里一个完成度较高、可实验化的“领域约束修补”模块。
- 可以作为辅贡献或方法细节。

#### 文件列名映射

- `tools/file_analyzer.py:97-111` 用 `services.standardizer.map_columns()` 先做任务诊断。
- 但宏观实际执行不用这套，而是走 `skills/macro_emission/excel_handler.py:226-261` 的三段式：direct -> AI JSON -> fuzzy。
- 微观实际执行更简单，只用 `skills/micro_emission/excel_handler.py:25-29, 69-77, 181-199` 的固定候选列名查找。

判断：

- 当前“文件列名映射”不是统一机制，而是“分析器一套、宏观执行一套、微观执行一套”。
- 论文里如果写，建议聚焦“宏观文件导入链”，不要泛化成整个系统都实现了统一列名标准化。

### 1.4 一个很重要的审计发现

`tools/file_analyzer.py` 对 `micro_has_required` 的判断偏乐观。

- 微观所需列在 `config/unified_mappings.yaml:291-333` 中只有 `speed_kph` 是 required。
- 因此像 `test_data/test_6links.xlsx` 这种宏观路段文件，只要有 `speed` 列，也会被分析器判成 `micro_has_required=True`。
- 实测 `test_data/test_6links.xlsx` 与 `test_data/test_shanghai_allroads.xlsx` 都出现了：
  - `task_type=macro_emission`
  - `macro_has_required=True`
  - `micro_has_required=True`

这说明：

- 文件分析器更适合做“候选提示”，不适合直接当高置信任务分类器指标。
- 如果做论文实验，必须把“任务识别”和“列覆盖判断”拆开评测。

---

## 2. 文件驱动工作流的真实决策链路

### 2.1 主链路

真实主链路如下：

`前端上传文件`
-> `api/routes.py /chat 或 /chat/stream`
-> 保存到临时目录 `TEMP_DIR`
-> `Session.chat(message, file_path)`
-> `UnifiedRouter.chat(user_message, file_path)`
-> 自动调用 `analyze_file`
-> 分析结果写入 memory/cache
-> `ContextAssembler` 将文件摘要前置拼进用户消息
-> `LLM chat_with_tools`
-> LLM 决定：澄清 / 调用微观工具 / 调用宏观工具 / 调用知识工具
-> `ToolExecutor` 执行，并自动补 `file_path`
-> 工具内实际读取文件、列映射、计算
-> `Router` 抽取文本 / 表格 / 图表 / 地图
-> API 返回前端

### 2.2 从上传开始的具体调用点

#### 前端

- `web/app.js` `handleFileSelect()` 会先调 `/api/file/preview` 做展示性预览。
- 这个 preview 不是主分析链，只是前端确认步骤。

#### API 主入口

- `api/routes.py:303-420` `/chat`
- `api/routes.py:438-625` `/chat/stream`

上传文件后会：

- 保存到 `/tmp/emission_agent/...`
- 把文件路径和提示文本拼到 message 后面
- 同时把真实 `input_file_path` 单独传给 `Session.chat(...)`

#### Router 层

- `core/router.py:90-128` 如果有 `file_path`，先调用 `_analyze_file()`
- `_analyze_file()` 在 `core/router.py:293-303`，本质是执行工具 `analyze_file`
- 文件分析结果会按 `file_path + mtime` 做缓存

#### 文件摘要如何拼进 prompt

- `core/assembler.py:100-105`
- `ContextAssembler._format_file_context()` 在 `core/assembler.py:211-231`

拼接内容包括：

- 文件名
- 文件路径
- `task_type`
- 行数
- 列名
- 前两行样例

并且是直接前置到 user message 前面，而不是作为独立结构化参数传给 LLM。

### 2.3 文件任务识别是谁做的

是 heuristics，不是 LLM。

主链识别逻辑在 `tools/file_analyzer.py:129-153`：

- 看列名里是否包含 `speed/time/acceleration`
- 或 `length/flow/traffic/link`
- 计算 `micro_score` 与 `macro_score`

这一步完全是规则判断。

### 2.4 LLM 在文件工作流里承担什么角色

LLM 主要承担三件事：

1. 根据拼进来的 `task_type` 和列摘要，决定是否直接调某个工具
2. 在参数不足时主动追问
3. 提供工具参数，如 `vehicle_type`、`pollutants`、`model_year`、`fleet_mix`

关键点：

- `config/prompts/core.yaml:49-64` 明确告诉 LLM：如果 `task_type` 已明确，不要再询问宏观/微观，直接用对应工具。
- `services/llm_client.py:189-252` 使用的是 function calling / tool use，不是独立 planner JSON。

### 2.5 哪些地方是 heuristics，哪些地方依赖 LLM

#### heuristics

- 文件类型识别：`tools/file_analyzer.py:129-153`
- 文件列初步映射：`services/standardizer.py:218-278`
- 宏观文件真实列映射 fallback：`skills/macro_emission/excel_handler.py:226-290`
- 微观文件读入：`skills/micro_emission/excel_handler.py:69-99`
- 宏观缺失 `fleet_mix` 的补齐：`tools/macro_emission.py:191-230`

#### 依赖 LLM

- 工具选择与澄清：`UnifiedRouter` -> `LLMClientService.chat_with_tools()`
- 宏观 Excel 处理器中的 AI 列映射：`skills/macro_emission/excel_handler.py:292-357`
- 知识问答的答案精炼：`skills/knowledge/skill.py:140-192`

### 2.6 preview 与主链并不一致

这是一个论文写作时必须说清楚的点。

- 前端预览 `/api/file/preview` 在 `api/routes.py:662-677`
- 它的逻辑是：
  - 先看是否含 `speed`
  - 再看是否含 `length`

因此含 `speed` 的宏观文件在 preview 层可能先被标成 `trajectory`。

但主链真正用于调用决策的不是这个 preview，而是 `analyze_file` 工具。

判断：

- preview 是 UI 辅助逻辑，不应当写成论文方法的一部分。

### 2.7 能否抽象成统一方法模块

可以抽象，但需要收敛表述：

可抽象成：

`File-aware task grounding module`

包含三步：

1. 规则化文件任务识别
2. 文件摘要注入对话上下文
3. LLM 驱动的工具调用与参数追问

但不能过度抽象成“统一文件智能理解方法”，因为目前代码仍明显混合了：

- 规则判断
- prompt 约束
- 工具内部各自解析

更准确的论文表达应是：

- “文件感知的工具调用编排层”
- 而不是“端到端文件理解模型”

---

## 3. 微观排放与宏观排放，是否真的可以统一成论文中的“双计算链”框架

### 3.1 可以统一的部分

两条链在“外层智能体框架”上已经统一：

| 维度 | 微观链 | 宏观链 | 是否统一 |
| --- | --- | --- | --- |
| NL 入口 | `UnifiedRouter.chat()` | `UnifiedRouter.chat()` | 是 |
| 工具注册 | `calculate_micro_emission` | `calculate_macro_emission` | 是 |
| 执行入口 | `ToolExecutor.execute()` | `ToolExecutor.execute()` | 是 |
| 透明参数标准化 | `vehicle_type/pollutants` | `vehicle_type/pollutants` | 基本是 |
| 文件入口兼容 | `file_path -> input_file` | `file_path -> input_file` | 是 |
| 返回结构 | `ToolResult(data/summary/...)` | `ToolResult(data/summary/...)` | 是 |
| 前端表格抽取 | `core/router.py _extract_table_data()` | 同一处 | 是 |

因此，作为论文可以写成：

“同一自然语言智能体外壳下挂接两类异构排放计算后端”

这个成立。

### 3.2 明显不统一的部分

#### 输入对象不统一

- 微观：单车轨迹点序列 `trajectory_data`，必须要有 `vehicle_type`
- 宏观：路段列表 `links_data`，可以没有单一 `vehicle_type`，而是 `fleet_mix`

#### 文件解析复杂度不统一

- 微观文件解析很轻：`skills/micro_emission/excel_handler.py:25-29, 69-111`
- 宏观文件解析很重：列映射、流量单位换算、车队组成解析、ZIP/Shapefile 支持，见 `skills/macro_emission/excel_handler.py`

#### 年份语义不统一

- 微观把年份映射为年龄组 `calculators/micro_emission.py:68-89`
- 宏观直接拿年份查 `modelYearID` `calculators/macro_emission.py:248-262`

#### 错误恢复不统一

- 宏观链有大量 auto-fix：字段名修补、`fleet_mix` 修补、缺省补齐
- 微观链基本没有类似的任务级 auto-fix

#### 输出能力不统一

- 微观：文本 + 表格 + 可下载结果
- 宏观：文本 + 表格 + 地图 + 可下载结果

### 3.3 代码层共性与差异

#### 共性

- 都依赖 MOVES 派生矩阵
- 都是“输入解析 -> 参数解释 -> 矩阵查询 -> 汇总统计 -> ToolResult”
- 都有 `query_info/results/summary`

#### 差异

- 微观核心是 `VSP -> opMode -> emission rate`
  - `calculators/micro_emission.py:109-141`
- 宏观核心是 `link × fleet_mix × average opMode(300)`
  - `calculators/macro_emission.py:136-246`

### 3.4 论文里应该如何抽象

可以写成“双计算链”，但建议抽象层级放高：

- 不要写成“统一排放计算方法”
- 应写成“统一交互/执行框架下的两类领域计算后端”

更稳妥的抽象是：

1. `trajectory-oriented micro chain`
2. `link-oriented macro chain`
3. 共享外层的 `NL routing + transparent standardization + file-aware invocation + structured result rendering`

### 3.5 论文里需要避开的说法

不建议写：

- “微观与宏观计算模块已完全统一”
- “参数语义在两条链中完全一致”
- “双链共享统一文件理解模块”

更合适的说法：

- “共享一套交互编排层，但保留任务特定计算语义”

---

## 4. 最适合作为“方法贡献”的模块到底是哪一个

### 候选 A：自然语言 + tool-use 的统一排放分析主链

#### 代码支持证据

- `core/router.py` `UnifiedRouter`
- `services/llm_client.py` `chat_with_tools()`
- `tools/definitions.py`
- `tools/registry.py`
- `api/routes.py /chat /chat/stream`

#### 是否足够新

- 通用意义上不算新。
- 但在“机动车排放分析”这个高约束专业域里，结合数值工具和文件工作流，仍有应用型新意。

#### 是否容易补实验

- 是。
- 可以做工具选择正确率、端到端任务完成率、澄清轮次等实验。

#### 适合角色

- 适合做论文主贡献，但要加上领域限定词。

建议表述：

- “面向机动车排放分析的领域智能体主链”

### 候选 B：执行层透明参数标准化

#### 代码支持证据

- `core/executor.py:66-80, 126-185`
- `services/standardizer.py`
- `tools/macro_emission.py:136-159`

#### 是否足够新

- 方法创新性中等偏低。
- 作为领域系统中的关键支撑机制是成立的。

#### 是否容易补实验

- 很容易。
- 最容易做 alias -> 标准值 -> 工具成功率 的消融。

#### 适合角色

- 适合做辅贡献。
- 不太适合单独撑起整篇论文主线。

### 候选 C：文件驱动任务识别与自动导入

#### 代码支持证据

- `tools/file_analyzer.py`
- `core/assembler.py:100-105`
- `config/prompts/core.yaml:49-64`
- `skills/macro_emission/excel_handler.py`
- `skills/micro_emission/excel_handler.py`

#### 是否足够新

- 通用领域不算很新。
- 在专业分析系统里，尤其文件上传后自动识别并导入到对应计算链，这个点比较像可写的“系统方法”。

#### 是否容易补实验

- 容易。
- 任务识别、列映射、端到端文件处理成功率都可做。

#### 适合角色

- 适合与候选 A 组合成主线。
- 如果只选一个“方法味”更浓的点，它比纯 tool-use 更有论文可操作性。

### 候选 D：双路径（数值计算 + RAG）系统

#### 代码支持证据

- 数值链：前述微/宏/排放因子
- RAG：`tools/knowledge.py` + `skills/knowledge/skill.py`

#### 是否足够新

- 新意一般。
- 更像系统完备性，而不是核心方法。

#### 是否容易补实验

- 中低。
- 当前索引构建链不在仓库内，且依赖 embedding/rerank 外部配置。

#### 适合角色

- 适合系统亮点。
- 不适合作为主贡献。

### 候选 E：GIS 联动可视化

#### 代码支持证据

- `tools/macro_emission.py:232-426`
- `api/routes.py:697-760`
- `web/app.js` `renderEmissionMap/initLeafletMap`
- `preprocess_gis.py`

#### 是否足够新

- 方法新意低。
- 更像展示层价值。

#### 是否容易补实验

- 可做案例展示，不容易做强量化。

#### 适合角色

- 适合系统亮点或案例。
- 不适合主贡献。

### 4.6 最推荐的“方法贡献”模块

最值得作为论文主线的不是单独某个点，而是一个组合：

`文件感知的自然语言工具调用主链`

具体由两部分组成：

1. 自然语言到多工具排放分析的统一编排链
2. 文件驱动的任务识别与自动导入机制

而“执行层透明参数标准化”最适合作为这个主线下的辅贡献。

---

## 5. 目前最容易设计量化实验的模块

下面只给 1-2 个月内现实可做、且尽量复用现有代码与数据的方案。

### 实验 1：参数标准化对工具成功率的提升

#### 目标

验证执行层透明标准化是否实质提升工具调用成功率。

#### 可用代码基础

- `core/executor.py`
- `services/standardizer.py`
- `tools/emission_factors.py`
- `tools/micro_emission.py`
- `tools/macro_emission.py`

#### 样本构造

- 人工整理 100-200 条参数表达：
  - 车型别名：小汽车 / SUV / 网约车 / 公交 / 大货车 / taxi / bus
  - 污染物别名：氮氧 / 颗粒物 / pm25 / carbon dioxide
  - `fleet_mix` 中的车型别名

#### baseline

1. 无标准化：直接把原始参数传给工具
2. 当前系统：执行层标准化 + 宏观 `fleet_mix` 标准化

#### 指标

- 标准化准确率
- 工具执行成功率
- 最终返回非错误结果比例

#### 现实性判断

- 最容易做。
- 不需要训练。
- 很适合写成消融实验。

### 实验 2：文件任务识别成功率

#### 目标

验证上传文件后，系统能否把文件导向正确计算链。

#### 可用代码基础

- `tools/file_analyzer.py`
- `core/assembler.py`
- `config/prompts/core.yaml`
- `test_data/` 下已有宏观样例

#### 样本构造

- 宏观样例可直接用：
  - `test_data/test_6links.xlsx`
  - `test_data/test_no_geometry.xlsx`
  - `test_data/test_shanghai_full.xlsx`
  - `test_data/test_shanghai_allroads.xlsx`
  - 对应 zip
- 微观样例当前仓库缺少标准测试文件，建议补 20-50 个小 CSV：
  - 列名变体：`speed_kph/time`、`速度/时间`、`speed/time_sec`
  - 可人工生成

#### baseline

1. preview 端简单启发式 `api/routes.py:662-677`
2. 主链分析器 `tools/file_analyzer.py`

#### 指标

- `task_type` 分类准确率
- 分类置信度分布
- “识别正确但需要继续澄清参数”的比例

#### 审计提醒

- 必须单独报告 `micro_has_required` 误判，不要把它当分类准确率。

### 实验 3：宏观文件列映射成功率

#### 目标

验证宏观 Excel 处理器对非标准列名的鲁棒性。

#### 可用代码基础

- `skills/macro_emission/excel_handler.py`

#### 样本构造

从现有宏观文件批量改名生成变体：

- 标准列：`length/flow/speed`
- 同义列：`distance/traffic/avg_speed`
- 中文列：`长度/流量/平均速度`
- 日流量列：`daily_traffic/aadt`
- 车型占比列：`公交车%/货车%/taxi`

#### baseline

1. direct match only
2. direct + fuzzy
3. 当前完整实现：direct + AI + fuzzy

如果外部 LLM 不稳定，可把第 3 组改为“当前实现在无 LLM 时的 fallback”。

#### 指标

- required field exact mapping accuracy
- full mapping exact match accuracy
- 文件解析成功率
- 端到端宏观计算成功率

#### 现实性判断

- 非常适合。
- 样本可自动生成。

### 实验 4：端到端任务完成率

#### 目标

测系统从自然语言输入到最终可用结果的完成能力。

#### 样本构造

按任务分 60-100 条：

- 排放因子查询
- 微观轨迹计算
- 宏观路段计算
- 文件上传宏观计算
- 知识问答

#### baseline

1. 简单关键词路由器
2. 当前 LLM tool-use 路由

#### 指标

- 任务完成率
- 首次工具选择正确率
- 平均澄清轮数
- 平均完成时间

#### 现实性判断

- 可做，但要人工标注 expected tool / success standard。

### 实验 5：人工流程 vs 系统流程效率比较

#### 目标

证明系统在实际分析任务上节省用户操作成本。

#### 场景

- 给定一个非标准列名的路段 Excel
- 给定一个带 geometry 的 Excel / zip shapefile

#### 对比

1. 人工方式：用户先重命名列、手工补车型组成、再调用计算
2. 系统方式：直接上传 + 自然语言说明

#### 指标

- 用户需要输入的参数数
- 完成所需轮次
- 总耗时
- 成功得到表格/地图/下载结果的比例

#### 现实性判断

- 很像系统论文实验。
- 不依赖训练。

### 5.6 如果只能优先做三组实验

建议优先级：

1. 参数标准化成功率与消融
2. 宏观文件列映射 / 文件任务识别
3. 端到端任务完成率 + 效率比较

---

## 6. 哪些“看起来很强”的点不应该写进论文主线

### 6.1 RAG / 知识问答

原因：

- 主链能调用，但复现实验链不完整。
- `skills/knowledge/retriever.py` 只真正使用 dense FAISS；`sparse_embeddings.pkl` 目前未进入在线检索流程。
- 检索索引虽然在仓库里，但构建过程不在当前仓库。
- 依赖外部 embedding / rerank / refiner 配置。
- 相关测试脚本中存在过时部分。

建议：

- 降级为附属能力或案例。

### 6.2 GIS 联动可视化

原因：

- 真实价值主要在展示层，不是智能决策核心。
- 地图结果主要来自宏观计算输出的 geometry + Leaflet 渲染。
- `preprocess_gis.py` 与 `static_gis/` 更像预处理资源，不是论文方法。

建议：

- 放系统展示、案例分析或附录。

### 6.3 本地标准化模型

原因：

- `config.py` 和 `shared/standardizer/local_client.py` 有接入口。
- 但当前仓库没有可直接复现的模型权重。
- 默认主流程也没有启用它。

建议：

- 不要当主线。
- 最多在 future work 或 engineering extension 里提一句。

### 6.4 多轮记忆

原因：

- 确实有 `core/memory.py`，但设计比较朴素：
  - recent working memory
  - fact memory
  - 简单 correction pattern
- 更像工程记忆，而不是强方法创新。
- 还存在 `MemoryManager` 与 `SessionManager` 双持久化并存的问题。

建议：

- 降级为系统支持能力。

### 6.5 旧 skill 框架 / 旧标准化模块

原因：

- `skills/*/skill.py`、`shared/standardizer/*`、`llm/client.py` 仍存在，但当前主链是 `core/ + tools/ + services/`。
- 新旧架构并存，不适合写成论文主方法。

建议：

- 论文正文只讲当前主链。
- 旧模块最多在附录说明“遗留组件未纳入评测”。

### 6.6 上海全路网样例

原因：

- `test_data/test_shanghai_allroads.xlsx` 的确规模大，但本质更像压力测试 / 展示集。
- 样例中 `flow/speed` 是测试数据，不是严肃 benchmark。

建议：

- 可做案例展示。
- 不要把“完整路网跑通”当成方法创新点。

---

## 7. 论文抽象建议

### 推荐论文类型

最推荐：

- 应用型系统论文

更准确地说：

- 面向机动车排放分析的领域智能体系统论文

不推荐直接包装成纯方法论文，原因是当前真正有说服力的是“系统化收敛”和“工作流编排”，不是单一新算法。

### 推荐题目方向（3 个备选）

1. 面向机动车排放分析的文件感知领域智能体系统
2. 融合工具调用与参数标准化的机动车排放自然语言分析系统
3. 面向微观与宏观排放任务的多工具交通排放分析智能体

### 最推荐的主线（1 条）

`文件感知的自然语言排放分析智能体`

展开后是：

- 用自然语言接入专业排放任务
- 通过文件识别与工具调用把任务导入正确计算链
- 在执行层做透明参数标准化与领域约束修补
- 输出结构化数值结果与可视化结果

### 可写成贡献点的 3 点

#### 主贡献

面向机动车排放分析的文件感知多工具智能体主链

证据：

- `core/router.py`
- `core/assembler.py`
- `tools/definitions.py`
- `api/routes.py`

性质判断：

- 偏系统方法。
- 不是新算法，但可以抽象成领域工作流框架。

#### 辅贡献

执行层透明参数标准化与宏观链约束修补机制

证据：

- `core/executor.py`
- `services/standardizer.py`
- `tools/macro_emission.py`
- `skills/macro_emission/excel_handler.py`

性质判断：

- 偏工程方法。
- 有清晰消融空间。

#### 系统亮点

统一智能体外壳下接入排放因子、微观排放、宏观排放与地图联动输出

证据：

- `tools/registry.py`
- `tools/emission_factors.py`
- `tools/micro_emission.py`
- `tools/macro_emission.py`
- `web/app.js`

性质判断：

- 适合作为系统完备性，不建议写成核心方法创新。

### 必须补齐的 3 类实验

1. 参数标准化实验
   - alias 标准化准确率
   - 去掉执行层标准化后的工具成功率对比

2. 文件驱动实验
   - 文件任务识别准确率
   - 宏观列映射准确率
   - 文件直传到可计算结果的成功率

3. 端到端系统实验
   - 工具选择正确率
   - 任务完成率
   - 人工流程 vs 系统流程效率

### 不建议硬写的内容

- RAG 作为主贡献
- GIS 作为方法创新
- 本地标准化模型作为已完成核心能力
- 强调“统一 planner / router 方法”
  - 因为当前没有独立 planner，实际是 function calling + tool use
- 强调“微观宏观算法统一”
  - 当前统一的是外层框架，不是内层算法

### 当前代码到论文之间最大的鸿沟

最大的鸿沟不是“功能不够多”，而是下面三点：

1. 缺少围绕主线组织过的 benchmark 与 baseline
2. 方法抽象尚散落在工程实现里，没有被收敛成清晰模块定义
3. 若想把文件驱动与标准化写成贡献，目前还缺系统性的消融和误差分析

换句话说：

- 代码已经足够支撑“系统论文原型”
- 但距离“可投稿论文”还差一套严肃的任务定义、评价集和对照实验

---

## 最终判断

如果只从当前本地代码现实出发，最适合的论文主线不是：

- RAG
- GIS
- 本地模型
- 纯算法创新

而是：

`面向机动车排放分析的文件感知、多工具自然语言智能体系统`

其中最值得抓住的三根主线是：

1. 文件驱动任务落地
2. 透明参数标准化
3. 微观/宏观双计算链在统一智能体外壳下的编排

只要后续 1-2 个月把实验做实，这条线是有论文包装可能性的；但它更像“有方法抽象的系统论文”，而不是“单点强创新方法论文”。
