# EXPERIMENT_DESIGN_AND_EVAL_PLAN

## 1. 范围说明

本轮工作不再做泛化功能总结，而是把当前代码库收敛成一套可执行的论文实验框架，主线聚焦为“文件感知的自然语言排放分析智能体”。本次落地的重点是：

- 在仓库内新增 `evaluation/` 目录、基准样本、评测脚本和人工对照模板。
- 在主系统中补齐可消融的运行时开关，而不是只在文档里口头说明。
- 给出可直接复现的 benchmark / baseline / ablation / 日志 schema。

需要明确的是：当前最稳定、最容易复现的是“离线可执行 lower-bound 实验”，即直接基于工具执行链、文件分析链和执行层标准化链做评测。真正的“自然语言 full router benchmark”仍然依赖外部 LLM 连接，因此已经在脚本中预留 `router` 模式，但不应作为当前阶段唯一主实验。

## 2. 已落地的评测目录结构

当前仓库中已经新增如下目录：

```text
evaluation/
├── eval_normalization.py
├── eval_file_grounding.py
├── eval_end2end.py
├── eval_ablation.py
├── utils.py
├── normalization/
│   └── samples.jsonl
├── file_tasks/
│   ├── samples.jsonl
│   └── data/
│       ├── micro_time_speed.csv
│       ├── micro_cn.csv
│       ├── micro_full.csv
│       ├── micro_speed_only.csv
│       ├── micro_time_sec_speed_kmh.csv
│       ├── macro_direct.csv
│       ├── macro_fuzzy.csv
│       └── macro_cn_fleet.csv
├── end2end/
│   └── samples.jsonl
├── human_compare/
│   └── samples.csv
└── logs/
```

### 2.1 四类任务集与建议格式

| 任务集 | 已落地格式 | 用途 | 说明 |
|---|---|---|---|
| `normalization` | `jsonl` | 参数标准化评测 | 适合逐样本记录原始参数、期望标准化结果、合法性 |
| `file_tasks` | `jsonl` + 配套 `csv/xlsx` 文件 | 文件任务识别、列映射、文件上下文注入评测 | 适合记录文件路径、期望 task_type、期望映射 |
| `end2end` | `jsonl` | 端到端任务完成率评测 | 既保留自然语言 query，也保留当前可执行的 tool arguments |
| `human_compare` | `csv` | 人工流程 vs 系统流程对照 | 当前先作为计时/人工标注模板，尚未自动打分 |

### 2.2 各任务集字段定义

#### `normalization/samples.jsonl`

建议字段：

- `sample_id`
- `tool_name`
- `raw_arguments`
- `expected_standardized`
- `focus_params`
- `expected_success`

当前已提供 10 条样本，覆盖：

- `vehicle_type`
- `pollutants`
- `season`
- `road_type`
- 非法车型输入

#### `file_tasks/samples.jsonl`

建议字段：

- `sample_id`
- `user_query`
- `file_path`
- `expected_task_type`
- `expected_tool_name`
- `expected_mapping`
- `expected_required_present`

当前已提供 10 条样本，覆盖：

- 5 个微观轨迹文件
- 3 个本地新增宏观 CSV
- 2 个现有宏观 Excel (`test_no_geometry.xlsx`, `test_6links.xlsx`)

#### `end2end/samples.jsonl`

建议字段：

- `sample_id`
- `user_query`
- `file_path`
- `expected_tool_name`
- `tool_arguments`
- `expected_success`
- `expected_outputs`

这里故意同时保留：

- `user_query`：用于后续 `router` 模式
- `tool_arguments`：用于当前可稳定执行的 `tool` 模式

#### `human_compare/samples.csv`

建议字段：

- `sample_id`
- `task_type`
- `user_query`
- `file_path`
- `manual_baseline`
- `expected_tool_name`
- `notes`

这一层现在是模板，不是自动评测脚本。

## 3. 已定位并已接入的消融开关点

本次不是只列位置，而是已经补成了可运行的 runtime flag。

| 消融点 | 模块路径 | 类/函数 | 当前实现方式 | 建议用途 |
|---|---|---|---|---|
| 文件分析器开/关 | `config.py` | `Config.enable_file_analyzer` | 通过运行时配置控制 | 比较有/无文件预分析时的任务识别能力 |
| 文件分析实际入口 | `core/router.py` | `UnifiedRouter.chat()` | 若关闭，则不调用 `_analyze_file()`，只保留最小文件元信息 | `no_file_awareness` baseline |
| 文件上下文注入开/关 | `config.py` | `Config.enable_file_context_injection` | 控制是否将 `file_context` 注入到用户消息前缀 | 测试 prompt grounding 贡献 |
| 文件上下文注入位置 | `core/assembler.py` | `ContextAssembler.assemble()` | 只有开关为真才调用 `_format_file_context()` | 文件理解消融 |
| 执行层参数标准化开/关 | `config.py` | `Config.enable_executor_standardization` | 控制 `_standardize_arguments()` 是否直接 passthrough | 透明标准化 ablation 主开关 |
| 执行层标准化逻辑 | `core/executor.py` | `ToolExecutor._standardize_arguments()` | 关闭后返回原始参数 | 比较 alias 输入下的成功率 |
| direct / AI / fuzzy 列映射切换 | `config.py` | `Config.macro_column_mapping_modes` | 例如 `("direct","fuzzy")` | 宏观列映射 ablation |
| 宏观列映射调度点 | `skills/macro_emission/excel_handler.py` | `ExcelHandler._resolve_column_mapping()` | 根据 mode 决定是否启用 `direct_candidates` / `_ai_mapping()` / `fuzzy_candidates` | 规则版 vs 混合版映射 |
| trace 日志落点 | `core/router.py`, `core/executor.py` | `UnifiedRouter.chat(trace=...)`, `ToolExecutor.execute()` | 已补 `_trace` 与 `trace` 字段 | 统一日志与错误归因 |

### 3.1 代码级说明

- 文件分析器开关在 [config.py](/home/kirito/Agent1/emission_agent/config.py) 中新增 `enable_file_analyzer`。
- 文件分析是否真正执行，由 [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py) 的 `UnifiedRouter.chat()` 决定。
- 文件上下文注入由 [core/assembler.py](/home/kirito/Agent1/emission_agent/core/assembler.py) 的 `ContextAssembler.assemble()` 决定。
- 执行层标准化开关在 [core/executor.py](/home/kirito/Agent1/emission_agent/core/executor.py) 的 `_standardize_arguments()` 中生效。
- 宏观列映射模式由 [skills/macro_emission/excel_handler.py](/home/kirito/Agent1/emission_agent/skills/macro_emission/excel_handler.py) 的 `_resolve_column_mapping()` 调度。

## 4. Benchmark 草案

### 4.1 参数标准化 benchmark

目标：评估 alias 输入下，执行层是否能把参数转成合法、统一、可执行的标准表达。

当前 schema 已落地为：

```json
{
  "sample_id": "norm_001",
  "tool_name": "query_emission_factors",
  "raw_arguments": {
    "vehicle_type": "网约车",
    "pollutants": ["氮氧化物", "二氧化碳"],
    "model_year": 2020,
    "season": "冬天",
    "road_type": "高速公路"
  },
  "expected_standardized": {
    "vehicle_type": "Passenger Car",
    "pollutants": ["NOx", "CO2"],
    "model_year": 2020,
    "season": "冬季",
    "road_type": "快速路"
  },
  "focus_params": ["vehicle_type", "pollutants", "season", "road_type"],
  "expected_success": true
}
```

当前 10 个样本主要检验：

- 车型 alias 归一化
- 污染物 alias 归一化
- `season` / `road_type` 是否真的被统一
- 非法车型是否被拒绝

这里有意把 `season` 和 `road_type` 也写入 benchmark，是因为当前代码并未真正统一这两项；如果论文要把“透明参数标准化”写成贡献，实验上就必须把这部分 gap 显性化。

### 4.2 文件驱动任务 benchmark

目标：评估从文件到任务识别、列映射、上下文注入的完整 grounding 链。

当前 schema：

```json
{
  "sample_id": "file_007",
  "user_query": "识别这个字段名称不完全标准的路网文件",
  "file_path": "evaluation/file_tasks/data/macro_fuzzy.csv",
  "expected_task_type": "macro_emission",
  "expected_tool_name": "calculate_macro_emission",
  "expected_mapping": {
    "link_length_km": "road_length_km",
    "traffic_flow_vph": "traffic_volume_per_hour",
    "avg_speed_kph": "avgVelocity",
    "link_id": "segment_name"
  },
  "expected_required_present": true
}
```

当前 10 个样本覆盖：

- 纯轨迹文件
- 中文轨迹文件
- 带加速度/坡度轨迹文件
- 只有速度列的最简轨迹文件
- 标准宏观列名 CSV
- 模糊宏观列名 CSV
- 中文宏观列名 + 车型构成 CSV
- 现有本地 Excel 路网样例

### 4.3 端到端任务 benchmark

目标：评估最终任务是否被正确执行并返回预期 artefact。

当前 schema：

```json
{
  "sample_id": "e2e_010",
  "user_query": "计算 test_6links 文件的CO2和NOx排放并返回地图",
  "file_path": "test_data/test_6links.xlsx",
  "expected_tool_name": "calculate_macro_emission",
  "tool_arguments": {
    "pollutants": ["CO2", "NOx"],
    "model_year": 2020,
    "season": "夏季"
  },
  "expected_success": true,
  "expected_outputs": {
    "has_map_data": true,
    "has_download_file": true
  }
}
```

当前 10 个样本分成三类：

- 排放因子查询 3 条
- 微观文件任务 3 条
- 宏观文件任务 4 条

其中 `tool` 模式已经可离线执行；`router` 模式用于后续接入真实 LLM 之后跑 full pipeline。

## 5. Baseline 设计

### 5.1 Full System

定义：

- 文件分析开启
- 文件上下文注入开启
- 执行层标准化开启
- 宏观列映射模式 `direct + ai + fuzzy`

对应实现：

- `enable_file_analyzer=True`
- `enable_file_context_injection=True`
- `enable_executor_standardization=True`
- `macro_column_mapping_modes=("direct","ai","fuzzy")`

### 5.2 无文件感知

定义：

- 不做 `analyze_file`
- 不向 prompt 注入 `file_context`

对应实现：

- `enable_file_analyzer=False`
- `enable_file_context_injection=False`

注意：在当前 `tool` 模式 end2end 中，这个 baseline 不会显著降低成功率，因为脚本直接提供了目标工具和文件路径。它更适合在 `file_grounding` 或未来 `router` 模式下评测。

### 5.3 无执行层标准化

定义：

- alias 输入直接透传给工具

对应实现：

- `enable_executor_standardization=False`

这是当前最值得优先写进论文的 ablation，因为它已经能明显拉开差距。

### 5.4 规则直连版宏观文件处理

定义：

- 不启用文件分析器
- 不启用文件上下文注入
- 不启用执行层标准化
- 宏观列映射只保留 `direct + fuzzy`
- 只跑 `calculate_macro_emission`

对应实现：

- `enable_file_analyzer=False`
- `enable_file_context_injection=False`
- `enable_executor_standardization=False`
- `macro_column_mapping_modes=("direct","fuzzy")`
- `only_task="calculate_macro_emission"`

这个 baseline 更像“工程下界”而不是论文主系统，但很适合作为对照。

## 6. 指标体系

### 6.1 统一日志 schema

当前脚本统一输出 `jsonl` 日志，建议最小 schema 为：

```json
{
  "sample_id": "e2e_008",
  "input": {
    "user_query": "分析这个非标准列名路段文件的CO2排放",
    "file_path": "evaluation/file_tasks/data/macro_fuzzy.csv",
    "tool_arguments": {
      "pollutants": ["CO2"],
      "model_year": 2020,
      "season": "夏季",
      "fleet_mix": {"小汽车": 80, "公交": 10, "货车": 10}
    }
  },
  "file_analysis": {},
  "routing_result": {},
  "standardization_result": {},
  "tool_call_logs": [],
  "final_status": {
    "success": true,
    "completion": true,
    "output_check": {}
  },
  "timing_ms": 352.12,
  "failure_type": "success",
  "recoverability": "success"
}
```

其中关键字段含义如下：

- `input`: 原始 query、文件、工具参数
- `file_analysis`: 文件分析器输出
- `routing_result`: 期望工具 vs 实际工具
- `standardization_result`: 原始参数 vs 标准化参数
- `tool_call_logs`: 工具调用与 trace
- `final_status`: 成功/完成率/输出 artefact 检查
- `timing_ms`: 单样本耗时
- `failure_type` / `recoverability`: 自动失败分类

### 6.2 指标定义

#### 参数标准化准确率

定义：

- 样本级：`actual_standardized == expected_standardized`
- 字段级：`focus_params` 中逐字段 exact match

当前脚本输出：

- `sample_accuracy`
- `field_accuracy`

#### 参数合法率

定义：

- 标准化后参数是否落在合法取值域

当前实现检查：

- `vehicle_type`
- `pollutants`
- `season`
- `road_type`
- `model_year`

#### 路由准确率

定义：

- `actual_task_type == expected_task_type`
- 或 `actual_tool_name == expected_tool_name`

当前在 `file_grounding` 和 `end2end` 中分别统计。

#### 列映射准确率

定义：

- `expected_mapping` 中每个字段是否映射到正确列

当前输出：

- `column_mapping_accuracy`

#### 端到端完成率

定义：

- 工具成功
- 且预期 artefact 存在（图/表/地图/下载）

当前输出：

- `end2end_completion_rate`

#### 平均交互轮次

定义：

- `tool` 模式固定为 1
- `router` 模式可由 trace 中的 `tool_execution` 批次数统计

#### 工具调用成功率

定义：

- `tool_result.success == True` 的比例

当前输出：

- `tool_call_success_rate`

## 7. 失败案例 taxonomy

### 7.1 分类体系

当前建议的失败类型为：

- `参数错误`
- `错误路由`
- `列映射失败`
- `缺失必要字段`
- `工具执行异常`
- `输出不完整`
- `可恢复失败`
- `不可恢复失败`

### 7.2 自动归类逻辑

已落在 [evaluation/utils.py](/home/kirito/Agent1/emission_agent/evaluation/utils.py)：

- `classify_failure(record)`
- `classify_recoverability(failure_type)`

当前规则大致依据：

- `error_type`
- `message/error` 文本
- 是否出现 `mapping` / `缺少字段` / `failed`

需要诚实说明：这还是规则归类，不是严格的 failure parser，但已经足够支撑论文里的 error analysis 表。

## 8. 脚本规划与当前实现状态

### 8.1 `eval_normalization.py`

位置：

- [evaluation/eval_normalization.py](/home/kirito/Agent1/emission_agent/evaluation/eval_normalization.py)

当前能力：

- 读取 `normalization/samples.jsonl`
- 调用 `ToolExecutor._standardize_arguments()`
- 统计样本准确率、字段准确率、参数合法率
- 支持 `--disable-executor-standardization`

### 8.2 `eval_file_grounding.py`

位置：

- [evaluation/eval_file_grounding.py](/home/kirito/Agent1/emission_agent/evaluation/eval_file_grounding.py)

当前能力：

- 调用 `tools/file_analyzer.py`
- 调用微观/宏观文件处理器提取实际列映射
- 验证 `task_type`
- 验证文件上下文是否真正注入
- 支持：
  - `--disable-file-analyzer`
  - `--disable-file-context-injection`
  - `--macro-modes`

### 8.3 `eval_end2end.py`

位置：

- [evaluation/eval_end2end.py](/home/kirito/Agent1/emission_agent/evaluation/eval_end2end.py)

当前能力：

- `tool` 模式：离线可执行，直接走 `ToolExecutor.execute()`
- `router` 模式：预留真实路由评测，但依赖外部 LLM
- 统一记录：
  - `file_analysis`
  - `routing_result`
  - `standardization_result`
  - `tool_call_logs`
  - `final_status`
  - `timing_ms`

### 8.4 `eval_ablation.py`

位置：

- [evaluation/eval_ablation.py](/home/kirito/Agent1/emission_agent/evaluation/eval_ablation.py)

当前能力：

- 运行 4 组 baseline：
  - `full_system`
  - `no_file_awareness`
  - `no_executor_standardization`
  - `macro_rule_only`
- 汇总 `normalization` / `file_grounding` / `end2end` 三组指标

## 9. 已完成的 smoke run 结果

以下结果来自本地实际执行，不是推测。

### 9.1 `normalization`

本地命令：

```bash
python evaluation/eval_normalization.py --output-dir evaluation/logs/_smoke_normalization
```

结果：

- `sample_accuracy = 0.1`
- `field_accuracy = 0.6786`
- `parameter_legal_rate = 0.2`

解释：

- 当前执行层真实稳定覆盖的是 `vehicle_type` 和 `pollutants`
- `season` / `road_type` benchmark 中故意按“论文期望态”打分，因此准确率被显著拉低

### 9.2 `file_grounding`

本地命令：

```bash
python evaluation/eval_file_grounding.py --output-dir evaluation/logs/_smoke_file_grounding
```

结果：

- `routing_accuracy = 0.9`
- `column_mapping_accuracy = 1.0`
- `required_field_accuracy = 0.8`

当前暴露出的真实问题：

- `macro_fuzzy.csv`：任务识别正确，但 `required_present` 未满足
- `macro_cn_fleet.csv`：被文件分析器识别成 `unknown`

这恰好说明：文件任务识别链和列映射链可以分开做实验，不能把它们混成一个指标。

### 9.3 `end2end`（tool mode）

本地命令：

```bash
python evaluation/eval_end2end.py --mode tool --output-dir evaluation/logs/_smoke_end2end
```

结果：

- `tool_call_success_rate = 1.0`
- `end2end_completion_rate = 1.0`

必须强调：

- 这是“工具执行下界”，不是 full NL router 上界
- 它证明的是当前数值计算、文件读写、导出、地图输出链本身是可执行的
- 它不能直接等价为“自然语言路由能力已经 100%”

### 9.4 `ablation`

本地命令：

```bash
python evaluation/eval_ablation.py --output-dir evaluation/logs/_smoke_ablation
```

关键现象：

- `no_executor_standardization` 下：
  - `normalization.field_accuracy = 0.0714`
  - `end2end_completion_rate = 0.4`
- 这说明“执行层透明参数标准化”是当前最容易形成量化增益的模块

而 `no_file_awareness` 在 `tool` 模式的 `end2end` 中几乎不掉点，原因不是系统特别强，而是该模式本来就绕开了 router。论文中必须把这一点写清楚。

## 10. 当前最容易先跑通的一组实验

如果只考虑 1 到 2 周内先拿到第一版实验表，最推荐的顺序是：

1. `normalization` 主实验 + `no_executor_standardization` ablation
2. `file_grounding` 主实验，拆成：
   - task recognition
   - column mapping
   - required field detection
3. `end2end(tool mode)` 作为系统可执行性证明

这三组实验的优点是：

- 不依赖重新训练
- 只弱依赖在线 LLM
- 能直接用现有代码和新增 benchmark 样本跑通
- 可以支撑“文件感知 + 执行层标准化 + 工具落地”的论文主线

## 11. 当前不建议过度承诺的部分

以下内容适合写成“后续扩展 / 系统能力”，但不建议现在硬写成主实验：

- `router` 模式 full benchmark
  - 原因：依赖外部 LLM 连通性和稳定性
- `human_compare` 自动评测
  - 原因：当前只有任务模板，没有自动计时与人工标注脚本
- AI 列映射的单独增益
  - 原因：当前仓库里 AI mapping 会在无网络时回退，真实对比还不稳定

## 12. 结论

当前代码库已经具备一套“能跑、能记日志、能做消融”的论文实验框架，但最稳妥的主战场仍然是：

- 文件任务识别与列 grounding
- 执行层透明参数标准化
- 以工具执行为核心的端到端任务完成率

如果论文主线定为“文件感知的自然语言排放分析智能体”，那么最先应该拿下的不是全量 router 指标，而是：

- `normalization` 的可量化收益
- `file_grounding` 的任务识别/列映射误差分析
- `tool mode end2end` 的稳定可执行性

这三组结果已经能构成一版务实的实验章节骨架。真正的 full NL router 实验，应在网络条件和 LLM 版本固定后作为第二阶段补齐。
