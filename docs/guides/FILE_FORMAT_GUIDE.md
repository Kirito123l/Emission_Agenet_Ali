# 排放计算系统 - 文件格式说明

## 📁 支持的文件格式

系统支持以下文件格式：
- `.csv` (推荐，UTF-8编码)
- `.xlsx` (Excel 2007+)
- `.xls` (Excel 97-2003)

---

## 🚗 微观排放计算 - 轨迹文件格式

### 必需列

| 列名 | 支持的变体 | 单位 | 说明 |
|------|-----------|------|------|
| **速度** | `speed_kph`, `speed_kmh`, `speed`, `车速`, `速度` | km/h | 车辆瞬时速度 |

### 可选列

| 列名 | 支持的变体 | 单位 | 说明 |
|------|-----------|------|------|
| **时间** | `t`, `time`, `time_sec`, `时间` | 秒 | 时间戳（如无则自动生成） |
| **加速度** | `acceleration`, `acc`, `acceleration_mps2`, `acceleration_m_s2`, `加速度` | m/s² | 加速度（如无则自动计算） |
| **坡度** | `grade_pct`, `grade`, `坡度` | % | 道路坡度（如无则默认0） |

### 示例文件

**micro_emission_example.csv**:
```csv
time_sec,speed_kmh,acceleration_m_s2
0,0,0
1,5,1.39
2,12,1.94
3,20,2.22
4,28,2.22
5,35,1.94
```

或者简化版本（只有速度列）：
```csv
speed_kph
0
5
12
20
28
35
```

---

## 🛣️ 宏观排放计算 - 路段文件格式

### 必需列

| 列名 | 支持的变体 | 单位 | 说明 |
|------|-----------|------|------|
| **路段长度** | `link_length_km`, `length_km`, `length`, `路段长度`, `长度` | km | 路段长度 |
| **交通流量** | `traffic_flow_vph`, `flow_vph`, `flow`, `traffic`, `link_volume_veh_per_hour`, `volume_veh_per_hour`, `volume`, `交通流量`, `流量` | 辆/小时 | 交通流量 |
| **平均速度** | `avg_speed_kph`, `speed_kph`, `speed`, `link_avg_speed_kmh`, `avg_speed_kmh`, `speed_kmh`, `平均速度`, `速度` | km/h | 平均行驶速度 |

### 可选列

| 列名 | 支持的变体 | 单位 | 说明 |
|------|-----------|------|------|
| **路段ID** | `link_id`, `id`, `路段ID`, `路段编号` | - | 路段标识（如无则自动生成） |
| **车型分布** | 见下方车型列名表 | % | 各车型百分比（如无则使用默认值） |

### 车型分布列名（可选）

系统支持 **13 种 MOVES 标准车型**，会自动识别包含以下车型名称的列（可以带 `%` 或 `％` 符号）：

| 序号 | 中文列名示例 | 英文列名示例 | MOVES 标准车型 |
|-----|------------|-------------|---------------|
| 1 | `摩托车%` | `Motorcycle%` | Motorcycle |
| 2 | `小汽车%`, `乘用车%`, `轿车%` | `Passenger Car%` | Passenger Car |
| 3 | `客车%`, `皮卡%` | `Passenger Truck%` | Passenger Truck |
| 4 | `轻型货车%`, `小货车%`, `轻型商用车%` | `Light Commercial Truck%` | Light Commercial Truck |
| 5 | `城际客车%`, `长途客车%` | `Intercity Bus%` | Intercity Bus |
| 6 | `公交车%`, `巴士%`, `市内公交%` | `Transit Bus%` | Transit Bus |
| 7 | `校车%` | `School Bus%` | School Bus |
| 8 | `垃圾车%`, `环卫车%` | `Refuse Truck%` | Refuse Truck |
| 9 | `单体短途货车%`, `短途货车%` | `Single Unit Short-haul Truck%` | Single Unit Short-haul Truck |
| 10 | `单体长途货车%`, `长途货车%` | `Single Unit Long-haul Truck%` | Single Unit Long-haul Truck |
| 11 | `房车%`, `旅居车%` | `Motor Home%` | Motor Home |
| 12 | `组合短途货车%`, `半挂短途%` | `Combination Short-haul Truck%` | Combination Short-haul Truck |
| 13 | `组合长途货车%`, `半挂长途%`, `重型货车%`, `大货车%`, `货车%` | `Combination Long-haul Truck%` | Combination Long-haul Truck |

**注意**：
- 车型百分比会自动归一化到 100%
- 如果不提供车型分布，系统使用默认值：小汽车70%、客车20%、轻型货车5%、公交车3%、重型货车2%

### 示例文件

**macro_emission_example.csv** (基础版本):
```csv
link_id,link_length_km,link_volume_veh_per_hour,link_avg_speed_kmh
Link_001,2.5,5000,60
Link_002,1.8,3500,45
Link_003,3.2,6000,80
```

**macro_emission_with_fleet.csv** (包含车队组成):
```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,公交车%,货车%
Link_001,2.5,5000,60,70,20,10
Link_002,1.8,3500,45,60,30,10
Link_003,3.2,6000,80,80,10,10
```

**注意**：车型百分比总和不必等于100，系统会自动归一化。例如上面的 70+20+10=100，但如果是 7+2+1=10，系统会自动转换为 70%+20%+10%。

---

## 📋 排放因子查询 - 无需文件

直接通过对话查询，例如：
- "2020年公交车的NOx排放因子"
- "查询2021年小汽车的CO2和PM2.5排放因子"
- "2018年货车在地面道路的NOx排放"

---

## ⚠️ 常见问题

### 1. 文件编码问题
- **推荐使用 UTF-8 编码**
- 如果 Excel 保存的 CSV 文件出现乱码，请使用 "UTF-8 with BOM" 编码

### 2. 列名不匹配
- 系统会自动清理列名中的前后空格
- 列名匹配不区分大小写
- 如果仍然报错"未找到XXX列"，请检查列名是否在支持列表中

### 3. 数据单位
- **速度**: km/h (不是 m/s)
- **加速度**: m/s²
- **坡度**: % (例如 5% 表示 5% 的坡度)
- **长度**: km (不是 m)
- **流量**: 辆/小时 (veh/h)

### 4. 车型分布
- 百分比可以是小数（如 70.5）
- 总和不必等于 100，系统会自动归一化
- 如果某个路段没有车型分布数据，使用默认值

---

## 💡 使用建议

1. **先预览文件**：上传文件后，系统会显示文件预览，确认列名是否正确识别
2. **查看错误提示**：如果列名不匹配，错误信息会列出支持的列名
3. **使用模板**：可以下载系统提供的模板文件作为参考
4. **保持简单**：如果不确定，只提供必需列即可，系统会自动处理可选列

---

## 📞 技术支持

如果遇到文件格式问题：
1. 检查文件编码（推荐 UTF-8）
2. 检查列名是否在支持列表中
3. 查看终端日志中的 `[DEBUG]` 信息
4. 提供文件的前几行内容以便诊断
