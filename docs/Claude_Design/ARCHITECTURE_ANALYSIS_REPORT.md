# Emission Agent 架构分析报告

## 1. 核心处理流程

```
用户消息 → FastAPI路由 → Agent.chat() → Planning → Validation → Execution → Synthesis → 返回结果
```

### 详细流程图

```
┌─────────────┐
│  用户发送   │
│  消息+文件  │
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ api/routes.py:chat_stream()                             │
│ - 保存上传文件到 TEMP_DIR                                │
│ - 修改消息: "文件已上传，路径: {path}\n请使用input_file参数" │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ agent/core.py:chat()                                    │
│ 1. 检查是否回顾性问题                                     │
│ 2. Planning + 验证 + 反思修复                            │
│ 3. 检查是否需要追问 (needs_clarification)                │
│ 4. 执行技能                                              │
│ 5. 检查Skill层追问需求                                   │
│ 6. 综合生成回答                                          │
│ 7. 记录学习                                              │
│ 8. 保存对话                                              │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ agent/core.py:_plan_with_validation()                   │
│ - 调用 _plan() 生成计划                                  │
│ - 参数合并 (_enrich_plan_for_validation)                │
│ - 验证计划 (PlanValidator)                               │
│ - 反思修复 (PlanReflector, 最多重试2次)                  │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ agent/core.py:_plan()                                   │
│ 1. 检查缓存                                              │
│ 2. 推断Skill类型                                         │
│ 3. 获取Few-shot学习示例                                  │
│ 4. 构建增强的System Prompt                               │
│ 5. 调用 LLM.chat_json_with_history()                    │
│ 6. 写入缓存                                              │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ agent/core.py:_execute_plan()                           │
│ - 遍历计划中的每个步骤                                    │
│ - 从注册表获取Skill                                       │
│ - 调用 skill.execute(**params)                          │
│ - 记录执行结果                                           │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ skills/micro_emission/skill.py:execute()                │
│ 或 skills/macro_emission/skill.py:execute()             │
│                                                         │
│ 1. 验证必需参数                                          │
│ 2. 提取参数                                              │
│ 3. 读取文件 (如果有input_file)                           │
│    - ExcelHandler.read_trajectory_from_excel()          │
│    - 使用 ColumnMapper 进行智能列名映射                   │
│ 4. 标准化车型/污染物                                      │
│ 5. 执行计算                                              │
│ 6. 生成下载文件 (generate_result_excel)                  │
│ 7. 返回 SkillResult                                     │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ agent/core.py:_synthesize()                             │
│ - 使用 SYNTHESIS_PROMPT                                 │
│ - 调用 synthesis_llm.chat()                             │
│ - 生成用户友好的回答                                      │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌─────────────────────────────────────────────────────────┐
│ api/routes.py:chat_stream()                             │
│ - 流式输出文本                                           │
│ - 提取图表/表格数据                                       │
│ - 添加下载链接                                           │
│ - 保存对话历史                                           │
└──────┬──────────────────────────────────────────────────┘
       │
       ▼
┌─────────────┐
│  返回给用户  │
└─────────────┘
```

### 关键文件和函数

- **入口**: `api/routes.py:chat_stream()` (line 361)
- **Planning**: `agent/core.py:_plan()` (line 296)
- **验证**: `agent/core.py:_plan_with_validation()` (line 139)
- **执行**: `agent/core.py:_execute_plan()` (line 362)
- **Skill执行**: `skills/micro_emission/skill.py:execute()` (line 159)
- **文件读取**: `skills/micro_emission/excel_handler.py:read_trajectory_from_excel()`
- **列名映射**: `skills/common/column_mapper.py:map_columns()`

## 2. 文件处理流程

### 文件从上传到处理的完整路径

```
1. 用户上传文件
   ↓
2. api/routes.py:chat_stream() (line 391-409)
   - 接收 UploadFile 对象
   - 保存到 TEMP_DIR/{session_id}_input{suffix}
   - 修改消息: message_with_file = f"{message}\n\n文件已上传，路径: {str(input_file_path)}\n请使用 input_file 参数处理此文件。"
   ↓
3. agent/core.py:chat() (line 45)
   - 接收包含文件路径的消息
   - 调用 _plan() 生成计划
   ↓
4. agent/core.py:_plan() (line 296)
   - LLM 看到消息中的 "文件已上传，路径: ..."
   - 根据 AGENT_SYSTEM_PROMPT 的指示
   - 生成包含 input_file 参数的计划
   - **注意**: Planning 阶段 LLM 只看到文件路径，看不到文件内容
   ↓
5. agent/core.py:_execute_plan() (line 362)
   - 调用 skill.execute(input_file="/path/to/file")
   ↓
6. skills/micro_emission/skill.py:execute() (line 183-191)
   - 调用 self._excel_handler.read_trajectory_from_excel(input_file)
   ↓
7. skills/micro_emission/excel_handler.py:read_trajectory_from_excel()
   - 读取 Excel/CSV 文件
   - 调用 ColumnMapper.map_columns() 进行智能列名映射
   - 使用 LLM 分析列名和样本数据
   - 返回标准化的轨迹数据
   ↓
8. skills/micro_emission/skill.py:execute() (继续)
   - 使用读取的数据进行计算
   - 生成结果文件 (generate_result_excel)
   - 返回 SkillResult (包含 metadata.download_file)
```

### 关键点

1. **文件路径传递**: 通过消息文本传递，格式为 `"文件已上传，路径: {path}"`
2. **Agent 知道文件的时机**: Planning 阶段，通过消息文本
3. **文件内容读取时机**: Skill 执行阶段，在 `ExcelHandler.read_trajectory_from_excel()` 中
4. **任务类型判断**:
   - **当前实现**: 由 LLM 在 Planning 阶段根据 System Prompt 中的规则判断
   - **实际执行**: 在 Skill 内部，通过 `ColumnMapper` 分析列名来确定

## 3. Planning 阶段详情

### 输入

1. **用户消息** (user_input): 包含文件路径信息的文本
   - 例如: `"帮我计算排放\n\n文件已上传，路径: D:\temp\data.xlsx\n请使用 input_file 参数处理此文件。"`

2. **对话上下文** (context):
   - 历史对话轮次 (最多20轮)
   - 之前的参数 (用于参数合并)
   - 通过 `context.build_messages_for_planning()` 构建

3. **System Prompt**:
   - `AGENT_SYSTEM_PROMPT` (627行)
   - 包含技能定义、任务类型判断规则、追问规则等
   - 可能增强的 Few-shot 学习示例

4. **Few-shot 示例** (可选):
   - 从 `AgentLearner` 获取相关案例
   - 基于推断的 Skill 类型和用户输入相似度

### 输出

Planning 返回一个字典，包含:

```python
{
    "understanding": str,  # 对用户意图的理解
    "plan": [              # 执行计划（步骤列表）
        {
            "skill": str,      # 技能名称
            "params": dict,    # 参数字典
            "purpose": str     # 步骤目的
        }
    ],
    "needs_clarification": bool,  # 是否需要追问
    "clarification_message": str  # 追问消息（如果需要）
}
```

### Planning 能否访问文件内容？

**否**。Planning 阶段只能看到:
- 用户消息文本（包含文件路径）
- 对话历史
- System Prompt

Planning 阶段**看不到**:
- 文件的实际内容
- 文件的列名
- 文件的行数
- 文件的数据类型

### 追问生成位置

追问可以在两个位置生成:

1. **Planning 阶段** (`agent/core.py:_plan()`, line 296)
   - LLM 根据 System Prompt 判断是否需要追问
   - 设置 `needs_clarification: true`
   - 提供 `clarification_message`
   - **问题**: LLM 看不到文件内容，只能根据经验判断

2. **Skill 执行阶段** (`agent/core.py:_check_clarification_needed()`, line 400)
   - Skill 执行后，检查 `result.metadata.needs_clarification`
   - 如果 Skill 发现缺少参数，返回追问信息
   - **优势**: Skill 已经读取了文件，知道实际缺少什么

## 4. Skill 执行详情

### Micro Emission Skill

**入口函数**: `skills/micro_emission/skill.py:execute()` (line 159)

**参数接收**:
```python
def execute(self, **params) -> SkillResult:
    # 从 params 字典中提取参数
    vehicle_type = params["vehicle_type"]
    input_file = params.get("input_file")
    trajectory_data = params.get("trajectory_data")
    # ...
```

**文件分析流程**:
1. 调用 `ExcelHandler.read_trajectory_from_excel(input_file)`
2. ExcelHandler 调用 `ColumnMapper.map_columns()`
3. ColumnMapper 使用 LLM 分析:
   - 列名列表
   - 前2行样本数据
   - 任务类型 (micro_emission)
4. 返回列名映射和标准化数据

**缺少参数处理**:
- 在 `validate_params()` 中检查必需参数
- 如果缺少 `vehicle_type`，返回:
  ```python
  SkillResult(
      success=False,
      error="缺少必需参数",
      metadata={
          "missing_params": {...},
          "needs_clarification": True
      }
  )
  ```

### Macro Emission Skill

**入口函数**: `skills/macro_emission/skill.py:execute()`

**参数接收**: 类似 Micro Emission

**文件分析流程**:
1. 调用 `ExcelHandler.read_links_from_excel(input_file)`
2. 自动识别:
   - 必需列 (link_length_km, traffic_flow_vph, avg_speed_kph)
   - 车型比例列 (包含 % 的列名)
3. 如果有车型比例列，自动使用
4. 如果没有，使用 `default_fleet_mix` 或默认值

**车型比例处理**:
- 如果文件包含车型比例列（如 `Car%`, `Bus%`），自动识别和使用
- 不需要追问用户

## 5. 智能列名映射

### 位置

`skills/common/column_mapper.py:map_columns()`

### 实现方式

使用 LLM 进行智能映射:

```python
def map_columns(
    df: pd.DataFrame,
    task_type: str,  # "micro_emission" 或 "macro_emission"
    llm_client: Optional[Any] = None
) -> Dict[str, Any]:
    # 1. 提取列名和样本数据
    columns = list(df.columns)
    sample_data = df.head(2).to_dict(orient="records")

    # 2. 构建 Prompt
    prompt = COLUMN_MAPPING_PROMPT.format(
        columns=columns,
        sample_data=json.dumps(sample_data, ensure_ascii=False),
        task_type=task_type,
        field_definitions=FIELD_DEFINITIONS[task_type]
    )

    # 3. 调用 LLM
    result = llm_client.chat_json(prompt)

    # 4. 返回映射结果
    return {
        "mapping": {...},        # 列名映射
        "fleet_mix": {...},      # 车型列映射（宏观）
        "confidence": 0.95,      # 置信度
        "warnings": [...],       # 警告信息
        "unmapped_columns": [...] # 未映射的列
    }
```

### 触发时机

在 Skill 执行阶段，读取文件时:
- `ExcelHandler.read_trajectory_from_excel()` (微观)
- `ExcelHandler.read_links_from_excel()` (宏观)

### 映射结果返回

映射结果不直接返回给用户或 Agent，而是:
1. 在 ExcelHandler 内部使用，读取正确的列
2. 如果映射失败，在 SkillResult.error 中返回错误信息
3. 警告信息可以在 SkillResult.metadata 中返回

## 6. System Prompt 结构

### 文件

`agent/prompts/system.py` (627行)

### 主要部分

```
AGENT_SYSTEM_PROMPT = """
1. 可用技能 (line 3-23)
   - query_emission_factors
   - calculate_micro_emission
   - calculate_macro_emission
   - query_knowledge

2. 重要原则 (line 24-31)
   - 利用对话历史
   - 必需参数不能省略
   - 参数保持原话
   - 可选参数可以省略
   - 多污染物查询

3. 任务类型判断规则 (line 32-88)
   - 判断方法（微观 vs 宏观特征）
   - 追问差异
   - 错误示例
   - 正确示例

4. 文件处理规则 (line 89-233)
   - 必须使用 input_file 参数
   - 智能参数处理
   - 错误示例
   - 正确示例
   - 文件类型识别
   - 文件格式要求

5. 追问规则 (line 124-176)
   - 先分析后追问
   - 明确说明缺少什么
   - 提供选项而非开放问题
   - 提供默认选项
   - 追问格式模板
   - 智能列名映射结果要体现

6. 示例 (line 278-627)
   - 各种场景的正确处理方式
   - 包含 JSON 格式的计划示例
```

### 结构清晰度

- **优点**:
  - 分节清晰，有明确的标题
  - 提供了大量示例
  - 包含错误示例和正确示例对比

- **缺点**:
  - 较长 (627行)，可能影响 LLM 理解
  - 部分规则重复（如文件处理规则在多处出现）
  - 追问规则和任务类型判断规则有交叉

## 7. 发现的问题

### 问题 1: Planning 阶段看不到文件内容

**现象**:
- LLM 在 Planning 阶段只能看到文件路径
- 无法知道文件的列名、行数、数据类型
- 只能根据 System Prompt 中的规则"猜测"

**影响**:
- 可能生成不准确的追问
- 可能选择错误的 Skill (micro vs macro)
- 追问质量依赖 System Prompt 的详细程度

**根本原因**:
- 文件分析能力在 Skill 内部 (ExcelHandler + ColumnMapper)
- Planning 阶段无法调用这些能力

### 问题 2: 追问逻辑分散

**现象**:
- 追问可以在 Planning 阶段生成 (LLM 判断)
- 也可以在 Skill 执行后生成 (代码判断)
- 两个位置的追问逻辑不一致

**影响**:
- Planning 阶段的追问可能不准确（因为看不到文件）
- Skill 执行后的追问更准确，但已经浪费了一次 LLM 调用

### 问题 3: 任务类型判断时机不当

**现象**:
- System Prompt 要求 LLM 在 Planning 阶段判断任务类型
- 但 LLM 看不到文件内容，只能根据经验判断
- 实际的任务类型判断在 Skill 内部 (ColumnMapper)

**影响**:
- 可能选择错误的 Skill
- 如果选错，需要重新 Planning 或返回错误

### 问题 4: System Prompt 过长且重复

**现象**:
- 627行的 System Prompt
- 文件处理规则在多处重复
- 追问规则和任务类型判断规则有交叉

**影响**:
- 增加 Token 消耗
- 可能降低 LLM 理解准确度
- 维护困难

### 问题 5: 为什么 Agent 会用 query_knowledge？

**根本原因**:
- Planning 阶段看不到文件内容
- LLM 不确定如何处理文件
- System Prompt 虽然说"不要使用 query_knowledge"，但没有提供替代方案
- LLM 可能认为需要先"了解"文件格式

**解决方案**:
- 在 Planning 阶段提供文件分析能力
- 或者在 System Prompt 中更明确地说明文件处理流程

## 8. 建议的改进点

### 改进 1: 在 Planning 前进行文件预分析

**方案**:
```python
# 在 agent/core.py:chat() 中
if "文件已上传，路径:" in user_input:
    # 提取文件路径
    file_path = extract_file_path(user_input)

    # 预分析文件
    file_analysis = self._analyze_file(file_path)
    # 返回: {
    #     "task_type": "micro_emission" | "macro_emission",
    #     "columns": [...],
    #     "row_count": 1200,
    #     "has_fleet_mix": True/False,
    #     "missing_required_columns": [...],
    #     "warnings": [...]
    # }

    # 将分析结果添加到消息中
    user_input_enhanced = f"{user_input}\n\n文件分析结果:\n{json.dumps(file_analysis)}"

    # 使用增强的消息进行 Planning
    plan_result = self._plan(user_input_enhanced)
```

**优势**:
- LLM 在 Planning 阶段就能看到文件内容
- 可以生成更准确的追问
- 可以正确选择 Skill 类型

### 改进 2: 简化 System Prompt

**方案**:
- 将文件处理规则合并到一个章节
- 移除重复的规则
- 将详细的示例移到 Few-shot 学习中
- 目标: 减少到 300-400 行

### 改进 3: 统一追问逻辑

**方案**:
- 在 Planning 阶段，如果文件分析显示缺少必需参数，直接生成追问
- 移除 Skill 层的追问逻辑（或仅用于异常情况）
- 追问格式统一使用模板

### 改进 4: 添加文件分析工具

**方案**:
```python
# 新增 skills/common/file_analyzer.py
class FileAnalyzer:
    def analyze(self, file_path: str) -> Dict:
        """快速分析文件，不进行完整计算"""
        df = pd.read_excel(file_path)

        # 判断任务类型
        task_type = self._infer_task_type(df)

        # 检查必需列
        missing_columns = self._check_required_columns(df, task_type)

        # 检查车型比例列（宏观）
        has_fleet_mix = self._check_fleet_mix_columns(df)

        return {
            "task_type": task_type,
            "columns": list(df.columns),
            "row_count": len(df),
            "has_fleet_mix": has_fleet_mix,
            "missing_columns": missing_columns,
            "warnings": [...]
        }
```

### 改进 5: 优化追问生成

**方案**:
```python
# 在 agent/core.py 中添加
def _generate_clarification(
    self,
    file_analysis: Dict,
    user_input: str
) -> Optional[str]:
    """基于文件分析结果生成追问"""

    if file_analysis["task_type"] == "micro_emission":
        # 微观排放：必须指定车型
        if "vehicle_type" not in extracted_params:
            return self._generate_vehicle_type_question(file_analysis)

    elif file_analysis["task_type"] == "macro_emission":
        # 宏观排放：如果有车型比例，不需要追问
        if file_analysis["has_fleet_mix"]:
            return None  # 不需要追问
        else:
            return self._generate_fleet_mix_question(file_analysis)

    return None
```

### 改进 6: 添加文件类型自动识别

**方案**:
- 在文件预分析阶段自动识别任务类型
- 不依赖 LLM 判断
- 使用规则引擎:
  ```python
  def _infer_task_type(self, df: pd.DataFrame) -> str:
      columns_lower = [c.lower() for c in df.columns]

      # 微观特征计数
      micro_score = 0
      if any("time" in c or "时间" in c for c in columns_lower):
          micro_score += 1
      if any("speed" in c or "速度" in c for c in columns_lower):
          micro_score += 1
      if any("acc" in c or "加速" in c for c in columns_lower):
          micro_score += 1
      if len(df) > 100:
          micro_score += 1

      # 宏观特征计数
      macro_score = 0
      if any("link" in c or "segment" in c or "路段" in c for c in columns_lower):
          macro_score += 1
      if any("length" in c or "长度" in c for c in columns_lower):
          macro_score += 1
      if any("flow" in c or "volume" in c or "流量" in c for c in columns_lower):
          macro_score += 1
      if any("%" in c or "pct" in c for c in columns_lower):
          macro_score += 1

      return "micro_emission" if micro_score > macro_score else "macro_emission"
  ```

## 9. 重构优先级建议

### P0 (立即修复)
1. **添加文件预分析** - 解决 Planning 阶段看不到文件内容的问题
2. **优化追问逻辑** - 基于文件分析结果生成准确的追问

### P1 (重要改进)
3. **简化 System Prompt** - 减少 Token 消耗，提高理解准确度
4. **添加文件类型自动识别** - 不依赖 LLM 判断任务类型

### P2 (优化体验)
5. **统一追问格式** - 使用模板生成一致的追问
6. **添加文件分析结果展示** - 在追问中展示文件分析结果

## 10. 总结

### 核心问题

**Planning 阶段与文件分析能力脱节**:
- Planning 阶段 (LLM) 看不到文件内容
- 文件分析能力 (ColumnMapper) 在 Skill 内部
- 导致 Planning 阶段的决策不准确

### 解决思路

**将文件分析前置到 Planning 之前**:
1. 用户上传文件
2. 立即进行文件预分析（不进行完整计算）
3. 将分析结果提供给 LLM
4. LLM 基于分析结果进行 Planning
5. 生成准确的追问或直接执行

### 预期效果

- ✅ Planning 阶段能看到文件内容
- ✅ 追问更准确，不会问用户已经提供的信息
- ✅ 任务类型判断更准确
- ✅ 减少不必要的 LLM 调用
- ✅ 提升用户体验
