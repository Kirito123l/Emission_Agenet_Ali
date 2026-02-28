# Emission Agent 重构：文件预分析方案

## 背景

基于架构分析报告，发现了核心问题：**Planning 阶段与文件分析能力脱节**

```
当前流程（有问题）：
用户上传文件 → Planning(只看到文件路径，不知道内容) → LLM瞎猜 → 执行Skill → Skill才读取文件
                     ↑
                     问题在这里！LLM看不到文件内容，所以：
                     - 可能选错Skill（把宏观当微观）
                     - 追问不准确（文件已有车型比例还问用户指定车型）
                     - 甚至用query_knowledge去"查"文件格式
```

```
改进后流程：
用户上传文件 → 文件预分析(读取列名、判断类型) → Planning(拿到分析结果) → 精准决策 → 执行
                     ↑
                     新增这一步！让Planning阶段就知道文件里有什么
```

## 项目位置
`D:\Agent_MCP\emission_agent`

---

## 核心改动：新增 FileAnalyzer

### 1. 创建文件分析器

**新建文件**: `skills/common/file_analyzer.py`

```python
"""
文件预分析器

在 Planning 阶段之前分析上传的文件，提取关键信息供 LLM 决策使用。
这样 LLM 就能看到文件内容，做出准确的判断。
"""

import pandas as pd
from typing import Dict, List, Any, Optional
from pathlib import Path


class FileAnalyzer:
    """文件预分析器 - 快速分析文件结构，不进行完整计算"""
    
    # 微观排放特征关键词
    MICRO_KEYWORDS = {
        "time": ["time", "t", "时间", "timestamp", "time_sec", "秒"],
        "speed": ["speed", "velocity", "v", "速度", "车速", "speed_kph"],
        "acceleration": ["acc", "acceleration", "加速度", "accel", "a"],
        "grade": ["grade", "slope", "坡度", "gradient"],
    }
    
    # 宏观排放特征关键词
    MACRO_KEYWORDS = {
        "link_id": ["link", "segment", "road", "路段", "id", "编号"],
        "length": ["length", "len", "长度", "距离", "distance"],
        "flow": ["flow", "volume", "traffic", "流量", "交通量"],
        "fleet_mix": ["%", "pct", "比例", "percent", "ratio"],
    }
    
    # 微观排放必需列
    MICRO_REQUIRED = ["speed"]  # 至少需要速度
    
    # 宏观排放必需列
    MACRO_REQUIRED = ["length", "flow", "speed"]  # 需要长度、流量、速度
    
    def analyze(self, file_path: str) -> Dict[str, Any]:
        """
        分析文件，返回结构化的分析结果
        
        Args:
            file_path: 文件路径
            
        Returns:
            {
                "success": True/False,
                "task_type": "micro_emission" | "macro_emission" | "unknown",
                "confidence": 0.0-1.0,
                "columns": ["col1", "col2", ...],
                "row_count": 1200,
                "column_analysis": {
                    "time_column": "time" | None,
                    "speed_column": "speed_kph" | None,
                    "acceleration_column": "acc" | None,
                    "link_id_column": "segment_id" | None,
                    "length_column": "length_km" | None,
                    "flow_column": "traffic_flow" | None,
                    "fleet_mix_columns": ["Car%", "Bus%"] | [],
                },
                "has_fleet_mix": True/False,
                "missing_for_micro": ["acceleration"],  # 微观排放缺少的列
                "missing_for_macro": [],  # 宏观排放缺少的列
                "warnings": ["日流量可能需要转换为小时流量"],
                "sample_data": [...],  # 前3行数据预览
                "error": None | "错误信息"
            }
        """
        try:
            # 读取文件
            df = self._read_file(file_path)
            if df is None:
                return self._error_result(f"无法读取文件: {file_path}")
            
            columns = list(df.columns)
            row_count = len(df)
            
            # 分析列名
            column_analysis = self._analyze_columns(columns)
            
            # 判断任务类型
            task_type, confidence = self._infer_task_type(df, column_analysis)
            
            # 检查缺失列
            missing_for_micro = self._check_missing_columns(column_analysis, "micro")
            missing_for_macro = self._check_missing_columns(column_analysis, "macro")
            
            # 生成警告
            warnings = self._generate_warnings(df, column_analysis, task_type)
            
            # 获取样本数据
            sample_data = df.head(3).to_dict(orient="records")
            
            return {
                "success": True,
                "task_type": task_type,
                "confidence": confidence,
                "columns": columns,
                "row_count": row_count,
                "column_analysis": column_analysis,
                "has_fleet_mix": len(column_analysis.get("fleet_mix_columns", [])) > 0,
                "missing_for_micro": missing_for_micro,
                "missing_for_macro": missing_for_macro,
                "warnings": warnings,
                "sample_data": sample_data,
                "error": None
            }
            
        except Exception as e:
            return self._error_result(str(e))
    
    def _read_file(self, file_path: str) -> Optional[pd.DataFrame]:
        """读取Excel或CSV文件"""
        path = Path(file_path)
        try:
            if path.suffix.lower() in ['.xlsx', '.xls']:
                return pd.read_excel(file_path)
            elif path.suffix.lower() == '.csv':
                # 尝试不同编码
                for encoding in ['utf-8', 'gbk', 'gb2312', 'latin1']:
                    try:
                        return pd.read_csv(file_path, encoding=encoding)
                    except UnicodeDecodeError:
                        continue
                return pd.read_csv(file_path, encoding='utf-8', errors='ignore')
            else:
                return None
        except Exception:
            return None
    
    def _analyze_columns(self, columns: List[str]) -> Dict[str, Any]:
        """分析列名，识别各类字段"""
        columns_lower = [c.lower() for c in columns]
        result = {
            "time_column": None,
            "speed_column": None,
            "acceleration_column": None,
            "grade_column": None,
            "link_id_column": None,
            "length_column": None,
            "flow_column": None,
            "avg_speed_column": None,
            "fleet_mix_columns": [],
        }
        
        for i, col in enumerate(columns):
            col_lower = col.lower()
            
            # 检查微观特征
            for keyword in self.MICRO_KEYWORDS["time"]:
                if keyword in col_lower:
                    result["time_column"] = col
                    break
            
            for keyword in self.MICRO_KEYWORDS["speed"]:
                if keyword in col_lower:
                    result["speed_column"] = col
                    break
                    
            for keyword in self.MICRO_KEYWORDS["acceleration"]:
                if keyword in col_lower:
                    result["acceleration_column"] = col
                    break
                    
            for keyword in self.MICRO_KEYWORDS["grade"]:
                if keyword in col_lower:
                    result["grade_column"] = col
                    break
            
            # 检查宏观特征
            for keyword in self.MACRO_KEYWORDS["link_id"]:
                if keyword in col_lower and result["link_id_column"] is None:
                    result["link_id_column"] = col
                    break
                    
            for keyword in self.MACRO_KEYWORDS["length"]:
                if keyword in col_lower:
                    result["length_column"] = col
                    break
                    
            for keyword in self.MACRO_KEYWORDS["flow"]:
                if keyword in col_lower:
                    result["flow_column"] = col
                    break
            
            # 检查车型比例列（包含%或pct）
            if "%" in col or "pct" in col_lower or "比例" in col:
                result["fleet_mix_columns"].append(col)
        
        return result
    
    def _infer_task_type(self, df: pd.DataFrame, column_analysis: Dict) -> tuple:
        """推断任务类型，返回 (类型, 置信度)"""
        micro_score = 0
        macro_score = 0
        
        # 微观特征评分
        if column_analysis["time_column"]:
            micro_score += 2
        if column_analysis["speed_column"]:
            micro_score += 1
        if column_analysis["acceleration_column"]:
            micro_score += 2  # 加速度是微观的强特征
        if column_analysis["grade_column"]:
            micro_score += 1
        if len(df) > 100:  # 数据量大通常是微观
            micro_score += 1
        if len(df) > 500:
            micro_score += 1
        
        # 宏观特征评分
        if column_analysis["link_id_column"]:
            macro_score += 2  # 路段ID是宏观的强特征
        if column_analysis["length_column"]:
            macro_score += 2
        if column_analysis["flow_column"]:
            macro_score += 2
        if column_analysis["fleet_mix_columns"]:
            macro_score += 2  # 车型比例是宏观的强特征
        if len(df) <= 100:  # 数据量小通常是宏观
            macro_score += 1
        
        # 计算置信度
        total_score = micro_score + macro_score
        if total_score == 0:
            return "unknown", 0.0
        
        if micro_score > macro_score:
            confidence = micro_score / (micro_score + macro_score + 1)
            return "micro_emission", min(confidence, 0.95)
        elif macro_score > micro_score:
            confidence = macro_score / (micro_score + macro_score + 1)
            return "macro_emission", min(confidence, 0.95)
        else:
            return "unknown", 0.5
    
    def _check_missing_columns(self, column_analysis: Dict, task_type: str) -> List[str]:
        """检查缺失的必需列"""
        missing = []
        
        if task_type == "micro":
            if not column_analysis["speed_column"]:
                missing.append("速度列 (speed)")
            # 时间和加速度可以缺失，但要标记
            if not column_analysis["time_column"]:
                missing.append("时间列 (time) - 可选")
            if not column_analysis["acceleration_column"]:
                missing.append("加速度列 (acceleration) - 可选，将使用默认值0")
        
        elif task_type == "macro":
            if not column_analysis["length_column"]:
                missing.append("路段长度列 (length)")
            if not column_analysis["flow_column"]:
                missing.append("交通流量列 (flow)")
            if not column_analysis["speed_column"]:
                missing.append("平均速度列 (speed)")
        
        return missing
    
    def _generate_warnings(self, df: pd.DataFrame, column_analysis: Dict, task_type: str) -> List[str]:
        """生成警告信息"""
        warnings = []
        
        # 检查流量单位（日流量 vs 小时流量）
        if column_analysis["flow_column"]:
            flow_col = column_analysis["flow_column"]
            if "daily" in flow_col.lower() or "日" in flow_col:
                warnings.append(f"'{flow_col}' 似乎是日流量，将自动转换为小时流量（÷24）")
            
            # 检查流量值是否异常大（可能是日流量）
            if flow_col in df.columns:
                max_flow = df[flow_col].max()
                if max_flow > 10000:
                    warnings.append(f"流量最大值为 {max_flow}，如果是日流量请确认是否需要转换")
        
        # 检查速度单位
        if column_analysis["speed_column"]:
            speed_col = column_analysis["speed_column"]
            if speed_col in df.columns:
                max_speed = df[speed_col].max()
                if max_speed > 200:
                    warnings.append(f"速度最大值为 {max_speed}，请确认单位是否为 km/h")
        
        # 微观排放缺少加速度
        if task_type == "micro_emission" and not column_analysis["acceleration_column"]:
            warnings.append("缺少加速度列，将使用默认值0进行计算（可能影响准确性）")
        
        return warnings
    
    def _error_result(self, error_msg: str) -> Dict[str, Any]:
        """生成错误结果"""
        return {
            "success": False,
            "task_type": "unknown",
            "confidence": 0.0,
            "columns": [],
            "row_count": 0,
            "column_analysis": {},
            "has_fleet_mix": False,
            "missing_for_micro": [],
            "missing_for_macro": [],
            "warnings": [],
            "sample_data": [],
            "error": error_msg
        }
    
    def format_for_llm(self, analysis: Dict) -> str:
        """
        将分析结果格式化为 LLM 可读的文本
        
        这个文本会被添加到用户消息中，让 LLM 在 Planning 阶段看到文件内容
        """
        if not analysis["success"]:
            return f"⚠️ 文件分析失败: {analysis['error']}"
        
        lines = []
        lines.append("=" * 50)
        lines.append("📊 文件预分析结果")
        lines.append("=" * 50)
        
        # 基本信息
        lines.append(f"• 数据行数: {analysis['row_count']} 行")
        lines.append(f"• 列名: {', '.join(analysis['columns'])}")
        
        # 任务类型判断
        task_type_cn = {
            "micro_emission": "微观排放（轨迹数据）",
            "macro_emission": "宏观排放（路段数据）",
            "unknown": "未知类型"
        }
        lines.append(f"• 推断任务类型: {task_type_cn.get(analysis['task_type'], '未知')}")
        lines.append(f"• 判断置信度: {analysis['confidence']:.0%}")
        
        # 列识别结果
        ca = analysis["column_analysis"]
        lines.append("\n📋 已识别的列:")
        
        if analysis["task_type"] == "micro_emission":
            lines.append(f"  - 时间列: {ca.get('time_column') or '❌ 未识别'}")
            lines.append(f"  - 速度列: {ca.get('speed_column') or '❌ 未识别'}")
            lines.append(f"  - 加速度列: {ca.get('acceleration_column') or '⚠️ 未识别（将使用默认值）'}")
            lines.append(f"  - 坡度列: {ca.get('grade_column') or '⚠️ 未识别（将使用默认值）'}")
        
        elif analysis["task_type"] == "macro_emission":
            lines.append(f"  - 路段ID列: {ca.get('link_id_column') or '⚠️ 未识别'}")
            lines.append(f"  - 长度列: {ca.get('length_column') or '❌ 未识别'}")
            lines.append(f"  - 流量列: {ca.get('flow_column') or '❌ 未识别'}")
            lines.append(f"  - 速度列: {ca.get('speed_column') or '❌ 未识别'}")
            
            if ca.get("fleet_mix_columns"):
                lines.append(f"  - 车型比例列: {', '.join(ca['fleet_mix_columns'])} ✅")
            else:
                lines.append("  - 车型比例列: ❌ 未识别（需要指定或使用默认值）")
        
        # 车型比例信息（对宏观排放很重要）
        if analysis["has_fleet_mix"]:
            lines.append("\n✅ 文件已包含车型比例信息，无需用户指定车型")
        elif analysis["task_type"] == "macro_emission":
            lines.append("\n⚠️ 文件未包含车型比例信息，需要询问用户或使用默认值")
        elif analysis["task_type"] == "micro_emission":
            lines.append("\n⚠️ 微观排放需要指定单一车型（如：小汽车、公交车等）")
        
        # 警告
        if analysis["warnings"]:
            lines.append("\n⚠️ 注意事项:")
            for warning in analysis["warnings"]:
                lines.append(f"  - {warning}")
        
        # 数据预览
        if analysis["sample_data"]:
            lines.append("\n📄 数据预览 (前3行):")
            for i, row in enumerate(analysis["sample_data"][:3], 1):
                # 截断过长的值
                row_str = ", ".join(f"{k}={str(v)[:20]}" for k, v in list(row.items())[:5])
                lines.append(f"  行{i}: {row_str}...")
        
        lines.append("=" * 50)
        
        return "\n".join(lines)


# 创建全局实例
file_analyzer = FileAnalyzer()
```

---

### 2. 修改 Agent 核心流程

**修改文件**: `agent/core.py`

在 `chat()` 方法中，Planning 之前添加文件预分析：

```python
# 在文件顶部添加导入
from skills.common.file_analyzer import file_analyzer

# 在 chat() 方法中，找到 Planning 调用之前的位置
async def chat(self, user_input: str, context: ConversationContext) -> AsyncGenerator[str, None]:
    """处理用户输入并生成回复"""
    
    # ===== 新增：文件预分析 =====
    file_analysis = None
    enhanced_input = user_input
    
    if "文件已上传，路径:" in user_input:
        # 提取文件路径
        import re
        match = re.search(r'文件已上传，路径:\s*([^\n]+)', user_input)
        if match:
            file_path = match.group(1).strip()
            
            # 执行文件预分析
            file_analysis = file_analyzer.analyze(file_path)
            
            # 将分析结果格式化并添加到消息中
            analysis_text = file_analyzer.format_for_llm(file_analysis)
            enhanced_input = f"{user_input}\n\n{analysis_text}"
            
            # 保存到上下文，供后续使用
            context.file_analysis = file_analysis
    
    # ===== 文件预分析结束 =====
    
    # 使用增强后的输入进行 Planning
    # 原来是: plan_result = await self._plan_with_validation(user_input, context)
    plan_result = await self._plan_with_validation(enhanced_input, context)
    
    # ... 后续代码不变 ...
```

---

### 3. 简化 System Prompt

**修改文件**: `agent/prompts/system.py`

因为现在 LLM 能看到文件分析结果，可以大幅简化 prompt：

```python
# 替换原有的任务类型判断规则和文件处理规则

TASK_TYPE_AND_FILE_RULES = """
## 文件处理规则

当用户上传文件时，系统会自动进行文件预分析，你会在消息中看到类似这样的内容：

```
==================================================
📊 文件预分析结果
==================================================
• 数据行数: 35 行
• 列名: segment_id, length_km, flow, speed, Car%, Bus%
• 推断任务类型: 宏观排放（路段数据）
• 判断置信度: 85%

📋 已识别的列:
  - 路段ID列: segment_id
  - 长度列: length_km
  - 流量列: flow
  - 速度列: speed
  - 车型比例列: Car%, Bus% ✅

✅ 文件已包含车型比例信息，无需用户指定车型
==================================================
```

### 根据文件分析结果决策

1. **如果分析显示是微观排放**:
   - 使用 `calculate_micro_emission` 技能
   - 必须有 `vehicle_type` 参数（文件分析会提示需要指定）
   - 如果用户没指定车型，生成追问

2. **如果分析显示是宏观排放**:
   - 使用 `calculate_macro_emission` 技能
   - 如果文件已有车型比例列（分析结果会显示 ✅），直接计算，不追问车型
   - 如果文件没有车型比例列，询问是否使用默认比例

3. **如果分析失败或类型未知**:
   - 根据用户描述判断（提到"轨迹"用微观，提到"路段"用宏观）
   - 或者询问用户

### 追问规则

基于文件分析结果生成追问：

**微观排放追问示例**（文件分析显示缺少车型）:
```
我已分析您上传的文件：

{直接引用文件分析结果}

文件是轨迹数据，需要指定车辆类型。请选择：
1. 小汽车 (Passenger Car)
2. 公交车 (Transit Bus)
3. 轻型货车 (Light Commercial Truck)
4. 重型货车 (Combination Long-haul Truck)
5. 其他（请说明）
```

**宏观排放追问示例**（文件分析显示无车型比例）:
```
我已分析您上传的文件：

{直接引用文件分析结果}

文件未包含车型比例信息。请选择：
1. 使用默认车型比例（小汽车70%、公交10%、货车20%）
2. 手动指定车型比例
```

**不需要追问的情况**:
- 宏观排放文件已有车型比例列
- 用户已在消息中指定了车型
- 用户说"直接计算"/"使用默认值"

### 错误示例（不要这样做）

❌ 忽略文件分析结果，凭猜测判断任务类型
❌ 文件分析显示已有车型比例，还追问车型
❌ 使用 query_knowledge 查询文件格式（文件分析已经做了这件事）
❌ 追问时不展示文件分析结果
"""
```

---

### 4. 修改 ConversationContext

**修改文件**: `agent/context.py`

添加 `file_analysis` 字段：

```python
@dataclass
class ConversationContext:
    # ... 现有字段 ...
    
    # 新增：文件分析结果
    file_analysis: Optional[Dict[str, Any]] = None
```

---

### 5. 可选优化：代码生成追问

如果想要更稳定的追问质量，可以用代码生成追问而不是让 LLM 生成：

**新建文件**: `agent/clarification_generator.py`

```python
"""
追问生成器

基于文件分析结果生成结构化的追问，不依赖 LLM 的随机性。
"""

from typing import Dict, Optional


class ClarificationGenerator:
    """追问生成器"""
    
    def generate(
        self,
        file_analysis: Dict,
        user_specified_params: Dict
    ) -> Optional[str]:
        """
        根据文件分析结果和用户已提供的参数，生成追问
        
        Returns:
            追问消息，如果不需要追问则返回 None
        """
        if not file_analysis or not file_analysis.get("success"):
            return None
        
        task_type = file_analysis["task_type"]
        
        if task_type == "micro_emission":
            return self._generate_micro_clarification(file_analysis, user_specified_params)
        elif task_type == "macro_emission":
            return self._generate_macro_clarification(file_analysis, user_specified_params)
        else:
            return self._generate_unknown_clarification(file_analysis)
    
    def _generate_micro_clarification(
        self,
        file_analysis: Dict,
        user_params: Dict
    ) -> Optional[str]:
        """生成微观排放的追问"""
        
        # 如果用户已指定车型，不需要追问
        if user_params.get("vehicle_type"):
            return None
        
        # 构建追问
        lines = []
        lines.append("我已分析您上传的文件：\n")
        
        # 文件概览
        lines.append(f"📊 **文件概览**：共 {file_analysis['row_count']} 条轨迹数据\n")
        
        # 已识别的列
        ca = file_analysis["column_analysis"]
        lines.append("✅ **已识别的字段**：")
        if ca.get("time_column"):
            lines.append(f"- 时间: {ca['time_column']}")
        if ca.get("speed_column"):
            lines.append(f"- 速度: {ca['speed_column']}")
        if ca.get("acceleration_column"):
            lines.append(f"- 加速度: {ca['acceleration_column']}")
        else:
            lines.append("- 加速度: ⚠️ 未识别（将使用默认值0）")
        
        lines.append("")
        
        # 缺少的信息
        lines.append("❌ **缺少必需信息**：")
        lines.append("- 车辆类型（用于选择对应的排放因子）")
        lines.append("")
        
        # 选项
        lines.append("请指定车辆类型：")
        lines.append("1. 小汽车 (Passenger Car) - 私家车、出租车、网约车")
        lines.append("2. 公交车 (Transit Bus) - 城市公交")
        lines.append("3. 轻型货车 (Light Commercial Truck) - 快递车、小货车")
        lines.append("4. 重型货车 (Combination Long-haul Truck) - 大货车、半挂车")
        lines.append("5. 其他（请说明）")
        lines.append("")
        lines.append("请回复数字或车型名称。")
        
        return "\n".join(lines)
    
    def _generate_macro_clarification(
        self,
        file_analysis: Dict,
        user_params: Dict
    ) -> Optional[str]:
        """生成宏观排放的追问"""
        
        # 如果文件已有车型比例，不需要追问
        if file_analysis["has_fleet_mix"]:
            return None
        
        # 如果用户已指定车型比例，不需要追问
        if user_params.get("fleet_mix") or user_params.get("default_fleet_mix"):
            return None
        
        # 构建追问
        lines = []
        lines.append("我已分析您上传的文件：\n")
        
        # 文件概览
        lines.append(f"📊 **文件概览**：共 {file_analysis['row_count']} 条路段数据\n")
        
        # 已识别的列
        ca = file_analysis["column_analysis"]
        lines.append("✅ **已识别的字段**：")
        if ca.get("link_id_column"):
            lines.append(f"- 路段ID: {ca['link_id_column']}")
        if ca.get("length_column"):
            lines.append(f"- 路段长度: {ca['length_column']}")
        if ca.get("flow_column"):
            lines.append(f"- 交通流量: {ca['flow_column']}")
        if ca.get("speed_column"):
            lines.append(f"- 平均速度: {ca['speed_column']}")
        
        lines.append("")
        
        # 缺少车型比例
        lines.append("⚠️ **文件未包含车型比例信息**")
        lines.append("")
        
        # 选项
        lines.append("请选择：")
        lines.append("1. 使用默认车型比例（小汽车70%、公交10%、货车20%）")
        lines.append("2. 手动指定车型比例")
        lines.append("")
        lines.append("回复 `1` 或 `默认` 使用默认比例，或告诉我具体的车型比例。")
        
        return "\n".join(lines)
    
    def _generate_unknown_clarification(self, file_analysis: Dict) -> str:
        """文件类型未知时的追问"""
        lines = []
        lines.append("我已尝试分析您上传的文件，但无法确定数据类型。\n")
        lines.append(f"📋 文件列名: {', '.join(file_analysis['columns'][:10])}")
        if len(file_analysis['columns']) > 10:
            lines.append(f"   ... 共 {len(file_analysis['columns'])} 列")
        lines.append("")
        lines.append("请问这是什么类型的数据？")
        lines.append("1. 轨迹数据（微观排放）- 包含时间、速度、加速度等")
        lines.append("2. 路段数据（宏观排放）- 包含路段长度、流量、速度等")
        
        return "\n".join(lines)


# 创建全局实例
clarification_generator = ClarificationGenerator()
```

---

## 文件修改清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `skills/common/file_analyzer.py` | **新建** | 文件预分析器 |
| `agent/core.py` | **修改** | 在 Planning 前添加文件预分析 |
| `agent/context.py` | **修改** | 添加 file_analysis 字段 |
| `agent/prompts/system.py` | **修改** | 简化任务类型判断和文件处理规则 |
| `agent/clarification_generator.py` | **新建**（可选） | 代码生成追问 |

---

## 测试用例

### 测试1：微观排放文件
```
上传: micro_trajectory.csv (有 time, speed, acceleration 列)
消息: "帮我计算排放"

期望:
1. 文件分析识别为微观排放
2. 追问车型（因为微观需要指定单一车型）
3. 追问内容包含文件分析结果
```

### 测试2：宏观排放文件（有车型比例）
```
上传: macro_network.csv (有 link_id, length, flow, speed, Car%, Bus% 列)
消息: "帮我计算排放"

期望:
1. 文件分析识别为宏观排放
2. 识别到车型比例列
3. 不追问，直接计算
```

### 测试3：宏观排放文件（无车型比例）
```
上传: macro_simple.csv (有 link_id, length, flow, speed 列，无 % 列)
消息: "帮我计算排放"

期望:
1. 文件分析识别为宏观排放
2. 未识别到车型比例列
3. 追问是否使用默认车型比例
```

### 测试4：用户直接指定参数
```
上传: any_file.csv
消息: "帮我计算小汽车的CO2排放"

期望:
1. 从消息中识别到 vehicle_type=小汽车, pollutants=[CO2]
2. 不需要追问（用户已提供参数）
3. 直接计算
```

---

## 执行顺序

1. 创建 `skills/common/file_analyzer.py`
2. 修改 `agent/context.py` 添加 file_analysis 字段
3. 修改 `agent/core.py` 添加文件预分析逻辑
4. 修改 `agent/prompts/system.py` 简化规则
5. （可选）创建 `agent/clarification_generator.py`
6. 重启服务器测试

---

## 核心思想总结

**改进前**：Planning 阶段是"盲人摸象"，LLM 只知道有个文件，不知道里面是什么

**改进后**：Planning 阶段是"明察秋毫"，LLM 在做决策前已经知道：
- 文件有多少行
- 有哪些列
- 是微观还是宏观
- 有没有车型比例
- 有什么警告

这样 LLM 就能做出准确的判断，不会再出现：
- 把宏观文件当微观处理
- 文件已有车型比例还追问用户
- 用 query_knowledge 去"查"文件格式
