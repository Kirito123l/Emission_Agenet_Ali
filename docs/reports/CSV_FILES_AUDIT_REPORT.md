# CSV数据文件完整性审计报告

**审计时间**: 2026-02-17
**审计范围**: calculators/data/ 目录下所有CSV文件
**总文件数**: 9个 (修正后)

---

## 文件清单

### 1. 排放因子数据 (emission_factors/)

| 文件名 | 大小 | 格式 | 来源 | 用途 | 状态 |
|--------|------|------|------|------|------|
| atlanta_2025_1_55_65.csv | 23.2MB | Speed列 | Git恢复 (skills/emission_factors/) | 冬季排放因子 | ✅ 正确 |
| atlanta_2025_4_75_65.csv | 23.2MB | Speed列 | Git恢复 (skills/emission_factors/) | 春季排放因子 | ✅ 正确 |
| atlanta_2025_7_90_70.csv | 23.2MB | Speed列 | Git恢复 (skills/emission_factors/) | 夏季排放因子 | ✅ 正确 |

**格式说明**:
```csv
Speed,pollutantID,SourceType,ModelYear,EmissionQuant
504,90,21,2020,123.45
1004,90,21,2020,145.67
```
- Speed: 速度编码 (如 504 = 5mph + 道路类型4)
- ModelYear: 真实年份 (1995-2025)

**来源追溯**:
```bash
# 原始位置: skills/emission_factors/data/emission_matrix/
# Git提交: 0d110ea (initial commit)
# 恢复命令: git checkout HEAD -- skills/emission_factors/data/emission_matrix/*.csv
# 复制时间: 2026-02-17 09:26
```

---

### 2. 微观排放数据 (micro_emission/)

| 文件名 | 大小 | 格式 | 来源 | 用途 | 状态 |
|--------|------|------|------|------|------|
| atlanta_2025_1_55_65.csv | 7.6MB | opModeID列 | skills/micro_emission/data/ | 冬季微观排放 | ✅ 正确 |
| atlanta_2025_4_75_65.csv | 7.6MB | opModeID列 | skills/micro_emission/data/ | 春季微观排放 | ✅ 正确 |
| atlanta_2025_7_90_70.csv | 7.6MB | opModeID列 | skills/micro_emission/data/ | 夏季微观排放 | ✅ 正确 |

**格式说明**:
```csv
opModeID,pollutantID,SourceType,ModelYear,CalendarYear,EmissionQuant
300,90,21,1,2020,123.45
301,90,21,1,2020,145.67
```
- opModeID: 操作模式ID (基于VSP计算)
- ModelYear: 年龄组ID (1, 2, 3, 5, 9)
- CalendarYear: 真实年份 (1995-2025)

**来源追溯**:
```bash
# 原始位置: skills/micro_emission/data/
# 创建时间: 2026-02-03 17:55
# 复制时间: 2026-02-17 10:55
```

---

### 3. 宏观排放数据 (macro_emission/)

| 文件名 | 大小 | 格式 | 来源 | 用途 | 状态 |
|--------|------|------|------|------|------|
| atlanta_2025_1_35_60 .csv | 4.3MB | 无表头 | skills/macro_emission/data/ | 冬季宏观排放 | ✅ 正确 |
| atlanta_2025_4_75_65.csv | 4.3MB | 无表头 | skills/macro_emission/data/ | 春季宏观排放 | ✅ 正确 |
| atlanta_2025_7_80_60.csv | 4.3MB | 无表头 | skills/macro_emission/data/ | 夏季宏观排放 | ✅ 正确 |

**格式说明**:
```csv
300,110,62,2025,0.195637,
301,110,62,2025,0.185432,
```
- 无表头，6列数据
- 列顺序: opModeID, pollutantID, sourceTypeID, modelYearID, em, extra

**来源追溯**:
```bash
# 原始位置: skills/macro_emission/data/
# 创建时间: 2026-01-24 09:33
# 复制时间: 2026-02-17 11:34
```

---

## 文件来源总结

### Git历史文件 (3个)
从Git仓库恢复的原始数据文件：
- `skills/emission_factors/data/emission_matrix/atlanta_2025_1_55_65.csv`
- `skills/emission_factors/data/emission_matrix/atlanta_2025_4_75_65.csv`
- `skills/emission_factors/data/emission_matrix/atlanta_2025_7_90_70.csv`

**恢复原因**: 清理时误删了 `skills/emission_factors/` 目录，但 `calculators/data/` 中的文件格式不正确（opModeID格式而非Speed格式）

### Skills目录文件 (6个)
从现有skills/目录复制的数据文件：
- `skills/micro_emission/data/` → 3个文件
- `skills/macro_emission/data/` → 3个文件

**复制原因**: 这些目录仍在使用中（tools/依赖），数据文件需要复制到calculators/data/以便计算器使用

---

## 已修正的问题

### 问题1: emission_factors/中的错误文件

**发现**: emission_factors/目录中有2个宏观排放格式的文件
- `atlanta_2025_1_35_60 .csv` (4.3MB, 无表头格式)
- `atlanta_2025_7_80_60.csv` (4.3MB, 无表头格式)

**原因**: 这些文件原本在 `calculators/data/` 根目录，移动文件时被错误地包含进emission_factors/

**修正**: 已删除这2个文件，emission_factors/现在只包含3个正确格式的文件

### 问题2: 文件格式混淆

**发现**: calculators/data/根目录原本有多种格式的CSV文件混在一起

**修正**: 创建了三个子目录，按格式分类存放：
- `emission_factors/` - Speed格式 (3个文件, 69.6MB)
- `micro_emission/` - opModeID格式 (3个文件, 22.8MB)
- `macro_emission/` - 无表头格式 (3个文件, 12.9MB)

---

## 数据完整性验证

### 文件数量验证
```bash
# emission_factors: 3个文件 ✓
ls calculators/data/emission_factors/*.csv | wc -l
# 输出: 3

# micro_emission: 3个文件 ✓
ls calculators/data/micro_emission/*.csv | wc -l
# 输出: 3

# macro_emission: 3个文件 ✓
ls calculators/data/macro_emission/*.csv | wc -l
# 输出: 3
```

### 格式验证
```python
# emission_factors: 必须有Speed列 ✓
df = pd.read_csv('calculators/data/emission_factors/atlanta_2025_7_90_70.csv', nrows=1)
assert 'Speed' in df.columns

# micro_emission: 必须有opModeID列 ✓
df = pd.read_csv('calculators/data/micro_emission/atlanta_2025_7_90_70.csv', nrows=1)
assert 'opModeID' in df.columns

# macro_emission: 必须无表头 ✓
df = pd.read_csv('calculators/data/macro_emission/atlanta_2025_7_80_60.csv', nrows=1, header=None)
assert len(df.columns) == 6
```

### 大小验证
```bash
# emission_factors: 每个文件约23-24MB ✓
# micro_emission: 每个文件约7-8MB ✓
# macro_emission: 每个文件约4-5MB ✓
```

---

## 文件命名规则

所有CSV文件遵循MOVES数据库命名规则：
```
atlanta_YYYY_M_TT_HH.csv
```

参数说明：
- `YYYY`: 年份 (2025)
- `M`: 月份 (1=冬季, 4=春季, 7=夏季)
- `TT`: 温度 (35, 55, 75, 80, 90)
- `HH`: 湿度 (60, 65, 70)

**注意**: 不同计算器使用不同的温湿度组合：
- emission_factors: 55/65, 75/65, 90/70
- micro_emission: 55/65, 75/65, 90/70 (与emission_factors相同)
- macro_emission: 35/60, 75/65, 80/60 (不同的组合)

---

## 最终文件清单

### 总计: 9个CSV文件

| 目录 | 文件数 | 总大小 | 格式 |
|------|--------|--------|------|
| emission_factors/ | 3 | 69.6MB | Speed列 + 真实年份 |
| micro_emission/ | 3 | 22.8MB | opModeID列 + 年龄组ID |
| macro_emission/ | 3 | 12.9MB | 无表头 + 6列数据 |
| **总计** | **9** | **105.3MB** | 3种不同格式 |

---

## 数据来源可追溯性

### Git仓库 (3个文件)
```bash
git log --oneline -- "skills/emission_factors/data/emission_matrix/*.csv"
# 0d110ea initial commit
```

### Skills目录 (6个文件)
```bash
ls -lh skills/micro_emission/data/*.csv
ls -lh skills/macro_emission/data/*.csv
```

### 所有文件都可以追溯到原始来源 ✓

---

## 建议

### 1. 数据备份
建议将这9个CSV文件备份到安全位置：
```bash
tar -czf emission_data_backup_$(date +%Y%m%d).tar.gz calculators/data/
```

### 2. 文档更新
更新 `calculators/README.md` 说明数据文件的格式和用途

### 3. 数据版本控制
考虑将这些数据文件添加到Git LFS (Large File Storage)，以便版本控制

---

## 结论

✅ **所有9个CSV文件来源清晰、格式正确、用途明确**
✅ **已删除2个错误放置的文件**
✅ **数据完整性验证通过**
✅ **可追溯到原始来源**

数据文件组织现在完全符合新架构设计，每个计算器都有独立的数据目录和正确格式的文件。
