# 13种车型映射完善报告

## 🎯 问题发现

用户指出系统应该支持 **13 种 MOVES 标准车型映射**，但经过检查发现：

### 原有问题

**微观排放 calculator** (`skills/micro_emission/calculator.py`):
- ✅ 已正确定义 13 种标准车型

**宏观排放 excel_handler** (`skills/macro_emission/excel_handler.py`):
- ❌ 只映射了 9 种车型
- ❌ 缺少 4 种车型：
  1. Single Unit Short-haul Truck (单体短途货车)
  2. Single Unit Long-haul Truck (单体长途货车)
  3. Motor Home (房车)
  4. Combination Short-haul Truck (组合短途货车)

---

## ✅ 修复内容

### 修复1: 补全宏观排放车型映射

**修改文件**: `skills/macro_emission/excel_handler.py`

**位置**: 第 27-45 行 → 第 27-68 行

**修改内容**: 添加了缺失的 4 种车型及其中文别名

```python
# 完整的13种MOVES标准车型
VEHICLE_TYPE_MAPPING = {
    # 1. 摩托车
    "摩托车": "Motorcycle",

    # 2. 乘用车
    "乘用车": "Passenger Car",
    "小汽车": "Passenger Car",
    "轿车": "Passenger Car",

    # 3. 客车/皮卡
    "客车": "Passenger Truck",
    "皮卡": "Passenger Truck",

    # 4. 轻型商用车
    "轻型货车": "Light Commercial Truck",
    "小货车": "Light Commercial Truck",
    "轻型商用车": "Light Commercial Truck",

    # 5. 城际客车
    "城际客车": "Intercity Bus",
    "长途客车": "Intercity Bus",

    # 6. 公交车
    "公交车": "Transit Bus",
    "巴士": "Transit Bus",
    "市内公交": "Transit Bus",

    # 7. 校车
    "校车": "School Bus",

    # 8. 垃圾车
    "垃圾车": "Refuse Truck",
    "环卫车": "Refuse Truck",

    # 9. 单体短途货车 ⭐ 新增
    "单体短途货车": "Single Unit Short-haul Truck",
    "短途货车": "Single Unit Short-haul Truck",

    # 10. 单体长途货车 ⭐ 新增
    "单体长途货车": "Single Unit Long-haul Truck",
    "长途货车": "Single Unit Long-haul Truck",

    # 11. 房车 ⭐ 新增
    "房车": "Motor Home",
    "旅居车": "Motor Home",

    # 12. 组合短途货车 ⭐ 新增
    "组合短途货车": "Combination Short-haul Truck",
    "半挂短途": "Combination Short-haul Truck",

    # 13. 组合长途货车/重型货车
    "组合长途货车": "Combination Long-haul Truck",
    "半挂长途": "Combination Long-haul Truck",
    "重型货车": "Combination Long-haul Truck",
    "大货车": "Combination Long-haul Truck",
    "货车": "Combination Long-haul Truck",
}
```

### 修复2: 更新文档

**修改文件**:
1. `FLEET_MIX_GUIDE.md` - 车队组成功能说明
2. `FILE_FORMAT_GUIDE.md` - 文件格式说明

**更新内容**:
- 明确标注支持 **13 种 MOVES 标准车型**
- 添加完整的车型列表（包含 Source Type ID）
- 补充新增车型的中英文列名示例

---

## 📊 完整的13种MOVES标准车型

| 序号 | MOVES 标准车型 | Source Type ID | 中文名称 | 英文列名示例 |
|-----|---------------|----------------|---------|-------------|
| 1 | Motorcycle | 11 | 摩托车 | `Motorcycle%` |
| 2 | Passenger Car | 21 | 小汽车、乘用车、轿车 | `Passenger Car%` |
| 3 | Passenger Truck | 31 | 客车、皮卡 | `Passenger Truck%` |
| 4 | Light Commercial Truck | 32 | 轻型货车、小货车、轻型商用车 | `Light Commercial Truck%` |
| 5 | Intercity Bus | 41 | 城际客车、长途客车 | `Intercity Bus%` |
| 6 | Transit Bus | 42 | 公交车、巴士、市内公交 | `Transit Bus%` |
| 7 | School Bus | 43 | 校车 | `School Bus%` |
| 8 | Refuse Truck | 51 | 垃圾车、环卫车 | `Refuse Truck%` |
| 9 | Single Unit Short-haul Truck | 52 | 单体短途货车、短途货车 | `Single Unit Short-haul Truck%` |
| 10 | Single Unit Long-haul Truck | 53 | 单体长途货车、长途货车 | `Single Unit Long-haul Truck%` |
| 11 | Motor Home | 54 | 房车、旅居车 | `Motor Home%` |
| 12 | Combination Short-haul Truck | 61 | 组合短途货车、半挂短途 | `Combination Short-haul Truck%` |
| 13 | Combination Long-haul Truck | 62 | 组合长途货车、半挂长途、重型货车、大货车、货车 | `Combination Long-haul Truck%` |

---

## 🧪 使用示例

### 示例1: 高速公路（含多种货车类型）

```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,客车%,单体短途货车%,单体长途货车%,组合短途货车%,组合长途货车%
Highway_G1,25.0,12000,100,50,10,5,10,10,15
```

### 示例2: 城市道路（含房车）

```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,公交车%,房车%,货车%
Urban_Road,5.0,6000,50,70,15,5,10
```

### 示例3: 工业区（含多种货车）

```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,轻型货车%,短途货车%,长途货车%,半挂长途%
Industrial_Zone,8.0,5000,40,30,20,15,15,20
```

---

## ⚠️ 重要说明

### 1. 车型分类说明

**单体货车 (Single Unit Truck)**:
- 车头和货箱为一体的货车
- 短途 (Short-haul): 主要用于城市配送
- 长途 (Long-haul): 用于长距离运输

**组合货车 (Combination Truck)**:
- 车头和拖车分离的货车（半挂车）
- 短途 (Short-haul): 区域运输
- 长途 (Long-haul): 长距离运输

**房车 (Motor Home)**:
- 自行式房车
- 用于旅行和休闲

### 2. 中文列名建议

为了更好的识别，建议使用以下中文列名：

| 车型 | 推荐列名 | 备选列名 |
|------|---------|---------|
| 单体短途货车 | `短途货车%` | `单体短途货车%` |
| 单体长途货车 | `长途货车%` | `单体长途货车%` |
| 房车 | `房车%` | `旅居车%` |
| 组合短途货车 | `半挂短途%` | `组合短途货车%` |
| 组合长途货车 | `半挂长途%` | `组合长途货车%`, `重型货车%` |

### 3. 默认车队组成

如果不提供车型分布，系统使用默认值：
- Passenger Car (小汽车): 70%
- Passenger Truck (客车): 20%
- Light Commercial Truck (轻型货车): 5%
- Transit Bus (公交车): 3%
- Combination Long-haul Truck (重型货车): 2%

**注意**: 默认值不包含新增的4种车型，如需使用这些车型，必须在文件中明确指定。

---

## 📝 文件修改清单

| 文件 | 修改内容 | 状态 |
|------|---------|------|
| `skills/macro_emission/excel_handler.py` | 补全13种车型映射 | ✅ 已完成 |
| `FLEET_MIX_GUIDE.md` | 更新车型列表 | ✅ 已完成 |
| `FILE_FORMAT_GUIDE.md` | 更新车型列表 | ✅ 已完成 |

---

## 🎯 测试建议

### 测试1: 验证新增车型识别

创建测试文件 `test_13_vehicles.csv`:

```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,小汽车%,短途货车%,长途货车%,房车%,半挂短途%,半挂长途%
Test_Link,10.0,5000,60,40,10,10,5,10,25
```

上传并计算，验证系统是否能正确识别所有车型。

### 测试2: 验证中英文混用

```csv
link_id,link_length_km,traffic_flow_vph,avg_speed_kph,Passenger Car%,短途货车%,Motor Home%,半挂长途%
Mixed_Link,5.0,3000,50,50,20,10,20
```

验证中英文列名混用是否正常工作。

---

## ✅ 成功标准

- [x] 宏观排放支持完整的13种MOVES标准车型
- [x] 每种车型都有合适的中文别名
- [x] 文档已更新，反映完整的车型列表
- [ ] 测试验证所有车型都能正确识别
- [ ] 测试验证车队组成计算正确

---

## 🙏 感谢

感谢用户指出这个重要的遗漏！现在系统已经支持完整的13种MOVES标准车型，可以更准确地进行宏观排放计算。

---

## 📞 后续工作

1. **重启服务器**以应用更新
2. **测试新增车型**的识别和计算
3. **更新用户文档**，告知支持完整的13种车型
4. **考虑添加车型说明**，帮助用户理解不同车型的区别
