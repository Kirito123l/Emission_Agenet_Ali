# 本地标准化模型微调任务

## 项目背景

emission_agent 项目当前使用云端 API 进行车型/污染物标准化。现在需要微调一个本地模型替代，降低成本和延迟。

## 项目位置

- **微调项目**: `D:\Agent_MCP\emission_agent\LOCAL_STANDARDIZER_MODEL`
- **参考代码**: `D:\Agent_MCP\emission_agent` (现有agent项目)

## 核心任务

从 0 开始完成本地标准化模型的数据准备工作，确保生成高质量、多样化的训练数据。

---

## 任务清单

### 任务1: 创建项目结构

```bash
LOCAL_STANDARDIZER_MODEL/
├── README.md                         # 已提供的开发文档
├── data/
│   ├── raw/
│   ├── augmented/
│   └── final/
├── scripts/
├── configs/
├── models/
│   ├── unified_lora/
│   └── column_lora/
└── tests/
```

### 任务2: 创建种子数据生成脚本

**文件**: `scripts/01_create_seed_data.py`

**要求**:
1. 从 README.md 中提取所有别名映射
2. 生成三个种子数据文件:
   - `data/raw/vehicle_type_seed.json`
   - `data/raw/pollutant_seed.json`
   - `data/raw/column_mapping_seed.json`

**参考 emission_agent 中的代码**:
- `shared/standardizer/vehicle.py` - 车型标准化逻辑
- `shared/standardizer/pollutant.py` - 污染物标准化逻辑
- `skills/micro_emission/excel_handler.py` - 微观排放列名
- `skills/macro_emission/excel_handler.py` - 宏观排放列名
- `agent/prompts/system.py` - System Prompt中的规则

**重要**: 确保从现有代码中提取所有已验证的别名，不要遗漏！

### 任务3: 创建数据增强脚本

**文件**: `scripts/02_augment_data.py`

**增强策略** (确保数据多样性):

```python
class DataAugmenter:
    """数据增强器 - 确保训练数据多样性"""
    
    def augment_text(self, text: str) -> List[str]:
        """生成文本变体"""
        variants = [text]
        
        # 1. 空格变体
        variants.append(text.replace(" ", ""))
        variants.append(" ".join(list(text)))
        
        # 2. 大小写变体 (英文)
        variants.extend([text.lower(), text.upper(), text.title()])
        
        # 3. 标点变体
        variants.extend([text + "。", text + "的", text + "?"])
        
        # 4. 上下文变体 (模拟用户真实输入)
        contexts = [
            f"查询{text}",
            f"我想查{text}",
            f"{text}类型",
            f"帮我查{text}的数据",
            f"{text}的排放",
            f"计算{text}排放",
            f"分析{text}",
        ]
        variants.extend(contexts)
        
        # 5. 修饰词变体 (仅车型)
        if self._is_vehicle(text):
            modifiers = ["新能源", "电动", "燃油", "混动", "柴油", "国六", "国五"]
            for mod in modifiers:
                variants.append(mod + text)
                variants.append(text + "（" + mod + "）")
        
        # 6. 简写/缩写变体
        # 7. 同义词替换
        # 8. 轻微错误（可选，提高鲁棒性）
        
        return list(set(variants))  # 去重
```

**列名增强策略**:

```python
def augment_column_data(columns: List[str], mapping: Dict) -> List[Dict]:
    """增强列名映射数据"""
    results = []
    
    # 1. 原始顺序
    results.append({"columns": columns, "mapping": mapping})
    
    # 2. 打乱顺序 (3-5种)
    for _ in range(5):
        shuffled = columns.copy()
        random.shuffle(shuffled)
        results.append({"columns": shuffled, "mapping": mapping})
    
    # 3. 添加干扰列 (不应该被映射的列)
    noise_cols = ["备注", "说明", "序号", "index", "Unnamed: 0", "id", "备注信息"]
    for noise in noise_cols:
        results.append({
            "columns": columns + [noise],
            "mapping": mapping  # mapping不变，noise列不应出现
        })
    
    # 4. 部分列 (测试处理不完整数据的能力)
    for i in range(len(columns)):
        partial_cols = columns[:i] + columns[i+1:]
        partial_mapping = {k: v for k, v in mapping.items() if k in partial_cols}
        if partial_cols and partial_mapping:
            results.append({"columns": partial_cols, "mapping": partial_mapping})
    
    # 5. 列名变体 (同一个标准字段的不同表示)
    # ... 在种子数据中已包含
    
    return results
```

### 任务4: 创建训练数据准备脚本

**文件**: `scripts/03_prepare_training_data.py`

**功能**:
1. 合并所有增强后的数据
2. 转换为 Qwen3 聊天格式
3. 划分训练集(85%)/验证集(10%)/测试集(5%)
4. 保存到 `data/final/`

**输出格式** (Qwen3 聊天格式):

```json
{
    "messages": [
        {"role": "system", "content": "..."},
        {"role": "user", "content": "..."},
        {"role": "assistant", "content": "..."}
    ]
}
```

### 任务5: 创建训练配置文件

**文件**: 
- `configs/unified_lora_config.yaml`
- `configs/column_lora_config.yaml`

参考 README.md 中的配置。

### 任务6: 创建训练脚本

**文件**: 
- `scripts/04_finetune_unified.py` (车型+污染物)
- `scripts/05_finetune_column.py` (列名映射)

使用 PEFT 库进行 LoRA 微调。

### 任务7: 创建评估脚本

**文件**: `scripts/06_evaluate.py`

评估指标:
- 车型标准化准确率 (目标 ≥95%)
- 污染物标准化准确率 (目标 ≥98%)
- 列名映射准确率 (目标 ≥90%)

### 任务8: 创建测试脚本

**文件**: `tests/test_standardizer.py`

测试用例:
1. 标准名称测试
2. 中文别名测试
3. 英文变体测试
4. 带噪声输入测试
5. 边界情况测试

---

## System Prompt 设计

### 统一模型 (unified) System Prompt

```
你是标准化助手。根据任务类型，将用户输入标准化为标准值。

任务类型:
- [vehicle]: 标准化为以下13种MOVES车型之一
- [pollutant]: 标准化为以下7种标准污染物之一

MOVES标准车型:
Motorcycle, Passenger Car, Passenger Truck, Light Commercial Truck,
Intercity Bus, Transit Bus, School Bus, Refuse Truck,
Single Unit Short-haul Truck, Single Unit Long-haul Truck,
Motor Home, Combination Short-haul Truck, Combination Long-haul Truck

标准污染物:
CO2, CO, NOx, PM2.5, PM10, THC, SO2

规则:
1. 只返回标准值，不要其他内容
2. 如果无法识别，返回最接近的标准值
3. 忽略修饰词（如"新能源"、"电动"），只关注核心车型
```

### 列名映射模型 (column) System Prompt

```
你是列名映射助手。分析Excel表格列名，将其映射到标准字段。

任务类型: {micro_emission 或 macro_emission}

微观排放标准字段:
- time_sec: 时间（秒）
- speed_kph: 速度（km/h）
- acceleration_mps2: 加速度（m/s²）
- grade_pct: 坡度（%）

宏观排放标准字段:
- link_id: 路段编号
- link_length_km: 路段长度（km）
- traffic_flow_vph: 交通流量（辆/小时）
- avg_speed_kph: 平均速度（km/h）
- [车型名]: 车队比例（%）

规则:
1. 返回JSON格式: {"原列名": "标准字段名", ...}
2. 只返回能识别的列，忽略无关列
3. 如果列名包含车型信息，映射到对应的MOVES车型
```

---

## 数据质量要求

### 必须满足的条件

1. **覆盖所有标准值**: 13种车型、7种污染物必须都有数据
2. **别名完整**: 从现有代码中提取的所有别名都要包含
3. **变体多样**: 每个标准值至少30种不同的输入变体
4. **格式正确**: 严格遵循 Qwen3 聊天格式
5. **无重复**: 去除完全相同的数据项
6. **均衡分布**: 各类别数据量相对均衡

### 数据示例

**车型标准化示例**:
```json
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "[vehicle] 大货车"}, {"role": "assistant", "content": "Combination Long-haul Truck"}]}
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "[vehicle] 查询重卡"}, {"role": "assistant", "content": "Combination Long-haul Truck"}]}
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "[vehicle] 新能源公交车"}, {"role": "assistant", "content": "Transit Bus"}]}
```

**污染物标准化示例**:
```json
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "[pollutant] 二氧化碳"}, {"role": "assistant", "content": "CO2"}]}
{"messages": [{"role": "system", "content": "..."}, {"role": "user", "content": "[pollutant] 氮氧化物排放"}, {"role": "assistant", "content": "NOx"}]}
```

**列名映射示例**:
```json
{"messages": [{"role": "system", "content": "...(micro_emission)..."}, {"role": "user", "content": "[\"车速km/h\", \"加速度\", \"时间\"]"}, {"role": "assistant", "content": "{\"车速km/h\": \"speed_kph\", \"加速度\": \"acceleration_mps2\", \"时间\": \"time_sec\"}"}]}
{"messages": [{"role": "system", "content": "...(macro_emission)..."}, {"role": "user", "content": "[\"路段长度\", \"流量\", \"小汽车%\", \"公交车%\"]"}, {"role": "assistant", "content": "{\"路段长度\": \"link_length_km\", \"流量\": \"traffic_flow_vph\", \"小汽车%\": \"Passenger Car\", \"公交车%\": \"Transit Bus\"}"}]}
```

---

## 执行顺序

1. **先读取 README.md** - 理解完整的项目背景和要求
2. **参考 emission_agent 代码** - 提取所有现有的别名映射规则
3. **创建目录结构**
4. **编写并运行 01_create_seed_data.py** - 生成种子数据
5. **编写并运行 02_augment_data.py** - 数据增强
6. **编写并运行 03_prepare_training_data.py** - 准备最终数据
7. **验证数据质量** - 检查数量、格式、覆盖率
8. **编写训练配置和脚本**
9. **编写评估脚本**

---

## 验收标准

完成后，请确认:

- [ ] `data/raw/` 包含3个种子数据文件
- [ ] `data/augmented/` 包含增强后的数据
- [ ] `data/final/` 包含训练集、验证集、测试集
- [ ] 统一模型数据量 ≥ 600 条
- [ ] 列名映射数据量 ≥ 400 条
- [ ] 所有13种车型都有数据
- [ ] 所有7种污染物都有数据
- [ ] 数据格式符合 Qwen3 聊天格式
- [ ] 训练脚本可以正常运行

---

## 重要提醒

1. **从现有代码提取规则** - 不要凭空创造别名，要从 emission_agent 的代码中提取
2. **确保数据多样性** - 使用多种增强策略
3. **保持格式一致** - 严格遵循 Qwen3 聊天格式
4. **测试数据质量** - 生成后检查数据是否符合预期

祝你顺利完成任务！
