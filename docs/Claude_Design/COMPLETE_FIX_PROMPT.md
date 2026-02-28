# 完整修复任务：恢复排放计算功能

## 问题诊断总结

根据 `ARCHITECTURE_DATA_FORMAT_COMPARISON.md` 的分析，新架构存在以下问题：

| 问题 | 优先级 | 影响 |
|------|--------|------|
| table_data 不完整 | 🔴 高 | 前端显示"暂无数据" |
| Synthesis Prompt 过于宽松 | 🔴 高 | LLM 编造数据（幻觉严重） |
| 缺少数据过滤机制 | 🟡 中 | LLM 无法获得准确数据 |
| download_file 位置不一致 | 🟢 低 | 下载链接可能失效 |

---

## 修复任务

### 任务 1：修复 table_data 提取逻辑 🔴

**文件**: `core/router.py`

**问题**: 当前 `_extract_table_data` 只返回 summary，缺少前端必需的字段：
- `columns` (列名)
- `preview_rows` (数据行)
- `total_rows`, `total_columns` (统计)

**修复**: 找到 `_extract_table_data` 方法（大约在 468-486 行），替换为：

```python
def _extract_table_data(self, tool_results: list) -> Optional[Dict]:
    """从工具结果提取表格数据，格式与前端 renderResultTable 兼容"""
    for r in tool_results:
        # 优先使用工具直接返回的 table_data
        if r["result"].get("table_data"):
            return r["result"]["table_data"]
        
        # 从计算工具的 data.results 构建表格数据
        if r["name"] in ["calculate_micro_emission", "calculate_macro_emission"]:
            data = r["result"].get("data", {})
            results = data.get("results", [])
            summary = data.get("summary", {})
            
            if not results:
                # 如果没有详细结果，至少返回汇总
                if summary:
                    total_emissions = summary.get("total_emissions_g", {}) or summary.get("total_emissions", {})
                    return {
                        "type": r["name"],
                        "columns": ["指标", "数值"],
                        "preview_rows": [
                            {"指标": k, "数值": f"{v:.2f} g"} 
                            for k, v in total_emissions.items()
                        ],
                        "total_rows": len(total_emissions),
                        "total_columns": 2,
                        "summary": summary
                    }
                continue
            
            # 从第一条结果提取列名
            first_result = results[0]
            
            # 微观排放的列名
            if r["name"] == "calculate_micro_emission":
                # 基础列
                columns = ["t", "speed_kph"]
                # 如果有加速度
                if "acceleration_mps2" in first_result:
                    columns.append("acceleration_mps2")
                # VSP
                if "vsp" in first_result or "VSP" in first_result:
                    columns.append("VSP")
                # 排放物列
                emissions = first_result.get("emissions", {})
                columns.extend(list(emissions.keys()))
                
                # 构建数据行
                preview_rows = []
                for row in results[:100]:  # 限制前100行
                    row_data = {
                        "t": row.get("t", row.get("time", "")),
                        "speed_kph": f"{row.get('speed_kph', row.get('speed', 0)):.1f}"
                    }
                    if "acceleration_mps2" in row:
                        row_data["acceleration_mps2"] = f"{row['acceleration_mps2']:.2f}"
                    if "vsp" in row:
                        row_data["VSP"] = f"{row['vsp']:.2f}"
                    elif "VSP" in row:
                        row_data["VSP"] = f"{row['VSP']:.2f}"
                    # 排放数据
                    for pol, val in row.get("emissions", {}).items():
                        row_data[pol] = f"{val:.4f}"
                    preview_rows.append(row_data)
                    
            # 宏观排放的列名
            else:  # calculate_macro_emission
                columns = ["link_id", "link_length_km", "traffic_flow_vph", "avg_speed_kph"]
                # 排放物列
                emissions = first_result.get("emissions", {})
                columns.extend([f"{k}_g" for k in emissions.keys()])
                
                # 构建数据行
                preview_rows = []
                for row in results[:100]:
                    row_data = {
                        "link_id": row.get("link_id", ""),
                        "link_length_km": f"{row.get('link_length_km', 0):.3f}",
                        "traffic_flow_vph": f"{row.get('traffic_flow_vph', 0):.0f}",
                        "avg_speed_kph": f"{row.get('avg_speed_kph', 0):.1f}"
                    }
                    for pol, val in row.get("emissions", {}).items():
                        row_data[f"{pol}_g"] = f"{val:.2f}"
                    preview_rows.append(row_data)
            
            return {
                "type": r["name"],
                "columns": columns,
                "preview_rows": preview_rows,
                "total_rows": len(results),
                "total_columns": len(columns),
                "summary": summary,
                "total_emissions": summary.get("total_emissions_g", {}) or summary.get("total_emissions", {})
            }
    
    return None
```

---

### 任务 2：修复 Synthesis Prompt 🔴

**文件**: `core/router.py`

**问题**: 当前 SYNTHESIS_PROMPT 过于宽松，导致 LLM 编造数据。

**修复**: 找到 `SYNTHESIS_PROMPT` 定义（大约在 17-30 行），替换为：

```python
SYNTHESIS_PROMPT = """你是机动车排放计算助手。请基于工具执行结果生成简洁回答。

## 严格要求
1. **只使用实际数据**: 只使用下方提供的工具执行结果，不要编造任何数值
2. **禁止编造分析**: 
   - ❌ 不要说"排放峰值出现在第X个点"
   - ❌ 不要说"空调导致增加X%"
   - ❌ 不要说"相当于X棵树的固碳量"
   - ❌ 不要进行任何数学计算或单位转换
3. **简洁格式**: 只需简短说明计算完成，详细数据由系统表格展示

## 回答模板

成功时：
```
已完成排放计算。

查询参数：
- 车型：{vehicle_type}
- 污染物：{pollutants}
- 年份：{model_year}
- 季节：{season}

计算结果：
- 数据点数：{num_points}
- 总排放量见下方表格

结果文件已生成，可点击下载查看详细数据。
```

失败时：
```
计算遇到问题：{error_message}

建议：{具体建议}
```

## 工具执行结果
{results}

请基于以上结果生成回答，不要添加任何未在结果中出现的数据或分析。
"""
```

---

### 任务 3：添加数据过滤机制 🟡

**文件**: `core/router.py`

**问题**: 当前没有过滤机制，LLM 只能看到简单的 summary 文本。

**修复**: 添加新方法 `_filter_results_for_synthesis`：

```python
def _filter_results_for_synthesis(self, tool_results: list) -> Dict:
    """
    过滤工具结果，只保留关键信息供 Synthesis 使用
    
    设计原则：
    - 保留足够信息让 LLM 生成准确回答
    - 移除大量详细数据（避免 token 浪费）
    - 保留汇总和关键参数
    """
    filtered = {}
    
    for r in tool_results:
        tool_name = r["name"]
        result = r["result"]
        
        # 处理失败的情况
        if not result.get("success"):
            filtered[tool_name] = {
                "success": False,
                "error": result.get("message") or result.get("error") or "未知错误"
            }
            continue
        
        data = result.get("data", {})
        
        # 对于排放计算工具，只保留汇总信息
        if tool_name in ["calculate_micro_emission", "calculate_macro_emission"]:
            summary = data.get("summary", {})
            results_list = data.get("results", [])
            
            # 提取查询参数（如果有）
            query_params = {}
            if data.get("vehicle_type"):
                query_params["vehicle_type"] = data["vehicle_type"]
            if data.get("pollutants"):
                query_params["pollutants"] = data["pollutants"]
            if data.get("model_year"):
                query_params["model_year"] = data["model_year"]
            if data.get("season"):
                query_params["season"] = data["season"]
            
            filtered[tool_name] = {
                "success": True,
                "summary": result.get("summary", "计算完成"),
                "num_points": len(results_list),
                "total_emissions": summary.get("total_emissions_g", {}) or summary.get("total_emissions", {}),
                "total_distance_km": summary.get("total_distance_km"),
                "total_time_s": summary.get("total_time_s"),
                "query_params": query_params,
                "has_download_file": bool(data.get("download_file"))
            }
        
        # 对于排放因子查询
        elif tool_name == "query_emission_factors":
            filtered[tool_name] = {
                "success": True,
                "summary": result.get("summary", "查询完成"),
                "data": data  # 排放因子数据量不大，可以保留
            }
        
        # 对于文件分析
        elif tool_name == "analyze_file":
            filtered[tool_name] = {
                "success": True,
                "file_type": data.get("detected_type"),
                "columns": data.get("columns"),
                "row_count": data.get("row_count")
            }
        
        # 其他工具
        else:
            filtered[tool_name] = {
                "success": True,
                "data": data
            }
    
    return filtered
```

---

### 任务 4：修改 `_synthesize_results` 方法 🟡

**文件**: `core/router.py`

**问题**: 当前只传递简单的 summary 文本给 LLM。

**修复**: 找到 `_synthesize_results` 方法，修改为使用过滤后的数据：

```python
async def _synthesize_results(self, context, original_response, tool_results: list) -> str:
    """
    综合工具执行结果，生成自然语言回复
    """
    # 1. 过滤数据，只保留关键信息
    filtered_results = self._filter_results_for_synthesis(tool_results)
    
    # 2. 格式化为 JSON
    import json
    results_json = json.dumps(filtered_results, ensure_ascii=False, indent=2)
    
    logger.info(f"Filtered results for synthesis:\n{results_json[:500]}...")
    
    # 3. 构建 synthesis prompt
    synthesis_prompt = SYNTHESIS_PROMPT.replace("{results}", results_json)
    
    # 4. 构建消息
    # 注意：不要传递 tools 参数，只做纯文本生成
    synthesis_messages = [
        {"role": "user", "content": context.messages[-1]["content"] if context.messages else "请总结计算结果"}
    ]
    
    # 5. 调用 LLM
    synthesis_response = await self.llm.chat(
        messages=synthesis_messages,
        system=synthesis_prompt
    )
    
    logger.info(f"Synthesis complete. Response length: {len(synthesis_response.content)} chars")
    
    # 检查是否有幻觉迹象
    hallucination_keywords = ["相当于", "棵树", "峰值出现在", "空调导致", "不完全燃烧"]
    for kw in hallucination_keywords:
        if kw in synthesis_response.content:
            logger.warning(f"⚠️ Possible hallucination detected: '{kw}' found in response")
    
    return synthesis_response.content
```

---

### 任务 5：修复 download_file 提取 🟢

**文件**: `core/router.py`

**问题**: download_file 位置不一致，可能提取失败。

**修复**: 找到 `_extract_download_file` 方法，确保能从多个位置提取：

```python
def _extract_download_file(self, tool_results: list) -> Optional[Dict]:
    """
    从工具结果提取下载文件信息
    
    返回格式：{"path": "...", "filename": "..."}
    """
    for r in tool_results:
        result = r["result"]
        
        # 位置1：顶层 download_file
        if result.get("download_file"):
            df = result["download_file"]
            if isinstance(df, str):
                return {"path": df, "filename": df.split("/")[-1]}
            return df
        
        # 位置2：data.download_file
        data = result.get("data", {})
        if data and data.get("download_file"):
            df = data["download_file"]
            if isinstance(df, str):
                return {"path": df, "filename": df.split("/")[-1]}
            return df
        
        # 位置3：metadata.download_file（兼容旧格式）
        metadata = result.get("metadata", {})
        if metadata and metadata.get("download_file"):
            return metadata["download_file"]
    
    return None
```

---

### 任务 6：确保 API 返回格式正确 🟢

**文件**: `api/routes.py`

**检查**: 确认 chat 路由返回的格式包含所有必需字段：

```python
# 找到 chat 路由的返回部分，确保格式如下：

return {
    "reply": result.text,
    "session_id": session_id,
    "success": True,
    "data_type": "table" if result.table_data else None,
    "chart_data": result.chart_data,
    "table_data": result.table_data,  # 必须有完整的表格数据
    "file_id": session_id if result.download_file else None
}
```

---

## 验证步骤

修复完成后，请执行以下验证：

### 1. 重启服务器
```bash
.\scripts\restart_server.ps1
```

### 2. 测试微观排放计算
- 上传 `micro_05_minimal.csv`
- 输入："帮我计算这个大货车的排放"
- 验证：
  - [ ] 前端显示表格（不是"暂无数据"）
  - [ ] 表格有列名和数据行
  - [ ] 下载按钮可用
  - [ ] LLM 回复简洁，不编造数据

### 3. 测试宏观排放计算
- 上传路段数据文件
- 输入："计算这些路段的排放"
- 验证同上

### 4. 检查日志
确认以下日志正常：
- `Filtered results for synthesis: ...`
- `Synthesis complete. Response length: ...`
- 没有 `⚠️ Possible hallucination detected` 警告

---

## 修改文件清单

| 文件 | 修改内容 |
|------|---------|
| `core/router.py` | 修复 `_extract_table_data`、`SYNTHESIS_PROMPT`、添加 `_filter_results_for_synthesis`、修改 `_synthesize_results`、修复 `_extract_download_file` |
| `api/routes.py` | 检查返回格式（可能不需要修改） |

---

## 注意事项

1. **不要修改 calculators/ 目录**：计算逻辑是另一个问题，先确保数据能正确显示
2. **不要修改 tools/ 目录的返回格式**：在 router 层做适配，避免影响工具逻辑
3. **保持向后兼容**：新的提取逻辑要能处理多种数据格式
4. **每步测试**：每修改一个方法就测试一次，不要一次性改完

开始执行修复吧！
