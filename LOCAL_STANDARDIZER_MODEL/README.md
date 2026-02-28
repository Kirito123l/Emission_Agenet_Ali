# 本地标准化模型微调开发文档

> 本文档用于指导 Claude Code 完成标准化模型的数据准备和微调工作

## 1. 项目概述

### 1.1 目标
微调 Qwen3-4B-Instruct-2507 模型，替代当前的云端 API 调用，实现本地标准化推理。

### 1.2 模型架构决策
采用**混合策略**：
- **unified_lora**: 车型标准化 + 污染物标准化（合并微调）
- **column_lora**: 列名映射（独立微调）

### 1.3 项目结构
```
LOCAL_STANDARDIZER_MODEL/
├── README.md                         # 本文档
├── data/
│   ├── raw/                          # 原始种子数据
│   │   ├── vehicle_type_seed.json
│   │   ├── pollutant_seed.json
│   │   └── column_mapping_seed.json
│   ├── augmented/                    # 增强后数据
│   │   ├── unified_augmented.json    # 车型+污染物
│   │   └── column_augmented.json     # 列名映射
│   └── final/                        # 最终训练数据
│       ├── unified_train.json
│       ├── unified_eval.json
│       ├── column_train.json
│       └── column_eval.json
├── scripts/
│   ├── 01_create_seed_data.py
│   ├── 02_augment_data.py
│   ├── 03_prepare_training_data.py
│   ├── 04_finetune_unified.py
│   ├── 05_finetune_column.py
│   ├── 06_evaluate.py
│   └── 07_export_model.py
├── configs/
│   ├── unified_lora_config.yaml
│   └── column_lora_config.yaml
├── models/
│   ├── unified_lora/
│   └── column_lora/
└── tests/
    └── test_standardizer.py
```

---

## 2. 现有系统规则参考 [重要]

### 2.1 MOVES 标准车型定义 (13种)

从 emission_agent 项目中提取的标准定义：

```python
# Source Type ID 映射
MOVES_VEHICLE_TYPES = {
    11: "Motorcycle",                      # 摩托车
    21: "Passenger Car",                   # 乘用车/小汽车
    31: "Passenger Truck",                 # 客货两用车/皮卡
    32: "Light Commercial Truck",          # 轻型货车
    41: "Intercity Bus",                   # 城际客车
    42: "Transit Bus",                     # 公交车
    43: "School Bus",                      # 校车
    51: "Refuse Truck",                    # 垃圾车
    52: "Single Unit Short-haul Truck",    # 单体短途货车
    53: "Single Unit Long-haul Truck",     # 单体长途货车
    54: "Motor Home",                      # 房车
    61: "Combination Short-haul Truck",    # 组合短途货车(半挂短途)
    62: "Combination Long-haul Truck",     # 重型货车(半挂长途)
}

# 标准车型英文名列表
STANDARD_VEHICLE_TYPES = [
    "Motorcycle",
    "Passenger Car",
    "Passenger Truck",
    "Light Commercial Truck",
    "Intercity Bus",
    "Transit Bus",
    "School Bus",
    "Refuse Truck",
    "Single Unit Short-haul Truck",
    "Single Unit Long-haul Truck",
    "Motor Home",
    "Combination Short-haul Truck",
    "Combination Long-haul Truck",
]
```

### 2.2 现有车型映射规则

从 `emission_agent/shared/standardizer/` 和 `skills/macro_emission/excel_handler.py` 提取：

```python
# 已验证的车型别名映射
VEHICLE_ALIASES = {
    "Motorcycle": [
        "摩托车", "机车", "两轮车", "motorcycle", "motorbike", "moto",
        "电动摩托", "燃油摩托", "踏板车", "骑士车", "重机", "电摩"
    ],
    
    "Passenger Car": [
        "小汽车", "轿车", "私家车", "乘用车", "sedan", "car", "小车",
        "出租车", "网约车", "滴滴", "uber", "私家轿车", "家用车",
        "紧凑型轿车", "中型轿车", "豪华轿车", "经济型轿车", "SUV",
        "越野车", "旅行车", "掀背车", "三厢车", "两厢车", "跑车",
        "轿跑", "新能源车", "电动汽车", "混动车", "passenger car",
        "乘用车辆", "小型汽车", "家庭用车", "代步车", "买菜车",
        "新能源小汽车", "电动轿车", "插电混动", "纯电动车"
    ],
    
    "Passenger Truck": [
        "客货两用车", "皮卡", "pickup", "pickup truck", "客货车",
        "小型客车", "面包车", "商务车", "MPV", "7座车", "五菱",
        "金杯", "微面", "小客车", "passenger truck", "轻客",
        "商务MPV", "家用MPV", "GL8", "奥德赛", "艾力绅"
    ],
    
    "Light Commercial Truck": [
        "轻型货车", "小货车", "light truck", "轻卡", "厢式货车",
        "微卡", "轻型卡车", "城市配送车", "快递车", "物流车",
        "小型货运", "light commercial truck", "4米2", "蓝牌货车",
        "轻型厢货", "城配车", "配送货车"
    ],
    
    "Intercity Bus": [
        "城际客车", "长途客车", "intercity bus", "大巴", "长途大巴",
        "客运大巴", "旅游大巴", "省际客车", "豪华大巴", "卧铺客车",
        "长途汽车", "省际大巴", "跨城客车", "intercity coach"
    ],
    
    "Transit Bus": [
        "公交车", "公共汽车", "transit bus", "city bus", "市内公交",
        "城市公交", "BRT", "快速公交", "电动公交", "新能源公交",
        "巴士", "公交巴士", "市区公交", "常规公交", "通勤巴士",
        "公交", "公汽", "trolleybus", "无轨电车"
    ],
    
    "School Bus": [
        "校车", "school bus", "学生校车", "幼儿园校车", "接送车",
        "通勤班车", "学校巴士", "接送校车", "黄色校车"
    ],
    
    "Refuse Truck": [
        "垃圾车", "环卫车", "refuse truck", "garbage truck", "清运车",
        "垃圾清运", "压缩垃圾车", "环卫垃圾车", "垃圾压缩车",
        "垃圾收集车", "环卫作业车"
    ],
    
    "Single Unit Short-haul Truck": [
        "短途货车", "单体短途货车", "城市货车", "配送货车", "中型货车",
        "4.2米货车", "箱货", "城市配送", "短途配送车", "市内货车",
        "single unit short-haul truck", "中卡", "黄牌货车"
    ],
    
    "Single Unit Long-haul Truck": [
        "单体长途货车", "中长途货车", "9.6米货车", "厢式长途货车",
        "长途货运", "干线货车", "single unit long-haul truck"
    ],
    
    "Motor Home": [
        "房车", "旅居车", "motor home", "RV", "露营车", "自行式房车",
        "旅行房车", "motorhome", "recreational vehicle", "自驾房车"
    ],
    
    "Combination Short-haul Truck": [
        "半挂短途", "短途半挂", "组合短途货车", "城际半挂",
        "区域配送半挂", "combination short-haul truck", "短途挂车"
    ],
    
    "Combination Long-haul Truck": [
        "重型卡车", "大货车", "半挂车", "拖头", "18轮", "重卡",
        "长途货车", "半挂长途", "挂车", "牵引车", "大型货车",
        "集装箱卡车", "大挂车", "重型半挂", "长途运输车",
        "干线运输车", "combination long-haul truck", "重型货车",
        "大卡车", "大车", "大挂", "半挂牵引车", "集卡"
    ]
}
```

### 2.3 标准污染物定义 (7种)

```python
STANDARD_POLLUTANTS = ["CO2", "CO", "NOx", "PM2.5", "PM10", "THC", "SO2"]

POLLUTANT_ALIASES = {
    "CO2": [
        "CO2", "二氧化碳", "碳排放", "carbon dioxide", "co2", "CO₂",
        "碳", "温室气体", "二氧化碳排放", "碳dioxide"
    ],
    
    "CO": [
        "CO", "一氧化碳", "carbon monoxide", "co", "CO气体",
        "一氧化碳排放"
    ],
    
    "NOx": [
        "NOx", "氮氧化物", "nitrogen oxides", "nox", "NOX",
        "氮氧化合物", "NO和NO2", "氮氧", "氮氧化物排放"
    ],
    
    "PM2.5": [
        "PM2.5", "细颗粒物", "pm2.5", "PM 2.5", "pm2_5",
        "2.5微米颗粒物", "细粒子", "PM25", "pm25"
    ],
    
    "PM10": [
        "PM10", "可吸入颗粒物", "pm10", "PM 10", "pm_10",
        "10微米颗粒物", "粗颗粒物", "颗粒物"
    ],
    
    "THC": [
        "THC", "总碳氢化合物", "碳氢化合物", "HC", "VOC",
        "挥发性有机物", "总烃", "烃类", "hydrocarbon"
    ],
    
    "SO2": [
        "SO2", "二氧化硫", "sulfur dioxide", "so2", "SO₂",
        "硫化物", "硫排放"
    ]
}
```

### 2.4 列名映射规则

从 `skills/micro_emission/excel_handler.py` 和 `skills/macro_emission/excel_handler.py` 提取：

```python
# 微观排放标准字段
MICRO_EMISSION_COLUMNS = {
    "time_sec": [
        "time", "t", "时间", "time_sec", "time_s", "秒", "timestamp",
        "时间戳", "time(s)", "时间(秒)", "Time", "TIME", "时间s"
    ],
    
    "speed_kph": [
        "speed", "速度", "车速", "speed_kph", "speed_kmh", "速度km/h",
        "velocity", "v", "speed(km/h)", "车速(km/h)", "瞬时速度",
        "实时速度", "spd", "Speed", "SPEED", "速度(km/h)", "speed_kmph",
        "车速km/h", "速度kmh", "link_avg_speed_kmh", "avg_speed_kmh"
    ],
    
    "acceleration_mps2": [
        "acceleration", "加速度", "acc", "a", "accel", "acceleration_mps2",
        "加速度m/s2", "加速度(m/s²)", "accel_mps2", "acc_mps2",
        "Acceleration", "加速度m/s²", "acceleration_m_s2"
    ],
    
    "grade_pct": [
        "grade", "坡度", "slope", "gradient", "坡度%", "grade_pct",
        "grade_percent", "道路坡度", "路面坡度", "Grade", "GRADE"
    ]
}

# 宏观排放标准字段
MACRO_EMISSION_COLUMNS = {
    "link_id": [
        "link_id", "路段ID", "路段编号", "id", "segment_id", "road_id",
        "link", "编号", "LinkID", "ID", "路段id", "link_ID"
    ],
    
    "link_length_km": [
        "length", "长度", "link_length", "路段长度", "距离", "length_km",
        "link_length_km", "len", "路段长度(km)", "distance", "里程",
        "Length", "LENGTH", "路段长度km", "长度km", "长度(km)"
    ],
    
    "traffic_flow_vph": [
        "flow", "流量", "traffic_flow", "交通流量", "volume",
        "traffic_flow_vph", "vol", "车流量", "小时流量",
        "link_volume_veh_per_hour", "volume_vph", "流量(辆/h)",
        "Flow", "FLOW", "交通量", "hourly_volume", "流量vph",
        "volume_veh_per_hour", "每小时流量"
    ],
    
    "avg_speed_kph": [
        "speed", "速度", "avg_speed", "平均速度", "mean_speed",
        "avg_speed_kph", "link_avg_speed_kmh", "平均车速",
        "average_speed", "速度(km/h)", "Speed", "SPEED",
        "avg_speed_kmh", "平均速度(km/h)", "速度kph"
    ]
}

# 车队组成列名（用于宏观排放）
FLEET_MIX_COLUMNS = {
    "Passenger Car": [
        "小汽车%", "passenger_car", "car_pct", "小汽车比例", "pc_pct",
        "乘用车%", "轿车比例", "私家车%", "小汽车", "Passenger Car",
        "passenger_car_pct", "car_ratio", "小轿车%"
    ],
    "Transit Bus": [
        "公交车%", "transit_bus", "bus_pct", "公交比例", "公交车比例",
        "巴士%", "Transit Bus", "transit_bus_pct", "公交", "公交%"
    ],
    "Light Commercial Truck": [
        "轻型货车%", "light_truck", "light_truck_pct", "轻卡%",
        "Light Commercial Truck", "小货车%", "轻型货车比例"
    ],
    "Combination Long-haul Truck": [
        "重型货车%", "heavy_truck", "truck_pct", "重卡%", "大货车%",
        "Combination Long-haul Truck", "半挂车%", "重型货车比例"
    ],
    # 其他车型类似...
}
```

### 2.5 现有 System Prompt 参考

从 `agent/prompts/system.py` 提取的标准化相关内容：

```python
STANDARDIZATION_RULES = """
## 参数标准化规则

### 车型标准化
用户可能使用各种方式描述车型，你需要理解并映射到以下13种MOVES标准车型之一：
- Motorcycle: 摩托车、机车、两轮车
- Passenger Car: 小汽车、轿车、私家车、乘用车、SUV、电动汽车
- Passenger Truck: 皮卡、面包车、MPV、商务车
- Light Commercial Truck: 轻型货车、小货车、快递车
- Intercity Bus: 长途客车、大巴、旅游大巴
- Transit Bus: 公交车、城市公交
- School Bus: 校车
- Refuse Truck: 垃圾车、环卫车
- Single Unit Short-haul Truck: 中型货车、城市配送车
- Single Unit Long-haul Truck: 中长途货车
- Motor Home: 房车、旅居车、RV
- Combination Short-haul Truck: 短途半挂
- Combination Long-haul Truck: 重型卡车、大货车、半挂车、挂车

### 污染物标准化
用户可能使用中文或英文描述污染物，标准化为：
- CO2: 二氧化碳、碳排放
- CO: 一氧化碳
- NOx: 氮氧化物
- PM2.5: 细颗粒物
- PM10: 可吸入颗粒物
- THC: 总碳氢化合物、HC、VOC
- SO2: 二氧化硫
"""
```

---

## 3. 数据集要求

### 3.1 统一模型 (Unified) 数据格式

```json
{
    "messages": [
        {
            "role": "system",
            "content": "你是标准化助手。根据任务类型，将用户输入标准化为标准值。\n\n任务类型:\n- [vehicle]: 标准化为13种MOVES车型之一\n- [pollutant]: 标准化为7种标准污染物之一\n\n只返回标准值，不要其他内容。"
        },
        {
            "role": "user",
            "content": "[vehicle] 大货车"
        },
        {
            "role": "assistant",
            "content": "Combination Long-haul Truck"
        }
    ]
}
```

### 3.2 列名映射模型 (Column) 数据格式

```json
{
    "messages": [
        {
            "role": "system",
            "content": "你是列名映射助手。分析Excel表格列名，将其映射到标准字段。\n\n任务类型: micro_emission\n\n标准字段:\n- time_sec: 时间(秒)\n- speed_kph: 速度(km/h)\n- acceleration_mps2: 加速度(m/s²)\n- grade_pct: 坡度(%)\n\n返回JSON格式的映射，只返回能识别的列。"
        },
        {
            "role": "user",
            "content": "[\"车速km/h\", \"加速度\", \"时间戳\", \"备注\"]"
        },
        {
            "role": "assistant",
            "content": "{\"车速km/h\": \"speed_kph\", \"加速度\": \"acceleration_mps2\", \"时间戳\": \"time_sec\"}"
        }
    ]
}
```

### 3.3 数据多样性要求

每种标准值需要覆盖以下变体类型：

| 变体类型 | 示例 | 数量要求 |
|---------|------|---------|
| 标准名称 | "Passenger Car" | 1 |
| 中文正式名 | "乘用车" | 1-2 |
| 中文口语 | "小汽车", "轿车" | 3-5 |
| 中文别名 | "私家车", "家用车" | 5-10 |
| 英文变体 | "car", "sedan" | 2-3 |
| 中英混合 | "passenger 车" | 2-3 |
| 带修饰词 | "新能源小汽车", "电动轿车" | 5-10 |
| 带噪声 | "小 汽 车", "小汽车。" | 3-5 |
| 上下文句子 | "我想查小汽车的" | 3-5 |
| 错别字 | "小气车" (可选) | 1-2 |

### 3.4 目标数据量

| 任务 | 类别数 | 每类变体 | 总计 |
|------|--------|---------|------|
| 车型标准化 | 13 | 30-50 | 400-650 |
| 污染物标准化 | 7 | 20-30 | 140-210 |
| 列名映射(微观) | 4 | 30-40 | 120-160 |
| 列名映射(宏观) | 4+车型 | 30-40 | 150-200 |
| **总计** | - | - | **800-1200** |

---

## 4. 数据增强策略

### 4.1 增强方法

```python
class DataAugmenter:
    """数据增强器"""
    
    def augment(self, text: str) -> List[str]:
        """生成多种变体"""
        variants = [text]  # 原始
        
        # 1. 空格变体
        variants.append(text.replace(" ", ""))  # 去空格
        variants.append(" ".join(text))  # 加空格
        
        # 2. 大小写变体（英文）
        variants.append(text.lower())
        variants.append(text.upper())
        variants.append(text.title())
        
        # 3. 标点变体
        variants.append(text + "。")
        variants.append(text + "的")
        
        # 4. 上下文变体
        contexts = [
            f"查询{text}",
            f"我想查{text}",
            f"{text}类型",
            f"属于{text}",
            f"{text}这个",
            f"帮我查{text}的数据",
        ]
        variants.extend(contexts)
        
        # 5. 修饰词变体（仅车型）
        modifiers = ["新能源", "电动", "燃油", "混动", "柴油", "国六"]
        for mod in modifiers:
            variants.append(mod + text)
        
        return list(set(variants))  # 去重
```

### 4.2 列名增强策略

```python
def augment_column_names(columns: List[str]) -> List[List[str]]:
    """增强列名组合"""
    variants = []
    
    # 1. 原始顺序
    variants.append(columns)
    
    # 2. 打乱顺序
    for _ in range(3):
        shuffled = columns.copy()
        random.shuffle(shuffled)
        variants.append(shuffled)
    
    # 3. 添加干扰列
    noise_columns = ["备注", "说明", "序号", "index", "Unnamed: 0"]
    for noise in noise_columns:
        variants.append(columns + [noise])
    
    # 4. 部分列（测试鲁棒性）
    for i in range(len(columns)):
        partial = columns[:i] + columns[i+1:]
        if partial:
            variants.append(partial)
    
    return variants
```

---

## 5. 训练配置

### 5.1 统一模型 LoRA 配置

```yaml
# configs/unified_lora_config.yaml
base_model: "Qwen/Qwen3-4B-Instruct-2507"

lora:
  r: 16
  lora_alpha: 32
  target_modules:
    - q_proj
    - k_proj
    - v_proj
    - o_proj
    - gate_proj
    - up_proj
    - down_proj
  lora_dropout: 0.05
  bias: "none"
  task_type: "CAUSAL_LM"

training:
  output_dir: "./models/unified_lora"
  num_train_epochs: 5
  per_device_train_batch_size: 4
  gradient_accumulation_steps: 4
  learning_rate: 2e-4
  warmup_ratio: 0.1
  fp16: true
  gradient_checkpointing: true
  logging_steps: 10
  save_steps: 100
  eval_steps: 100

data:
  train_file: "./data/final/unified_train.json"
  eval_file: "./data/final/unified_eval.json"
  max_length: 256
```

### 5.2 列名模型 LoRA 配置

```yaml
# configs/column_lora_config.yaml
base_model: "Qwen/Qwen3-4B-Instruct-2507"

lora:
  r: 32  # 列名映射更复杂，用更大的r
  lora_alpha: 64
  target_modules:
    - q_proj
    - k_proj
    - v_proj
    - o_proj
    - gate_proj
    - up_proj
    - down_proj
  lora_dropout: 0.05
  bias: "none"
  task_type: "CAUSAL_LM"

training:
  output_dir: "./models/column_lora"
  num_train_epochs: 8  # 更多epochs
  per_device_train_batch_size: 4
  gradient_accumulation_steps: 4
  learning_rate: 1e-4  # 稍低的学习率
  warmup_ratio: 0.1
  fp16: true
  gradient_checkpointing: true
  logging_steps: 10
  save_steps: 100
  eval_steps: 100

data:
  train_file: "./data/final/column_train.json"
  eval_file: "./data/final/column_eval.json"
  max_length: 512  # 列名映射需要更长的上下文
```

---

## 6. 评估指标

### 6.1 准确率目标

| 任务 | 目标准确率 | 最低可接受 |
|------|-----------|-----------|
| 车型标准化 | ≥95% | 90% |
| 污染物标准化 | ≥98% | 95% |
| 列名映射 | ≥90% | 85% |

### 6.2 评估方法

```python
def evaluate_unified_model(model, test_data):
    """评估统一模型"""
    correct = {"vehicle": 0, "pollutant": 0}
    total = {"vehicle": 0, "pollutant": 0}
    
    for item in test_data:
        task_type = "vehicle" if "[vehicle]" in item["input"] else "pollutant"
        predicted = model.generate(item["input"])
        expected = item["output"]
        
        total[task_type] += 1
        if predicted.strip() == expected.strip():
            correct[task_type] += 1
    
    return {
        "vehicle_accuracy": correct["vehicle"] / total["vehicle"],
        "pollutant_accuracy": correct["pollutant"] / total["pollutant"],
        "overall_accuracy": sum(correct.values()) / sum(total.values())
    }

def evaluate_column_model(model, test_data):
    """评估列名映射模型"""
    exact_match = 0
    partial_match = 0
    total = len(test_data)
    
    for item in test_data:
        predicted = json.loads(model.generate(item["input"]))
        expected = json.loads(item["output"])
        
        if predicted == expected:
            exact_match += 1
        elif all(k in predicted and predicted[k] == v for k, v in expected.items()):
            partial_match += 1
    
    return {
        "exact_match": exact_match / total,
        "partial_match": (exact_match + partial_match) / total
    }
```

---

## 7. 部署集成

### 7.1 集成到 emission_agent

修改 `emission_agent/config.py`:

```python
# 添加本地模型配置
LOCAL_STANDARDIZER_CONFIG = {
    "enabled": True,
    "base_model": "Qwen/Qwen3-4B-Instruct-2507",
    "unified_lora": "./LOCAL_STANDARDIZER_MODEL/models/unified_lora",
    "column_lora": "./LOCAL_STANDARDIZER_MODEL/models/column_lora",
    "device": "cuda",  # 或 "cpu"
    "max_length": 256,
}
```

### 7.2 创建本地客户端

在 `emission_agent/shared/standardizer/local_client.py` 中：

```python
class LocalStandardizer:
    """本地标准化模型"""
    
    def __init__(self, config):
        self.model = self._load_model(config)
        self.adapters = self._load_adapters(config)
        self.current_adapter = None
    
    def standardize_vehicle(self, input_text: str) -> str:
        self._switch_adapter("unified")
        return self._generate(f"[vehicle] {input_text}")
    
    def standardize_pollutant(self, input_text: str) -> str:
        self._switch_adapter("unified")
        return self._generate(f"[pollutant] {input_text}")
    
    def map_columns(self, columns: list, task_type: str) -> dict:
        self._switch_adapter("column")
        prompt = self._build_column_prompt(columns, task_type)
        result = self._generate(prompt)
        return json.loads(result)
```

---

## 8. 开发检查清单

### Phase 1: 数据准备
- [ ] 创建目录结构
- [ ] 编写种子数据生成脚本
- [ ] 从现有代码提取别名映射
- [ ] 生成种子数据文件
- [ ] 编写数据增强脚本
- [ ] 生成增强后的数据
- [ ] 划分训练集/验证集/测试集
- [ ] 验证数据格式正确

### Phase 2: 模型训练
- [ ] 安装训练依赖
- [ ] 编写训练配置文件
- [ ] 编写训练脚本
- [ ] 训练统一模型 (unified_lora)
- [ ] 训练列名模型 (column_lora)
- [ ] 保存模型检查点

### Phase 3: 评估测试
- [ ] 编写评估脚本
- [ ] 在测试集上评估
- [ ] 分析错误案例
- [ ] 如需要，补充数据重训

### Phase 4: 部署集成
- [ ] 导出最终模型
- [ ] 创建本地客户端
- [ ] 集成到 emission_agent
- [ ] 端到端测试

---

## 9. 常见问题

### Q1: 显存不足怎么办？
- 使用 `gradient_checkpointing: true`
- 减小 `per_device_train_batch_size` 到 2 或 1
- 增加 `gradient_accumulation_steps`
- 使用 QLoRA (4bit量化)

### Q2: 训练后准确率不达标？
- 检查数据质量，移除噪声数据
- 增加训练数据量
- 调整学习率 (尝试 1e-4 或 5e-5)
- 增加训练 epochs
- 增大 LoRA 的 r 值

### Q3: 推理速度慢？
- 使用 vLLM 或 llama.cpp 部署
- 量化模型到 INT4
- 使用更小的 max_length

---

## 10. 参考资源

- Qwen3 模型: https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507
- PEFT 文档: https://huggingface.co/docs/peft
- LoRA 论文: https://arxiv.org/abs/2106.09685
- emission_agent 项目: `D:\Agent_MCP\emission_agent`
