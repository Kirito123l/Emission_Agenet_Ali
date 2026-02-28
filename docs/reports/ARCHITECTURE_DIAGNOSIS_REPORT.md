# Emission Agent 架构诊断报告

**生成日期**: 2026-02-03
**分析工具**: Claude Code (Sonnet 4.5)
**代码版本**: v1.2.0
**分析范围**: 完整代码库扫描 + 深度架构分析

---

## 执行摘要

### 关键发现

本次诊断对 Emission Agent 项目进行了全面深度分析，发现系统采用了 **混合架构模式**：LLM驱动的智能决策 + 大量硬编码规则作为后备。主要发现：

1. **System Prompt 过载严重** (617行)：包含大量示例、规则和特殊情况处理
2. **硬编码规则广泛分布**：50+ 决策关键词、40+ 列名模式、30+ 车型别名、20+ 字段修正规则
3. **双重标准化机制**：LLM标准化 + 硬编码映射表，存在冗余
4. **验证层复杂**：多层验证（Schema验证、语义验证、反思修复）增加了系统复杂度
5. **参数合并逻辑复杂**：上下文管理器中的增量对话支持包含大量特殊情况处理

### 优势

- ✅ 清晰的 Agent-Skill 分层架构
- ✅ 完善的错误处理和降级机制
- ✅ 支持本地模型，降低成本
- ✅ 灵活的列名映射（LLM + 硬编码双保险）
- ✅ 丰富的中英文支持

### 问题

- ⚠️ System Prompt 维护成本高，规则累积严重
- ⚠️ 硬编码规则分散在多个文件，难以统一管理
- ⚠️ 决策逻辑部分依赖关键词匹配，不够智能
- ⚠️ 验证和修复逻辑增加了系统复杂度
- ⚠️ 缺乏统一的规则配置中心

### 建议优先级

**高优先级**（立即执行）：
1. 提取 System Prompt 中的规则到配置文件
2. 统一硬编码映射表到单一配置中心
3. 简化验证逻辑，减少层级

**中优先级**（2-3周）：
1. 重构 Agent 决策逻辑，减少关键词依赖
2. 优化参数合并机制，简化增量对话逻辑
3. 建立规则版本管理机制

**低优先级**（长期演进）：
1. 探索更智能的意图理解方式
2. 减少对示例的依赖，提升泛化能力
3. 建立规则自动学习机制

---

## 1. 项目概况

### 1.1 文件结构总览

```
emission_agent/
├── agent/                    # Agent层 (9个文件)
│   ├── core.py              # 核心逻辑 (600+ 行)
│   ├── context.py           # 上下文管理 (300+ 行)
│   ├── validator.py         # 参数验证 (400+ 行)
│   ├── reflector.py         # 反思修复 (200+ 行)
│   ├── learner.py           # 学习机制 (150+ 行)
│   ├── monitor.py           # 性能监控 (150+ 行)
│   ├── cache.py             # 计划缓存 (100+ 行)
│   └── prompts/             # Prompt模板 (2个文件)
│       ├── system.py        # 系统Prompt (617行)
│       └── synthesis.py     # 综合Prompt (42行)
│
├── skills/                   # Skill层 (15个文件)
│   ├── base.py              # Skill基类
│   ├── registry.py          # Skill注册表
│   ├── common/              # 通用工具
│   │   ├── file_analyzer.py    # 文件分析 (300+ 行)
│   │   └── column_mapper.py    # 列名映射 (200+ 行)
│   ├── emission_factors/    # 排放因子查询
│   ├── micro_emission/      # 微观排放计算
│   ├── macro_emission/      # 宏观排放计算
│   └── knowledge/           # 知识检索
│
├── shared/                   # 共享模块 (6个文件)
│   └── standardizer/        # 标准化器
│       ├── vehicle.py       # 车型标准化
│       ├── pollutant.py     # 污染物标准化
│       ├── constants.py     # 常量定义 (重要！)
│       ├── cache.py         # 缓存管理
│       └── local_client.py  # 本地模型客户端
│
├── llm/                      # LLM管理 (3个文件)
├── api/                      # Web API (5个文件)
├── web/                      # Web前端 (3个文件)
└── LOCAL_STANDARDIZER_MODEL/ # 本地模型训练 (10+个文件)

总计：
- Python文件：70个
- 代码总行数：~12,000行
- 文档文件：87个 (.md)
- 数据文件：100+ 个 (CSV, JSON, JSONL)
```

### 1.2 代码行数统计

| 模块 | 文件数 | 代码行数 | 占比 |
|------|--------|----------|------|
| Agent层 | 9 | ~2,500 | 21% |
| Skills层 | 15 | ~3,500 | 29% |
| Shared层 | 6 | ~1,200 | 10% |
| API层 | 5 | ~800 | 7% |
| LLM层 | 3 | ~500 | 4% |
| Web前端 | 3 | ~1,000 | 8% |
| 本地模型 | 10+ | ~1,500 | 13% |
| 其他 | 19 | ~1,000 | 8% |
| **总计** | **70** | **~12,000** | **100%** |

### 1.3 依赖关系图

```
用户界面层 (Web/CLI/API)
    ↓
Agent层 (core.py)
    ↓
├─→ Context Manager (context.py) ← 上下文管理
├─→ Validator (validator.py) ← 参数验证
├─→ Reflector (reflector.py) ← 反思修复
├─→ Learner (learner.py) ← 学习机制
├─→ Monitor (monitor.py) ← 性能监控
└─→ Planning Cache (cache.py) ← 计划缓存
    ↓
Skill Registry (skills/registry.py)
    ↓
├─→ Emission Factors Skill
├─→ Micro Emission Skill
├─→ Macro Emission Skill
└─→ Knowledge Skill
    ↓
共享服务层
├─→ Standardizer (vehicle.py, pollutant.py)
│   ├─→ LLM Client (API模式)
│   └─→ Local Client (本地模式)
├─→ File Analyzer (file_analyzer.py)
├─→ Column Mapper (column_mapper.py)
└─→ LLM Client (llm/client.py)
    ↓
数据层
├─→ MOVES数据 (CSV文件)
├─→ 会话存储 (JSON文件)
└─→ 学习案例 (JSONL文件)
```

---

## 2. System Prompt 诊断

### 2.1 Prompt 文件清单

| 文件路径 | 行数 | 用途 | 复杂度 |
|---------|------|------|--------|
| `agent/prompts/system.py` | 617 | Agent规划决策 | ⚠️ 极高 |
| `agent/prompts/synthesis.py` | 42 | 结果综合回答 | ✅ 低 |
| `shared/standardizer/vehicle.py` | 12 | 车型标准化 | ✅ 低 |
| `shared/standardizer/pollutant.py` | 12 | 污染物标准化 | ✅ 低 |
| `skills/common/column_mapper.py` | 68 | 列名映射 | ⚠️ 中 |

**总计**: 751行 Prompt 代码

### 2.2 规则分类统计

#### AGENT_SYSTEM_PROMPT (617行) 详细分析

| 规则类型 | 行数 | 数量 | 示例 |
|---------|------|------|------|
| **技能定义** | 23 | 4个技能 | query_emission_factors, calculate_micro_emission |
| **重要原则** | 10 | 5条原则 | 利用对话历史、必需参数不能省略 |
| **文件处理规则** | 120 | 15+条规则 | 文件预分析、追问规则、错误示例 |
| **追问规则** | 90 | 10+条规则 | 先分析后追问、明确说明缺少什么 |
| **文件格式要求** | 45 | 30+列名模式 | speed_kph, length_km, flow_vph |
| **示例场景** | 175 | 8个完整示例 | 缺少参数、多污染物查询、轨迹处理 |
| **增量对话支持** | 75 | 3个场景示例 | 查询后修改、宏观排放修改 |
| **参数简写识别** | 15 | 20+简写规则 | NOx/氮氧/氮氧化物 |
| **回顾性问题** | 8 | 10+关键词 | 刚才、刚刚、上次、之前 |
| **错误处理** | 6 | 3条规则 | 检查错误记录、解释错误 |
| **输出格式** | 10 | JSON Schema | understanding, plan, needs_clarification |

**关键问题**：
1. ⚠️ **过度依赖示例**：8个完整示例占175行，LLM可能过拟合示例格式
2. ⚠️ **规则累积**：文件处理规则从最初的简单说明演变为120行的详细指南
3. ⚠️ **"补丁式"规则明显**：如"错误示例（不要这样做）"、"注意事项"等防御性规则
4. ⚠️ **列名模式硬编码**：30+列名变体直接写在Prompt中，应该提取到配置

### 2.3 "补丁式"规则识别

通过分析Prompt中的语言模式，识别出以下"补丁式"规则（为解决特定问题而添加）：

| 规则位置 | 规则内容 | 问题指征 | 严重程度 |
|---------|---------|---------|---------|
| 行32-34 | "文件处理规则：当用户上传文件时..." | 使用"当...时"模式 | 中 |
| 行106-112 | "错误示例（不要这样做）" | 明确的反面教材 | 高 |
| 行215-221 | "文件类型识别：不要使用 query_knowledge 查询文件格式！" | 使用感叹号强调 | 高 |
| 行223-266 | "文件格式要求（重要！）：当用户上传文件时，如果执行失败..." | 长篇错误处理说明 | 高 |
| 行203-213 | "错误示例（不要这样做）" | 第二次出现反面教材 | 高 |
| 行442-605 | "增量对话支持（重要）" | 大量场景示例 | 中 |

**"补丁"特征**：
- 使用"不要"、"注意"、"重要"等强调词
- 包含"错误示例"、"正确示例"对比
- 长篇的"如果...则..."条件判断
- 重复强调同一规则（如文件处理）

### 2.4 问题严重程度评估

#### 🔴 严重问题（需立即处理）

1. **Prompt 过载** (617行)
   - 影响：LLM推理延迟增加、Token成本高、维护困难
   - 根因：规则不断累积，缺乏重构
   - 建议：拆分为多个专用Prompt，按场景动态组合

2. **硬编码列名模式** (30+个)
   - 影响：新增列名变体需要修改Prompt
   - 根因：列名映射逻辑部分在Prompt中，部分在代码中
   - 建议：统一到 column_mapper.py 的配置中

3. **示例过拟合风险**
   - 影响：LLM可能严格模仿示例格式，缺乏灵活性
   - 根因：8个完整示例占175行
   - 建议：减少示例数量，增加原则性说明

#### 🟡 中等问题（需计划处理）

4. **规则重复**
   - 文件处理规则在多处重复强调
   - 追问规则有多个版本
   - 建议：合并重复规则，建立规则索引

5. **防御性编程过度**
   - 大量"不要这样做"的反面教材
   - 说明系统曾出现过这些问题
   - 建议：从根源解决问题，而非在Prompt中打补丁

#### 🟢 轻微问题（可延后处理）

6. **中英文混用**
   - Prompt主体是中文，但参数名是英文
   - 影响较小，但可能造成理解偏差
   - 建议：统一语言风格

---

## 3. Agent 层诊断

### 3.1 意图理解机制

**当前实现**：LLM驱动 + 关键词后备

```python
# agent/core.py: _plan() 方法
# 主要流程：
1. 构建完整上下文（历史对话 + 文件分析结果）
2. 调用 LLM 生成 Planning JSON
3. 解析 JSON 提取 skill、params、understanding
4. 如果 LLM 失败，使用关键词推断（_infer_skill_from_input）
```

**关键词推断逻辑** (`agent/core.py:374-389`):
```python
if any(kw in user_input for kw in ["轨迹", "trajectory", "逐秒"]):
    return "calculate_micro_emission"
elif any(kw in user_input for kw in ["路段", "links", "link", "宏观"]):
    return "calculate_macro_emission"
elif any(kw in user_input for kw in ["因子", "factor", "排放率"]):
    return "query_emission_factors"
elif any(kw in user_input for kw in ["知识", "法规", "标准", "什么是"]):
    return "query_knowledge"
```

**问题分析**：
- ⚠️ **关键词匹配过于简单**：只检查是否包含关键词，无法处理复杂语义
- ⚠️ **中英文混合**：同时支持中英文关键词，但可能遗漏其他表达方式
- ⚠️ **优先级不明确**：if-elif链条的顺序决定了优先级，但缺乏文档说明
- ✅ **作为后备机制合理**：仅在LLM失败时使用，不是主要决策路径

### 3.2 决策逻辑流程图

```
用户输入
    │
    ▼
检查是否回顾性问题？ ──Yes──> 从历史中提取答案
    │ No
    ▼
检测文件上传？ ──Yes──> 执行文件预分析
    │ No/After
    ▼
Planning (LLM)
    │
    ├─> 成功 ──> 解析JSON
    │            │
    │            ├─> 格式正确？ ──Yes──> 继续
    │            │      │ No
    │            │      └──> 尝试修复JSON
    │            │
    │            └─> 参数合并（从上下文）
    │
    └─> 失败 ──> 关键词推断 ──> 优雅降级
    │
    ▼
参数验证 (Validator)
    │
    ├─> 通过 ──> 继续
    │
    └─> 失败 ──> 反思修复 (Reflector)
                  │
                  ├─> 修复成功 ──> 继续
                  └─> 修复失败 ──> 优雅降级
    │
    ▼
需要追问？ ──Yes──> 返回追问消息
    │ No
    ▼
执行 Skill
    │
    ▼
Skill 需要追问？ ──Yes──> 返回追问消息
    │ No
    ▼
综合回答 (Synthesis LLM)
    │
    ▼
保存上下文 + 学习记录
    │
    ▼
返回用户
```

**复杂度分析**：
- 🔴 **决策路径过多**：至少7个分支点
- 🔴 **多层验证**：Planning验证 → 参数验证 → 反思修复，增加延迟
- 🟡 **两次追问检查**：Agent层追问 + Skill层追问，可能造成混淆
- ✅ **完善的降级机制**：每个失败点都有后备方案

### 3.3 参数提取方式

**混合模式**：LLM提取 + 上下文合并 + 验证修正

#### 1. LLM提取 (主要方式)
- 位置：`agent/core.py:_plan()`
- 方法：通过 System Prompt 指导 LLM 输出 JSON 格式参数
- 优点：灵活，能理解自然语言
- 缺点：可能输出格式错误或遗漏参数

#### 2. 上下文合并 (增量对话支持)
- 位置：`agent/context.py:merge_params()`
- 方法：从历史 Skill 执行中提取参数，与新参数合并
- 复杂度：⚠️ **高** - 包含大量特殊情况处理

```python
# context.py:103-180 参数合并逻辑
def merge_params(self, skill_name: str, new_params: Dict) -> Dict:
    # 1. 获取历史参数
    historical = self._get_last_params(skill_name)

    # 2. 深度合并
    merged = self._deep_merge(historical, new_params)

    # 3. 特殊处理：宏观排放的增量更新
    if skill_name == "calculate_macro_emission":
        # 更新 links_data 中的单个字段
        if "traffic_flow_vph" in new_params:
            merged["links_data"][0]["traffic_flow_vph"] = new_params["traffic_flow_vph"]
        # ... 更多特殊情况

    return merged
```

**问题**：
- ⚠️ **特殊情况过多**：宏观排放有专门的合并逻辑（45行代码）
- ⚠️ **类型检查复杂**：需要区分简单字段更新 vs 完整数据替换
- ⚠️ **难以扩展**：新增 Skill 可能需要添加新的合并逻辑

#### 3. 验证修正 (Validator)
- 位置：`agent/validator.py`
- 方法：Schema验证 + 字段名自动修正 + 语义验证
- 修正规则：20+ 字段名映射（如 `length_km` → `link_length_km`）

**问题**：
- ⚠️ **修正规则硬编码**：`FIELD_CORRECTIONS` 字典包含20+映射
- ⚠️ **与 LLM 职责重叠**：LLM 应该输出正确字段名，但 Validator 又做了一次修正
- ✅ **作为安全网合理**：防止 LLM 输出错误

### 3.4 上下文管理

**实现**：`agent/context.py` - ConversationContext 类

**核心功能**：
1. **Turn 管理**：保存每轮对话的输入、输出、Skill执行记录
2. **参数记忆**：记录最近成功的 Skill 参数，用于增量对话
3. **上下文压缩**：保留最近N轮完整对话，早期对话压缩为摘要（未实现）
4. **文件分析缓存**：保存文件预分析结果

**数据结构**：
```python
class ConversationTurn:
    user_input: str
    assistant_response: str
    understanding: str
    skill_executions: List[SkillExecution]
    timestamp: datetime

class SkillExecution:
    skill_name: str
    parameters: Dict
    result: Dict
    success: bool
    error_message: Optional[str]
```

**问题**：
- 🟡 **上下文压缩未实现**：代码中有 `max_turns=20` 但没有实际压缩逻辑
- 🟡 **参数合并逻辑复杂**：`merge_params()` 方法180行，包含大量特殊情况
- ✅ **结构清晰**：Turn 和 SkillExecution 的分离设计合理

### 3.5 发现的问题

#### 🔴 严重问题

1. **多层验证增加延迟**
   - Planning → Validator → Reflector → Skill验证
   - 每层都可能调用 LLM，累积延迟
   - 建议：合并验证逻辑，减少 LLM 调用次数

2. **参数合并逻辑过于复杂**
   - 宏观排放有45行专门的合并代码
   - 难以维护和扩展
   - 建议：简化合并逻辑，使用统一的合并策略

#### 🟡 中等问题

3. **关键词推断过于简单**
   - 仅作为后备机制，但实现过于粗糙
   - 建议：要么增强关键词匹配（使用语义相似度），要么完全依赖 LLM

4. **两次追问检查**
   - Agent层和Skill层都可能触发追问
   - 可能造成用户困惑
   - 建议：统一追问逻辑，由Agent层统一处理

#### 🟢 轻微问题

5. **上下文压缩未实现**
   - 长对话可能导致上下文过长
   - 建议：实现上下文压缩或滑动窗口机制

---

## 4. Skill 层诊断

### 4.1 Skill 清单与职责

| Skill名称 | 文件位置 | 代码行数 | 职责 | 复杂度 |
|----------|---------|---------|------|--------|
| **query_emission_factors** | `skills/emission_factors/` | ~400 | 查询MOVES排放因子曲线 | 中 |
| **calculate_micro_emission** | `skills/micro_emission/` | ~800 | 基于轨迹计算排放(VSP方法) | 高 |
| **calculate_macro_emission** | `skills/macro_emission/` | ~700 | 基于路段计算排放(MOVES-Matrix) | 高 |
| **query_knowledge** | `skills/knowledge/` | ~300 | 向量检索知识库 | 低 |
| **通用工具** | `skills/common/` | ~500 | 文件分析、列名映射 | 中 |

**总计**：4个核心Skill + 2个通用工具，约2,700行代码

### 4.2 代码重复分析

#### 重复1：车型映射表

**位置**：
- `shared/standardizer/constants.py:1-15` (13种车型 + 别名)
- `skills/macro_emission/excel_handler.py:41-85` (完全相同的13种车型)
- `skills/emission_factors/calculator.py:19-33` (车型到SourceType ID映射)

**问题**：
- 🔴 **三处维护**：新增车型需要修改3个文件
- 🔴 **不一致风险**：可能出现某处更新了，其他地方未更新

**建议**：
- 统一使用 `shared/standardizer/constants.py` 中的定义
- 其他文件通过 import 引用

#### 重复2：列名模式

**位置**：
- `agent/prompts/system.py:227-240` (Prompt中的列名示例)
- `skills/common/file_analyzer.py:17-30` (关键词列表)
- `skills/micro_emission/excel_handler.py:26-29` (列名列表)
- `skills/macro_emission/excel_handler.py:26-37` (列名列表)

**问题**：
- 🔴 **四处维护**：新增列名变体需要修改4个地方
- 🟡 **部分重叠**：不同文件中的列名列表有重叠但不完全相同

**建议**：
- 建立统一的列名配置文件（如 `shared/column_patterns.py`）
- 从 Prompt 中移除列名示例，改为引用配置

#### 重复3：默认值

**位置**：
- `agent/prompts/system.py` (Prompt中提到默认值)
- `skills/macro_emission/excel_handler.py:88-94` (DEFAULT_FLEET_MIX)
- `skills/micro_emission/skill.py` (默认污染物列表)

**问题**：
- 🟡 **文档与代码不同步**：Prompt中的默认值可能与代码不一致

**建议**：
- 将默认值提取到配置文件
- Prompt 中动态引用配置

### 4.3 耦合度评估

#### Skill 与 Agent 的耦合

**耦合点**：
1. **参数格式约定**：Skill 期望特定的参数名和类型
2. **追问机制**：Skill 返回特殊格式表示需要追问
3. **文件路径传递**：Agent 负责文件上传，Skill 接收路径

**耦合度**：🟡 **中等**
- ✅ 通过 SkillResult 统一返回格式
- ✅ Skill 不直接调用 Agent 方法
- ⚠️ 参数格式约定较强，修改需要同步更新 Prompt

#### Skill 与 Standardizer 的耦合

**耦合点**：
1. 所有 Skill 都依赖 Standardizer 进行车型/污染物标准化
2. Standardizer 可能调用 LLM 或本地模型

**耦合度**：✅ **低**
- Standardizer 是独立模块，接口清晰
- 支持多种实现（LLM API / 本地模型）

#### Skill 之间的耦合

**耦合度**：✅ **极低**
- 各 Skill 完全独立，无相互调用
- 共享工具通过 `skills/common/` 提供

### 4.4 发现的问题

#### 🔴 严重问题

1. **车型映射表重复**
   - 三处定义，维护成本高
   - 建议：统一到 `shared/standardizer/constants.py`

2. **列名模式分散**
   - 四处定义，容易不一致
   - 建议：建立统一配置文件

#### 🟡 中等问题

3. **Excel处理逻辑重复**
   - `micro_emission/excel_handler.py` 和 `macro_emission/excel_handler.py` 有相似的文件读取、列名查找逻辑
   - 建议：提取公共基类或工具函数

4. **硬编码的MOVES数据路径**
   - 数据文件路径硬编码在 Calculator 中
   - 建议：使用配置文件管理数据路径

#### 🟢 轻微问题

5. **缺少单元测试**
   - Skill 层缺少系统的单元测试
   - 建议：为每个 Skill 编写测试用例

---

## 5. 硬编码规则全览

### 5.1 按位置分类

| 位置 | 规则数量 | 类型 |
|------|----------|------|
| `shared/standardizer/constants.py` | 78 | VSP参数、常量映射 |
| `agent/prompts/system.py` | 100+ | 列名映射、格式规则、示例 |
| `skills/common/file_analyzer.py` | 40+ | 关键词列表、列名模式 |
| `agent/validator.py` | 25+ | 字段校正、参数模式 |
| `skills/emission_factors/calculator.py` | 30+ | 业务映射 |
| `skills/macro_emission/excel_handler.py` | 50+ | 车型别名、默认车队 |
| `skills/micro_emission/excel_handler.py` | 20+ | 列名映射 |

### 5.2 按类型分类

| 类型 | 数量 | 示例 |
|------|------|------|
| 车辆类型映射 | 30+ | "小汽车" → "Passenger Car" |
| 污染物映射 | 15+ | "氮氧" → "NOx" |
| 列名映射 | 50+ | "速度" → "speed_kph" |
| 季节映射 | 12 | "春季" → 4 |
| 路型映射 | 8 | "快速路" → 4 |
| 字段校正 | 25+ | length_km → link_length_km |
| 参数简写 | 20+ | "1000辆" → traffic_flow_vph: 1000 |

### 5.3 按严重程度分类

| 严重程度 | 数量 | 描述 |
|----------|------|------|
| 关键(业务逻辑) | 50+ | 车辆/污染物标准化、VSP参数 |
| 中等(UX边界) | 35+ | 字段名校正、列名同义词 |
| 低(便利性) | 60+ | 参数简写、季节变化、路型别名 |

### 5.4 完整规则清单表格

#### 5.4.1 车辆类型映射 (13种MOVES标准)

| 标准名 | 中文别名 | 代码 | 位置 |
|--------|----------|------|------|
| Motorcycle | 摩托车 | 11 | constants.py |
| Passenger Car | 小汽车、乘用车、轿车 | 21 | constants.py |
| Passenger Truck | 客车、皮卡、SUV | 31 | constants.py |
| Light Commercial Truck | 轻型货车、小货车 | 32 | constants.py |
| Single Unit Short-Haul Truck | 短途卡车 | 41 | constants.py |
| Single Unit Long-Haul Truck | 长途卡车 | 42 | constants.py |
| Combination Short-Haul Truck | 短途挂车 | 43 | constants.py |
| Combination Long-Haul Truck | 长途挂车 | 44 | constants.py |
| Bus | 公交车、巴士 | 51 | constants.py |
| School Bus | 校车 | 52 | constants.py |
| Refuse Truck | 垃圾车 | 61 | constants.py |
| Motor Home | 房车 | 62 | constants.py |
| Motor Home Pulling | 拖挂房车 | 63 | constants.py |

#### 5.4.2 污染物映射 (11种)

| 污染物 | ID | 中文别名 |
|--------|-----|----------|
| THC | 1 | 碳氢化合物 |
| CO | 2 | 一氧化碳 |
| NOx | 3 | 氮氧化物、氮氧 |
| VOC | 5 | 挥发性有机物 |
| SO2 | 30 | 二氧化硫 |
| NH3 | 35 | 氨 |
| NMHC | 79 | 非甲烷碳氢 |
| CO2 | 90 | 二氧化碳 |
| Energy | 91 | 能耗 |
| PM10 | 100 | 颗粒物PM10 |
| PM2.5 | 110 | 颗粒物PM2.5、PM2.5 |

#### 5.4.3 列名同义词映射

**微观排放必需列**:
| 标准列名 | 同义词列表 | 数量 |
|----------|------------|------|
| speed_kph | speed, speed_kmh, speed, 速度, 车速, velocity, v | 8 |
| time | t, time, time_sec, 时间, timestamp, 秒 | 7 |
| acceleration | acc, acceleration, acceleration_mps2, 加速度, accel, a | 6 |
| grade | grade_pct, grade, 坡度, slope, gradient | 5 |

**宏观排放必需列**:
| 标准列名 | 同义词列表 | 数量 |
|----------|------------|------|
| link_length_km | length_km, length, 长度, 距离, distance, len | 8 |
| traffic_flow_vph | flow_vph, flow, 流量, 交通量, volume, vph | 7 |
| avg_speed_kph | speed_kph, speed, 速度, 平均速度, avg_speed | 6 |
| link_id | link, segment, road, 路段, id, 编号 | 7 |

---

## 6. 数据流分析

### 6.1 主要数据流图

```
用户输入 (文本 + 可选文件)
    │
    ▼
┌─────────────────────────┐
│  文件预分析              │ ← Excel/CSV → DataFrame
│  (file_analyzer.py)     │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  计划生成 (Planning)     │ ← LLM生成JSON计划
│  (core.py:_plan())      │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  参数丰富化              │ ← 与历史合并
│  (context.py:merge_params)│
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  验证 (Validator)        │ ← 字段+类型+语义检查
│  (validator.py)         │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  反思 (Reflector)        │ ← 修复错误(如需要)
│  (reflector.py)         │
└──────────┬──────────────┘
           │
           ▼
┌─────────────────────────┐
│  执行 (Skill.execute())  │
└──────────┬──────────────┘
           │
           ├─→ 标准化 (车辆/污染物)
           ├─→ 文件读取 (列映射)
           ├─→ 计算 (VSP/MOVES)
           └─→ 结果生成
           │
           ▼
┌─────────────────────────┐
│  综合 (Synthesis)        │ ← 生成自然语言响应
│  (synthesis.py)         │
└──────────┬──────────────┘
           │
           ▼
      响应用户
```

### 6.2 数据转换点

| 转换点 | 输入 | 输出 | 位置 |
|--------|------|------|------|
| 文件分析 | Excel/CSV | DataFrame + 任务类型 | file_analyzer.py |
| 列识别 | 原始列名 | 标准列名 | file_analyzer.py |
| 计划生成 | 用户输入 | JSON计划 | core.py:325-372 |
| 字段校正 | 原始JSON | 校正JSON | validator.py:209-232 |
| 标准化 | 用户术语 | 标准术语 | standardizer/*.py |
| 列映射 | 原始列 | 标准列 | column_mapper.py |

### 6.3 潜在问题点

| 点 | 问题 | 影响 | 建议 |
|----|------|------|------|
| 文件预分析 | 基于关键词的类型检测可能失败 | 错误分类文件 | 增加LLM辅助判断 |
| 参数合并 | 复杂嵌套结构逻辑 | 令人困惑的更新 | 简化合并策略 |
| 列映射 | LLM回退可能丢失数据 | 静默失败 | 增加警告机制 |
| 标准化 | 多种匹配策略 | 不一致行为 | 统一匹配策略 |

---

## 7. 文件健康度分析

### 7.1 冗余文件清单

| 文件 | 重复内容 | 建议 |
|------|----------|------|
| `shared/standardizer/vehicle.py` | 车辆映射重复 | 保留，作为标准来源 |
| `shared/standardizer/pollutant.py` | 污染物映射重复 | 保留，作为标准来源 |
| `skills/micro_emission/excel_handler.py` | Excel处理逻辑 | 考虑提取到公共模块 |
| `skills/macro_emission/excel_handler.py` | Excel处理逻辑 | 考虑提取到公共模块 |

### 7.2 未使用文件清单

| 文件 | 状态 | 建议 |
|------|------|------|
| `data/sessions/history/*.json` | 会话历史 | 保留用于学习 |
| `__pycache__/*.pyc` | Python缓存 | 可清理 |
| `*.backup` | 备份文件 | 可清理 |

### 7.3 文档同步状态

| 文档 | 状态 | 说明 |
|------|------|------|
| README.md | 同步 | 基本使用说明 |
| ARCHITECTURE.md | 同步 | 架构设计 |
| docs/Claude_Design/*.md | 新增 | 设计文档 |

### 7.4 建议清理的文件

| 文件 | 原因 |
|------|------|
| `__pycache__/*.pyc` | Python缓存文件，可由.gitignore忽略 |
| `*.backup` | 备份文件，应使用版本控制 |
| `docs/Claude_Design/*.md` | 设计文档，部分可归档 |

---

## 8. 与 ChatGPT 体验的差距分析

### 8.1 当前交互模式

**优势**:
- 特定领域知识（排放计算）
- 智能文件上传分析
- 多轮对话上下文
- 可视化输出（图表、表格）

**劣势**:
- 严重依赖结构化提示词
- 提示词中有大量错误示例（显示脆弱性）
- 多层验证机制（暗示LLM不可靠）
- 到处都有回退机制

### 8.2 期望交互模式

**ChatGPT特点**:
- 简洁的系统提示词（估计<100行）
- 最少的硬编码规则
- 自然对话流程
- LLM驱动的理解

### 8.3 差距识别

| 方面 | 当前状态 | ChatGPT级别 | 差距 |
|------|----------|-------------|------|
| 提示词大小 | 617行 | <100行 | 6倍差距 |
| 硬规则数量 | 107+映射 | 最小化 | 严重 |
| 验证层数 | 3层 | 1-2层 | 过度 |
| 错误恢复 | 反思+回退 | 自然重新提示 | 复杂 |
| 参数提取 | 模式驱动 | 自然理解 | 僵化 |

### 8.4 改进路径

1. **第一阶段**: 压缩提示词，移除静态示例
2. **第二阶段**: 引入多代理架构，分散职责
3. **第三阶段**: 学习驱动优化，自动模式发现

---

## 9. 架构优化建议

### 9.1 短期优化（可立即执行）

#### 9.1.1 压缩系统提示词

**目标**: 617 → ~200 行

**措施**:
1. 将示例移至独立参考文档
2. 使用动态few-shot替代硬编码示例
3. 移除重复的规则说明

**预期效果**:
- Token消耗减少50%
- LLM泛化能力提升
- 维护成本降低

#### 9.1.2 整合映射

**目标**: 单一数据源

**措施**:
1. `constants.py` 作为车辆/污染物类型的唯一来源
2. 移除其他文件中的重复映射
3. 统一导入路径

**代码示例**:
```python
# 所有模块统一导入
from shared.standardizer.constants import (
    VEHICLE_TYPE_MAPPING,
    POLLUTANT_MAPPING,
    SEASON_CODES
)
```

#### 9.1.3 简化验证

**目标**: 3次验证 → 2次

**措施**:
1. 合并字段校正与验证
2. 移除重复检查
3. 优化验证顺序

### 9.2 中期重构（需要2-3周）

#### 9.2.1 动态提示词构建

**设计**:
```python
def build_system_prompt(task_type: str) -> str:
    """根据任务类型动态构建提示词"""
    base_prompt = get_base_prompt()  # 核心规则
    examples = load_examples(task_type)  # 相关示例
    return f"{base_prompt}\n\n{examples}"
```

**预期效果**:
- 提示词大小减少50%
- 只包含任务相关内容
- 更好的LLM理解

#### 9.2.2 提高LLM可靠性

**措施**:
1. 温度调优
2. 结构化输出强制
3. 减少对反思层的依赖

#### 9.2.3 文件处理重构

**目标**: 统一的文件处理管道

**设计**:
```
文件上传
    ↓
统一预处理器
    ↓
类型检测器
    ↓
列名映射器
    ↓
标准化数据
```

### 9.3 长期演进（架构级改动）

#### 9.3.1 多代理架构

**设计**:
```
用户输入
    ↓
┌─────────────────┐
│  协调代理        │ ← 轻量级，任务路由
└────────┬────────┘
         │
    ┌────┴────┬────────┬────────┐
    │         │        │        │
    ▼         ▼        ▼        ▼
┌────────┐ ┌────────┐ ┌────────┐ ┌────────┐
│规划代理│ │验证代理│ │执行代理│ │综合代理│
└────────┘ └────────┘ └────────┘ └────────┘
```

**优势**:
- 每个代理专注，提示词小
- 自然代理间通信
- 更容易调试和优化

#### 9.3.2 学习驱动改进

**设计**:
```python
def auto_optimize_prompts():
    """使用Learner数据优化提示词"""
    failure_patterns = learner.analyze_failures()
    for pattern in failure_patterns:
        if pattern.frequency > threshold:
            add_rule_to_prompt(pattern.rule)
```

#### 9.3.3 工具使用替代规则

**当前**: 硬编码规则
**目标**: 定义工具（函数）

```python
# 当前: 硬编码列名映射
MICRO_KEYWORDS = {"speed": ["speed", "速度", ...]}

# 未来: 工具定义
@tool
def map_column_name(raw_name: str, task_type: str) -> str:
    """智能列名映射"""
    # LLM理解工具描述，自动使用
```

---

## 10. 优先级排序

### 影响程度 vs 实施难度矩阵

```
高影响
    │
    │  [1]      [2]
    │  压缩提示  多代理架构
    │
    │           [3]
    │           动态提示词
    │
低影响
    │  [4]      [5]
    │  整合映射  文件处理重构
    │
    └────────────────────►
    低难度          高难度
```

| 优先级 | 任务 | 影响 | 难度 | 预期收益 |
|--------|------|------|------|----------|
| 1 | 压缩系统提示词 | 高 | 低 | Token-50%, 维护↓ |
| 2 | 多代理架构 | 高 | 高 | 可扩展性↑ |
| 3 | 动态提示词 | 中 | 中 | 灵活性↑ |
| 4 | 整合映射 | 低 | 低 | 代码质量↑ |
| 5 | 文件处理重构 | 中 | 中 | 一致性↑ |

---

## 附录

### A. 完整文件树

```
emission_agent/
├── .env
├── .env.example
├── README.md
├── ARCHITECTURE.md
├── ARCHITECTURE_DIAGNOSIS_REPORT.md
├── config.py
├── main.py
├── requirements.txt
├── agent/
│   ├── __init__.py
│   ├── cache.py
│   ├── context.py
│   ├── core.py
│   ├── learner.py
│   ├── monitor.py
│   ├── prompts/
│   │   ├── synthesis.py
│   │   └── system.py
│   ├── reflector.py
│   └── validator.py
├── api/
│   ├── main.py
│   ├── models.py
│   ├── routes.py
│   └── session.py
├── data/
│   ├── collection/
│   │   ├── pollutant.jsonl
│   │   └── vehicle_type.jsonl
│   ├── learning/
│   │   └── cases.jsonl
│   └── sessions/
│       ├── history/
│       └── sessions_meta.json
├── llm/
│   ├── client.py
│   └── data_collector.py
├── outputs/
├── shared/
│   └── standardizer/
│       ├── constants.py
│       ├── local_client.py
│       ├── pollutant.py
│       └── vehicle.py
├── skills/
│   ├── base.py
│   ├── common/
│   │   ├── column_mapper.py
│   │   └── file_analyzer.py
│   ├── emission_factors/
│   │   ├── calculator.py
│   │   └── skill.py
│   ├── knowledge/
│   │   ├── retriever.py
│   │   └── skill.py
│   ├── macro_emission/
│   │   ├── calculator.py
│   │   ├── excel_handler.py
│   │   └── skill.py
│   ├── micro_emission/
│   │   ├── calculator.py
│   │   ├── excel_handler.py
│   │   └── skill.py
│   └── registry.py
├── web/
│   ├── index.html
│   └── app.js
└── docs/
    └── Claude_Design/
```

### B. 所有 Prompt 原文摘要

#### B.1 主系统提示词摘要

**文件**: `agent/prompts/system.py` (617行)

**核心结构**:
```python
SYSTEM_PROMPT = """
# 角色定义
你是一个智能排放计算助手...

# 可用技能
1. query_emission_factors - 查询排放因子
2. calculate_micro_emission - 计算微观排放
3. calculate_macro_emission - 计算宏观排放
4. query_knowledge - 知识库查询

# 重要原则
- 重视对话历史
- 检查必需参数
- 不要使用query_knowledge查询文件格式！

# 文件处理规则
[40行硬编码列名规则]

# 澄清规则
[41行模板规则]

# 错误示例
[53行错误处理]

# 详细示例
[102行8个场景示例]

# 增量对话支持
[309行对话示例]

# 参数简写
[21行映射规则]

# 错误处理
[19行错误恢复]
"""
```

### C. 硬编码规则详细清单

#### C.1 字段校正规则 (validator.py)

```python
FIELD_CORRECTIONS = {
    # 微观排放字段
    "speed": "speed_kph",
    "acceleration": "acceleration_mps2",
    "trajectory": "trajectory_data",
    "input_file": "trajectory_data",

    # 宏观排放字段
    "length": "link_length_km",
    "flow": "traffic_flow_vph",
    "links": "links_data",
    "fleet_mix": "default_fleet_mix",

    # 排放因子字段
    "vehicle": "vehicle_type",
    "pollutant": "pollutants",
    "year": "model_year",
}
```

#### C.2 参数简写识别规则

```python
# 污染物简写
{"NOx", "氮氧", "氮氧化物"} → "NOx"
{"PM2.5", "颗粒物"} → "PM2.5"
{"CO2", "二氧化碳"} → "CO2"

# 交通量简写
{"1000辆", "车流量1000", "1000车/小时"} → 1000
{"3公里", "3km", "3000米"} → 3.0
{"60码", "时速60", "60km/h"} → 60.0
```

#### C.3 回顾性问题关键词

```python
{"刚才", "刚刚", "上次", "之前", "那个", "那个数据"}
```

### D. 代码复杂度统计

| 文件 | 行数 | 圈复杂度估计 | 维护性 |
|------|------|--------------|--------|
| agent/core.py | 652 | 高 | 中 |
| agent/prompts/system.py | 617 | - | 低 |
| skills/common/file_analyzer.py | 453 | 中 | 中 |
| agent/context.py | 313 | 中 | 中 |
| agent/validator.py | 290 | 中 | 中 |
| skills/macro_emission/skill.py | 400+ | 高 | 中 |
| skills/micro_emission/skill.py | 363 | 中 | 中 |

---

## 结论

Emission Agent 系统展示了**架构良好但规则驱动严重**的LLM任务执行方法。Agent-Skill分离是合理的，但系统累积了**显著的复杂性**：

1. **庞大的系统提示词**（617行），包含大量示例和规则
2. **107+硬编码映射**用于领域概念
3. **多层验证机制**处理LLM不可靠性
4. **补丁式修复**针对特定边界情况

这表明**灵活性与可靠性之间存在张力**：
- 添加规则提高了已知案例的可靠性
- 但降低了LLM泛化到新案例的能力

**建议**: 转向**多代理架构**，使用更小、更集中的提示词和更好的工具定义，而不是带有大量示例的单一提示词。

---

**报告生成**: 2026-02-03
**分析文件数**: 25+核心文件
**总发现数**: 107+硬编码规则，20+改进领域