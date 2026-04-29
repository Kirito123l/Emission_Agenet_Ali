# 替换排放数据库的完整流程

## 设计原则

Agent 架构干净的标准是: "agent 不知道数据库内容"。Phase 5.2 Round 2/2.5 实施后, agent 层 6 处硬编码全部移除, agent 通过 `emission_domain_schema` 接口跟数据库对话, 不再直接引用 1995/2025/"夏季"/"快速路" 等数据库特定值。

## 替换层级

替换排放数据库分 2 层, 边界清晰:

### 层 1: agent 层 (本流程聚焦, 零代码改动)

通过修改 `config/emission_domain_schema.yaml` 描述新数据库的领域维度:

- 6 维度的 `standard_names` (vehicle_type / pollutant / road_type / season 等 对新数据库的标准列表)
- 维度的 `default` 和 `default_policy` (model_year default / road_type default / season default 等)
- 维度的 `range` (model_year range, 1995-2025 → 2018-2024)

agent 层代码零改动。验证:

```bash
pytest tests/test_emission_schema.py tests/test_runtime_defaults_consistency.py
```

### 层 2: 工具实现层

修改 `calculators/*.py` 中的数据库特定映射:

- `VEHICLE_TO_SOURCE_TYPE` — 车辆类型名 → 数据库 source type ID
- `POLLUTANT_TO_ID` — 污染物名 → 数据库 pollutant ID
- CSV 文件路径 + 列名常量
- VSP bin 映射 (如适用于新数据库)

这些映射是工具实现细节, 跟 agent 架构可拓展性论点无关。不同排放数据库 (MOVES Atlanta、本地实测、COPERT) 在这里各自有 adapter 实现, 实现了 "agent 层通用 + 工具层适配" 的清晰分层。

**Phase 5.2 论文定位**:
- 层 1 的零代码改动 → §4.5 系统可拓展性章节的核心硬证据
- 层 2 的 adapter 实现 → 工程实施细节, 跟架构"干净性"主张无关

## 例子: 从 MOVES Atlanta 换到本地实测数据库

### 假设新数据库特征

- vehicle_type 使用字符串标识 (如 `"passenger_car"`), 不是 MOVES SourceType ID (21/31/32...)
- model_year 范围 2018-2024
- 默认 model_year 是 2022 (近期实测数据集)
- pollutant 列表更广 (CO2 / NOx / PM2.5 / PM10 / VOC)
- 本地实测的 season 默认策略不同 (冬季为主)

### 改动 (层 1: agent 层 — 零代码改动)

只改 `config/emission_domain_schema.yaml`:

```yaml
dimensions:
  vehicle_type:
    standard_names: [...]  # 跟新数据库的 vehicle type 列表一致

  model_year:
    range: {min: 2018, max: 2024, step: 1}  # 改 range
    default: 2022                              # 改默认值

  pollutant:
    standard_names: [CO2, NOx, PM2.5, PM10, VOC]  # 加 VOC
```

效果:
- `ClarificationContract` 的 model_year 校验区间 → 自动从 YAML `range` 读, 跟着改
- `runtime_defaults` 的 model_year 默认值 → 自动从 YAML `default` 读, 跟着改
- `standardization_engine` 的 valid values → 自动从 YAML `standard_names` 读, 跟着改
- `LLMReplyParser` 生成的提示中的年份示例 → 自动从 schema 读, 跟着改

**agent 层 git diff 为零修改** — 这是 Phase 5.2 的核心可拓展性证据。

### 改动 (层 2: 工具实现层)

在 `calculators/emission_calculator.py` 和其他 calculator 中:

```python
# 修改前 (MOVES Atlanta)
VEHICLE_TO_SOURCE_TYPE = {
    "Passenger Car": 21,
    "Motorcycle": 11,
    ...
}
POLLUTANT_TO_ID = {"CO2": 1, "NOx": 2, ...}

# 修改后 (本地实测)
VEHICLE_TYPE_MAP = {
    "passenger_car": "local_car_profile",
    ...
}
```

这些是工具实现细节。详见 `docs/phase5_2_recon_agent_db_decoupling.md` 第 3 节 (13 个 MOVES CSV 文件分析)。

## 论文论点对应

| 论文章节 | 引用素材 | 内容 |
|---------|---------|------|
| §4.5 系统可拓展性 | `emission_domain_schema.yaml` + 层 1 流程 | 替换数据库时 agent 层零代码改动 |
| §5.2 数据库切换案例 | 上面例子 + git diff 证据 | 从 MOVES Atlanta 换到本地实测, agent 层 diff 为空 |
| §4.2 架构设计 | Phase 5.2 Round 2/3 改造总结 | 41 处 Type A 耦合点消除, agent 通过 schema 接口对话 |

## 验证清单

替换数据库后:

```bash
# agent 层一致性测试
pytest tests/test_emission_schema.py tests/test_runtime_defaults_consistency.py

# 全量回归
pytest tests/

# 手动抽查: 确认 LLMReplyParser 生成的提示中不出现旧数据库特定值
# (例如不再硬编码 "1995-2025" 或 "2020")
```
