# 文档完善和车队组成功能说明

## 📋 完成内容

### 1. 创建了完整的文件格式说明文档

**文件**: `FILE_FORMAT_GUIDE.md`

**包含内容**：
- ✅ 支持的文件格式（CSV, XLSX, XLS）
- ✅ 微观排放文件格式（必需列、可选列、示例）
- ✅ 宏观排放文件格式（必需列、可选列、车型分布、示例）
- ✅ 所有支持的列名变体
- ✅ 数据单位说明
- ✅ 常见问题解答
- ✅ 使用建议

### 2. 创建了车队组成功能说明文档

**文件**: `FLEET_MIX_GUIDE.md`

**包含内容**：
- ✅ 车队组成功能说明
- ✅ 支持的车型列名（中英文对照）
- ✅ 百分比处理规则（自动归一化、默认值）
- ✅ 实际应用示例（城市道路、高速公路、公交专用道等）
- ✅ 技术实现细节
- ✅ 注意事项和使用建议

### 3. 改进了 Agent 的 System Prompt

**文件**: `agent/prompts/system.py`

**新增内容**：
- ✅ 文件格式要求说明
- ✅ 支持的列名列表
- ✅ 文件格式示例
- ✅ 车队组成说明

**效果**：当用户上传文件失败时，Agent 会明确告知支持的列名和格式要求。

---

## 🎯 车队组成功能分析

### ✅ 系统已完整支持车队组成！

经过代码分析，确认系统已经实现了完整的车队组成功能：

#### 1. 自动识别车型列

系统会自动识别包含以下车型名称的列（支持中英文）：

| 车型类别 | 中文列名 | 英文列名 | 标准名称 |
|---------|---------|---------|---------|
| 乘用车 | 小汽车、乘用车、轿车 | Passenger Car | Passenger Car |
| 客车 | 客车、皮卡 | Passenger Truck | Passenger Truck |
| 公交车 | 公交车、巴士 | Transit Bus | Transit Bus |
| 轻型货车 | 轻型货车、小货车 | Light Commercial Truck | Light Commercial Truck |
| 重型货车 | 重型货车、大货车、货车 | Combination Long-haul Truck | Combination Long-haul Truck |
| 其他 | 摩托车、校车、城际客车、垃圾车 | Motorcycle, School Bus, Intercity Bus, Refuse Truck | 对应标准名称 |

#### 2. 智能处理百分比

- **自动归一化**：无论输入的百分比总和是多少，系统都会自动归一化到 100%
  - 例如：7+2+1=10 → 自动转换为 70%+20%+10%
- **默认值**：如果不提供车型分布，使用默认值（小汽车70%、客车20%、轻型货车5%、公交车3%、重型货车2%）

#### 3. 灵活的列名格式

支持多种列名格式：
- ✅ `小汽车%` (带百分号)
- ✅ `小汽车` (不带百分号)
- ✅ `乘用车%` (同义词)
- ✅ `Passenger Car%` (英文)
- ✅ `公交车％` (全角百分号)

#### 4. 实际应用示例

**城市主干道**：
```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,公交车%,货车%
Main_Street,3.5,8000,50,75,15,10
```

**高速公路**：
```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,客车%,重型货车%
Highway_G1,25.0,12000,100,60,20,20
```

**公交专用道**：
```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,公交车%,货车%
Bus_Lane,3.0,3000,30,20,70,10
```

---

## 📊 文件格式完整说明

### 微观排放（轨迹文件）

**必需列**：
- 速度：`speed_kph`, `speed_kmh`, `speed`, `车速`, `速度`

**可选列**：
- 时间：`t`, `time`, `time_sec`, `时间`
- 加速度：`acceleration`, `acc`, `acceleration_mps2`, `acceleration_m_s2`, `加速度`
- 坡度：`grade_pct`, `grade`, `坡度`

**示例**：
```csv
time_sec,speed_kmh,acceleration_m_s2
0,0,0
1,5,1.39
2,12,1.94
```

### 宏观排放（路段文件）

**必需列**：
- 路段长度：`link_length_km`, `length_km`, `length`, `路段长度`, `长度`
- 交通流量：`traffic_flow_vph`, `flow_vph`, `flow`, `traffic`, `link_volume_veh_per_hour`, `volume_veh_per_hour`, `volume`, `交通流量`, `流量`
- 平均速度：`avg_speed_kph`, `speed_kph`, `speed`, `link_avg_speed_kmh`, `avg_speed_kmh`, `speed_kmh`, `平均速度`, `速度`

**可选列**：
- 路段ID：`link_id`, `id`, `路段ID`, `路段编号`
- 车型分布：列名包含车型名称+`%`

**示例（基础）**：
```csv
link_id,link_length_km,link_volume_veh_per_hour,link_avg_speed_kmh
Link_001,2.5,5000,60
Link_002,1.8,3500,45
```

**示例（含车队组成）**：
```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,公交车%,货车%
Link_001,2.5,5000,60,70,20,10
Link_002,1.8,3500,45,60,30,10
```

---

## 🔄 Agent 回复改进

现在当用户上传文件失败时，Agent 会：

1. **明确指出问题**：例如"未找到速度列"
2. **列出支持的列名**：告知用户所有支持的列名变体
3. **提供示例格式**：展示正确的文件格式
4. **说明车队组成**：如果是宏观排放，说明如何添加车型分布

**示例回复**：
```
根据执行结果，文件读取失败。

**问题**：未找到交通流量列

**支持的列名**：
- 交通流量：traffic_flow_vph, flow_vph, flow, traffic, link_volume_veh_per_hour, volume_veh_per_hour, volume, 交通流量, 流量

**您的文件列名**：link_id, link_length_km, link_volume, link_avg_speed_kmh

**建议**：请将 "link_volume" 改为 "link_volume_veh_per_hour" 或其他支持的列名。

**正确的文件格式示例**：
```csv
link_id,link_length_km,link_volume_veh_per_hour,link_avg_speed_kmh
Link_001,2.5,5000,60
```

**可选：添加车队组成**
如果需要指定不同车型的百分比，可以添加车型列：
```csv
link_id,link_length_km,link_volume_veh_per_hour,link_avg_speed_kmh,小汽车%,公交车%,货车%
Link_001,2.5,5000,60,70,20,10
```
```

---

## 📁 创建的文档

1. **FILE_FORMAT_GUIDE.md** - 完整的文件格式说明
2. **FLEET_MIX_GUIDE.md** - 车队组成功能详细说明

这两个文档可以：
- 提供给用户作为参考
- 作为系统文档的一部分
- 帮助新用户快速上手

---

## ✅ 总结

### 回答您的问题：

1. **我们支持哪些列名？**
   - 已在 `FILE_FORMAT_GUIDE.md` 中详细列出
   - Agent 的 system prompt 已更新，会在错误时告知用户

2. **车队组成如何呈现？**
   - 在宏观排放文件中添加包含车型名称的列（如 `小汽车%`, `公交车%`）
   - 系统会自动识别并处理
   - 已在 `FLEET_MIX_GUIDE.md` 中详细说明

3. **当前能否处理车队组成？**
   - ✅ **完全支持！**
   - 系统已实现完整的车队组成功能
   - 支持中英文车型名称
   - 自动归一化百分比
   - 提供默认值

### 下一步：

1. 重启服务器以应用 system prompt 的更新
2. 测试文件上传功能，验证 Agent 是否能正确提示用户
3. 将文档提供给用户参考

---

## 📞 用户使用指南

**如果文件上传失败**：
1. 查看 Agent 的错误提示，了解缺少哪个列
2. 参考 `FILE_FORMAT_GUIDE.md` 查看支持的列名
3. 修改文件列名后重新上传

**如果需要指定车队组成**：
1. 参考 `FLEET_MIX_GUIDE.md` 了解如何添加车型列
2. 在文件中添加车型百分比列（如 `小汽车%`, `公交车%`）
3. 系统会自动识别并使用

**如果不确定格式**：
1. 查看文档中的示例文件
2. 下载系统提供的模板文件
3. 先上传文件预览，确认列名是否正确识别
