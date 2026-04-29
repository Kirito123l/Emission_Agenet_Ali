# Phase 5.2 架构 Recon: Agent ↔ Database 解耦审计

Date: 2026-04-29
Branch: `phase3-governance-reset`
Scope: 只 recon, 不动代码。为 E-剩余.4 实施方向提供决策依据。

---

## 问题 1: 排放数据库当前形态

**形态**: 不是 SQL/API, 是 **13 个 MOVES Atlanta CSV 文件**, 总计 ~100 MB (未压缩)。

### 数据文件分布

#### 主计算器数据 (`calculators/data/`)

| 目录 | 文件 | 大小 | Schema |
|---|---|---|---|
| `emission_factors/` | `atlanta_2025_1_55_65.csv` (冬) | 24.3 MB | `Speed, pollutantID, SourceType, ModelYear, EmissionQuant` |
| | `atlanta_2025_4_75_65.csv` (春/秋) | 24.3 MB | 同上 |
| | `atlanta_2025_7_90_70.csv` (夏) | 24.3 MB | 同上 |
| `macro_emission/` | `atlanta_2025_1_35_60 .csv` (冬) | 4.5 MB | `opModeID, pollutantID, sourceTypeID, modelYearID, em` |
| | `atlanta_2025_4_75_65.csv` (春/秋) | 4.5 MB | 同上 |
| | `atlanta_2025_7_80_60.csv` (夏) | 4.5 MB | 同上 |
| `micro_emission/` | `atlanta_2025_1_55_65.csv` (冬) | 8.0 MB | `opModeID, pollutantID, SourceType, ModelYear, CalendarYear, EmissionQuant` |
| | `atlanta_2025_4_75_65.csv` (春/秋) | 8.0 MB | 同上 |
| | `atlanta_2025_7_90_70.csv` (夏) | 8.0 MB | 同上 |

#### 重复副本 (`skills/`)

| 目录 | 文件数 | 总大小 |
|---|---|---|
| `skills/macro_emission/data/` | 3 | 13.5 MB |
| `skills/micro_emission/data/` | 3 | 23.4 MB |

与 `calculators/data/` 内容相同, 独立维护。

#### 其他数据文件

| 文件 | 大小 | 用途 |
|---|---|---|
| `calculators/data/dispersion_models/model_z=*/` | — | XGBoost `.json` 模型 (按粗糙度高度分目录, 每目录 12 个) |
| `config/meteorology_presets.yaml` | 1.4 KB | 气象预设 |
| `config/dispersion_pollutants.yaml` | 1.2 KB | 扩散支持的污染物列表 |
| `data/users.db` | 20 KB | SQLite 用户认证 (与排放无关) |
| `data/sessions/*.json` | — | 会话持久化 |
| `skills/knowledge/index/` | — | FAISS 知识检索索引 |

### SQLite 数据库

`api/database.py:13` — `data/users.db`, 仅用于用户认证 (`users` 表: id, username, password_hash, email, created_at, updated_at, last_login)。与排放因子无关。

### 数据维度

| 维度 | 数据库内容 | 代码表示 |
|---|---|---|
| vehicle_type | 13 MOVES SourceType ID (21=Passenger Car, 31=Transit Bus, 42=…, 62=Combination Long-haul Truck) | 数字 ID |
| pollutant | 6 种, MOVES pollutantID (90=CO2, 3=NOx, 110=PM2.5 等) | 数字 ID |
| model_year | 1995-2025 range | 整数 |
| season | 冬=1月, 春=4月, 夏=7月, 秋=4月 | 文件名编码 |
| road_type | 通过 Speed 列编码: roadTypeID=4 (快速路), 5 (地面道路) | 嵌入 Speed 值 (`7705` = 77mph + roadType 5) |
| opModeID | VSP bin → Operating mode (300=average 常用于宏观) | 整数 |

### 数据源特征

- **地域**: Atlanta (美国, 非中国)
- **年份**: 2025 (文件名 `atlanta_2025_*`)
- **生成工具**: 推测 MOVES runspec 导出 (非 Python 生成)
- **体量**: 大 (单文件 24MB / 94 万行), 已跟踪在 git (binary), 有重复副本

---

## 问题 2: 数据库 Schema 抽象层

**答案: 没有。**

不存在 `EmissionFactorRepository` / adapter / DAO 类。三层计算器各自独立直接调用 `pd.read_csv()`。

### 计算器层: 原始 CSV 读取 (无抽象)

| 计算器 | 文件 | `pd.read_csv` 位置 | 列名常量定义 |
|---|---|---|---|
| `EmissionFactorCalculator` | `calculators/emission_factors.py` | line 245 | line 12-16: `COL_SPEED='Speed'`, `COL_SOURCE_TYPE='SourceType'`, `COL_POLLUTANT='pollutantID'`, `COL_MODEL_YEAR='ModelYear'`, `COL_EMISSION='EmissionQuant'` |
| `MacroEmissionCalculator` | `calculators/macro_emission.py` | line 147-158 | line 18-22: `COL_OPMODE='opModeID'`, `COL_POLLUTANT='pollutantID'`, `COL_SOURCE_TYPE='sourceTypeID'`, `COL_MODEL_YEAR='modelYearID'`, `COL_EMISSION='em'` |
| `MicroEmissionCalculator` | `calculators/micro_emission.py` | line 178 | line 13-17: `COL_OPMODE='opModeID'`, `COL_POLLUTANT='pollutantID'`, `COL_SOURCE_TYPE='SourceType'`, `COL_MODEL_YEAR='ModelYear'`, `COL_EMISSION='EmissionQuant'` |

**三个计算器之间**: 列名定义不共享, 命名约定不一致 (驼峰 vs 小写后缀 `ID`), 各自硬编码 CSV 文件路径。

### vehicle_type → MOVES ID 映射: 三处独立

| 计算器 | 变量名 |
|---|---|
| `calculators/emission_factors.py` | `VEHICLE_TO_SOURCE_TYPE` (类属性 dict) |
| `calculators/macro_emission.py` | `VEHICLE_TO_SOURCE_TYPE_MAP` (类属性 dict) |
| `calculators/micro_emission.py` | `VEHICLE_TO_SOURCE_TYPE_MAP` (类属性 dict) |

三个 dict 映射相同的 13 种 MOVES 车辆名→相同的 SourceType ID, 但不共享代码。

### 标准器层: YAML 映射的独立副本

| 文件 | 内容 |
|---|---|
| `config/unified_mappings.yaml` (line 9-211) | 13 vehicle types + MOVES SourceType ID + VSP params + aliases |
| `shared/standardizer/constants.py` (line 1-15) | `VEHICLE_TYPE_MAPPING` — 相同的 13 种车 + 中文别名, **不含 SourceType ID** |
| `shared/standardizer/constants.py` (line 52-66) | `VSP_PARAMETERS` — 13 种车的 A/B/C/M/m 物理参数 (与 unified_mappings.yaml 重复) |

`shared/standardizer/constants.py` 与 `config/unified_mappings.yaml` 之间存在**部分重复**:
- 车辆名 + 中文别名: 两份都写 (constants.py 面向标准器 fuzzy match, YAML 面向配置管理)
- VSP 参数: 两份都写
- SourceType ID: YAML 有, constants.py **没有** (标准器不需要知道 MOVES ID, 只做文本→标准名映射)

### 工具层: 函数参数默认值的独立副本

每个工具在自己的 `execute()` 函数签名或 kwargs fallback 中重复硬编码默认值:

| 工具 | 默认值 | 位置 |
|---|---|---|
| `tools/emission_factors.py` | `season="夏季"`, `road_type="快速路"` | line 73-74, 100-101, 108-109 |
| `tools/macro_emission.py` | `model_year=2020`, `season="夏季"` | line 636-638, 651-653 |
| `tools/micro_emission.py` | `model_year=2020`, `season="夏季"` | line 75-76 |

### 唯一的"抽象"边界

```
tools/emission_factors.py  →  calculators/emission_factors.py
tools/macro_emission.py    →  calculators/macro_emission.py
tools/micro_emission.py    →  calculators/micro_emission.py
```

这个委托只是函数调用, 没有接口/协议的定义。计算器换了, 工具代码也要跟着改 (因为参数名、返回值格式都由调用方预期)。

---

## 问题 3: 工具 ↔ 数据库耦合点 (数据库切换成本)

**假设场景**: 换排放数据库为 EPA MOVES (不同版本, schema 可能变: column 命名, SourceType ID 重新分配, 或新增 CalendarYear 列) 或 COPERT (用 category 字符串而非数字 ID)。

### 需要改的文件完整清单

| 层 | 文件 | 改动类型 | 具体内容 |
|---|---|---|---|
| **计算器** | `calculators/emission_factors.py` | adapter | CSV path (line 68-74), column names 5 常量 (line 12-16), `VEHICLE_TO_SOURCE_TYPE` dict, `POLLUTANT_TO_ID` dict, `ROAD_TYPE_ROADMODE` dict (line 60-64), `SEASON_MONTH_MAP` (line 52-55) |
| **计算器** | `calculators/macro_emission.py` | adapter | CSV path (line 74-78), column names 5 常量 (line 18-22), `VEHICLE_TO_SOURCE_TYPE_MAP` dict, `POLLUTANT_TO_ID` dict, `SEASON_MONTH_MAP` (line 56-61), `DEFAULT_FLEET_MIX` (line 65-71) |
| **计算器** | `calculators/micro_emission.py` | adapter | CSV path (line 60-73), column names 5 常量 (line 13-17), `VEHICLE_TO_SOURCE_TYPE_MAP` dict, `POLLUTANT_TO_ID` dict, `SEASON_MONTH_MAP` (line 53-58) |
| **计算器** | `calculators/vsp.py` | adapter | VSP 参数 per vehicle type (line 52-66 in constants.py, 但 vsp.py 读取它), VSP bins (14 个) |
| **工具** | `tools/emission_factors.py` | 逻辑 | `season="夏季"`, `road_type="快速路"` 默认值 (line 73-74, 100-101, 108-109) |
| **工具** | `tools/macro_emission.py` | 逻辑 | `model_year=2020`, `season="夏季"` 默认值 (line 636-638), `defaults_used` 记录 (line 651-653) |
| **工具** | `tools/micro_emission.py` | 逻辑 | `model_year=2020`, `season="夏季"` 默认值 (line 75-76) |
| **工具** | `tools/dispersion.py` | 逻辑 | 污染物支持列表 (line 150-152 via dispersion_pollutants.yaml) |
| **配置** | `config/unified_mappings.yaml` | 配置 | vehicle types × 13 (line 9-211), pollutants × 6 (line 213-261), season × 4 (line 263-287), road types × 5 (line 289-323), defaults (line 539-553), VSP bins × 14 (line 556-599) |
| **配置** | `config/tool_contracts.yaml` | 配置 | per-tool defaults: `query_emission_factors` (line 37-39), `calculate_micro_emission` (line 103-104), `calculate_macro_emission` (line 190-191), model_year range description (line 64), season/road_type descriptions (line 70, 76) |
| **配置** | `config/cross_constraints.yaml` | 配置 | vehicle-pollutant 约束规则 (引用 MOVES 覆盖范围) |
| **标准化** | `shared/standardizer/constants.py` | 配置 | `VEHICLE_TYPE_MAPPING` (line 1-15), `POLLUTANT_MAPPING` (line 26-33), `SEASON_MAPPING` (line 44-49), `VSP_PARAMETERS` (line 52-66), `VSP_BINS` (line 69-84) |
| **标准化** | `services/standardization_engine.py` | 逻辑 | `PARAM_TYPE_REGISTRY` (line 37-45), `LEGACY_FUZZY_THRESHOLDS` (line 47-54), `"default_value": "夏季"` (line 76), `"default_value": "快速路"` (line 83), `_FAILURE_MESSAGES` (line 103-108), method_map (line 207-214) |
| **标准化** | `services/standardizer.py` | 逻辑 | fallback defaults: `"夏季"` (line 128), `"快速路"` (line 143) |
| **Agent** | `core/contracts/runtime_defaults.py` | 逻辑 | `model_year: 2020` (line 8-10) — 如果新 DB 的 model_year 范围不同, 默认值也需审视 |
| **Agent** | `core/contracts/clarification_contract.py` | 逻辑 | `YEAR_RANGE_MIN=1995` / `YEAR_RANGE_MAX=2025` (line 29-30), `model_year=2020` 在 LLM system prompt 中 (line 847), `range(YEAR_RANGE_MIN, YEAR_RANGE_MAX+1, 5)` 生成合法值 (line 1253) |
| **Agent** | `core/governed_router.py` | 逻辑 | per-tool slot→argument 映射 (line 822-891) |
| **Agent** | `core/router.py` | 逻辑 | year example in clarification text: `"例如 2020、2021 这样的年份"` (line 1782, 4222) |
| **Agent** | `core/remediation_policy.py` | 逻辑 | traffic flow/speed lookup tables by highway class (line 56-93) — 如果 road_type 分类体系变 |
| **Skills** | `skills/macro_emission/data/` | adapter | CSV 副本 × 3 (13.5 MB) |
| **Skills** | `skills/micro_emission/data/` | adapter | CSV 副本 × 3 (23.4 MB) |
| **Skills** | `skills/macro_emission/excel_handler.py` | 逻辑 | `DEFAULT_FLEET_MIX` (line 97-103, 第 3 份重复) |
| **测试** | `evaluation/eval_normalization.py` | 逻辑 | `SEASON_ALLOWED`, `ROAD_TYPE_ALLOWED` (line 28-29) |

### 切换成本直觉评分: 5/5

**散落 15+ 处文件**, 没有一处是"只换一个 adapter 文件"就完事的。关键痛点是:

1. **计算器层有 "看起来该是 adapter" 的代码但没有独立为 adapter** — `VEHICLE_TO_SOURCE_TYPE` / `POLLUTANT_TO_ID` 在每个计算器内部是私有类属性, 不是可插拔 adapter
2. **YAML 配置是人工维护的不是自动生成的** — `unified_mappings.yaml` 包含 MOVES SourceType ID, 但没有一个 `emission_db_manifest.yaml` 作为数据库自描述文件
3. **同一知识在多个不相干的地方重复** — `model_year=2020` 出现在 runtime_defaults.py / clarification_contract.py LLM prompt / tools/macro_emission.py / tools/micro_emission.py 四处, 没有共享来源
4. **CSV 数据文件有重复副本** — 15 个 CSV 副本 (calculators/ 9 个 + skills/ 6 个), 换 DB 需要全部替换

---

## 问题 4: Agent 层 ↔ 数据库耦合点

逐文件 audit agent 层中哪些直接知道数据库内容 (具体值), 哪些只通过接口对话。

### 4a. `core/contracts/runtime_defaults.py` (34 lines)

```python
_RUNTIME_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "query_emission_factors": {
        "model_year": 2020,       # ← 具体值硬编码, 无来源注释
    },
}
```

| 耦合项 | 判断 |
|---|---|
| `model_year` 作为 slot 名 | **合理** — agent 参数 schema 概念 (tool_contracts 也声明了此 slot) |
| `2020` 具体值 | **耦合** — 数据库内容的具体值出现在 agent 层 Python 代码 |
| `query_emission_factors` 工具名 | **合理** — agent 路由决策需要知道工具名 |

**解耦方向**: `model_year=2020` 应该从 YAML 声明式源读取。当前 `get_runtime_defaults()` 已从 `tool_contracts.yaml` 读 defaults 再 overlay `_RUNTIME_DEFAULTS`, 但 `tool_contracts.yaml` 的 `query_emission_factors.defaults` 段**不含 model_year** (只含 season + road_type)。如果将 model_year 补入 tool_contracts.yaml, 则 Python `_RUNTIME_DEFAULTS` 可删。

### 4b. `core/contracts/clarification_contract.py`

| Line | 内容 | 耦合类型 |
|---|---|---|
| 29-30 | `YEAR_RANGE_MIN = 1995`, `YEAR_RANGE_MAX = 2025` | **数据库内容硬编码** — 类常量, 被多处引用 |
| 847 | `"runtime_defaults 字段列出了当前工具可用的运行时默认值（如 model_year=2020）"` | **具体值嵌在 LLM system prompt** |
| 1234-1244 | `slot_name → 中文名` 映射 | schema 概念, 合理 |
| 1253-1254 | `range(YEAR_RANGE_MIN, YEAR_RANGE_MAX + 1, 5)` — 生成合法值列表给 LLM | **从硬编码 range 派生** |
| 996-1000 | tool intent 描述 | schema 概念, 合理 |
| 1624-1626 | known_tokens 结果类型列表 | schema 概念, 合理 |

最严重的耦合是 `YEAR_RANGE_MIN/MAX` — 如果换为 COPERT 数据 (覆盖 1990-2030), 这个 range 要同步改。LLM prompt 里的 `model_year=2020` 是 K4 知识注入, 把具体值刻在 LLM context 里。

### 4c. `services/standardization_engine.py`

| Line | 内容 | 耦合类型 |
|---|---|---|
| 37-45 | `PARAM_TYPE_REGISTRY` (6 个参数类型名) | schema 概念, 合理 |
| 47-54 | `LEGACY_FUZZY_THRESHOLDS` | 算法 tuning, 不直接耦合数据 |
| 76, 83 | `"default_value": "夏季"`, `"default_value": "快速路"` | **具体值硬编码** |
| 103-108 | `_FAILURE_MESSAGES` | schema 概念, 合理 |
| 207-214 | `method_map` / `lookup_map` | schema 概念, 合理 |

`"夏季"`/`"快速路"` 是参数标准化层的硬编码 fallback — 跟 `runtime_defaults.py` 的 2020 性质相同: agent 层在替数据库决定默认值。

### 4d. `core/ao_manager.py`

**结论: 不含数据库内容硬编码。**

`_extract_implied_tools` (line 566-586) 映射的是**工具意图关键字** (如 `"因子"` → `query_emission_factors`), 不是数据库内容。`MULTI_STEP_SIGNAL_PATTERNS` (line 72-87) 是中文语言特征正则, 也不含数据库内容。这是 agent 层中最干净的模块。

### 4e. `config/unified_mappings.yaml`

**结论: 全量硬编码 MOVES 数据库内容, 非 auto-generated。**

| Line | 内容 | 耦合类型 |
|---|---|---|
| 9-211 | 13 MOVES vehicle types + SourceType ID + VSP 参数 | **数据库 schema + 内容全量编码** |
| 213-261 | 6 pollutants + MOVES pollutantID | **数据库内容编码** |
| 263-287 | 4 seasons + aliases | 领域概念, 合理 |
| 289-323 | 5 road types + aliases | 领域概念, 合理 |
| 539-553 | defaults (season, road_type, model_year, pollutants[], fleet_mix{}) | **数据库默认值编码** |
| 556-599 | VSP bins × 14 | **数据库内容编码** |

**关键判断**: YAML 中 vehicle type 段含 `id: 21` (MOVES SourceType ID) — 这是**数据库内容**, 不是抽象 schema。当 CSV 换为不同 MOVES 版本 (ID 可能重新分配) 或 COPERT (用字符串 category 而非数字 ID), YAML 必须全量重写。这是一个**手动维护的 MOVES 数据库内容快照**, 不是从数据库自动生成的。

### 4f. `core/governed_router.py` + `core/router.py`

| Line | 内容 | 耦合类型 |
|---|---|---|
| governed_router:822-891 | per-tool slot→argument 映射 | schema 概念, 合理 |
| governed_router:374-384 | `tool_name == "query_emission_factors"` 特殊处理 | 工具名, 合理 (但 hardcoded) |
| router:1782, 4222 | `"请告诉我例如 2020、2021 这样的年份"` | **具体年份示例嵌入对话文本** |

耦合轻但散 — 对话文本里的 `2020` 跟 `_RUNTIME_DEFAULTS` 里的 `2020` 是同一知识在不同层的独立重复。

---

## 总览: Agent ↔ Database 耦合全景图

```
┌─────────────────────────────────────────────────────────┐
│ Agent 层 (知道数据库内容的部分)                            │
│                                                         │
│ clarification_contract.py:29-30  YEAR_RANGE 1995-2025   │
│ clarification_contract.py:847    LLM prompt "model_year │
│                                   =2020"                │
│ runtime_defaults.py:8-10         model_year=2020        │
│ standardization_engine.py:76,83  season=夏季 road=快速路 │
│ router.py:1782                   "例如 2020、2021"       │
│                                                         │
│ unified_mappings.yaml            ← 全量 MOVES 内容       │
│   vehicle_type × 13 + SourceType IDs                    │
│   pollutant × 6 + pollutantIDs                          │
│   season × 4, road_type × 5                             │
│   defaults (season, road, year, pollutants, fleet_mix)  │
│   VSP bins × 14, VSP params × 13                        │
│                                                         │
│ shared/standardizer/constants.py ← 与 YAML 部分重复      │
│   VEHICLE_TYPE_MAPPING, POLLUTANT_MAPPING,              │
│   SEASON_MAPPING, VSP_PARAMETERS, VSP_BINS              │
├─────────────────────────────────────────────────────────┤
│ 工具层 (不直接知道 DB 内容, 但硬编码默认值)                 │
│                                                         │
│ tools/macro_emission.py:636      model_year=2020        │
│ tools/micro_emission.py:75       model_year=2020        │
│ tools/emission_factors.py:108    season=夏季,road=快速路 │
├─────────────────────────────────────────────────────────┤
│ 计算器层 (直接嵌入 MOVES schema, 无 adapter 抽象)         │
│                                                         │
│ emission_factors.py    VEHICLE_TO_SOURCE_TYPE,          │
│                        POLLUTANT_TO_ID,                 │
│                        ROAD_TYPE_ROADMODE               │
│ macro_emission.py      VEHICLE_TO_SOURCE_TYPE_MAP,      │
│                        DEFAULT_FLEET_MIX                │
│ micro_emission.py      VEHICLE_TO_SOURCE_TYPE_MAP       │
│ vsp.py                 VSP 参数 × 13                     │
└─────────────────────────────────────────────────────────┘
```

### 论文论点评估

**Claim: "agent 架构应该跟具体数据库解耦"** — 当前代码**不支持**此论点。

| 发现 | 对论文论点影响 |
|---|---|
| 计算器层无 adapter 抽象 — 3 个计算器各自独立硬编码 MOVES ID 映射 | 论文如果要 claim adapter 模式, 需要重构出 adapter 层 |
| `unified_mappings.yaml` 是手工维护的 MOVES 快照, 非从 DB 自动生成 | 论文如果要 claim 配置驱动, 需要明确 YAML 是声明式但手工维护 |
| `model_year=2020` 在 6 处独立重复 | 论文如果要 claim single source of truth, 需要集中管理默认值 |
| `ao_manager.py` 不含 DB 内容硬编码 — agent 的 AO 分类逻辑与 DB 内容解耦 | **可 claim 的正面案例** |
| `DEFAULT_FLEET_MIX` 在 3 处重复 (calculator + excel_handler + YAML) | 反例 — fleet mix 是领域数据, 但散落在多层 |

### 解耦的可行路径 (后续 Phase)

1. **计算器层注入 adapter**: 定义 `EmissionDataSource` protocol, 三个计算器不再 hardcode CSV path + column names, 改为注入 adapter
2. **车辆/污染物映射统一到 YAML 单源**: 删除 `shared/standardizer/constants.py` 的 VSP/VSP_BINS, 从 `unified_mappings.yaml` 读; 删除计算器各自的 `VEHICLE_TO_SOURCE_TYPE`, 从 YAML 动态生成
3. **model_year default 集中到 tool_contracts.yaml**: `_RUNTIME_DEFAULTS` 可删, `clarification_contract.py` 不要 hardcode `YEAR_RANGE_MIN/MAX`, 从 tool_contracts 的参数描述里读取
4. **加 `emission_db_manifest.yaml`**: 数据库自描述文件, 声明 "sourceType 21 是 Passenger Car", agent 层不直接知道这些映射, 通过 manifest 间接引用
