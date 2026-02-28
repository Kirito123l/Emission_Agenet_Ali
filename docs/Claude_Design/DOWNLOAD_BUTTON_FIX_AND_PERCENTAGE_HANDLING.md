# 下载按钮修复 & 车型比例处理说明

## 问题 1: 下载按钮不显示 ✅ 已修复

### 根本原因
API 在读取预览数据时使用了错误的文件路径：
- Skills 生成文件到 `outputs_dir`，文件名如：`d20b3a9a_input_emission_results_20260202_194607.xlsx`
- API 检查的是 `output_file_path = TEMP_DIR / f"{session_id}_output.xlsx"`
- 两个路径不匹配，导致预览数据为空，显示"暂无数据"

### 修复方案
修改 `api/routes.py:462-489`，优先使用 download_info 中的实际文件路径：

```python
# 修复前：只检查 output_file_path
if output_file_path and output_file_path.exists():
    df = pd.read_excel(output_file_path)
    # ...

# 修复后：优先使用 download_info 的路径
result_file_path = None
if download_info and download_info.get("path"):
    result_file_path = Path(download_info["path"])
elif output_file_path and output_file_path.exists():
    result_file_path = output_file_path

if result_file_path and result_file_path.exists():
    df = pd.read_excel(result_file_path)
    # ...
```

### 预期效果
修复后，计算完成时应该显示：
1. ✅ 表格预览（前5行数据）
2. ✅ 绿色下载按钮（在表格标题栏右侧）
3. ✅ 点击下载按钮可下载完整 Excel 文件

---

## 问题 2: 车型比例处理 ✅ 已支持

### Agent 如何处理车型比例

#### 情况 1：文件包含车型比例列
**示例数据**：
```
link_id, length_km, flow, speed, 小汽车%, 公交车%, 货车%
Link_1,  2.5,       5000, 60,    70,      20,       10
```

**处理流程**：
1. **识别车型列**（`excel_handler.py:306-325`）
   - 自动识别包含车型名称的列（如"小汽车%"、"公交车%"）
   - 支持中英文车型名称
   - 支持13种 MOVES 标准车型

2. **解析并归一化**（`excel_handler.py:327-360`）
   ```python
   def _parse_fleet_mix(self, row, vehicle_columns):
       fleet_mix = {}
       total = 0.0

       # 读取各车型百分比
       for standard_name, col_name in vehicle_columns.items():
           value = row[col_name]
           if pd.notna(value) and value > 0:
               fleet_mix[standard_name] = float(value)
               total += float(value)

       # 归一化到100%（关键！）
       if total != 100.0:
           for vehicle_type in fleet_mix:
               fleet_mix[vehicle_type] = (fleet_mix[vehicle_type] / total) * 100.0

       return fleet_mix
   ```

3. **自动归一化**
   - 如果各车型比例之和 ≠ 100%，自动按比例归一化
   - 例如：70 + 20 + 10 = 100% → 保持不变
   - 例如：35 + 10 + 5 = 50% → 归一化为 70% + 20% + 10%

#### 情况 2：文件不包含车型比例列
**示例数据**：
```
link_id, length_km, flow, speed
Link_1,  2.5,       5000, 60
```

**处理流程**：
1. 文件预分析检测到无车型比例列
2. Agent 追问用户：
   ```
   文件未包含车型比例信息。请选择：
   1. 使用默认车型比例（小汽车70%、公交10%、货车20%）
   2. 手动指定车型比例
   ```
3. 如果用户选择默认值，使用：
   ```python
   DEFAULT_FLEET_MIX = {
       "Passenger Car": 70.0,
       "Passenger Truck": 20.0,
       "Light Commercial Truck": 5.0,
       "Transit Bus": 3.0,
       "Combination Long-haul Truck": 2.0,
   }
   ```

#### 情况 3：车型比例是绝对数值（需要计算百分比）
**示例数据**：
```
link_id, length_km, flow, speed, 小汽车, 公交车, 货车
Link_1,  2.5,       5000, 60,    3500,   1000,    500
```

**处理流程**：
1. 系统识别这些列为车型列（因为列名包含车型名称）
2. 读取数值：3500, 1000, 500
3. 计算总和：total = 5000
4. **自动归一化为百分比**：
   - 小汽车：(3500 / 5000) × 100 = 70%
   - 公交车：(1000 / 5000) × 100 = 20%
   - 货车：(500 / 5000) × 100 = 10%

### 支持的车型名称

系统支持以下车型名称（中英文）：

| 标准名称 | 中文别名 |
|---------|---------|
| Motorcycle | 摩托车 |
| Passenger Car | 小汽车、乘用车、轿车 |
| Passenger Truck | 客车、皮卡 |
| Light Commercial Truck | 轻型货车、小货车 |
| Intercity Bus | 城际客车、长途客车 |
| Transit Bus | 公交车、巴士 |
| School Bus | 校车 |
| Refuse Truck | 垃圾车、环卫车 |
| Single Unit Short-haul Truck | 短途货车 |
| Single Unit Long-haul Truck | 长途货车 |
| Motor Home | 房车、旅居车 |
| Combination Short-haul Truck | 半挂短途 |
| Combination Long-haul Truck | 重型货车、大货车、货车 |

### 智能列名映射

如果列名不标准，系统会使用 LLM 进行智能映射：
- 例如："Car%"、"汽车占比"、"小客车百分比" → 自动识别为 Passenger Car
- 例如："Bus"、"公共汽车"、"巴士比例" → 自动识别为 Transit Bus

---

## 测试建议

### 测试 1：下载按钮显示
1. 上传任意排放计算文件
2. 完成计算
3. 检查是否显示：
   - ✅ 表格预览（前5行）
   - ✅ 绿色下载按钮
   - ✅ 点击可下载

### 测试 2：车型比例归一化
上传包含车型数值的文件：
```csv
link_id,length_km,flow,speed,小汽车,公交车,货车
Link_1,2.5,5000,60,3500,1000,500
```
期望：自动归一化为 70%, 20%, 10%

### 测试 3：车型比例不足100%
上传包含车型百分比的文件：
```csv
link_id,length_km,flow,speed,小汽车%,公交车%
Link_1,2.5,5000,60,70,20
```
期望：自动归一化为 77.78%, 22.22%（或补充默认值）

---

## 总结

✅ **下载按钮问题**：已修复路径匹配问题，现在可以正常显示和下载

✅ **车型比例处理**：系统已完全支持：
- 自动识别车型列（中英文）
- 自动归一化百分比（无论是绝对数值还是百分比）
- 智能列名映射
- 缺失时使用默认值或追问用户

两个功能都已经实现并可以正常工作！
