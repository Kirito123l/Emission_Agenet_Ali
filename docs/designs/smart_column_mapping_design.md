# 智能表格处理方案设计

## 问题分析

### 当前方案的缺陷

```python
# 当前：硬编码列名映射
SPEED_COLUMNS = ["speed_kph", "speed_kmh", "speed", "车速", "速度", "link_avg_speed_kmh", ...]
FLOW_COLUMNS = ["traffic_flow_vph", "flow_vph", "volume", "交通流量", ...]

# 问题：
# 1. 无法覆盖所有可能的列名变体
# 2. 每次遇到新列名都要修改代码
# 3. 车型映射更复杂（13种车型 × 多种中英文别名）
# 4. 用户体验差：经常报错"未找到XXX列"
```

### 理想方案

让Agent智能理解用户的列名，自动建立映射关系，而不是依赖硬编码。

---

## 方案设计：LLM辅助的智能列名映射

### 核心思路

```
用户上传文件
    ↓
提取列名 + 前2行数据（作为样本）
    ↓
构造Prompt，让LLM理解并映射列名
    ↓
LLM返回标准化的JSON映射
    ↓
使用映射关系处理数据
```

### 优势

1. **零硬编码**：不需要预定义列名列表
2. **自适应**：能理解任何合理的列名
3. **智能推断**：根据数据内容推断列含义
4. **低成本**：只调用一次LLM，处理列名映射
5. **向后兼容**：如果LLM失败，回退到硬编码方案

---

## 详细设计

### 1. 文件预处理函数

```python
# skills/common/file_analyzer.py

import pandas as pd
import json
from typing import Dict, Any, Optional, Tuple

def analyze_file_structure(file_path: str, max_rows: int = 3) -> Dict[str, Any]:
    """
    分析文件结构，提取列名和样本数据
    
    Returns:
        {
            "columns": ["link_id", "length_km", "volume_vph", ...],
            "sample_data": [
                {"link_id": "L001", "length_km": 2.5, "volume_vph": 5000, ...},
                {"link_id": "L002", "length_km": 1.8, "volume_vph": 3500, ...}
            ],
            "row_count": 100,
            "file_type": "csv"
        }
    """
    # 读取文件
    if file_path.endswith('.csv'):
        df = pd.read_csv(file_path, nrows=max_rows + 1)  # +1 for header detection
    else:
        df = pd.read_excel(file_path, nrows=max_rows + 1)
    
    # 清理列名
    df.columns = df.columns.str.strip()
    
    # 提取样本数据
    sample_data = df.head(max_rows).to_dict('records')
    
    return {
        "columns": list(df.columns),
        "sample_data": sample_data,
        "row_count": len(pd.read_csv(file_path)) if file_path.endswith('.csv') else len(pd.read_excel(file_path)),
        "file_type": file_path.split('.')[-1]
    }
```

### 2. LLM列名映射Prompt

```python
# skills/common/column_mapper.py

COLUMN_MAPPING_PROMPT = """
你是一个数据分析专家。请分析以下表格数据，将用户的列名映射到标准字段。

## 用户文件信息

**列名**: {columns}

**样本数据（前2行）**:
```json
{sample_data}
```

## 任务类型: {task_type}

## 标准字段定义

{field_definitions}

## 输出要求

请返回一个JSON对象，格式如下：
```json
{{
    "mapping": {{
        "用户列名1": "标准字段名1",
        "用户列名2": "标准字段名2",
        ...
    }},
    "fleet_mix": {{
        "用户车型列名1": "标准车型名1",
        ...
    }},
    "confidence": 0.95,
    "warnings": ["可能的问题1", ...],
    "unmapped_columns": ["无法识别的列1", ...]
}}
```

## 映射规则

1. **智能匹配**：根据列名含义和数据内容推断对应的标准字段
2. **车型识别**：识别所有包含车型名称的列（通常带有%符号）
3. **单位推断**：根据数据范围推断单位（如速度列值在0-200可能是km/h）
4. **灵活处理**：即使列名拼写略有不同，也要尽量匹配

## 示例

输入列名: ["link_id", "len_km", "vol_per_hr", "avg_spd_kmh", "car_pct", "truck_pct"]
样本数据: [{{"link_id": "L1", "len_km": 2.5, "vol_per_hr": 5000, "avg_spd_kmh": 60, "car_pct": 70, "truck_pct": 30}}]

输出:
```json
{{
    "mapping": {{
        "link_id": "link_id",
        "len_km": "link_length_km",
        "vol_per_hr": "traffic_flow_vph",
        "avg_spd_kmh": "avg_speed_kph"
    }},
    "fleet_mix": {{
        "car_pct": "Passenger Car",
        "truck_pct": "Combination Long-haul Truck"
    }},
    "confidence": 0.9,
    "warnings": [],
    "unmapped_columns": []
}}
```

请只返回JSON，不要有其他内容。
"""

# 不同任务类型的字段定义
FIELD_DEFINITIONS = {
    "micro_emission": """
### 微观排放计算（轨迹数据）

**必需字段**:
- `speed_kph`: 速度（km/h），数值范围通常0-200

**可选字段**:
- `time_sec`: 时间（秒），从0开始递增
- `acceleration_mps2`: 加速度（m/s²），通常-5到5
- `grade_pct`: 坡度（%），通常-10到10
""",
    
    "macro_emission": """
### 宏观排放计算（路段数据）

**必需字段**:
- `link_id`: 路段标识，字符串
- `link_length_km`: 路段长度（km），正数
- `traffic_flow_vph`: 交通流量（辆/小时），通常100-50000
- `avg_speed_kph`: 平均速度（km/h），通常10-120

**可选字段（车型分布）**:
识别包含以下13种MOVES标准车型名称的列：

| 标准车型名 | 常见中文名 | Source Type ID |
|-----------|-----------|----------------|
| Motorcycle | 摩托车 | 11 |
| Passenger Car | 小汽车、乘用车、轿车 | 21 |
| Passenger Truck | 客车、皮卡、SUV | 31 |
| Light Commercial Truck | 轻型货车、小货车、面包车 | 32 |
| Intercity Bus | 城际客车、长途客车 | 41 |
| Transit Bus | 公交车、巴士 | 42 |
| School Bus | 校车 | 43 |
| Refuse Truck | 垃圾车、环卫车 | 51 |
| Single Unit Short-haul Truck | 短途货车、城配货车 | 52 |
| Single Unit Long-haul Truck | 长途货车 | 53 |
| Motor Home | 房车、旅居车 | 54 |
| Combination Short-haul Truck | 半挂短途、短途挂车 | 61 |
| Combination Long-haul Truck | 重型货车、大货车、半挂长途 | 62 |

车型列通常以百分比形式出现（带有%、pct、percent等后缀）。
"""
}
```

### 3. 列名映射执行函数

```python
# skills/common/column_mapper.py

from typing import Dict, Any, Optional
import json

async def map_columns_with_llm(
    file_info: Dict[str, Any],
    task_type: str,  # "micro_emission" or "macro_emission"
    llm_client: Any
) -> Dict[str, Any]:
    """
    使用LLM智能映射列名
    
    Args:
        file_info: analyze_file_structure() 的返回值
        task_type: 任务类型
        llm_client: LLM客户端
    
    Returns:
        {
            "mapping": {"用户列名": "标准列名", ...},
            "fleet_mix": {"用户车型列名": "标准车型名", ...},
            "confidence": 0.95,
            "warnings": [...],
            "unmapped_columns": [...]
        }
    """
    # 构造Prompt
    prompt = COLUMN_MAPPING_PROMPT.format(
        columns=json.dumps(file_info["columns"], ensure_ascii=False),
        sample_data=json.dumps(file_info["sample_data"], ensure_ascii=False, indent=2),
        task_type=task_type,
        field_definitions=FIELD_DEFINITIONS[task_type]
    )
    
    # 调用LLM
    response = await llm_client.chat(
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1,  # 低温度，确保输出稳定
        max_tokens=1000
    )
    
    # 解析JSON
    try:
        # 提取JSON（处理可能的markdown代码块）
        content = response.content
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0]
        elif "```" in content:
            content = content.split("```")[1].split("```")[0]
        
        result = json.loads(content.strip())
        return result
    except json.JSONDecodeError as e:
        # LLM返回格式错误，回退到硬编码方案
        print(f"[WARNING] LLM列名映射失败: {e}")
        return None


def apply_column_mapping(df: pd.DataFrame, mapping: Dict[str, str]) -> pd.DataFrame:
    """
    应用列名映射
    """
    # 只重命名存在的列
    rename_dict = {k: v for k, v in mapping.items() if k in df.columns}
    return df.rename(columns=rename_dict)
```

### 4. 集成到Skill中

```python
# skills/macro_emission/excel_handler.py

from skills.common.file_analyzer import analyze_file_structure
from skills.common.column_mapper import map_columns_with_llm, apply_column_mapping

class MacroEmissionExcelHandler:
    
    def __init__(self, llm_client=None):
        self.llm_client = llm_client
    
    async def read_links_file(self, file_path: str) -> Tuple[bool, Optional[pd.DataFrame], str]:
        """
        智能读取路段文件
        """
        # 1. 分析文件结构
        file_info = analyze_file_structure(file_path)
        print(f"[DEBUG] 文件列名: {file_info['columns']}")
        print(f"[DEBUG] 样本数据: {file_info['sample_data'][:1]}")
        
        # 2. 尝试LLM智能映射
        mapping_result = None
        if self.llm_client:
            try:
                mapping_result = await map_columns_with_llm(
                    file_info, 
                    "macro_emission", 
                    self.llm_client
                )
                print(f"[DEBUG] LLM映射结果: {mapping_result}")
            except Exception as e:
                print(f"[WARNING] LLM映射失败，回退到硬编码: {e}")
        
        # 3. 读取完整数据
        if file_path.endswith('.csv'):
            df = pd.read_csv(file_path)
        else:
            df = pd.read_excel(file_path)
        df.columns = df.columns.str.strip()
        
        # 4. 应用列名映射
        if mapping_result and mapping_result.get("mapping"):
            df = apply_column_mapping(df, mapping_result["mapping"])
            fleet_mix_mapping = mapping_result.get("fleet_mix", {})
            
            # 处理车型列
            if fleet_mix_mapping:
                df = self._process_fleet_mix(df, fleet_mix_mapping)
            
            # 检查是否有警告
            if mapping_result.get("warnings"):
                print(f"[WARNING] {mapping_result['warnings']}")
            
            # 检查置信度
            confidence = mapping_result.get("confidence", 0)
            if confidence < 0.7:
                print(f"[WARNING] 映射置信度较低: {confidence}")
        else:
            # 回退到硬编码方案
            df = self._fallback_column_mapping(df)
        
        # 5. 验证必需列
        required = ["link_length_km", "traffic_flow_vph", "avg_speed_kph"]
        missing = [col for col in required if col not in df.columns]
        if missing:
            return False, None, f"缺少必需列: {missing}。文件列名: {list(df.columns)}"
        
        return True, df, "成功"
    
    def _process_fleet_mix(self, df: pd.DataFrame, fleet_mix_mapping: Dict[str, str]) -> pd.DataFrame:
        """
        处理车型分布列
        """
        fleet_mix_data = {}
        for user_col, standard_type in fleet_mix_mapping.items():
            if user_col in df.columns:
                fleet_mix_data[standard_type] = df[user_col].values
                df = df.drop(columns=[user_col])
        
        if fleet_mix_data:
            df["_fleet_mix"] = [
                {k: v[i] for k, v in fleet_mix_data.items()}
                for i in range(len(df))
            ]
        
        return df
    
    def _fallback_column_mapping(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        硬编码回退方案（保持向后兼容）
        """
        # ... 现有的硬编码映射逻辑 ...
        pass
```

---

## 方案优势

### 1. 智能理解各种列名

```
用户列名                    → 标准列名
─────────────────────────────────────────
link_volume_veh_per_hour   → traffic_flow_vph  ✅
vol_per_hr                 → traffic_flow_vph  ✅
hourly_traffic             → traffic_flow_vph  ✅
每小时车流量               → traffic_flow_vph  ✅
link_avg_speed_kmh         → avg_speed_kph     ✅
average_velocity           → avg_speed_kph     ✅
```

### 2. 智能识别车型

```
用户列名        → 标准车型
─────────────────────────────────
car_pct        → Passenger Car      ✅
小轿车%        → Passenger Car      ✅
truck_ratio    → Combination Long-haul Truck  ✅
公共汽车占比   → Transit Bus        ✅
```

### 3. 根据数据内容推断

```
列名: "speed"
数据: [45, 60, 80, 55]
推断: 数值范围0-200，应该是 km/h → avg_speed_kph

列名: "length"
数据: [2.5, 1.8, 3.2]
推断: 小数，合理的路段长度 → link_length_km
```

---

## 成本分析

### LLM调用成本

- **调用频率**：每个文件只调用1次
- **输入Token**：约 500-800 tokens（Prompt + 列名 + 样本数据）
- **输出Token**：约 200-400 tokens（JSON映射结果）
- **总成本**：约 $0.001-0.002 / 文件（使用GPT-4o-mini）

### 性能影响

- **额外延迟**：约 1-2 秒（LLM调用）
- **可接受性**：文件处理本身需要时间，额外1-2秒可接受

---

## 实现步骤

### Phase 1: 基础实现（1小时）

1. 创建 `skills/common/file_analyzer.py`
2. 创建 `skills/common/column_mapper.py`
3. 编写LLM Prompt

### Phase 2: 集成到Skill（1小时）

4. 修改 `skills/macro_emission/excel_handler.py`
5. 修改 `skills/micro_emission/excel_handler.py`
6. 添加回退机制

### Phase 3: 测试验证（30分钟）

7. 测试各种列名格式
8. 测试车型识别
9. 测试回退机制

---

## 给Claude Code的Prompt

```
实现智能表格列名映射功能

项目位置: D:\Agent_MCP\emission_agent

## 任务概述

当前系统使用硬编码列名映射，用户体验差。
需要实现LLM辅助的智能列名映射。

## 实现步骤

### 1. 创建文件分析模块
路径: skills/common/file_analyzer.py

功能:
- analyze_file_structure(file_path) → 提取列名和样本数据

### 2. 创建列名映射模块
路径: skills/common/column_mapper.py

功能:
- COLUMN_MAPPING_PROMPT: LLM Prompt模板
- FIELD_DEFINITIONS: 不同任务的字段定义
- map_columns_with_llm(): 调用LLM进行映射
- apply_column_mapping(): 应用映射结果

### 3. 修改宏观排放处理器
路径: skills/macro_emission/excel_handler.py

修改:
- __init__ 添加 llm_client 参数
- read_links_file 改为 async
- 集成智能映射逻辑
- 保留硬编码作为回退

### 4. 修改微观排放处理器
路径: skills/micro_emission/excel_handler.py（如果存在）

同上修改。

## 关键代码

详见本文档中的代码示例。

## 测试用例

1. 标准列名: link_id, link_length_km, traffic_flow_vph, avg_speed_kph
2. 非标准列名: id, len_km, vol_per_hr, avg_spd
3. 中文列名: 路段编号, 长度, 流量, 平均速度
4. 带车型: ..., 小汽车%, 公交车%, 货车%
5. 混合格式: link_id, 长度km, volume_vph, 速度

## 成功标准

- [ ] 能识别各种格式的列名
- [ ] 能智能识别车型列
- [ ] LLM失败时回退到硬编码
- [ ] 添加调试日志
- [ ] 保持向后兼容
```

---

## 总结

这个方案的核心思想是：

1. **不再穷举列名**：让LLM理解列名含义
2. **利用样本数据**：帮助LLM推断数据类型
3. **保持简单**：只调用一次LLM，只做列名映射
4. **向后兼容**：LLM失败时回退到硬编码

这样既解决了列名匹配的问题，又不会大幅增加系统复杂度。
