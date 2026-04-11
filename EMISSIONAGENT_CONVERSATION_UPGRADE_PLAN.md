# EmissionAgent 多轮对话升级方案

> 目标：实现类似 ChatGPT 的垂域智能体持续对话体验
> 基于：MULTI_TURN_DIAGNOSTIC.md 诊断结果 + CODEBASE_AUDIT_FOR_PAPER.md 架构审计
> 原则：不降低当前效果、最小侵入性改动、分阶段可交付

---

## 诊断结论回顾（升级前必须理解的现状）

当前系统的对话模型本质是：

```
┌─────────────────────────────────────────────────────────────────┐
│  当前：3轮滑动窗口 + fact slots + 500字符 session summary      │
│                                                                  │
│  第1轮  第2轮  第3轮  第4轮  第5轮  第6轮  第7轮  ...            │
│                            ┌───────────────┐                     │
│                            │ LLM 能看到的  │                     │
│                            │  只有这3轮    │                     │
│                            └───────────────┘                     │
│  ████  ████  ████  [轮5]  [轮6]  [轮7]                          │
│  丢失   丢失  丢失   ↑最近3轮↑                                   │
│                                                                  │
│  + fact_memory: recent_vehicle, recent_pollutants, active_file   │
│  + session_summary: 500 chars 硬截断                             │
│  + SessionContextStore: 工具结果语义存储（不直接回注prompt）      │
└─────────────────────────────────────────────────────────────────┘
```

目标是变成：

```
┌─────────────────────────────────────────────────────────────────┐
│  目标：分层记忆 + 对话意图路由 + 渐进式上下文加载              │
│                                                                  │
│  Layer 3 - 长期记忆（全会话摘要，可检索）                        │
│  Layer 2 - 中期记忆（最近N轮压缩摘要）                          │
│  Layer 1 - 短期记忆（最近3轮完整对话）                           │
│  Layer 0 - 当前轮（用户消息 + 工具结果）                         │
│                                                                  │
│  + 意图路由器：闲聊/追问/新任务/继续任务 → 不同处理路径          │
│  + 按需加载：只在需要时检索历史细节，不每轮全量注入              │
└─────────────────────────────────────────────────────────────────┘
```

---

## 阶段一：修基础（~1-2天，效果立竿见影）

这个阶段不改架构，只修诊断发现的硬伤。

### 1.1 修正 Router 实际模型（P0）

**问题**：`core/router.py:341` 硬编码 `model="qwen-plus"`，配置层的 `qwen3-max` 没生效。

**改法**：

```python
# core/router.py:341
# 改前：
self.llm_client = get_llm_client("agent", model="qwen-plus")
# 改后：
self.llm_client = get_llm_client("agent")  # 使用 config.py 的默认配置
```

确认 `config.py:25-38` 的 `model` 配置指向 `qwen3-max`。这一步解锁 256K 上下文窗口。

**验证**：加一行日志，在 `_run_state_loop` 入口打印 `self.llm_client.model`。

### 1.2 修 synthesis 大对象注入（P0）

**问题**：`core/router_render_utils.py:683-742` 对 dispersion/hotspot/map/compare 结果没有裁剪，可能单轮塞入几十K的 raster_grid。

**改法**：在 `filter_results_for_synthesis()` 中增加大对象裁剪。

```python
# core/router_render_utils.py — filter_results_for_synthesis() 内部
# 对以下工具结果做裁剪：

HEAVY_KEYS_TO_STRIP = {
    "raster_grid", "matrix_mean", "concentration_grid",
    "cell_centers_wgs84", "contour_bands", "contour_geojson",
    "receptor_top_roads", "cell_receptor_map",
    "map_data", "geojson", "features",
}

def _strip_heavy_payload(data: dict) -> dict:
    """保留 summary 级字段，裁掉大矩阵/大GeoJSON"""
    if not isinstance(data, dict):
        return data
    stripped = {}
    for k, v in data.items():
        if k in HEAVY_KEYS_TO_STRIP:
            stripped[k] = f"[{k}: stripped for synthesis, {_estimate_size(v)}]"
        elif isinstance(v, dict):
            stripped[k] = _strip_heavy_payload(v)
        elif isinstance(v, list) and len(v) > 20:
            stripped[k] = v[:5] + [f"... ({len(v)-5} more items)"]
        else:
            stripped[k] = v
    return stripped
```

**验证**：跑一个完整的 `macro_emission → dispersion → hotspot` 链路，在 synthesis 前打印 `results_json` 的 `len()`，确认 < 5000 chars。

### 1.3 修 FileContext 列名膨胀（P1）

**问题**：`core/assembler.py:335-355` 的 `max_tokens` 参数没实际执行，宽表列名会无限膨胀。

**改法**：

```python
# core/assembler.py — _format_file_context() 
# 在 Columns: 列表生成后加截断

columns_str = ", ".join(fc.columns)
MAX_COLUMNS_CHARS = 500
if len(columns_str) > MAX_COLUMNS_CHARS:
    # 保留前20列 + 省略提示
    shown = fc.columns[:20]
    columns_str = ", ".join(shown) + f" ... ({len(fc.columns) - 20} more columns)"
```

### 1.4 加 Token Telemetry（P1）

**问题**：`estimated_tokens` 严重低估，skill mode 只算工具名列表（204 chars），实际 schema 是 10414 chars。

**改法**：在 `services/llm_client.py` 的 `chat_with_tools()` 返回值中，提取 API 响应的 `usage` 字段并记录。

```python
# services/llm_client.py — chat_with_tools() 返回后
if hasattr(response, 'usage') and response.usage:
    logger.info(f"[TOKEN_TELEMETRY] prompt={response.usage.prompt_tokens}, "
                f"completion={response.usage.completion_tokens}, "
                f"total={response.usage.total_tokens}")
```

这不改任何逻辑，只加观测。后续所有优化决策都需要这个数据。

---

## 阶段二：意图路由器（~2-3天，体验质变的关键）

这是从"纯任务型 agent"升级到"类 ChatGPT 对话体验"的核心改动。

### 2.1 问题分析

当前系统的根本问题：**每条用户消息都走完整的状态机流程**。用户说"解释一下 NOx 是什么"，系统也会走 `INPUT_RECEIVED → GROUNDED → EXECUTING` 全流程，尝试做文件分析、readiness评估、工具选择等。

ChatGPT 的体验之所以流畅，是因为它能识别：这条消息是闲聊？追问？新任务？还是对上一轮的修正？

### 2.2 新增：ConversationIntentClassifier

在 `_run_state_loop()` **最前面**加一个轻量分类器，决定走哪条路径。

```python
# 新文件：core/conversation_intent.py

from enum import Enum
from dataclasses import dataclass

class ConversationIntent(Enum):
    # 纯对话类 —— 不需要走工具/状态机
    CHITCHAT = "chitchat"              # 闲聊、打招呼
    EXPLAIN_RESULT = "explain_result"  # "解释一下刚才的结果"
    KNOWLEDGE_QA = "knowledge_qa"      # "NOx 是什么"、"PM2.5 的标准是多少"
    
    # 任务类 —— 走完整状态机
    NEW_TASK = "new_task"              # 新的分析任务
    CONTINUE_TASK = "continue_task"    # "继续"、"画个图"、"做扩散"
    MODIFY_PARAMS = "modify_params"    # "把车型换成公交车"、"改成冬季"
    
    # 修正/恢复类
    RETRY = "retry"                    # "再试一次"
    UNDO = "undo"                      # "撤销"、"回到上一步"
    CONFIRM = "confirm"                # 对参数协商/输入补全的回复

@dataclass
class IntentResult:
    intent: ConversationIntent
    confidence: float
    reasoning: str
    # 对 EXPLAIN_RESULT：提取用户关心的具体方面
    # 对 MODIFY_PARAMS：提取要修改的参数和新值
    extracted_entities: dict = None


class ConversationIntentClassifier:
    """
    轻量意图分类器。
    
    设计原则：
    - 规则优先，LLM 兜底（减少延迟和token消耗）
    - 误分类代价不对称：把任务误判为闲聊 >> 把闲聊误判为任务
    - 所以规则层倾向于放行到状态机，只对高置信度闲聊做拦截
    """
    
    # 高置信度闲聊/追问模式（正则匹配）
    CHITCHAT_PATTERNS = [
        r'^(你好|hi|hello|hey|嗨|在吗)',
        r'^(谢谢|thanks|thank you|辛苦了)',
        r'^(好的|ok|明白|知道了|了解)',
    ]
    
    EXPLAIN_PATTERNS = [
        r'(解释|说明|什么意思|为什么|怎么理解|能.*解释)',
        r'(刚才|上面|这个|那个).*(结果|数据|图|表|值|排放|浓度)',
        r'(what does|explain|why|how come|what is this)',
    ]
    
    KNOWLEDGE_PATTERNS = [
        r'(是什么|什么是|定义|标准|规范|限值|含义)',
        r'(NOx|PM2\.5|PM10|CO2|CO|THC|VSP|MOVES).*(是什么|标准|定义)',
    ]
    
    CONTINUE_PATTERNS = [
        r'^(继续|接着|然后|下一步|next)',
        r'(画.*图|做.*扩散|做.*热点|渲染|可视化|dispersion|hotspot)',
        r'(对比|比较|scenario|情景)',
    ]
    
    MODIFY_PATTERNS = [
        r'(换成|改成|改为|修改|调整|更换|切换)',
        r'(把.*改|将.*改|用.*替换)',
    ]
    
    RETRY_PATTERNS = [
        r'(再试|重试|重新|再来|retry|again)',
    ]
    
    CONFIRM_PATTERNS = [
        r'^[1-6一二三四五六]$',
        r'(选.*[1-6]|第[1-6]个|option\s*[1-6])',
        r'(都不对|都不是|none)',
    ]
    
    def classify(
        self,
        user_message: str,
        has_active_negotiation: bool = False,
        has_active_completion: bool = False,
        has_file: bool = False,
        has_new_file: bool = False,
        last_tool_name: str = None,
    ) -> IntentResult:
        msg = user_message.strip().lower()
        
        # 1. 最优先：如果有活跃的参数协商/输入补全，优先判断为确认
        if has_active_negotiation or has_active_completion:
            if self._match_any(msg, self.CONFIRM_PATTERNS):
                return IntentResult(ConversationIntent.CONFIRM, 0.95, "active negotiation + confirm pattern")
        
        # 2. 新文件上传 → 一定是新任务或继续任务
        if has_new_file:
            return IntentResult(ConversationIntent.NEW_TASK, 0.9, "new file uploaded")
        
        # 3. 规则匹配
        if self._match_any(msg, self.RETRY_PATTERNS):
            return IntentResult(ConversationIntent.RETRY, 0.85, "retry pattern")
        
        if self._match_any(msg, self.MODIFY_PATTERNS):
            return IntentResult(ConversationIntent.MODIFY_PARAMS, 0.8, "modify pattern")
        
        if self._match_any(msg, self.CONTINUE_PATTERNS):
            return IntentResult(ConversationIntent.CONTINUE_TASK, 0.85, "continue pattern")
        
        if self._match_any(msg, self.EXPLAIN_PATTERNS) and last_tool_name:
            return IntentResult(ConversationIntent.EXPLAIN_RESULT, 0.8, "explain pattern + has prior result")
        
        if self._match_any(msg, self.KNOWLEDGE_PATTERNS) and not has_file:
            return IntentResult(ConversationIntent.KNOWLEDGE_QA, 0.8, "knowledge pattern, no file context")
        
        if self._match_any(msg, self.CHITCHAT_PATTERNS) and len(msg) < 20:
            return IntentResult(ConversationIntent.CHITCHAT, 0.9, "short chitchat pattern")
        
        # 4. 默认：走完整状态机（新任务或继续任务）
        if has_file or has_new_file:
            return IntentResult(ConversationIntent.CONTINUE_TASK, 0.6, "has file context, default to continue")
        
        return IntentResult(ConversationIntent.NEW_TASK, 0.5, "default: full state machine")
    
    def _match_any(self, text: str, patterns: list) -> bool:
        import re
        return any(re.search(p, text) for p in patterns)
```

### 2.3 修改 Router：根据意图分流

```python
# core/router.py — _run_state_loop() 入口处（约 L1362 之后）

async def _run_state_loop(self, user_message, file_path, trace_obj):
    # === 新增：意图分类 ===
    intent_result = self.intent_classifier.classify(
        user_message=user_message,
        has_active_negotiation=bool(self._live_parameter_negotiation),
        has_active_completion=bool(self._live_input_completion),
        has_file=bool(self.memory.get_fact("active_file")),
        has_new_file=bool(file_path),
        last_tool_name=self.memory.get_fact("last_tool_name"),
    )
    
    trace_obj.add_step("INTENT_CLASSIFICATION", intent=intent_result.intent.value,
                       confidence=intent_result.confidence)
    
    # === 意图分流 ===
    if intent_result.intent == ConversationIntent.CHITCHAT:
        return await self._handle_chitchat(user_message, trace_obj)
    
    elif intent_result.intent == ConversationIntent.EXPLAIN_RESULT:
        return await self._handle_explain(user_message, trace_obj)
    
    elif intent_result.intent == ConversationIntent.KNOWLEDGE_QA:
        return await self._handle_knowledge_qa(user_message, trace_obj)
    
    elif intent_result.intent == ConversationIntent.RETRY:
        return await self._handle_retry(user_message, file_path, trace_obj)
    
    # 其余意图（NEW_TASK, CONTINUE_TASK, MODIFY_PARAMS, CONFIRM）
    # 走原有完整状态机
    # ... 原有 _run_state_loop 逻辑 ...
```

### 2.4 轻量对话处理器（不走状态机）

```python
# core/router.py — 新增方法

async def _handle_chitchat(self, user_message, trace_obj):
    """闲聊处理：不走工具选择，直接 LLM 对话"""
    messages = self.assembler.build_messages_for_chat(
        user_message=user_message,
        mode="conversational",  # 新模式：不注入工具定义
    )
    response = await self.llm_client.chat(messages, system=self._get_conversational_system_prompt())
    self.memory.update(user_message, response, tool_calls=None)
    return RouterResponse(text=response)

async def _handle_explain(self, user_message, trace_obj):
    """结果解释：注入上一轮工具结果摘要，但不走工具选择"""
    last_summary = self.memory.get_fact("last_tool_summary") or ""
    last_snapshot = self.memory.get_fact("last_tool_snapshot") or ""
    context_summary = self.context_store.get_context_summary() if self.context_store else ""
    
    explain_system = f"""你是交通排放分析助手。用户想要理解之前的分析结果。
基于以下上下文回答用户的问题，用通俗易懂的语言解释。

上一次分析工具: {self.memory.get_fact('last_tool_name') or '未知'}
分析摘要: {last_summary}
结果快照: {last_snapshot[:1000]}
会话上下文: {context_summary}"""
    
    messages = self.assembler.build_messages_for_chat(
        user_message=user_message,
        mode="conversational",
    )
    response = await self.llm_client.chat(messages, system=explain_system)
    self.memory.update(user_message, response, tool_calls=None)
    return RouterResponse(text=response)

async def _handle_knowledge_qa(self, user_message, trace_obj):
    """知识问答：调用 knowledge 工具但不走完整状态机"""
    # 直接调用 query_knowledge 工具
    from tools.registry import ToolRegistry
    knowledge_tool = ToolRegistry().get_tool("query_knowledge")
    if knowledge_tool:
        result = await knowledge_tool.execute(query=user_message)
        if result.success and result.summary:
            # 用 LLM 把知识库结果转化为自然对话
            messages = self.assembler.build_messages_for_chat(
                user_message=user_message,
                mode="conversational",
            )
            system = f"基于以下知识库检索结果回答用户问题：\n{result.summary[:2000]}"
            response = await self.llm_client.chat(messages, system=system)
            self.memory.update(user_message, response, tool_calls=None)
            return RouterResponse(text=response)
    
    # 回退到普通对话
    return await self._handle_chitchat(user_message, trace_obj)

async def _handle_retry(self, user_message, file_path, trace_obj):
    """重试：用上一轮的参数重新执行上一个工具"""
    last_tool = self.memory.get_fact("last_tool_name")
    if not last_tool:
        return await self._handle_chitchat(user_message, trace_obj)
    
    # 走完整状态机，但在 _state_handle_grounded 中注入上一轮工具名作为 hint
    # 这样 LLM 更可能选同一个工具
    return await self._run_state_loop_internal(
        user_message=f"请重新执行上一次的 {last_tool} 分析",
        file_path=file_path or self.memory.get_fact("active_file"),
        trace_obj=trace_obj,
        retry_hint=last_tool,
    )
```

### 2.5 ContextAssembler 新增 conversational 模式

```python
# core/assembler.py — 新增方法

def build_messages_for_chat(self, user_message: str, mode: str = "conversational"):
    """
    构建不含工具定义的对话消息。
    用于闲聊、解释、知识问答等非工具场景。
    
    Token 预算大幅降低：
    - 无 9 工具 schema（省 ~2.6K tokens）
    - 无 readiness / capability 注入
    - 保留完整对话历史窗口（甚至可以放宽到 5 轮）
    """
    messages = []
    
    # 历史：conversational 模式下放宽到 5 轮，因为不需要工具 schema 的预算
    recent_turns = self.memory.get_working_memory(limit=5)
    for turn in recent_turns:
        messages.append({"role": "user", "content": turn["user"]})
        if turn.get("assistant"):
            # conversational 模式下不截断 assistant 回复
            messages.append({"role": "assistant", "content": turn["assistant"]})
    
    # 当前消息
    messages.append({"role": "user", "content": user_message})
    
    return messages
```

---

## 阶段三：分层记忆系统（~3-5天，长期对话的基础）

### 3.1 问题分析

当前的 3 轮窗口 + fact slots 组合，在第 4 轮后就丢失了所有自然语言细节。
`compressed_memory` 虽然存在但是死存储——写了不用。

目标：让 LLM 在第 20 轮对话时，仍然能"记住"第 1 轮用户上传的文件特征和讨论的关键决策。

### 3.2 三层记忆架构

```python
# core/memory_v2.py — 重构后的记忆系统

class LayeredMemory:
    """
    Layer 0: 短期记忆（原有的 working_memory）
    - 最近 3 轮完整对话
    - 每轮保留完整 user + 截断 assistant（300 chars）
    - 直接注入 prompt
    
    Layer 1: 中期摘要（利用 compressed_memory 的位置）
    - 每 3 轮生成一次摘要
    - 摘要格式："轮次4-6：用户上传了路网文件并计算了宏观排放，使用默认车队组成，
      结果显示3号路段排放最高(12.5 kg/hr)。用户要求做 NOx 扩散分析。"
    - 最多保留 5 段摘要（覆盖 ~15 轮）
    - 每段限制 200 字
    - 注入方式：拼在 system prompt 的会话上下文中
    
    Layer 2: 长期事实（原有的 fact_memory 增强版）
    - 结构化槽位（vehicle, pollutants, file 等）
    - 新增：用户偏好槽位（语言风格、关注的污染物、常用车型）
    - 新增：会话主题标签（"宏观排放分析"、"NOx扩散模拟"等）
    - 直接注入 prompt
    """
    
    def __init__(self, session_id, storage_dir):
        self.short_term = ShortTermMemory(max_turns=3)       # Layer 0
        self.mid_term = MidTermSummary(max_segments=5)       # Layer 1
        self.long_term = LongTermFacts(slots=FACT_SLOTS_V2)  # Layer 2
        self.turn_counter = 0
    
    def update(self, user_message, assistant_response, tool_calls=None, 
               file_path=None, file_context=None):
        self.turn_counter += 1
        
        # Layer 0: 滑动窗口
        self.short_term.add(user_message, assistant_response, tool_calls)
        
        # Layer 2: 更新事实槽位（同原有逻辑）
        self.long_term.extract_and_update(user_message, assistant_response, 
                                          tool_calls, file_path, file_context)
        
        # Layer 1: 每 3 轮生成一次中期摘要
        if self.turn_counter % 3 == 0:
            recent_3 = self.short_term.get_last_n(3)
            summary = self._generate_segment_summary(recent_3)
            self.mid_term.add_segment(
                turn_range=(self.turn_counter - 2, self.turn_counter),
                summary=summary
            )
    
    def _generate_segment_summary(self, turns: list) -> str:
        """
        用 LLM 或规则生成 3 轮对话的摘要。
        
        设计选择：用规则而非 LLM。
        原因：每 3 轮触发一次 LLM 摘要调用会增加延迟和成本。
        规则摘要虽然粗糙，但结构化信息（工具名、参数、结果数值）
        已经够用了。
        """
        parts = []
        for turn in turns:
            if turn.get("tool_calls"):
                for tc in turn["tool_calls"]:
                    tool_name = tc.get("name", "unknown")
                    summary = tc.get("summary", "")[:100]
                    parts.append(f"执行了 {tool_name}: {summary}")
            else:
                # 非工具轮次：提取用户意图
                user_short = turn.get("user", "")[:80]
                parts.append(f"用户: {user_short}")
        
        return f"轮次{turns[0].get('turn', '?')}-{turns[-1].get('turn', '?')}: " + "; ".join(parts)
    
    def build_context_for_prompt(self) -> str:
        """构建注入 prompt 的记忆上下文"""
        sections = []
        
        # Layer 2: 长期事实
        facts = self.long_term.format_for_prompt()
        if facts:
            sections.append(f"[会话事实]\n{facts}")
        
        # Layer 1: 中期摘要
        summaries = self.mid_term.format_for_prompt()
        if summaries:
            sections.append(f"[历史摘要]\n{summaries}")
        
        return "\n\n".join(sections)


# 新增的事实槽位
FACT_SLOTS_V2 = {
    # 原有槽位
    "recent_vehicle": None,
    "recent_pollutants": None,
    "recent_year": None,
    "active_file": None,
    "file_analysis": None,
    "last_tool_name": None,
    "last_tool_summary": None,
    "last_tool_snapshot": None,
    "last_spatial_data": None,
    
    # 新增槽位
    "session_topic": None,           # "宏观排放分析" / "NOx扩散模拟" / ...
    "user_language_preference": None, # "zh" / "en" / "mixed"
    "cumulative_tools_used": [],      # ["calculate_macro_emission", "calculate_dispersion"]
    "key_findings": [],               # ["3号路段排放最高(12.5 kg/hr)", "热点集中在交叉口附近"]
    "user_corrections": [],           # 用户纠正过的参数/理解
}
```

### 3.3 Assembler 集成分层记忆

```python
# core/assembler.py — 修改 _build_skill_mode_messages()

def _build_skill_mode_messages(self, ...):
    messages = []
    
    # System prompt（原有逻辑）
    system_prompt = self._build_system_prompt(...)
    
    # === 新增：注入分层记忆上下文 ===
    memory_context = self.memory.build_context_for_prompt()
    if memory_context:
        system_prompt += f"\n\n{memory_context}"
    
    # Layer 0: 短期记忆（原有的 3 轮窗口逻辑，不变）
    recent_turns = self.memory.short_term.get_all()
    for turn in recent_turns:
        messages.append({"role": "user", "content": turn["user"]})
        if turn.get("assistant"):
            messages.append({"role": "assistant", "content": turn["assistant"][:300]})
    
    # 当前 user message + file context
    current_content = self._format_current_message(user_message, file_context)
    messages.append({"role": "user", "content": current_content})
    
    return system_prompt, messages
```

### 3.4 Token 预算估算（升级后）

```
阶段三升级后的 token 预算（以 qwen3-max 256K 为前提）：

固定开销：
  System prompt (core_v3 + skill injection):    ~1.0K tokens
  9 工具 schema:                                 ~2.6K tokens
  长期事实 (Layer 2):                            ~0.3K tokens
  中期摘要 (Layer 1, 5段 × 200字):              ~1.0K tokens
  小计:                                          ~4.9K tokens

可变开销（封顶）：
  短期记忆 (Layer 0, 3轮):                      ~1.5K tokens
  FileContext:                                    ~0.5K tokens（修复后）
  Session summary:                                ~0.25K tokens
  小计:                                          ~2.25K tokens

总计（每轮主工具选择调用）:                       ~7.2K tokens
256K 窗口利用率:                                  ~2.8%

结论：即使加了分层记忆，离 256K 上限还差得非常远。
空间充裕到足以将短期记忆窗口扩大到 5-8 轮。
```

---

## 阶段四：细节打磨（~2-3天）

### 4.1 LLM 调用重试与降级

```python
# services/llm_client.py — 包装主 chat/chat_with_tools

async def chat_with_retry(self, messages, tools=None, system=None, 
                           max_retries=2, backoff_base=1.0):
    """带重试和指数退避的 LLM 调用"""
    for attempt in range(max_retries + 1):
        try:
            if tools:
                return await self.chat_with_tools(messages, tools, system)
            else:
                return await self.chat(messages, system)
        except Exception as e:
            if attempt == max_retries:
                raise
            wait = backoff_base * (2 ** attempt)
            logger.warning(f"LLM call attempt {attempt+1} failed: {e}, retrying in {wait}s")
            await asyncio.sleep(wait)
```

### 4.2 流程态持久化

```python
# api/session.py — save_router_state() 增强

def save_router_state(self):
    state = {
        "context_store": self.router.context_store.to_dict(),
        # === 新增：持久化流程态 ===
        "live_parameter_negotiation": self.router._live_parameter_negotiation,
        "live_input_completion": self.router._live_input_completion,
        "live_continuation_bundle": self.router._live_continuation_bundle,
    }
    # ... 写入 JSON 文件 ...
```

### 4.3 Conversational System Prompt

```python
# core/router.py — 新增

def _get_conversational_system_prompt(self):
    """闲聊/解释/知识问答模式下的 system prompt"""
    memory_context = self.memory.build_context_for_prompt() if hasattr(self.memory, 'build_context_for_prompt') else ""
    session_summary = self.context_store.get_context_summary() if self.context_store else ""
    
    return f"""你是 EmissionAgent，一个专注于交通尾气排放分析的智能助手。

你的能力范围：道路交通排放估算（宏观/微观）、污染物扩散模拟、热点识别、情景对比。
你使用的计算引擎基于 US EPA MOVES 模型和 PS-XGB-RLINE 代理扩散模型。

当前对话上下文：
{memory_context}

会话摘要：{session_summary}

回答要求：
- 用通俗易懂的语言解释专业概念
- 如果用户问的问题需要执行计算工具，主动引导用户提供所需信息
- 保持对话连贯，引用之前讨论过的内容
- 中英文混合回复（跟随用户语言习惯）"""
```

### 4.4 会话清理机制

```python
# api/session.py — 新增自动清理

class SessionManager:
    SESSION_TTL_HOURS = 72  # 72 小时无活动自动清理
    
    async def cleanup_idle_sessions(self):
        """定期清理空闲会话"""
        now = time.time()
        to_remove = []
        for sid, session in self._sessions.items():
            if now - session.last_active > self.SESSION_TTL_HOURS * 3600:
                to_remove.append(sid)
        for sid in to_remove:
            await self._sessions[sid].cleanup()
            del self._sessions[sid]
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} idle sessions")
```

---

## 实施路线图

```
Week 1:
├── Day 1-2: 阶段一（修基础）
│   ├── 1.1 修正 Router 模型 → qwen3-max
│   ├── 1.2 修 synthesis 大对象裁剪
│   ├── 1.3 修 FileContext 列名截断
│   └── 1.4 加 Token Telemetry
│
├── Day 3-5: 阶段二（意图路由器）
│   ├── 2.2 ConversationIntentClassifier
│   ├── 2.3 Router 意图分流
│   ├── 2.4 轻量对话处理器
│   └── 2.5 Assembler conversational 模式

Week 2:
├── Day 6-8: 阶段三（分层记忆）
│   ├── 3.2 LayeredMemory 实现
│   ├── 3.3 Assembler 集成
│   └── 3.4 Token 预算验证
│
├── Day 9-10: 阶段四（细节打磨）
│   ├── 4.1 LLM 重试/降级
│   ├── 4.2 流程态持久化
│   ├── 4.3 Conversational system prompt
│   └── 4.4 会话清理机制
```

---

## 每个阶段的效果对比

| 维度 | 当前 | 阶段一后 | 阶段二后 | 阶段三后 |
|------|------|----------|----------|----------|
| 闲聊处理 | 走完整状态机（慢且浪费） | 同左 | 独立快路径（~0.5s） | 同阶段二 |
| 结果解释 | 依赖3轮窗口 | 同左 | 专用处理器+结果注入 | +历史摘要辅助 |
| 第10轮连贯性 | 只有fact slots | 同左 | 同左 | 中期摘要覆盖 |
| 第20轮连贯性 | 几乎丢失 | 同左 | 同左 | 长期事实+主题标签 |
| 单轮爆炸风险 | 高（大payload） | 已修复 | 已修复 | 已修复 |
| 模型能力 | qwen-plus | qwen3-max | qwen3-max | qwen3-max |
| LLM 调用次数/轮 | 1-4次（全走工具） | 同左 | 闲聊0次工具调用 | 同阶段二 |
| Token 消耗/轮 | ~3.7K-5K | ~3.7K-5K | 闲聊~1K/任务~5K | 闲聊~1.5K/任务~7K |

---

## Codex 执行建议

每个阶段可以单独作为一个 Codex 工作包：

- **WP-CONV-1**: 阶段一的 4 个修复点，每个都是精确到行号的定点改动
- **WP-CONV-2**: 阶段二的意图路由器，新文件 `core/conversation_intent.py` + 修改 `core/router.py` 和 `core/assembler.py`
- **WP-CONV-3**: 阶段三的分层记忆，新文件 `core/memory_v2.py` + 修改 `core/assembler.py` 和 `core/router.py`
- **WP-CONV-4**: 阶段四的 4 个打磨点
