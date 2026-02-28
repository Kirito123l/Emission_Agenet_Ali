# 车队组成（Fleet Mix）功能说明

## ✅ 功能状态

**系统已完整支持车队组成输入！**

## 📊 功能说明

### 1. 什么是车队组成？

车队组成（Fleet Mix）是指在宏观排放计算中，每个路段上不同车型的百分比分布。例如：
- 小汽车：70%
- 公交车：20%
- 货车：10%

### 2. 如何在文件中指定车队组成？

在宏观排放的输入文件中，添加包含车型名称的列（可以带 `%` 符号）：

**示例文件**：
```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,公交车%,货车%
Link_001,2.5,5000,60,70,20,10
Link_002,1.8,3500,45,60,30,10
Link_003,3.2,6000,80,80,10,10
```

### 3. 支持的车型列名

系统支持 **13 种 MOVES 标准车型**，会自动识别包含以下车型名称的列：

| 序号 | 中文列名 | 英文列名 | MOVES 标准车型 | Source Type ID |
|-----|---------|---------|---------------|----------------|
| 1 | 摩托车 | Motorcycle | Motorcycle | 11 |
| 2 | 小汽车、乘用车、轿车 | Passenger Car | Passenger Car | 21 |
| 3 | 客车、皮卡 | Passenger Truck | Passenger Truck | 31 |
| 4 | 轻型货车、小货车、轻型商用车 | Light Commercial Truck | Light Commercial Truck | 32 |
| 5 | 城际客车、长途客车 | Intercity Bus | Intercity Bus | 41 |
| 6 | 公交车、巴士、市内公交 | Transit Bus | Transit Bus | 42 |
| 7 | 校车 | School Bus | School Bus | 43 |
| 8 | 垃圾车、环卫车 | Refuse Truck | Refuse Truck | 51 |
| 9 | 单体短途货车、短途货车 | Single Unit Short-haul Truck | Single Unit Short-haul Truck | 52 |
| 10 | 单体长途货车、长途货车 | Single Unit Long-haul Truck | Single Unit Long-haul Truck | 53 |
| 11 | 房车、旅居车 | Motor Home | Motor Home | 54 |
| 12 | 组合短途货车、半挂短途 | Combination Short-haul Truck | Combination Short-haul Truck | 61 |
| 13 | 组合长途货车、半挂长途、重型货车、大货车、货车 | Combination Long-haul Truck | Combination Long-haul Truck | 62 |

**列名示例**：
- ✅ `小汽车%`
- ✅ `小汽车`
- ✅ `乘用车%`
- ✅ `Passenger Car%`
- ✅ `公交车％` (全角百分号也支持)

### 4. 百分比处理规则

#### 自动归一化
系统会自动将百分比归一化到 100%。例如：

**输入**：
```csv
link_id,小汽车%,公交车%,货车%
Link_001,7,2,1
```

**系统自动转换为**：
- 小汽车：70% (7/10 * 100)
- 公交车：20% (2/10 * 100)
- 货车：10% (1/10 * 100)

#### 默认值
如果某个路段没有提供车型分布，系统使用默认值：
- Passenger Car (小汽车): 70%
- Passenger Truck (客车): 20%
- Light Commercial Truck (轻型货车): 5%
- Transit Bus (公交车): 3%
- Combination Long-haul Truck (重型货车): 2%

### 5. 实际应用示例

#### 示例1：城市主干道
```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,公交车%,货车%
Main_Street,3.5,8000,50,75,15,10
```

#### 示例2：高速公路
```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,客车%,重型货车%
Highway_G1,25.0,12000,100,60,20,20
```

#### 示例3：混合使用中英文
```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,Passenger Car%,Transit Bus%,货车%
Mixed_Road,5.0,6000,60,70,10,20
```

#### 示例4：不提供车型分布（使用默认值）
```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph
Simple_Road,2.0,4000,55
```
系统会自动使用默认车队组成。

## 🔧 技术实现

### 识别逻辑

1. **列名清理**：去除 `%` 和 `％` 符号，去除前后空格
2. **模式匹配**：检查列名是否包含车型关键词（如"小汽车"、"公交车"）
3. **标准化映射**：将中文车型名映射到标准英文名称
4. **数据解析**：读取每行的百分比值
5. **归一化**：将百分比总和归一化到 100%

### 代码位置

- **列名映射**：`skills/macro_emission/excel_handler.py` 第 27-45 行
- **识别函数**：`_identify_vehicle_columns()` 第 215-236 行
- **解析函数**：`_parse_fleet_mix()` 第 239-253 行

## ⚠️ 注意事项

1. **列名必须包含车型关键词**
   - ✅ `小汽车%`, `乘用车`, `Passenger Car%`
   - ❌ `Type1%`, `Vehicle1%` (无法识别)

2. **百分比可以是小数**
   - ✅ `70.5`, `20.3`, `9.2`

3. **总和不必等于 100**
   - 系统会自动归一化
   - 例如：7+2+1=10 → 70%+20%+10%

4. **可以只指定部分车型**
   - 例如只指定"小汽车%"和"公交车%"
   - 其他车型默认为 0%
   - 系统会归一化到 100%

5. **每个路段可以有不同的车队组成**
   - 不同行可以有不同的百分比分布

## 📝 使用建议

1. **城市道路**：小汽车比例较高（70-80%）
2. **高速公路**：货车比例较高（20-30%）
3. **公交专用道**：公交车比例较高（50-70%）
4. **工业区道路**：货车比例较高（30-50%）

## 🧪 测试示例

创建测试文件 `test_fleet_mix.csv`：

```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,公交车%,货车%,备注
Urban_Road,2.5,5000,40,75,15,10,城市道路
Highway,15.0,8000,90,60,5,35,高速公路
Bus_Lane,3.0,3000,30,20,70,10,公交专用道
Industrial,5.0,4000,50,40,5,55,工业区道路
```

上传此文件并发送消息："计算这些路段的排放"

系统会：
1. 识别每个路段的车队组成
2. 根据不同的车队组成计算排放
3. 返回每个路段的排放结果

## 📞 技术支持

如果车队组成功能不工作：
1. 检查列名是否包含支持的车型关键词
2. 查看终端日志中的 `[DEBUG]` 信息
3. 确认百分比值是否为有效数字
4. 提供文件内容以便诊断
