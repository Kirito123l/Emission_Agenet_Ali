# Phase 5.2 Round 1 — Emission DB Schema 设计

Date: 2026-04-29
Branch: `phase3-governance-reset`
Status: 设计草案, 无代码改动

Related: `docs/phase5_2_recon_agent_db_decoupling.md` (commit `7c68938`)

---

## §1 六维度 Codebase Audit

每个维度逐点列 file:line + 分类:

- **类型 A**: 数据库内容硬编码 (具体值 / ID 映射 / range / 默认数值) — Round 2 解耦目标
- **类型 B**: schema 概念 (此字段存在 / 类型 / 约束) — agent 层保留 OK
- **类型 C**: 工具语义 (关键词→工具映射 / 对话文本 / LLM prompt 结构) — 与 DB schema 解耦正交, 不动

---

### 1.1 vehicle_type

| # | 文件 | 行 | 内容摘要 | 类型 |
|---|---|---|---|---|
| 1 | `config/unified_mappings.yaml` | 9-211 | 13 MOVES vehicle types, 每个含 `id` (MOVES SourceType ID 11-62), `standard_name`, `display_name_zh`, `aliases`, VSP params (A/B/C/M/m) | **A** (ID 是 DB 内容) + **B** (standard_name + aliases 是 schema 概念) |
| 2 | `shared/standardizer/constants.py` | 1-15 | `VEHICLE_TYPE_MAPPING`: 13 种车的中文名 + 别名 (不含 MOVES ID) | **B** (标准化别名, 不含 DB ID) |
| 3 | `shared/standardizer/constants.py` | 52-66 | `VSP_PARAMETERS`: 13 车辆类型的 A/B/C/M/m 物理参数 (含 MOVES ID 作为 key) | **A** (VSP 参数含 MOVES ID 作为索引) |
| 4 | `calculators/emission_factors.py` | 19-34 | `VEHICLE_TO_SOURCE_TYPE`: 标准名→MOVES SourceType ID (11-62) | **A** |
| 5 | `calculators/macro_emission.py` | 25-38 | `VEHICLE_TO_SOURCE_TYPE`: 完全相同的 dict (三 copy) | **A** |
| 6 | `calculators/micro_emission.py` | 20-34 | `VEHICLE_TO_SOURCE_TYPE`: 完全相同的 dict (三 copy) | **A** |
| 7 | `calculators/vsp.py` | 24 | 从 `ConfigLoader.get_vehicle_types()` 读 VSP 参数 | **A** (读 YAML 中的 ID+参数) |
| 8 | `services/standardizer.py` | 91-108 | `vehicle_lookup` dict — 从 YAML aliases→standard_name 构建 | **B** (纯别名 lookup) |
| 9 | `services/standardization_engine.py` | 37-38 | `PARAM_TYPE_REGISTRY["vehicle_type"]` | **B** |
| 10 | `core/contracts/clarification_contract.py` | 1234 | `"vehicle_type": "车辆类型"` (display name) | **B** |
| 11 | `core/governed_router.py` | 824-826 | `args["vehicle_type"] = read("vehicle_type")` | **B** |
| 12 | `tools/registry.py` / `tools/definitions.py` | — | JSON schema 含 `vehicle_type: {type: string}` | **B** |

**分析**: vehicle_type 的 Type A 耦合集中在两点: (1) MOVES SourceType ID 映射, 三份完全相同地出现在 3 个计算器, (2) VSP 物理参数含 MOVES ID 作为索引。Type B (标准化别名/display name) 已在 YAML 中集中管理, 解耦良好。

**重复统计**: `VEHICLE_TO_SOURCE_TYPE` (13 项 × 3 份) = 完全相同的 dict 写了 3 遍。

---

### 1.2 model_year

| # | 文件 | 行 | 内容摘要 | 类型 |
|---|---|---|---|---|
| 1 | `core/contracts/runtime_defaults.py` | 8-10 | `"model_year": 2020` — 无来源注释的 magic number | **A** |
| 2 | `core/contracts/clarification_contract.py` | 29-30 | `YEAR_RANGE_MIN = 1995`, `YEAR_RANGE_MAX = 2025` — 类常量 | **A** |
| 3 | `core/contracts/clarification_contract.py` | 847 | LLM system prompt: `"runtime_defaults 字段列出了当前工具可用的运行时默认值（如 model_year=2020）"` — K4 知识注入 | **A** |
| 4 | `core/contracts/clarification_contract.py` | 1253-1254 | `range(YEAR_RANGE_MIN, YEAR_RANGE_MAX + 1, 5)` → 生成 `["1995","2000","2005","2010","2015","2020","2025"]` 作合法值列表给 LLM | **A** |
| 5 | `core/router.py` | 1782, 4222 | 对话文本: `"请告诉我例如 2020、2021 这样的年份"` | **A** (具体年份示例) |
| 6 | `config/unified_mappings.yaml` | 542 | `defaults.model_year: 2020` | **A** |
| 7 | `config/tool_contracts.yaml` | 34, 59-64 | `optional_slots: [model_year]`, schema 描述 `"Range: 1995-2025"` | **B** (schema 概念 + range 声明) |
| 8 | `core/governed_router.py` | 383, 407-408, 828-835 | model_year 的 runtime default 应用逻辑 (从 defaults 读值) | **B** (逻辑读接口, 不 hardcode 值) |
| 9 | `core/memory.py` | 327, 672-679 | `fact_memory.recent_year` — 记住最近使用的 model_year | **B** (用户状态, 非 DB 默认) |
| 10 | `core/router_render_utils.py` | 354, 396, 410-419, 591-609 | model_year 的 display name + render text | **B** (display logic) |
| 11 | `tools/macro_emission.py` | 636, 651 | `model_year = kwargs.get("model_year", 2020)`, `defaults_used["model_year"] = 2020` | **A** |
| 12 | `tools/micro_emission.py` | 75 | `model_year = kwargs.get("model_year", 2020)` | **A** |
| 13 | `core/contracts/split_contract_utils.py` | 37 | Slot-filling slot_prompt: `"不要编造 model_year"` | **B** (LLM guard, 不 hardcode 值) |
| 14 | `calculators/emission_factors.py` | 15 | `COL_MODEL_YEAR = 'ModelYear'` — CSV 列名 | **A** (DB schema 列名) |
| 15 | `calculators/macro_emission.py` | 21 | `COL_MODEL_YEAR = 'modelYearID'` — 不同的列名约定 | **A** |
| 16 | `calculators/micro_emission.py` | 16 | `COL_MODEL_YEAR = 'ModelYear'` | **A** |

**分析**: model_year 是 Type A 耦合**最严重**的维度。同一个值 `2020` 出现在 6 处 (runtime_defaults, clarification_contract LLM prompt, router 对话文本, unified_mappings defaults, macro_emission tool, micro_emission tool), 且 3 个计算器各自定义不同的 CSV 列名 (ModelYear / modelYearID)。

**默认值本质**: `model_year=2020` 是**数据库内容决定的默认** (MOVES Atlanta 数据覆盖到 2025, 取近年代表示例), 不是"无论什么数据库都是 2020"的领域真理。换 2026 年的 COPERT 数据库, 默认值应该是 2026。但当前这个默认值以 hardcoded literal 形式散落在 agent 层, 装成"这就是默认"。

**range 本质**: `1995-2025` 同样由 MOVES Atlanta 数据的实际覆盖范围决定。不是一个"排放分析的永远合理的 model_year 范围"。

---

### 1.3 pollutant

| # | 文件 | 行 | 内容摘要 | 类型 |
|---|---|---|---|---|
| 1 | `config/unified_mappings.yaml` | 213-261 | 6 pollutants, 每个含 `id` (MOVES pollutantID: 1,2,3,90,110,111), `standard_name`, `display_name_zh`, `aliases` | **A** (ID 是 DB 内容) + **B** |
| 2 | `config/unified_mappings.yaml` | 543-546 | `defaults.pollutants: [CO2, NOx, PM2.5]` | **A** (具体默认列表) |
| 3 | `shared/standardizer/constants.py` | 26-33 | `POLLUTANT_MAPPING`: 6 pollutants + 中文别名 (不含 MOVES ID) | **B** (标准化别名) |
| 4 | `calculators/emission_factors.py` | 36-43 | `POLLUTANT_TO_ID`: 标准名→MOVES pollutantID | **A** |
| 5 | `calculators/macro_emission.py` | — | `POLLUTANT_TO_ID` (同上, 独立副本) | **A** |
| 6 | `calculators/micro_emission.py` | 37-45 | `POLLUTANT_TO_ID` (同上, 第三份副本) | **A** |
| 7 | `calculators/emission_factors.py` | 14 | `COL_POLLUTANT = 'pollutantID'` | **A** |
| 8 | `calculators/macro_emission.py` | 19 | `COL_POLLUTANT = 'pollutantID'` | **A** |
| 9 | `calculators/micro_emission.py` | 14 | `COL_POLLUTANT = 'pollutantID'` | **A** |
| 10 | `config/dispersion_pollutants.yaml` | — | 扩散支持的污染物 + 半衰期等参数 | **A** (扩散特有的污染物属性) |
| 11 | `services/standardizer.py` | 110-119 | `pollutant_lookup` — 从 YAML aliases→standard_name | **B** |
| 12 | `services/standardization_engine.py` | 38-39 | `PARAM_TYPE_REGISTRY["pollutant"]` / `["pollutants"]` | **B** |
| 13 | `core/contracts/clarification_contract.py` | 1236-1237 | `"pollutants": "污染物"`, `"pollutant": "污染物"` | **B** |
| 14 | `evaluation/eval_normalization.py` | — | 无 pollutant 硬编码 (pass through) | — |

**分析**: 结构类似 vehicle_type — 3 份 `POLLUTANT_TO_ID` 在计算器层独立副本。MOVES pollutantID (1,2,3,90,110,111) 是 DB 内容硬编码。扩散特有的 pollutant 属性 (半衰期) 在独立的 `dispersion_pollutants.yaml` — 这可能需要独立处理, 不一定是 emission_db_schema 的一部分。

---

### 1.4 road_type

| # | 文件 | 行 | 内容摘要 | 类型 |
|---|---|---|---|---|
| 1 | `config/unified_mappings.yaml` | 289-323 | 5 road types: 快速路, 高速公路, 主干道, 次干道, 支路, 每个含 `aliases` | **B** (标准化别名, 无 MOVES ID) |
| 2 | `config/unified_mappings.yaml` | 541 | `defaults.road_type: "快速路"` | **A** (具体默认值) |
| 3 | `config/tool_contracts.yaml` | 39, 76 | `defaults: {road_type: "快速路"}`, schema 描述 | **B + A** (YAML 声明了默认值) |
| 4 | `services/standardizer.py` | 130-143 | `road_type_lookup` — 从 YAML 构建, `road_type_default = "快速路"` | **B** (后接), **A** (硬编码 fallback) |
| 5 | `services/standardization_engine.py` | 83 | `"default_value": "快速路"` | **A** |
| 6 | `calculators/emission_factors.py` | 60-64 | `ROAD_TYPE_ROADMODE`: 快速路→4, 高速公路→4, 城市道路→4, 地面道路→5, 居民区道路→5 | **A** (MOVES roadTypeID 映射) |
| 7 | `calculators/emission_factors.py` | 108-109 | Function 默认值: `season="夏季"`, `road_type="快速路"` | **A** |
| 8 | `tools/emission_factors.py` | 73-74, 100-101, 108-109 | kwarg fallback: `road_type="快速路"` (重复 3 次) | **A** |
| 9 | `evaluation/eval_normalization.py` | 29 | `ROAD_TYPE_ALLOWED = {"快速路", "地面道路"}` | **A** (与实际 5 类不一致) |

**分析**: road_type 的 Type A 耦合在默认值 `"快速路"` 和 MOVES roadTypeID 映射 (roadmode 4/5)。标准化体系已较好 (5 road types, aliases 在 YAML 集中管理)。但 `eval_normalization.py` 的 ROAD_TYPE_ALLOWED 只含 2 类, 与实际 5 类不一致 — cross-cutting bug。

**注意**: road_type 标准化默认值 "快速路" 是**领域合理默认** (排放分析中通常关注快速路/高速路), 不是"某数据库决定的"。这与 model_year=2020 的性质不同 — model_year 是 DB 内容决定, road_type 默认是领域实践决定。

---

### 1.5 season

| # | 文件 | 行 | 内容摘要 | 类型 |
|---|---|---|---|---|
| 1 | `config/unified_mappings.yaml` | 263-287 | 4 seasons: 春季, 夏季, 秋季, 冬季, 每个含 `aliases` | **B** (标准化别名) |
| 2 | `config/unified_mappings.yaml` | 540 | `defaults.season: "夏季"` | **A** (具体默认值) |
| 3 | `config/tool_contracts.yaml` | 38, 70, 104, 191 | 3 个工具的 defaults 含 `season: "夏季"` | **B + A** |
| 4 | `services/standardizer.py` | 111-128 | `season_lookup`, `season_default = "夏季"` | **B + A** |
| 5 | `services/standardization_engine.py` | 76 | `"default_value": "夏季"` | **A** |
| 6 | `shared/standardizer/constants.py` | 44-49 | `SEASON_MAPPING`: 别名→标准名 (春→春季, etc.) | **B** |
| 7 | `calculators/emission_factors.py` | 52-55 | `SEASON_MONTH_MAP = {"春季":4, "夏季":7, "秋季":4, "冬季":1}` | **A** (MOVES 月份映射) |
| 8 | `calculators/macro_emission.py` | 56-61 | `SEASON_MONTH_MAP` (独立副本) | **A** |
| 9 | `calculators/micro_emission.py` | 53-58 | `SEASON_MONTH_MAP` (独立副本) | **A** |
| 10 | `tools/emission_factors.py` | 73, 100, 108 | kwarg fallback: `season="夏季"` (重复 3 次) | **A** |
| 11 | `tools/macro_emission.py` | 637, 652 | kwarg: `season="夏季"` | **A** |
| 12 | `tools/micro_emission.py` | 75 | kwarg: `season="夏季"` | **A** |
| 13 | `evaluation/eval_normalization.py` | 28 | `SEASON_ALLOWED = {"春季", "夏季", "秋季", "冬季"}` | **B** |

**分析**: season 的 Type A 耦合分两类: (1) 默认值 `"夏季"` — 与 road_type 同理, 是领域实践决定 (季节代表性), 不是 DB 内容决定; (2) `SEASON_MONTH_MAP` — 纯 DB 内容 (MOVES CSV 按月份分文件, 春季=4月, 夏季=7月, etc.)。

**season 默认 "夏季" 的领域合理性**: 排放分析通常以夏季作为默认 (高温高排放), 这是一个**跨数据库都成立的领域默认**, 不像 model_year=2020 是 MOVES Atlanta 特定值。

---

### 1.6 meteorology (含 stability_class)

| # | 文件 | 行 | 内容摘要 | 类型 |
|---|---|---|---|---|
| 1 | `config/unified_mappings.yaml` | 325-373 | `meteorology.presets`: 6 个预设 (urban_summer_day, urban_summer_night, urban_winter_day, urban_winter_night, windy_neutral, calm_stable), 每个含 aliases | **B** (预设名称 + 别名) |
| 2 | `config/unified_mappings.yaml` | 375-410 | `stability_classes`: 6 个 (VS, S, N1, N2, U1, U2), 每个含 aliases | **B** |
| 3 | `config/meteorology_presets.yaml` | — | 6 个预设的物理参数: `wind_speed_mps`, `wind_direction_deg`, `stability_class`, `mixing_height_m`, `temperature_k`, `description` | **A** (具体气象参数值 — 这些是领域知识, 非 DB 内容) |
| 4 | `services/standardizer.py` | 145-166 | `meteorology_lookup`, `meteorology_presets`, `stability_lookup`, `stability_classes` — 从 YAML 构建 | **B** |
| 5 | `services/standardization_engine.py` | 43-44, 52-53 | `PARAM_TYPE_REGISTRY["meteorology"]`, `["stability_class"]`, fuzzy thresholds | **B** |
| 6 | `services/standardization_engine.py` | 88-100 | meteorology passthrough patterns (`.sfc$`, `^custom$`), stability_class default=None (无可用的统一默认) | **B** |
| 7 | `config/tool_contracts.yaml` | 442 | dispersion tool 的 `default: urban_summer_day` (meteorology 参数) | **A** |
| 8 | `calculators/dispersion.py` | 145-164 | 加载 meteorology_presets.yaml + dispersion_pollutants.yaml, 解析为 python 对象 | **A** (读 YAML 中的具体物理值) |

**分析**: meteorology 维度较干净 — 预设名称和 stability class 标准值已在 YAML 中集中管理。Type A 的耦合在 `meteorology_presets.yaml` 的具体物理参数 (风速/温度/混合高度) 和 tool_contracts 的默认预设名。但气象参数**不是 DB 内容** — 是领域知识 (物理模型输入)。解耦时需区分"DB schema"和"领域知识配置"。

---

### 1.7 六维度 Type A 耦合汇总

| 维度 | Type A 点数 | 重复项 | 最大问题 |
|---|---|---|---|
| vehicle_type | 5 | VEHICLE_TO_SOURCE_TYPE × 3 | MOVES SourceType ID 散落, 三副本 |
| model_year | 11 | `2020` 值 × 6, YEAR_RANGE × 2 | 最高耦合 — 6 处独立出现 2020 |
| pollutant | 7 | POLLUTANT_TO_ID × 3, 列名 × 3 | MOVES pollutantID 散落 |
| road_type | 6 | `"快速路"` 默认 × 5, ROAD_TYPE_ROADMODE × 1 | 默认值重复; MOVES roadTypeID 映射 |
| season | 9 | `"夏季"` 默认 × 6, SEASON_MONTH_MAP × 3 | 默认值 + MOVES 月份映射重复 |
| meteorology | 3 | 少 | 气象参数是领域知识不是 DB 内容 — 从 DB schema 解耦角度不是问题 |

---

## §2 Schema 设计草案

### 2.1 设计目标

> Agent 层通过 schema 接口读维度定义, 不硬编码数据库内容。任何遵守 schema 的排放数据库 (MOVES / COPERT / 本地实测) 可接入, agent 层零改动。

### 2.2 顶层结构

```
emission_db_schema.yaml
├── schema_version: str           # schema 自身的版本号
├── description: str              # "Emission Agent standard dimension schema"
├── dimensions:                   # 6 个维度的字段定义
│   ├── vehicle_type:
│   │   ├── field_type: enum      # "categorical"
│   │   ├── value_type: str       # "string"
│   │   ├── standard_names: [...] # agent 层可见的标准名列表
│   │   ├── display_name_zh: str  # "车辆类型"
│   │   ├── required: bool
│   │   ├── default_policy: str   # "mandatory" | "optional_no_default" | "schema_default" | "db_default"
│   │   └── cross_db_key: str     # "vehicle_type" — agent 层用此 key 引用
│   ├── model_year:
│   │   ├── field_type: enum      # "integer_range"
│   │   ├── value_type: str       # "integer"
│   │   ├── display_name_zh: str
│   │   ├── required: bool
│   │   ├── default_policy: str   # "db_default" (具体值由 DB manifest 提供)
│   │   ├── range_policy: str     # "db_declared" (range 由 DB manifest 提供)
│   │   └── cross_db_key: str     # "model_year"
│   ├── pollutant:
│   │   └── ...
│   └── ...
├── defaults:                     # schema-level defaults (跨数据库都成立)
│   ├── season: "夏季"
│   ├── road_type: "快速路"
│   └── pollutants: [CO2, NOx, PM2.5]
└── db_manifest:                  # 此 schema 对应的数据库 manifest 文件名约定
    └── expected_path: "config/emission_db_manifest.yaml"
```

### 2.3 每个维度的字段

**核心字段** (所有维度共有):

| 字段 | 类型 | 说明 |
|---|---|---|
| `field_type` | enum | `categorical` (vehicle_type/pollutant/season/road_type/meteorology), `integer_range` (model_year) |
| `value_type` | str | `string` / `integer` / `float` |
| `standard_names` | list[str] | agent 层可见的合法标准名 (不含 DB 内部 ID) |
| `display_name_zh` | str | LLM prompt 中的中文名 |
| `required` | bool | 此维度是否强制要求 |
| `default_policy` | enum | 见 §2.4 |
| `cross_db_key` | str | agent 层引用此维度时用的 key (跨 DB 不变) |

**category 类型额外字段** (`vehicle_type`, `pollutant`, `season`, `road_type`, `meteorology`, `stability_class`):

| 字段 | 说明 |
|---|---|
| `aliases_for_standardization` | 是否在 schema 内提供别名表 (option: schema 提供 / db manifest 提供) |

**integer_range 类型额外字段** (`model_year`):

| 字段 | 说明 |
|---|---|
| `range_policy` | `"db_declared"` — range 由 DB manifest 提供 |

### 2.4 default_policy 设计 (核心设计决策)

每个维度有自己的 `default_policy`, 分 4 档:

| default_policy | 含义 | 适用于 |
|---|---|---|
| `"mandatory"` | 无默认值, 必须用户提供 | vehicle_type (排放分析不能随便猜车型) |
| `"optional_no_default"` | 可选, 无默认 | meteorology (用户不提供则扩散工具用自带内置值) |
| `"schema_default"` | schema 提供跨 DB 都成立的领域默认 | season="夏季" (领域实践: 高温高排放代表季), road_type="快速路" (领域实践: 排放分析主场景) |
| `"db_default"` | 具体数值由 DB manifest 提供 | model_year=2020 (由 DB 数据覆盖范围决定), pollutants=[CO2,NOx,PM2.5] (由 DB 实际支持的污染物决定) |

**设计原则**:
- `"schema_default"` 的场景: agent 层直接读 schema 文件取默认值, 不依赖具体 DB
- `"db_default"` 的场景: agent 层读 schema 知道 "model_year 的默认值在 db manifest 里", 通过 db manifest 间接取, **不硬编码具体值**
- 区分标准: 问 "换了数据库(例如从 MOVES Atlanta 换 COPERT Europe), 这个默认值会不会变?" 如果会 → `db_default`; 如果不会 → `schema_default`

当前代码里的问题: `model_year=2020` 是 `db_default` 性质, 但被当作 `schema_default` 硬编码在 agent 层 — 这是要解耦的。

### 2.5 跨数据库映射规则

**原则**: agent 层只看标准名 (e.g. `vehicle_type = "Passenger Car"`), 不知道数据库内部用什么 ID (e.g. MOVES SourceType 21 / COPERT category string "PC").

映射关系由 **db manifest** 承担:

```yaml
# config/emission_db_manifest.yaml (未来, 不在 Round 1 范围)
db_info:
  name: "MOVES Atlanta 2025"
  source: "EPA MOVES runspec export"
  coverage_year_min: 1995
  coverage_year_max: 2025

dimension_mappings:
  vehicle_type:
    mapping_type: "integer_id"  # 此 DB 用数字 ID
    entries:
      - standard_name: "Passenger Car"
        db_value: 21
      - standard_name: "Transit Bus"
        db_value: 42
      # ...

  pollutant:
    mapping_type: "integer_id"
    entries:
      - standard_name: "CO2"
        db_value: 90
      # ...

  model_year:
    mapping_type: "passthrough"  # 不需要映射
    db_default: 2020

  season:
    mapping_type: "integer_month"  # 映射 春季→4, 夏季→7, etc.
    entries:
      - standard_name: "春季"
        db_value: 4
      # ...

  road_type:
    mapping_type: "integer_roadmode"
    entries:
      - standard_name: "快速路"
        db_value: 4
      # ...
```

**备选方案** (简化, 推荐 Phase 5.2 采用): 不在 db manifest 中做复杂映射, 而是让 `schemas/emission_db_schema.yaml` 定义 "跨数据库标准名", 计算器 adapter (未来 Phase 5.2+ 重构时) 负责 id↔标准名映射。当前阶段 (计算器层不动) 不需要 `dimension_mappings` 的复杂定义。

### 2.6 与现有文件的关系

| 现有文件 | 行数 | 内容 | 与 emission_db_schema 关系 |
|---|---|---|---|
| `config/unified_mappings.yaml` | 598 | vehicle types + pollutants + seasons + road types + meteorology + VSP + defaults | **是 emission_db_schema 的事实上的前身**。未来: (a) 维度定义 (字段类型/标准名/default_policy) 迁到 emission_db_schema, (b) 别名/标准化配置 保留在 unified_mappings, (c) VSP 参数/VSP bins 迁出到独立的 `vsp_config.yaml` (这些是物理模型参数, 不是 DB schema) |
| `config/tool_contracts.yaml` | ~700 | required_slots/optional_slots/defaults per tool | 保留, 不改。tool_contracts 的 defaults 段应该**引用** emission_db_schema 的 default_policy, 不重复声明具体值 |
| `shared/standardizer/constants.py` | 85 | 与 YAML 重复的 VEHICLE_TYPE_MAPPING / POLLUTANT_MAPPING / VSP | 删除重复项, 全部从 YAML 读 (Phase 5.2 范围外, 但设计上要标出来) |
| `config/dispersion_pollutants.yaml` | 38 | 扩散特有的污染物属性 (半衰期) | 独立保留 — 这是扩散物理模型配置, 不是 DB schema |
| `config/meteorology_presets.yaml` | ~50 | 气象预设物理参数 | 独立保留 — 物理模型配置 |

**单源真理目标**: emission_db_schema 定义"什么是维度", unified_mappings 保留"维度的标准化别名" (是 schema 引用的 reference data), tool_contracts 定义"哪个工具需要哪个维度"。

---

## §3 三个关键决策点

### 决策 1: Schema 文件独立 vs 合并 vs 拆分

| 选项 | 描述 | 优 | 劣 |
|---|---|---|---|
| **A: 独立** | 新建 `config/emission_db_schema.yaml`, 仅含维度定义 + default_policy + cross_db_key。`unified_mappings.yaml` 不动。 | 清晰分离 "schema" vs "reference data", 不影响现有文件, 改动范围最小 | 多一个 YAML 文件, 维护时要保持与 unified_mappings 的 vehicle_type/pollutant 列表一致 |
| **B: 合并** | 改造 `unified_mappings.yaml`, 在现有结构上加 `dimension_definitions:` 段 | 单文件, 不增加文件数 | `unified_mappings.yaml` 已经 598 行, 合并会更长; 且包含 VSP params/bins 等非 schema 内容, 文件职责模糊 |
| **C: 拆分** | `unified_mappings.yaml` 拆为 3 个: `emission_db_schema.yaml` (维度定义), `standardization_aliases.yaml` (别名), `vsp_config.yaml` (VSP 物理参数) | 最清晰, 最论文-friendly | 最大改动范围, 影响所有读 unified_mappings 的代码 (standardizer/router 等) |

**推荐: 选项 A (独立文件)**。理由:
- Round 1 目标是设计 schema, 不是重构 unified_mappings
- 独立文件改动范围最小, 不碰现有代码路径
- unified_mappings 作为 "标准化别名 + VSP" 的事实上的 reference data 保持不动
- emission_db_schema 是**增量**, 用 default_policy / cross_db_key 等字段补充 unified_mappings 没有的信息
- 未来 Phase 5.3+ 如需重构, 可以在有 schema 文件作为设计锚点的基础上做拆分

### 决策 2: Schema-level defaults vs DB-level defaults

| 选项 | 描述 | 优 | 劣 |
|---|---|---|---|
| **A: Schema 只定义语义, DB manifest 给值** | schema 说 `model_year.default_policy = "db_default"`, DB manifest 说 `model_year.db_default = 2020`. agent 层读 schema 知道 "取 DB 默认", 再读 manifest 取具体值 | 最干净的解耦 — agent 不知道 2020 | 需要两个 YAML 读取, 增加一次 I/O; manifest 尚未存在 (Round 2 创建) |
| **B: Schema 直接给具体默认值** | schema 里写 `model_year.default_value: 2020`, agent 直接读 | 简单, 一个文件 | 数据库换了默认值得改 schema — 这就是当前的耦合 |
| **C: Schema 给值 + 标注来源** | schema 写 `model_year.default_value: 2020` 并标注 `default_source: "MOVES Atlanta 2025 DB, recent representative year"` | 改动最小 (只加注释字段), agent 逻辑不动 | 不真正解耦, 只是文档化耦合 |

**推荐: 选项 A (分层), 但分两步落地**:
- Round 2: schema 文件定义 `default_policy` 字段 (e.g. `model_year: db_default`, `season: schema_default`), 具体默认值暂存在 schema 文件内 (选项 C 的标注形式), agent 层改成从 schema 文件读而不 hardcode
- 后续 (Phase 5.3+): 创建 db manifest, `db_default` 类型的值迁到 manifest, agent 层链式读 schema→manifest

理由: 两步落地避免 "大爆炸" (一次同时创建 schema + manifest + 改 agent 读逻辑)。Round 2 先建立 `default_policy` 概念并改 agent 读 schema, 默认值仍在 schema 内但不再在 agent Python 代码中。db manifest 放后续。

### 决策 3: 跨数据库映射模板放在 schema 还是 db manifest

| 选项 | 描述 | 优 | 劣 |
|---|---|---|---|
| **A: Schema 内置映射模板** | schema 里定义 `vehicle_type.cross_db_mapping_template: {standard_name: str, db_value: any}`, agent 层可见此结构 | 一个文件完整描述维度 | schema 掺杂了 "这个 DB 用 int ID / 那个 DB 用 string category" 的实现细节 |
| **B: DB manifest 提供映射** | schema 只定义标准名, manifest 定义 `dimension_mappings: {standard_name → db_value}` | schema 保持纯净 (只含标准名 + 字段类型), manifest 含 DB 相关映射 | manifest 尚未存在; agent 层需要 manifest 才能理解 DB |
| **C: 不做 (Phase 5.2 不切换 DB, 假设规则写注释)** | schema 文件里有注释说明 "换 DB 时需提供 XXX 映射", 不做抽象 | 零复杂度 | 对解耦无实际贡献, 只有文档价值 |

**推荐: 选项 C (不做, 注释说明)**, 在 Round 2 阶段。

理由:
- Phase 5.2 范围内只有一个数据库 (MOVES Atlanta CSV), 没有切换场景
- 跨数据库映射的**抽象**应该在纸面设计里确定原则, 但不应该编码为 YAML 结构 — 没有第二个 DB 来验证抽象是否正确
- 在 schema 文件注释里写清楚映射规则 (例: "schema 使用标准英文名, 数据库内部可用 int ID / string / 任何表示。adapter 层负责 id↔标准名 映射")
- Phase 5.3+ 或 user study 阶段如果真需要换 DB (或接入 COPERT), 有了真实用例再设计 manifest 的映射结构

---

## §4 Round 2 实施概要 (供用户决策参考, 不是 Round 1 产出)

基于以上 audit + 设计草案 + 决策推荐:

**Round 2 产出**:
1. 创建 `config/emission_db_schema.yaml` (独立文件, 选项 A), 含 6 个维度的字段定义 + default_policy + cross_db_key
2. 改 `core/contracts/runtime_defaults.py`: 从 schema YAML 读 model_year 默认值 (不再 hardcode)
3. 改 `core/contracts/clarification_contract.py`: 从 schema YAML 读 YEAR_RANGE / 默认值, 不再用类常量
4. 改 `core/router.py`: 对话文本里 "例如 2020、2021" 改为从 schema 读 (或保留 generic "例如 2020" 作为无害的对话示例, 但**注释说明此行不是权威默认**)
5. test: 新增 CI check (E-剩余.4 原 scope), 验证 Python 侧 model_year 默认跟 YAML schema 一致

**不做** (明确排除在 Phase 5.2 外):
- 不创建 db manifest (放 Phase 5.3+)
- 不改 3 个计算器的 VEHICLE_TO_SOURCE_TYPE / POLLUTANT_TO_ID (计算器层不动)
- 不改 unified_mappings.yaml 结构
- 不删 shared/standardizer/constants.py 的重复项
