# Benchmark Pipeline 诊断报告

本文基于 2026-04-11 对 `evaluation/benchmarks/end2end_tasks.jsonl` 的修复前基线审计。修复脚本 `evaluation/pipeline_v2/curate_existing_benchmark.py` 已把明确判定争议同步写回 benchmark，但本报告的数据现状章节保留原始基线，用于解释为什么需要 Pipeline V2。

## 1. 数据集现状

### 1.1 规模与类别分布

修复前总量为 64 条：

- `simple`: 9
- `parameter_ambiguous`: 11
- `multi_step`: 12
- `incomplete`: 18
- `constraint_violation`: 14

主要问题不是规模小，而是类别内部重复模式强：`incomplete` 有 6 条完全空参数/空工具链签名，`constraint_violation` 里摩托车高速模式占比过高。

本次 curation 后仍保留 64 条，不删除记录；类别变为 `simple=11`、`parameter_ambiguous=14`、`multi_step=12`、`incomplete=14`、`constraint_violation=13`。

### 1.2 参数空间覆盖率（对照 unified_mappings.yaml）

- 车型：已覆盖 6/13，缺失: `Passenger Truck`, `Light Commercial Truck`, `Intercity Bus`, `Refuse Truck`, `Single Unit Short-haul Truck`, `Motor Home`, `Combination Short-haul Truck`
- 污染物：已覆盖 5/6，缺失: `THC`
- 季节：已覆盖 4/4，但 `春季` 和 `秋季` 各只有 1 条，属于弱覆盖
- 道路类型：已覆盖 5/5，但 `高速公路` 和 `次干道` 各只有 1 条，属于弱覆盖
- 气象预设：已覆盖 4/6，缺失: `urban_winter_day`, `windy_neutral`
- 工具链组合：已覆盖 12 种；缺失的关键组合: `calculate_micro_emission -> render_spatial_map`, `calculate_micro_emission -> calculate_dispersion -> render_spatial_map`
- Cross-constraint 规则：9 条可测试规则中原始覆盖 6 条，缺失 `vehicle_pollutant_relevance:Motorcycle:PM10`, `pollutant_task_applicability:THC:calculate_dispersion`, `season_meteorology_consistency:夏季:urban_winter_day`

额外质量问题：修复前 `expected_params.vehicle_type` 出现非标准值 `家用车`，它不是 `unified_mappings.yaml` 支持的 MOVES 标准名，也不是现有规则可稳定标准化的别名。

### 1.3 语言覆盖

- 纯中文: 35
- 纯英文: 0
- 中英混杂: 29

审稿风险点是没有纯英文自然请求；如果论文声称系统支持英文或双语交互，至少需要 5 条纯英文 smoke 样本。

### 1.4 测试文件覆盖（有无 geometry 文件？）

Benchmark 使用的文件分布修复前为：

- `(none)`: 32
- `evaluation/file_tasks/data/macro_direct.csv`: 14
- `evaluation/file_tasks/data/micro_time_speed.csv`: 11
- `evaluation/file_tasks/data/macro_fuzzy.csv`: 3
- `evaluation/file_tasks/data/macro_cn_fleet.csv`: 2
- `evaluation/file_tasks/data/micro_cn.csv`: 1
- `test_data/test_6links.xlsx`: 1

`evaluation/file_tasks/data/*.csv` 都没有 geometry/WKT/经纬度列。`test_data/test_6links.xlsx` 有 `geometry` 列，但只被 1 条任务使用；`test_data/test_20links.xlsx`、`test_shanghai_allroads.xlsx`、`test_shanghai_full.xlsx` 也有 geometry 列，但 benchmark 未覆盖。

### 1.5 重复模式分析（同一参数组合出现多少次？）

主要重复：

- 空 `incomplete` 签名出现 6 次：空工具链、空参数、无文件。
- `Transit Bus + NOx + 快速路 + query_emission_factors` 出现 2 次。
- `macro_direct.csv + CO2 + macro -> dispersion` 出现 2 次。
- `macro_direct.csv + NOx + macro -> dispersion -> hotspot` 出现 2 次。
- 摩托车高速约束原始检测到 7 条，修复后显式标注 8 条，其中只保留 3 条为代表，其余用 `benchmark_metadata.redundant_pattern=motorcycle_highway` 标记。

## 2. Pipeline 现状

### 2.1 生成流程

现有 `evaluation/generate_e2e_tasks.py` 约 944 行，核心流程是按类别循环生成：

1. 读取系统能力、工具契约、已有 benchmark。
2. 按 `simple / parameter_ambiguous / multi_step / incomplete / constraint_violation` 类别构造 prompt。
3. 调用 `LLMGenerator`（默认 `qwen3-max`，temperature 0.8）。
4. 做结构归一化和内置验证。
5. 把候选写入 `evaluation/generated/e2e_tasks_<category>.jsonl`，并更新 summary。

主要缺陷：它“按类别盲生成”，没有先做参数空间差集，所以会继续生成已过度覆盖的乘用车、公交、CO2、NOx 和摩托车高速样本，而不会主动补齐 7 个缺失车型、THC、纯英文样本或缺失气象预设。

### 2.2 验证规则完整性

`config/cross_constraints.yaml` 当前有 4 个约束组且都有规则，不再是空槽位：

- `vehicle_road_compatibility`: Motorcycle + 高速公路 blocked
- `vehicle_pollutant_relevance`: Motorcycle + PM2.5/PM10 warning
- `pollutant_task_applicability`: CO2/THC + calculate_dispersion warning
- `season_meteorology_consistency`: 冬夏季与相反季节气象预设 warning

问题在 benchmark 标注层：修复前多条 `constraint_violation` 任务没有显式 `expected_params`，也没有记录 `violated_constraints`。因此任务能“看起来像约束测试”，但审计器和人工审阅无法稳定判断它具体覆盖哪条 YAML 规则。

### 2.3 LLM 生成的质量（从 generated/ 目录的 valid/needs_review/invalid 比例看）

`evaluation/generated/e2e_tasks_summary.json` 显示：

- usable candidates: 60
- `valid`: 44
- `needs_review`: 16
- discarded `invalid`: 35

类别层面，`parameter_ambiguous` 曾累计 15 条 invalid，`multi_step` 11 条 invalid，说明 prompt 对“可执行但口语化”和“工具链依赖”这两类任务约束不足。现有验证器能发现一部分问题，但它不是覆盖率驱动，也没有独立 LLM 自检层。

## 3. 已识别的覆盖缺口（按优先级排序）

### 🔴 P0 - 论文可信度直接受影响

- 7/13 车型完全缺失，论文若讨论 MOVES source type 泛化能力会被直接质疑。
- `THC` 完全缺失，污染物空间未闭合。
- 纯英文任务为 0，不能支撑英文或双语 claims。
- `expected_params.vehicle_type=家用车` 是非标准期望值；这会污染覆盖率统计，也会让标准化评测语义不清。
- 约束任务缺少显式规则标注；摩托车高速样本过多但 PM10、THC dispersion、夏季+urban_winter_day 未覆盖。

### 🟡 P1 - 审稿人可能质疑

- Geometry 文件覆盖不足：只有 1 条使用带 `geometry` 的 `test_6links.xlsx`，空间链路的成功/中止语义缺少足够证据。
- `calculate_micro_emission -> render_spatial_map` 和 `calculate_micro_emission -> calculate_dispersion -> render_spatial_map` 缺失。
- `urban_winter_day` 和 `windy_neutral` 未覆盖。
- `春季/秋季`、`高速公路/次干道` 虽已出现，但样本数过低。

### 🟢 P2 - 锦上添花

- 增加不同文件结构的同能力样本，例如中文列名、fuzzy 列名、geometry xlsx、shapefile/zip。
- 增加 non-happy-path 的人工审阅样本，明确哪些是系统默认可执行、哪些必须追问。
- 记录 task provenance：由人工、旧 pipeline、V2 generation、curation 哪个路径产生。

## 4. 判定标准争议清单

- `e2e_incomplete_009` / `e2e_incomplete_016`: 原判 `incomplete`，但离线直接调用 `MacroEmissionTool(file_path=macro_direct.csv, pollutants=[CO2])` 成功，并使用默认 `model_year=2020`、`season=夏季`、默认 `fleet_mix`；已重分类为 `simple`。
- `e2e_incomplete_008` / `e2e_incomplete_015`: “家用车”不是当前支持别名，不能写入标准化后的 `expected_params.vehicle_type`；已改为需要协商的 `parameter_ambiguous`，并把原始歧义参数放入 `benchmark_metadata`。
- `e2e_constraint_013`: “高架”按现有标准化器落到 `快速路`，不是 `高速公路`，不触发摩托车高速约束；已从 `constraint_violation` 改为 `parameter_ambiguous`。
- `e2e_constraint_009`: 用户明确说“摩托车在高速上录的轨迹”，原期望是追问；更合理的 benchmark 语义是 `vehicle_road_compatibility` hard block，已改为 `constraint_blocked=true`。
- `e2e_constraint_005`: 用户消息包含 `urban_summer_day`，但修复前 `expected_params` 漏了 `meteorology`；已补齐。
- `e2e_constraint_001` 到 `004` 等早期约束任务缺少显式参数和规则标注；已补 `expected_params` 和 `benchmark_metadata.violated_constraints`。
- `CO2 + calculate_dispersion` 会触发 `pollutant_task_applicability` warning；对应 constraint 样本已补 secondary coverage metadata。
- `unified_mappings.yaml` 的默认污染物是 `[CO2, NOx, PM2.5]`，但 `MacroEmissionTool` 实际默认是 `[CO2, NOx]`。Pipeline V2 的 regression check 应专门抓“benchmark 期望与工具实际默认不一致”的任务。
