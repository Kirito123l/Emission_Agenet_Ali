# 加一个新工具的完整流程

Phase 5.2 实施后, 加新工具只需要做以下 3 件事。

## 必做

### 1. 实现工具类 `tools/<tool_name>.py`

继承 `BaseTool`, 只覆写一个抽象方法:

```python
from tools.base import BaseTool, ToolResult

class NewTool(BaseTool):
    async def execute(self, **kwargs) -> ToolResult:
        # 工具核心逻辑
        return self._success(
            data={"result": ...},
            summary="处理完成",
        )
```

可选的覆写 (有默认实现):
- `preflight_check(parameters)` — 资产可用性检查 (默认返回 `is_ready=True`)

### 2. 在 `config/tool_contracts.yaml` 声明完整 tool spec

在 `tools:` 下新增入口, 并在 `tool_definition_order:` 末尾追加工具名。

必填字段 (按 Phase 5.2 声明式注册要求):

| 字段 | 用途 | 类型 |
|------|------|------|
| `display_name` | 展示名 | string |
| `description` | 工具描述 (给 LLM 的 function definition) | string |
| `required_slots` | conversation-layer 必填参数 | list |
| `optional_slots` | conversation-layer 可选参数 | list |
| `defaults` | 工具级默认值 | dict |
| `clarification_followup_slots` | 需要二次追问的参数 | list |
| `confirm_first_slots` | 触发 confirm-first 行为的参数 | list |
| `parameters` | 完整参数 schema (见下) | dict |
| `dependencies` | `{requires: [], provides: []}` | dict |
| `readiness` | readiness 配置 | dict |
| `continuation_keywords` | router 续接关键词 (中英文) | list |
| `completion_keywords` | 目标识别关键词 (三段式, 见下) | dict |
| `available_in_naive` | 是否进入 NaiveRouter 白名单 (默认 true) | bool |

参数级字段 (parameters 下每个参数):

| 字段 | 用途 |
|------|------|
| `required` | 是否必填 (bool) |
| `standardization` | 标准化策略名 (如 `vehicle_type`, `pollutant_list`) 或 null |
| `type_coercion` | `preserve` / `as_list` / `safe_int` / `safe_float` / `as_string` |
| `schema` | JSON Schema (type, description, enum, default 等) |

completion_keywords 三段式 (D2-C):

```yaml
completion_keywords:
  primary: []         # 强信号, 命中后互斥 (其他工具不再匹配)
  secondary: []       # 弱信号, 由关键词触发
  requires: []        # AND 条件, secondary + requires 同时命中才触发
```

### 3. 在 `tools/registry.py:init_tools()` 加一行 register

```python
from tools.new_tool import NewTool
register_tool("new_tool_name", NewTool())
```

## 不需要做

加新工具后, agent 层以下文件 **不需要修改**:

- ❌ `core/governed_router.py` — `_snapshot_to_tool_args` 不再需要加工具特定 if 分支。参数提取通过 YAML `type_coercion` 字段声明驱动 (Phase 5.2 Round 3)。
- ❌ `core/ao_manager.py` — `_extract_implied_tools` 不再需要加工具特定 if/elif 块。关键词匹配通过 YAML `completion_keywords` 三段式声明驱动 (Phase 5.2 Round 3)。
- ❌ `core/naive_router.py` — 不再有 `NAIVE_TOOL_NAMES` 硬编码元组。白名单通过 YAML `available_in_naive` 字段声明驱动 (Phase 5.2 Round 3)。
- ❌ `config/emission_domain_schema.yaml` — 除非新工具引入新的领域维度 (例如新增 `noise_source_type`), 这是罕见情况。
- ❌ `ClarificationContract` / `standardization_engine` / `contract_loader` 等 governance 层模块 — 这些层通过 registry 接口对话, 不感知具体工具。

## 例外: 2 个特例 hook (需改动 agent 层)

以下场景是声明式无法表达的工程例外, 需要在 `core/governed_router.py:_snapshot_to_tool_args` 中添加特例处理:

### 跨参数 fallback (pre-processing hook)

新工具的某个参数 X 缺失时, 需要从另一个参数 Y 推断。
例如 dispersion 工具: `pollutant` 缺失时从 `pollutants[0]` 推断。

在 pre-processing 段添加 (第 811-818 行附近):

```python
if tool_name in ("your_tool",):
    if read("target_param") is None and read("source_param") is not None:
        # 跨参数推断逻辑
```

### 工具特异性 default injection (post-processing hook)

某参数有运行时计算的默认值 (例如从其他配置加载), 而非 YAML 静态声明。

在 post-processing 段添加 (第 832-839 行附近):

```python
if some_condition and tool_name == "your_tool" and "param" not in args:
    # 注入默认值
```

Phase 5.2 决策 D1 已接受这两种例外为合理, 不属于架构漏损。

## 验证

运行 `pytest tests/test_tool_extensibility.py` 验证新工具可被所有 agent 层组件正确识别。测试覆盖:

- `_snapshot_to_tool_args` 基于 YAML `type_coercion` 正确 coerce 参数
- `_extract_implied_tools` 基于 YAML `completion_keywords` 正确识别触发词
- `NaiveRouter` 基于 YAML `available_in_naive` 正确过滤白名单
