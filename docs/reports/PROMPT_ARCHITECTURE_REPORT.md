# EmissionAgent 提示词架构探索与优化方案报告

**日期**: 2026-03-22
**目标**: 分析当前系统提示词架构，量化瓶颈，设计按需注入的 skill 化方案

---

## 第 1 部分：现有提示词架构探索

### 1.1 系统提示词组装入口

**核心组装文件**: `core/assembler.py` — `ContextAssembler.assemble()` 方法 (L42-L121)

**组装流程**:

1. **Core prompt** (L72): 从 `config/prompts/core.yaml` 的 `system_prompt` 字段加载
2. **Tool definitions** (L76): 通过 `ConfigLoader.load_tool_definitions()` → `tools/definitions.py` 的 `TOOL_DEFINITIONS` 加载
3. **Fact memory** (L83-L90): 格式化为 `[Context from previous conversations]` 系统消息
4. **Working memory** (L94-L99): 最近 3 轮对话历史（assistant 截断到 300 字符）
5. **File context** (L103-L105): 注入到 user message 前面
6. **Current user message** (L108): 添加到 messages 末尾

**LLM 调用入口**: `core/router.py` — `_state_handle_input()` 方法 (L529-L533)
```python
response = await self.llm.chat_with_tools(
    messages=context.messages,
    tools=context.tools,
    system=context.system_prompt
)
```

**最终 messages 结构**:
| 位置 | role | 内容 |
|------|------|------|
| 1 | system | core.yaml 的 system_prompt（由 LLM client 注入） |
| 2 | system | `[Context from previous conversations]` + fact memory |
| 3-8 | user/assistant | 最近 3 轮 working memory |
| 9 | user | file_context + 当前用户消息 |

注意：`services/llm_client.py:244-245` 中 `chat_with_tools` 会将 `system` 参数作为第一条 system message 插入 `full_messages` 列表开头。

### 1.2 当前系统提示词内容分析

**来源文件**: `config/prompts/core.yaml` (L6-L73)

**内容结构**:

| 段落 | 行号 | 内容概要 | 估计字符数 |
|------|------|----------|-----------|
| 角色定义 | L7 | "你是一个智能机动车排放计算助手" | 15 |
| 能力列表 | L9-L16 | 查询排放因子、微观排放、宏观排放、文件分析 | 120 |
| 交互原则 | L18-L23 | 理解意图、友好询问、使用工具、简洁回复 | 150 |
| 澄清规则 | L25-L41 | 车辆类型确认、示例对话 | 280 |
| 历史对话 | L43-L47 | 引用历史、结合上下文 | 100 |
| 文件处理 | L49-L58 | task_type 判断、自动分析 | 250 |
| 地图可视化 | L60-L66 | render_spatial_map 使用规则 | 200 |
| 重要提示 | L68-L72 | 工具描述、参数标准化 | 80 |

**总计**: 1192 字符，~596 tokens

**关键发现**: 系统提示词本身并不长（仅 596 tokens），问题出在 **工具 schema 定义**。

### 1.3 工具 Schema 注入方式

**加载路径**: `services/config_loader.py:64-73` → `tools/definitions.py`

**各工具 schema 大小**:

| 工具名 | description (chars) | parameters (chars) | 总计 (chars) |
|--------|--------------------|--------------------|-------------|
| query_emission_factors | 76 | 875 | 951 |
| calculate_micro_emission | 115 | 896 | 1,011 |
| calculate_macro_emission | 106 | 739 | 845 |
| analyze_file | 73 | 140 | 213 |
| query_knowledge | 82 | 421 | 503 |
| **calculate_dispersion** | **1,094** | **2,709** | **3,803** |
| **analyze_hotspots** | **627** | **1,191** | **1,818** |
| render_spatial_map | 188 | 580 | 768 |

**全部工具定义 JSON 总计**: 10,722 chars → **~5,361 tokens**

**关键发现**:
- `calculate_dispersion` 单个工具就占 3,803 chars (~1,954 tokens)，超过系统提示词的 3 倍
- `analyze_hotspots` 占 1,818 chars (~960 tokens)
- 这两个工具合计占全部工具定义的 52%
- `calculate_dispersion` 的 description 长达 1,094 字符，其中包含了大段 LLM 行为指令（气象条件询问、coverage 警告等）

### 1.4 量化当前提示词总长度

**典型场景：排放完成后请求扩散分析**

| 组件 | 字符数 | 估计 tokens |
|------|--------|------------|
| System prompt (core.yaml) | 1,192 | ~596 |
| Tool definitions (8 tools, JSON) | 10,738 | ~5,369 |
| Fact memory (含上轮排放结果) | ~471 | ~235 |
| Working memory (3 turns, truncated) | ~156 | ~78 |
| File context | ~205 | ~102 |
| **总计** | **~12,762** | **~6,381** |

**Qwen-Plus 模型配置** (`config.py:14`): `max_tokens = 8000` (output limit)
- Qwen-Plus context window: 131,072 tokens
- `ContextAssembler.MAX_CONTEXT_TOKENS = 6000` (L32 的保守限制)

**关键发现**: 总上下文 ~6,381 tokens 已接近 assembler 的保守限制 6,000 tokens。工具 schema 占了总上下文的 **84%**。

### 1.5 Router 的意图判断逻辑

**工具选择机制**: 完全依赖 LLM 的 function calling（`tool_choice="auto"`），无预处理意图检测。

- `services/llm_client.py:253`: `tool_choice="auto"` — LLM 自己决定调哪个工具
- Router 不做任何意图预检测或关键词匹配
- Router 在 `_state_handle_grounded()` (L577-L626) 做参数完整性检查和依赖检查
- `core/tool_dependencies.py`: 定义了工具依赖图（如 `calculate_dispersion` 需要 `emission_result`）

**后续引导机制**: 有限
- `_state_handle_executing()` 尾部 (L946-L974): 检测是否有空间数据但未可视化，会添加可视化建议
- 但**没有**"排放完成后引导扩散"或"扩散完成后引导热点分析"的引导机制
- 没有按需加载提示词的基础设施

**关键发现**: 当前架构中，所有行为指令都必须放在系统提示词或工具 description 中，没有按需注入的机制。

### 1.6 记忆和上下文注入

**Fact memory** (`core/assembler.py:123-170`):
- 典型大小: ~235 tokens
- 包含: 车型、污染物、年份、活跃文件、上轮工具名/摘要/快照

**Working memory** (`core/assembler.py:172-211`):
- 最多 3 轮，assistant 截断到 300 字符
- 典型大小: ~78 tokens（中文短对话）

**File context** (`core/assembler.py:213-233`):
- 注入到 user message 前面
- 典型大小: ~102 tokens

**记忆合计**: ~415 tokens，占总上下文的 ~6.5%

---

## 第 2 部分：问题诊断

### 2.1 提示词总长度瓶颈

在"排放完成后请求扩散"场景下的 messages 列表：

```
system message (core.yaml):              596 tokens   (9.3%)
tool definitions (8 tools, JSON):      5,369 tokens  (84.1%)  ← 主要瓶颈
fact memory:                             235 tokens   (3.7%)
working memory:                           78 tokens   (1.2%)
file context + user message:             103 tokens   (1.6%)
─────────────────────────────────────────────────────────────
总计:                                  6,381 tokens  (100%)
```

虽然 6,381 tokens 远小于 Qwen-Plus 的 131K context window，但问题不在于超限，而在于**信号稀释**：

- 关键指令（如"主动询问气象条件"）被埋在 5,369 tokens 的工具 schema 中
- LLM 注意力被 8 个工具的详细参数定义分散
- 当前轮实际需要的只是 `calculate_dispersion` 一个工具，但 LLM 必须"阅读"全部 8 个

### 2.2 关键指令被淹没

| 关键指令 | 位置 | 问题 |
|----------|------|------|
| "如果用户未指定气象条件，应告知默认条件并询问" | `tools/definitions.py:176-212`，在 `calculate_dispersion` 的 description 第 548 字符处 | 埋在 1,094 字符的 description 中段偏后 |
| "排放完成后建议扩散" | **不存在** | 系统提示词和工具 description 中均无此引导 |
| "coverage 覆盖度解释" | `tools/definitions.py:180-183`，在 dispersion description 中 | 同上，埋在长 description 中 |

**关键发现**:
1. **气象条件询问指令**位于 dispersion 工具 description 的第 548/1094 字符处，前面有大段模型说明
2. **排放→扩散引导**完全缺失，系统提示词中没有任何工具链式推荐机制
3. 系统提示词中关于地图可视化的引导 (L60-L66) 可以部分起到"计算→可视化"的引导作用，但没有"排放→扩散"的类似引导

### 2.3 工具 Schema 冗余分析

**典型场景下的工具需求**:

| 场景 | 实际需要的工具 | 可节省的 schema |
|------|----------------|----------------|
| 排放计算 | calculate_macro_emission, analyze_file | 其他 6 个工具 ~3,508 tokens |
| 扩散分析 | calculate_dispersion, render_spatial_map | 其他 6 个工具 ~2,427 tokens |
| 排放因子查询 | query_emission_factors | 其他 7 个工具 ~4,886 tokens |
| 热点分析 | analyze_hotspots, render_spatial_map | 其他 6 个工具 ~3,921 tokens |

**如果只注入当前场景需要的 2-3 个工具**:
- 排放场景: 从 5,369 → ~1,861 tokens，节省 **65%**
- 扩散场景: 从 5,369 → ~2,942 tokens，节省 **45%**

---

## 第 3 部分：优化方案设计

### 3.1 提示词分层结构

#### Layer 1: Core System Prompt（常驻，目标 < 800 tokens）

```yaml
# config/prompts/core_v3.yaml
system_prompt: |
  你是一个智能机动车排放计算助手。

  ## 核心规则
  1. 理解用户意图，信息不足时友好询问
  2. 使用工具获取数据，不编造数据
  3. 回复简洁清晰，突出关键结果
  4. 绝不假设车辆类型，必须先确认
  5. 用户引用历史时，结合对话上下文理解
  6. 文件上传后根据 task_type 自动选择对应工具
  7. 参数标准化由系统自动处理，传递用户原始表述即可

  ## 可用工具概览
  - query_emission_factors: 查询排放因子曲线
  - calculate_micro_emission: 微观轨迹排放计算
  - calculate_macro_emission: 宏观路段排放计算
  - calculate_dispersion: 大气扩散浓度分布计算
  - analyze_hotspots: 污染热点识别与溯源
  - render_spatial_map: 空间数据地图可视化
  - analyze_file: 分析上传文件结构
  - query_knowledge: 查询排放知识库

  {situational_prompt}
```

**预计**: ~400 tokens（不含 situational_prompt 占位）

**与当前版本的区别**:
- 删除了示例对话（"请问这是什么类型的车辆？"）
- 删除了地图可视化详细规则（移入 spatial_skill）
- 删除了文件处理详细规则（移入 file_upload_guide）
- 添加了工具概览（一句话描述，不含参数）
- 添加了 `{situational_prompt}` 占位符

#### Layer 2: Tool Skills（按需注入，每个 200-400 tokens）

当意图检测确定需要某个工具时，将该工具的完整 schema + 使用指南注入。其他工具仅保留 Layer 1 中的一句话概览。

#### Layer 3: Situational Prompts（动态生成，100-200 tokens）

根据 `fact_memory.last_tool_name` 和当前对话状态动态生成短提示，填入 `{situational_prompt}` 占位。

### 3.2 Skill 文件设计

```
config/skills/
├── dispersion_skill.yaml
├── hotspot_skill.yaml
├── emission_skill.yaml
├── spatial_skill.yaml
├── post_emission_guide.yaml
├── post_dispersion_guide.yaml
├── file_upload_guide.yaml
└── meteorology_guide.yaml
```

#### dispersion_skill.yaml
- **注入时机**: 用户消息含"扩散/浓度/dispersion/concentration"，或 last_tool_name 为 calculate_macro_emission 且用户请求下一步
- **核心指令**:
  1. 扩散需要先有排放结果（emission_result），如无则先引导做排放
  2. 如果用户未指定气象条件，**必须**告知默认值并询问是否调整
  3. 可以用 preset + 单参数覆盖的组合方式
  4. 结果的 coverage 评估要解释给用户
  5. 完成后建议做热点分析或地图可视化
- **包含**: `calculate_dispersion` 的完整 tool schema
- **预计**: ~400 tokens（skill 指令） + ~1,954 tokens（tool schema）

#### hotspot_skill.yaml
- **注入时机**: 用户消息含"热点/hotspot"，或 last_tool_name 为 calculate_dispersion
- **核心指令**:
  1. 需要先有扩散结果
  2. 默认用 percentile 方法（top 5%），可调整
  3. 解释 source_attribution 结果：哪些路段贡献最大
  4. 完成后建议可视化
- **包含**: `analyze_hotspots` 的完整 tool schema
- **预计**: ~200 tokens + ~960 tokens

#### emission_skill.yaml
- **注入时机**: 用户消息含"排放/emission/计算"，或 file_context.task_type 为 micro/macro_emission
- **核心指令**:
  1. 根据 task_type 自动选择 micro 或 macro
  2. micro 需要 vehicle_type，macro 有默认 fleet_mix
  3. 计算完成后，如有空间数据，建议可视化或扩散分析
- **包含**: `calculate_micro_emission` 和 `calculate_macro_emission` 的完整 schema
- **预计**: ~200 tokens + ~1,400 tokens

#### spatial_skill.yaml
- **注入时机**: 用户消息含"地图/可视化/visualization/map"
- **核心指令**:
  1. 使用 data_source="last_result" 获取上一步数据
  2. 自动检测 layer_type
  3. 如无前序结果，告知用户需要先做计算
- **包含**: `render_spatial_map` 的完整 schema
- **预计**: ~100 tokens + ~384 tokens

#### post_emission_guide.yaml
- **注入时机**: `last_tool_name == "calculate_macro_emission"` 且当前消息无明确指令
- **核心指令**:
  ```
  上一步完成了路段排放计算。你可以建议用户：
  1. 在地图上可视化排放分布（render_spatial_map）
  2. 进行大气扩散分析，了解污染物浓度分布（calculate_dispersion）
  3. 调整参数重新计算
  用自然的语气提及这些选项，不要生硬列举。
  ```
- **预计**: ~100 tokens

#### post_dispersion_guide.yaml
- **注入时机**: `last_tool_name == "calculate_dispersion"`
- **核心指令**:
  ```
  上一步完成了扩散分析。你可以建议用户：
  1. 识别污染热点区域（analyze_hotspots）
  2. 在地图上查看浓度分布（render_spatial_map）
  3. 调整气象条件重新计算
  如果 coverage 评估有警告，主动解释其含义。
  ```
- **预计**: ~100 tokens

#### file_upload_guide.yaml
- **注入时机**: `file_context` 存在
- **核心指令**:
  ```
  用户上传了文件。task_type 字段说明：
  - "micro_emission": 微观轨迹数据，用 calculate_micro_emission
  - "macro_emission": 宏观路段数据，用 calculate_macro_emission
  - "unknown": 需要询问用户
  如果 task_type 已明确，直接使用对应工具，不要再问。
  ```
- **预计**: ~100 tokens

#### meteorology_guide.yaml
- **注入时机**: 用户消息含气象关键词，或 dispersion_skill 激活时自动附带
- **核心指令**:
  ```
  气象条件对扩散结果影响极大（静风可产生 5x 浓度差异）。
  可用预设：urban_summer_day, urban_summer_night, urban_winter_day,
  urban_winter_night, windy_neutral, calm_stable
  可以用 preset + 单参数覆盖。
  如果用户未指定，告知默认值并询问。
  ```
- **预计**: ~150 tokens

### 3.3 工具 Schema 精简方案

#### Overview 版本（Layer 1 常驻）

不通过 `tools` 参数传递，而是直接写在系统提示词中（见 3.1 的"可用工具概览"）。这样 LLM 知道有哪些工具可用，但不会被详细参数分散注意力。

#### Full 版本（Layer 2 按需注入）

当某个 skill 被激活时，只将对应工具的完整 schema 注入到 `tools` 参数中。

**示例 — 扩散分析场景**:

| 注入方式 | tools 参数包含 | 总 schema tokens |
|---------|---------------|-----------------|
| 当前（全量） | 8 个完整 schema | ~5,369 |
| 优化后 | calculate_dispersion + render_spatial_map | ~2,338 |
| **节省** | | **56%** |

### 3.4 注入逻辑设计

#### 改造方案: `core/skill_injector.py`（新文件）

```python
"""
Skill-based prompt injector.
Determines which skills and tool schemas to inject based on conversation state.
"""
import yaml
import logging
from pathlib import Path
from typing import List, Dict, Set, Optional

logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).parent.parent / "config" / "skills"

# Keyword-based intent detection rules
INTENT_RULES = {
    "dispersion": {
        "keywords": ["扩散", "浓度", "dispersion", "concentration", "大气"],
        "tools": ["calculate_dispersion", "render_spatial_map"],
        "skills": ["dispersion_skill", "meteorology_guide"],
    },
    "hotspot": {
        "keywords": ["热点", "hotspot", "高浓度", "溯源"],
        "tools": ["analyze_hotspots", "render_spatial_map"],
        "skills": ["hotspot_skill"],
    },
    "emission": {
        "keywords": ["排放", "emission", "计算", "calculate"],
        "tools": ["calculate_macro_emission", "calculate_micro_emission", "analyze_file"],
        "skills": ["emission_skill"],
    },
    "visualization": {
        "keywords": ["地图", "可视化", "visualization", "map", "展示"],
        "tools": ["render_spatial_map"],
        "skills": ["spatial_skill"],
    },
    "query_ef": {
        "keywords": ["排放因子", "曲线", "emission factor"],
        "tools": ["query_emission_factors"],
        "skills": [],
    },
    "knowledge": {
        "keywords": ["知识", "标准", "法规", "什么是"],
        "tools": ["query_knowledge"],
        "skills": [],
    },
}

# Post-tool guides based on last_tool_name
POST_TOOL_GUIDES = {
    "calculate_macro_emission": "post_emission_guide",
    "calculate_micro_emission": "post_emission_guide",
    "calculate_dispersion": "post_dispersion_guide",
}


class SkillInjector:
    """Determines which skills and tool schemas to inject."""

    def __init__(self):
        self._skill_cache: Dict[str, str] = {}

    def detect_intents(
        self,
        user_message: str,
        last_tool_name: Optional[str] = None,
        file_context: Optional[Dict] = None,
    ) -> Set[str]:
        """Detect user intent from message + state. Returns set of intent keys."""
        intents = set()

        # 1. Keyword matching on user message
        msg_lower = user_message.lower()
        for intent_key, rule in INTENT_RULES.items():
            if any(kw in msg_lower for kw in rule["keywords"]):
                intents.add(intent_key)

        # 2. File context drives emission intent
        if file_context:
            task_type = file_context.get("task_type") or file_context.get("detected_type")
            if task_type in ("micro_emission", "macro_emission"):
                intents.add("emission")
            intents.add("file_upload")  # Always add file guide when file present

        # 3. If no intent detected, fall back to last_tool guidance
        if not intents and last_tool_name:
            if last_tool_name in POST_TOOL_GUIDES:
                intents.add(f"post_{last_tool_name}")

        # 4. If still no intent, inject all tools (safety net)
        if not intents:
            intents.add("_fallback_all")

        return intents

    def get_tools_for_intents(self, intents: Set[str]) -> List[str]:
        """Get tool names needed for detected intents."""
        if "_fallback_all" in intents:
            return []  # Empty = use all tools (current behavior)

        tools = set()
        for intent in intents:
            rule = INTENT_RULES.get(intent, {})
            tools.update(rule.get("tools", []))

        # Always include analyze_file and query_knowledge as lightweight defaults
        tools.update(["analyze_file", "query_knowledge"])

        return sorted(tools)

    def get_situational_prompt(
        self,
        intents: Set[str],
        last_tool_name: Optional[str] = None,
    ) -> str:
        """Build situational prompt (Layer 3) from detected intents."""
        parts = []

        # Post-tool guides
        if last_tool_name and last_tool_name in POST_TOOL_GUIDES:
            guide_name = POST_TOOL_GUIDES[last_tool_name]
            content = self._load_skill(guide_name)
            if content:
                parts.append(content)

        # Intent-specific skill content
        for intent in intents:
            rule = INTENT_RULES.get(intent, {})
            for skill_name in rule.get("skills", []):
                content = self._load_skill(skill_name)
                if content:
                    parts.append(content)

        return "\n\n".join(parts) if parts else ""

    def _load_skill(self, skill_name: str) -> Optional[str]:
        """Load skill content from YAML file with caching."""
        if skill_name in self._skill_cache:
            return self._skill_cache[skill_name]

        path = SKILL_DIR / f"{skill_name}.yaml"
        if not path.exists():
            return None

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
            content = data.get("content", "")
            self._skill_cache[skill_name] = content
            return content
        except Exception as e:
            logger.error(f"Failed to load skill {skill_name}: {e}")
            return None
```

#### 改造方案: `core/assembler.py` 修改

```python
def assemble(self, user_message, working_memory, fact_memory, file_context=None):
    # NEW: Detect intent and select skills
    injector = self.skill_injector
    intents = injector.detect_intents(
        user_message=user_message,
        last_tool_name=fact_memory.get("last_tool_name"),
        file_context=file_context,
    )

    # Layer 1: Core prompt + situational prompt
    situational = injector.get_situational_prompt(intents, fact_memory.get("last_tool_name"))
    system_prompt = self.core_prompt_template.replace("{situational_prompt}", situational)

    # Layer 2: Select tool schemas
    needed_tools = injector.get_tools_for_intents(intents)
    if needed_tools:
        tools = [t for t in self.all_tools if t["function"]["name"] in needed_tools]
    else:
        tools = self.all_tools  # Fallback: all tools

    # Rest of assembly unchanged...
```

#### 决策树

```
用户消息到达
  ├── 有文件上传？
  │   ├── 是 → 注入 file_upload_guide + emission_skill
  │   └── 否 → 继续
  ├── 消息含扩散/浓度关键词？
  │   ├── 是 → 注入 dispersion_skill + meteorology_guide
  │   └── 否 → 继续
  ├── 消息含热点关键词？
  │   ├── 是 → 注入 hotspot_skill
  │   └── 否 → 继续
  ├── 消息含排放/计算关键词？
  │   ├── 是 → 注入 emission_skill
  │   └── 否 → 继续
  ├── 消息含地图/可视化关键词？
  │   ├── 是 → 注入 spatial_skill
  │   └── 否 → 继续
  ├── 上轮工具有 post_guide？
  │   ├── 是 → 注入对应 post_guide
  │   └── 否 → 继续
  └── 无匹配？
      └── 注入全部工具（安全回退）
```

### 3.5 实施风险评估

#### 风险 1: 意图检测错误导致漏注入

**概率**: 中等
**场景**: 用户说"帮我分析一下这个数据的浓度分布"，keyword 匹配到"浓度"但实际需要的是排放后再扩散
**缓解措施**:
- **安全回退**: 如果没有匹配到任何意图，注入全部工具
- **多意图支持**: 允许同时匹配多个意图（如"排放+扩散"）
- **依赖图自动补充**: 如果注入了 dispersion 但没有 emission，且 available_results 中无 emission_result，自动补充 emission 工具
- **渐进策略**: 初期只精简 description 不删 tool schema，观察效果后再进一步

#### 风险 2: 对现有功能的兼容性

**影响**: 低
**原因**: 改造是增量式的，`_fallback_all` 保证了无匹配时等价于当前行为
**建议**: 添加一个配置开关 `enable_skill_injection`，初期默认 false

#### 风险 3: Skill 文件维护成本

**影响**: 中
**缓解**: Skill 文件是独立的 YAML，易于版本控制和 A/B 测试

#### 测试策略

1. **单元测试**: 测试 `SkillInjector.detect_intents()` 的意图匹配准确性
2. **集成测试**: 模拟完整对话流程，验证各场景下注入的 tools 和 skills 正确
3. **A/B 测试**: 同一组测试用例，对比全量注入 vs skill 注入的 LLM 输出质量
4. **回归测试**: 确保 `_fallback_all` 路径等价于当前行为

---

## 第 4 部分：快速验证实验

### 实验设计

对比两组 prompt 调用 Qwen-Plus API，观察 LLM 是否更好地遵循气象条件询问指令。

```python
#!/usr/bin/env python3
"""
Prompt Architecture A/B Test
Compare full prompt vs. skill-injected prompt for dispersion scenario.

Usage: python3 test_prompt_ab.py
"""
import json
import os
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

client = OpenAI(
    api_key=os.getenv("QWEN_API_KEY"),
    base_url=os.getenv("QWEN_BASE_URL"),
)

# === Group A: Current full prompt ===
SYSTEM_A = """你是一个智能机动车排放计算助手。

## 你的能力
你可以通过调用工具来帮助用户：
- 查询排放因子曲线
- 计算车辆轨迹排放（微观）
- 计算路段排放（宏观）
- 分析用户上传的数据文件

## 交互原则
1. 理解用户的真实意图，即使表达不完整或不规范
2. 信息不足时，友好地询问，并给出选项或建议
3. 使用工具获取数据，不要编造数据
4. 回复简洁清晰，突出关键结果

## 关于澄清
当需要更多信息时，请：
- 直接、友好地询问
- 提供选项让用户选择
- 可以给出推荐的默认选项

**特别重要：车辆类型确认**
- 绝不假设或猜测车辆类型
- 如果用户没有明确说明车型，必须先询问

## 关于历史对话
- 用户可能引用之前的内容
- 结合对话历史理解用户意图
- 只修改用户提到的参数，保留其他参数

## 关于文件
- 用户上传文件时，系统会自动分析文件结构
- 如果 task_type 已明确，直接使用对应的工具

## 关于地图可视化
- 计算完成后可使用 render_spatial_map 生成地图
- render_spatial_map 可以使用上一步计算结果

## 重要提示
- 所有工具的具体使用方法由工具自身的描述说明
- 参数标准化由系统自动处理
"""

# All 8 tool schemas (current behavior)
from tools.definitions import TOOL_DEFINITIONS
TOOLS_A = TOOL_DEFINITIONS

MESSAGES_A = [
    {"role": "system", "content": "[Context from previous conversations]\nLast successful tool: calculate_macro_emission\nLast tool summary: Calculated emissions for 150 road links"},
    {"role": "user", "content": "帮我做扩散分析"},
]


# === Group B: Skill-injected prompt ===
SYSTEM_B = """你是一个智能机动车排放计算助手。

## 核心规则
1. 理解用户意图，信息不足时友好询问
2. 使用工具获取数据，不编造数据
3. 回复简洁清晰，突出关键结果
4. 绝不假设车辆类型，必须先确认

## 当前可用工具
- calculate_dispersion: 大气扩散浓度分布计算
- render_spatial_map: 空间数据地图可视化

## 扩散分析指南
- 气象条件对结果影响极大（静风可产生 5x 浓度差异）
- **如果用户未指定气象条件，你必须告知默认条件并询问是否调整**
- 可用预设：urban_summer_day, urban_summer_night, urban_winter_day, urban_winter_night, windy_neutral, calm_stable
- 可以用 preset + 单参数覆盖
- 结果含 coverage 评估，需解释给用户
- 完成后建议做热点分析或地图可视化

## 上一步状态
上一步完成了路段排放计算（150条路段）。排放数据可直接用于扩散分析。
"""

# Only 2 relevant tool schemas
TOOLS_B = [
    t for t in TOOL_DEFINITIONS
    if t["function"]["name"] in ("calculate_dispersion", "render_spatial_map")
]

MESSAGES_B = [
    {"role": "user", "content": "帮我做扩散分析"},
]


def run_test(name, system, messages, tools):
    print(f"\n{'='*60}")
    print(f"Group {name}")
    print(f"System prompt: {len(system)} chars")
    print(f"Tool schemas: {len(tools)} tools, {len(json.dumps(tools))} chars")
    print(f"{'='*60}")

    full_messages = [{"role": "system", "content": system}] + messages

    response = client.chat.completions.create(
        model="qwen-plus",
        messages=full_messages,
        tools=tools,
        tool_choice="auto",
        temperature=0.0,
        max_tokens=2000,
    )

    msg = response.choices[0].message
    print(f"\nContent: {msg.content}")
    if msg.tool_calls:
        for tc in msg.tool_calls:
            print(f"\nTool call: {tc.function.name}")
            args = json.loads(tc.function.arguments)
            print(f"Arguments: {json.dumps(args, ensure_ascii=False, indent=2)}")

    # Check if meteorology was mentioned
    all_text = (msg.content or "")
    if msg.tool_calls:
        all_text += " " + " ".join(tc.function.arguments for tc in msg.tool_calls)

    asked_meteo = any(kw in all_text for kw in ["气象", "meteorology", "风", "wind", "urban_summer", "preset", "默认"])
    print(f"\n✓ Asked about meteorology: {asked_meteo}")


if __name__ == "__main__":
    run_test("A (Full prompt)", SYSTEM_A, MESSAGES_A, TOOLS_A)
    run_test("B (Skill-injected)", SYSTEM_B, MESSAGES_B, TOOLS_B)
```

### 预期结果

| 指标 | Group A (当前) | Group B (Skill) |
|------|---------------|-----------------|
| System prompt tokens | ~596 | ~300 |
| Tool schema tokens | ~5,369 | ~2,338 |
| 总输入 tokens | ~6,381 | ~2,873 |
| 主动询问气象条件 | 可能不会（指令被稀释） | 大概率会（指令突出） |
| 提及上一步排放结果 | 可能不会 | 会（situational prompt 引导） |

### 实验执行

```bash
# 在项目根目录下运行
cd /home/kirito/Agent1/emission_agent
python3 test_prompt_ab.py
```

脚本已设计好，可在有 API 访问权限时直接运行。

---

## 第 5 部分：实施优先级与预期收益

### 推荐实施顺序

| 优先级 | 任务 | 工作量 | 预期收益 |
|--------|------|--------|----------|
| **P0** | 缩短 `calculate_dispersion` 的 description，将行为指令移到 skill 文件 | 2h | 立即减少工具 schema 42%，气象询问指令不再被稀释 |
| **P0** | 添加 post_emission_guide（在 fact_memory 注入 situational prompt） | 1h | 排放完成后主动引导扩散 |
| **P1** | 实现 `SkillInjector` + 按需注入工具 schema | 4h | 各场景 45-65% 的 schema 精简 |
| **P1** | 创建 8 个 skill YAML 文件 | 3h | 所有行为指令集中管理 |
| **P2** | A/B 测试框架 | 2h | 量化验证改善效果 |
| **P2** | 配置开关 + 渐进灰度 | 1h | 降低上线风险 |

### P0 快速胜利方案（不改架构，2-3 小时可完成）

即使不做完整的 skill 注入改造，也可以通过以下最小改动获得显著改善：

1. **在 `core/assembler.py` 的 `_format_fact_memory()` 中添加 post-tool 引导**:

```python
# 在 fact_memory formatting 末尾添加:
if fact_memory.get("last_tool_name") == "calculate_macro_emission":
    lines.append("\n[Guide] 上一步完成了排放计算。如用户未明确下一步，可建议：扩散分析或地图可视化。")
elif fact_memory.get("last_tool_name") == "calculate_dispersion":
    lines.append("\n[Guide] 上一步完成了扩散分析。可建议：热点分析或地图可视化。")
```

2. **精简 `calculate_dispersion` 的 description**，将 1,094 chars 缩短到 ~300 chars，将详细指令移入系统提示词尾部（更容易被注意到）。

### 预期收益总结

| 指标 | 当前 | P0 优化后 | 完整 Skill 方案 |
|------|------|----------|----------------|
| 系统提示词 | 596 tokens | ~700 tokens | ~500 tokens |
| 工具 schema | 5,369 tokens | ~3,500 tokens | ~2,000-2,500 tokens（按场景） |
| 总输入 | ~6,381 tokens | ~4,615 tokens | ~3,000-3,500 tokens |
| 气象条件询问率 | 低（指令被稀释） | 中（指令前移） | 高（指令突出） |
| 排放→扩散引导 | 无 | 有（post-tool guide） | 有（skill 化） |
| 扩散→热点引导 | 无 | 有 | 有 |
