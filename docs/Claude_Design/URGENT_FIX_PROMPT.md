# 紧急修复任务：恢复正常的排放计算功能

## 问题总结

当前系统存在三个严重问题，导致用户体验完全无法接受：

### 问题1：LLM 严重幻觉 🔴
- 实际 CO2 = 5,821 kg，LLM 说成 1.72 kg（相差 3,384 倍）
- LLM 编造"排放峰值在第42-48个点"等完全不存在的分析
- LLM 编造"空调导致增加7%"等虚假细节

### 问题2：计算结果未正确返回前端 🔴
- 前端显示"暂无数据"
- 没有表格数据
- 没有下载链接
- 与原架构的正常输出完全不同

### 问题3：计算数值可能异常 🟡
- CO2 排放 5,239 kg/km（正常值 0.5-1 kg/km）
- 可能是单位问题，但这是次要问题，先确保数据能正确显示

## 修复目标

恢复到原架构的正常输出效果（参考截图）：
1. ✅ 显示结构化的参数信息
2. ✅ 显示计算结果表格
3. ✅ 提供 Excel 下载链接
4. ✅ 简洁的文字说明（不编造）

## 修复任务

### 任务1：分析原架构的输出格式

首先，请仔细阅读以下文件，理解原架构如何返回数据给前端：

```bash
# 1. 查看原架构的 API 返回格式
cat legacy/agent/core.py | grep -A 50 "_synthesize"

# 2. 查看原架构的 Skill 返回格式
cat legacy/skills/micro_emission/skill.py | grep -A 30 "return SkillResult"

# 3. 查看前端期望的数据格式
cat api/routes.py | grep -A 20 "def chat"

# 4. 查看前端如何渲染数据
cat web/app.js | grep -A 30 "table_data\|chart_data\|download"
```

记录下：
- 前端期望的 JSON 格式是什么
- `table_data` 的结构是什么
- `chart_data` 的结构是什么
- `download_file` 如何传递

### 任务2：修复 SYNTHESIS_PROMPT

修改 `core/router.py` 中的 `SYNTHESIS_PROMPT`：

```python
SYNTHESIS_PROMPT = """你是机动车排放计算助手。请基于工具返回的实际数据生成简洁回答。

## 严格要求

1. **只报告实际数据**: 直接使用工具返回的数值，不要修改
2. **禁止编造**: 
   - ❌ 不要编造"排放峰值在第X个点"
   - ❌ 不要编造"空调导致增加X%"  
   - ❌ 不要编造"相当于X棵树"
   - ❌ 不要进行单位转换或数学计算
3. **简洁格式**: 只需要一句话说明计算完成，具体数据由系统表格展示

## 回答模板

如果计算成功：
"已完成{vehicle_type}的排放计算，共处理{n}条数据，计算了{pollutants}的排放量。详细结果请查看下方表格，完整数据可下载Excel文件。"

如果有错误：
"计算遇到问题：{error_message}"

注意：不要在回答中列出具体数值，表格会自动显示。只需要简短说明。
"""
```

### 任务3：修复数据返回链路

这是最关键的修复。需要确保工具返回的数据正确传递给前端。

#### 3.1 检查 tools/micro_emission.py 的返回格式

确保返回的 ToolResult 包含前端需要的所有字段：

```python
# tools/micro_emission.py

async def execute(self, **kwargs) -> ToolResult:
    # ... 计算逻辑 ...
    
    # 返回格式必须与前端兼容
    return ToolResult(
        success=True,
        data={
            "summary": {
                "vehicle_type": vehicle_type,
                "model_year": model_year,
                "pollutants": pollutants,
                "total_points": len(trajectory_data),
                "total_distance_km": total_distance,
                "total_time_s": total_time,
                "total_emissions_g": {
                    "CO2": co2_total,
                    "NOx": nox_total,
                    "PM2.5": pm25_total
                }
            },
            "results": results_list,  # 详细结果
        },
        # 重要：这些字段必须在顶层，不是嵌套在 data 里
        table_data={
            "headers": ["指标", "数值"],
            "rows": [
                ["总CO2排放", f"{co2_total:.2f} g"],
                ["总NOx排放", f"{nox_total:.2f} g"],
                ["总PM2.5排放", f"{pm25_total:.2f} g"],
                ["总距离", f"{total_distance:.3f} km"],
                ["总时间", f"{total_time} s"]
            ]
        },
        download_file={
            "path": output_path,
            "filename": output_filename,
            "description": "完整排放计算结果"
        },
        summary=f"已计算{vehicle_type}的排放，共{len(trajectory_data)}个数据点"
    )
```

#### 3.2 修复 core/router.py 的数据提取

确保 RouterResponse 正确提取工具返回的数据：

```python
# core/router.py

def _extract_table_data(self, tool_results: List[Dict]) -> Optional[Dict]:
    """从工具结果提取表格数据"""
    for r in tool_results:
        result = r.get("result", {})
        # 检查多个可能的位置
        if result.get("table_data"):
            return result["table_data"]
        if result.get("data", {}).get("table_data"):
            return result["data"]["table_data"]
        # 如果没有 table_data，从 summary 构建
        summary = result.get("data", {}).get("summary", {})
        if summary.get("total_emissions_g"):
            emissions = summary["total_emissions_g"]
            return {
                "headers": ["指标", "数值 (g)"],
                "rows": [[k, f"{v:.2f}"] for k, v in emissions.items()]
            }
    return None

def _extract_download_file(self, tool_results: List[Dict]) -> Optional[str]:
    """从工具结果提取下载文件"""
    for r in tool_results:
        result = r.get("result", {})
        # 检查多个可能的位置
        if result.get("download_file"):
            df = result["download_file"]
            return df.get("path") or df.get("filename")
        if result.get("data", {}).get("download_file"):
            df = result["data"]["download_file"]
            return df.get("path") or df.get("filename")
        if result.get("metadata", {}).get("download_file"):
            df = result["metadata"]["download_file"]
            return df.get("path") or df.get("filename")
    return None
```

#### 3.3 修复 API 返回格式

确保 `api/routes.py` 正确返回数据给前端：

```python
# api/routes.py

@router.post("/chat")
async def chat(request: ChatRequest):
    # ... 处理逻辑 ...
    
    result = await session.chat(message, file_path)
    
    # 确保返回格式与前端兼容
    return {
        "reply": result.text,
        "session_id": session_id,
        "success": True,
        "data_type": "emission_result" if result.table_data else None,
        "table_data": result.table_data,  # 必须有这个字段
        "chart_data": result.chart_data,
        "download_file": result.download_file  # 必须有这个字段
    }
```

### 任务4：修复 tools/macro_emission.py

同样的修复应用到宏观排放工具：

```python
# 确保返回格式一致
return ToolResult(
    success=True,
    data={"summary": summary, "results": results},
    table_data={
        "headers": ["路段", "CO2 (g)", "NOx (g)", "PM2.5 (g)"],
        "rows": [[r["link_id"], r["CO2"], r["NOx"], r["PM2.5"]] for r in results]
    },
    download_file={"path": output_path, "filename": filename},
    summary=f"已计算{len(results)}个路段的排放"
)
```

### 任务5：添加调试日志

在关键位置添加日志，方便排查问题：

```python
# core/router.py - 在 _process_response 方法中

# 工具执行后
logger.info(f"Tool result keys: {list(result.keys())}")
logger.info(f"Tool result.data keys: {list(result.get('data', {}).keys())}")
logger.info(f"table_data present: {result.get('table_data') is not None}")
logger.info(f"download_file present: {result.get('download_file') is not None}")

# 数据提取后
table_data = self._extract_table_data(tool_results)
download_file = self._extract_download_file(tool_results)
logger.info(f"Extracted table_data: {table_data is not None}")
logger.info(f"Extracted download_file: {download_file}")
```

### 任务6：验证修复

修复完成后，创建测试脚本验证：

```python
# test_fix.py
import asyncio
from core.router import UnifiedRouter

async def test():
    router = UnifiedRouter(session_id="test")
    
    # 测试1：简单查询
    result = await router.chat("查询2020年小汽车的CO2排放因子")
    print(f"Test 1 - table_data: {result.table_data is not None}")
    print(f"Test 1 - text length: {len(result.text)}")
    
    # 测试2：文件计算（需要先上传文件）
    # result = await router.chat("帮我计算排放", file_path="test.csv")
    # print(f"Test 2 - table_data: {result.table_data}")
    # print(f"Test 2 - download_file: {result.download_file}")

asyncio.run(test())
```

## 检查清单

修复完成后，确认以下所有项目：

- [ ] `SYNTHESIS_PROMPT` 已修改，禁止 LLM 编造数据
- [ ] `tools/micro_emission.py` 返回正确的 `table_data` 格式
- [ ] `tools/macro_emission.py` 返回正确的 `table_data` 格式
- [ ] `core/router.py` 的 `_extract_table_data` 能正确提取数据
- [ ] `core/router.py` 的 `_extract_download_file` 能正确提取下载链接
- [ ] `api/routes.py` 返回的 JSON 包含 `table_data` 和 `download_file`
- [ ] 前端能显示表格数据
- [ ] 前端能显示下载链接
- [ ] LLM 回复简洁，不编造数据

## 执行顺序

1. 先阅读理解原架构的数据格式（任务1）
2. 修复 SYNTHESIS_PROMPT（任务2）
3. 修复工具返回格式（任务3.1, 任务4）
4. 修复数据提取逻辑（任务3.2）
5. 确认 API 返回格式（任务3.3）
6. 添加调试日志（任务5）
7. 重启服务器测试
8. 验证修复效果（任务6）

## 重要提醒

1. **不要修改 calculators/ 目录的计算逻辑**，那是另一个问题
2. **专注于数据传递链路**：工具 → router → API → 前端
3. **保持与原架构的输出格式兼容**
4. **每修复一步就测试一步**，不要一次性改太多

开始执行吧！先从任务1开始，理解原架构的数据格式。
