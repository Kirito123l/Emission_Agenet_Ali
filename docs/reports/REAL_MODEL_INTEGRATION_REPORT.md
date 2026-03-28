# EmissionAgent 真实模型集成测试报告

生成时间：`2026-03-21`  
项目根目录：`/home/kirito/Agent1/emission_agent`

## 一、模型加载结果

### 1.1 模型文件完整性

- surrogate 模型目录：`ps-xgb-aermod-rline-surrogate/models/`
- roughness 目录：`model_z=0.05`、`model_z=0.5`、`model_z=1`
- 每个 roughness 目录均包含 `12` 个模型文件
- 总模型文件数：`36`

### 1.2 全量真实模型加载结果

本次通过 `tests/test_real_model_integration.py::test_load_all_real_models` 实际加载了全部 `36` 个模型文件。

实际输出：

```text
REAL_MODELS roughness=0.05 stability_classes=6 directional_models=12
REAL_MODELS roughness=0.5 stability_classes=6 directional_models=12
REAL_MODELS roughness=1.0 stability_classes=6 directional_models=12
REAL_MODELS total_loaded=36 models_dir=/home/kirito/Agent1/emission_agent/ps-xgb-aermod-rline-surrogate/models
```

结论：

- 3 套 roughness 模型集均完整
- 6 个稳定度类别均可正常加载
- 每个稳定度类别均有 `x0` 和 `x-1` 两个方向模型

### 1.3 特征维度验证

本次通过 `tests/test_real_model_integration.py::test_model_feature_dimensions` 实际验证了真实模型的特征维度与 `predict_time_series_xgb()` 的实现一致：

| 稳定度类别 | 预期特征维度 | 实测 |
|---|---:|---:|
| `VS` | 7 | 7 |
| `S` | 7 | 7 |
| `N1` | 7 | 7 |
| `N2` | 8 | 8 |
| `U` | 8 | 8 |
| `VU` | 8 | 8 |

结论：

- `VS/S/N1` 的无 HC 分支是 `7` 维
- `N2/U/VU` 的含 HC 分支是 `8` 维
- 与 Sprint 8 的实现假设一致

## 二、真实链路测试结果

### 2.1 `test_20links.xlsx` 完整真实链路

测试链路：

```text
test_20links.xlsx
  -> MacroEmissionCalculator
  -> EmissionToDispersionAdapter
  -> DispersionCalculator (real XGBoost models)
```

实际结果：

```text
MACRO_CHAIN links=20 roads=20 emissions=20
CHAIN_20LINKS receptors=44172 time_steps=1 mean=0.012964 max=1.044068 lon_range=(121.391344,121.499446) lat_range=(31.205890,31.300982)
```

结果解读：

- 宏观排放阶段成功计算 `20` 条路段
- Adapter 成功生成 `20` 条道路和 `20` 条排放记录
- 真实扩散推理成功生成 `44,172` 个受体结果
- 平均浓度：`0.012964 μg/m³`
- 最大浓度：`1.044068 μg/m³`
- 经纬度范围位于上海附近，坐标转换链路正常

### 2.2 六个气象预设对比

测试数据：`test_6links.xlsx`  
roughness：`0.5`

| 气象预设 | 受体数 | 平均浓度 (μg/m³) | 最大浓度 (μg/m³) |
|---|---:|---:|---:|
| `urban_summer_day` | 11024 | 0.017771 | 0.823113 |
| `urban_summer_night` | 11024 | 0.063030 | 2.731809 |
| `urban_winter_day` | 11024 | 0.012329 | 0.743327 |
| `urban_winter_night` | 11024 | 0.069499 | 2.983957 |
| `windy_neutral` | 11024 | 0.021546 | 1.054351 |
| `calm_stable` | 11024 | 0.081312 | 3.651528 |

观察：

- 六个预设全部成功完成真实推理
- `calm_stable` 浓度最高，符合“静风稳定最不利扩散”的物理直觉
- 夜间稳定条件整体高于白天不稳定条件，趋势合理

### 2.3 三个 roughness 模型集对比

测试数据：`test_6links.xlsx`  
气象：`urban_summer_day`

| roughness | 受体数 | 平均浓度 (μg/m³) | 最大浓度 (μg/m³) |
|---|---:|---:|---:|
| `0.05` | 11024 | 0.022686 | 1.374235 |
| `0.5` | 11024 | 0.017771 | 0.823113 |
| `1.0` | 11024 | 0.017879 | 0.773287 |

观察：

- 三套 roughness 模型均可正常工作
- `0.05` 产生更高的平均/峰值浓度
- `0.5` 与 `1.0` 的均值接近，但峰值仍有差异

### 2.4 `spatial_renderer` 渲染结果

测试链路：

```text
real dispersion result
  -> SpatialRendererTool.execute(data_source=result["data"])
```

实际结果：

```text
SPATIAL_RENDERER type=concentration features=995
```

结论：

- 真实扩散结果可被 `SpatialRendererTool` 正确识别为 `concentration` 图层
- 后端成功构建浓度点图层 GeoJSON
- 渲染输出 feature 数量为 `995`

说明：

- 扩散结果总受体数为 `11024`
- 渲染层 feature 少于总受体数，是因为当前 `_build_concentration_map()` 会优先过滤 `mean_conc <= 0` 的零值受体，只保留正浓度点用于前端展示

## 三、性能基线

测试场景：

- 道路数据：`test_20links.xlsx`
- 排放：真实宏观排放结果经 Adapter 转换
- 模型：真实 surrogate 模型，roughness=`0.5`
- 气象：`urban_summer_day`
- 时间步：`1`

实际输出：

```text
============================================================
PERFORMANCE BASELINE (20 links, 1 time step, roughness=0.5)
============================================================
  Total time: 19.30s
  Receptors: 44172
  Mean conc: 0.012964 μg/m³
  Max conc: 1.044068 μg/m³
  Time per receptor: 0.4370ms
============================================================
```

性能结论：

- 20 条路、1 个时间步的真实扩散计算总耗时约 `19.30s`
- 结果规模为 `44,172` 个受体
- 平均到每个受体的推理耗时约 `0.4370ms`

## 四、发现的问题

### 4.1 环境前置：`scikit-learn` 缺失

首次尝试加载真实模型时，当前实现通过 `xgboost.XGBRegressor.load_model()` 载入 JSON 模型，因此运行环境必须安装 `scikit-learn`。在本环境里最初缺少该依赖，真实模型加载直接失败。

错误现象：

```text
ImportError: sklearn needs to be installed in order to use this module
```

处理方式：

- 已在当前 conda 环境中执行 `pip install scikit-learn`
- 安装后，36 个真实模型全部加载成功

影响评估：

- 这不是仓库代码回归
- 这是“真实模型集成测试”特有的环境前置条件
- 后续 benchmark/真实联调环境需要确保 `scikit-learn` 可用

### 4.2 `joblib` 串行模式告警

本次真实模型测试中出现了以下 warning：

```text
UserWarning: [Errno 13] Permission denied.  joblib will operate in serial mode
```

影响：

- 不影响功能正确性
- 但意味着当前环境下 joblib 未启用多进程辅助能力
- 真实测试结果有效，但性能基线偏保守

### 4.3 浓度图层默认过滤零值受体

这是当前设计行为，不是错误，但会影响“结果点数”的直觉理解：

- 扩散器返回 `11024` 个受体
- 渲染器最终绘制 `995` 个 feature

原因：

- `SpatialRendererTool._build_concentration_map()` 默认优先渲染正浓度受体
- 零值受体不会进入前端主图层

## 五、测试结果汇总

### 5.1 真实模型测试文件

命令：

```bash
pytest tests/test_real_model_integration.py -v -s 2>&1 | tee REAL_MODEL_TEST_OUTPUT.txt
```

结果：

- `14 passed, 1 warning in 81.50s`
- 输出文件：`REAL_MODEL_TEST_OUTPUT.txt`

### 5.2 全量回归

命令：

```bash
pytest -q
```

结果：

- `319 passed, 20 warnings in 83.76s`

说明：

- 新增真实模型测试后，测试总数从 `305` 增加到 `319`
- 现有测试无回归

## 六、结论

结论：**真实模型集成测试通过。**

已验证的链路：

1. 真实 surrogate 模型文件可完整加载
2. 真实宏观排放结果可通过 `EmissionToDispersionAdapter` 转为扩散输入
3. `DispersionCalculator` 可在真实模型下完成 `macro -> dispersion` 推理
4. 六个气象预设和三套 roughness 模型集均可正常工作
5. 真实扩散结果可被 `SpatialRendererTool` 渲染为浓度图层

是否可进入 benchmark 构建阶段：**可以。**

建议的下一步：

1. 用 `test_shanghai_full.xlsx` 增加一组中等规模真实 benchmark
2. 为真实模型测试补充一个固定输出快照或统计阈值，形成可重复基线
3. 如果要做更稳定的性能对比，建议单独记录“冷启动含模型加载”和“热启动复用模型”两套基线
