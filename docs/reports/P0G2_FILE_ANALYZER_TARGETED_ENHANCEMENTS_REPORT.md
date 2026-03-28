# P0G2 File Analyzer Targeted Enhancements Report

## 1. Summary

本轮在不改变 planning / repair / continuation 主语义的前提下，增强了 `tools/file_analyzer.py` 的 file grounding 深度。实现重点是：

- ZIP/GIS 多数据集场景下的 rule-first 多表角色识别
- 结构化 missing-field diagnostics
- Shapefile 关键空间元数据提取
- 对应 trace 的正式发射与 formatter 支持

目标已达到：file analyzer 现在不再只输出单一 `selected_primary_table`，而是能在 canonical analysis dict 中同时暴露 `dataset_roles`、`dataset_role_summary`、`missing_field_diagnostics`、`spatial_metadata`，并且这些增强信息仍然兼容现有 router state loop 的 `file_context` 读取方式。

## 2. Files Changed

- `tools/file_analyzer.py`
  - 新增多数据集角色分配 helper、missing-field diagnostics、spatial metadata 提取。
  - 重写 ZIP 分析主路径为“提取 candidate datasets -> rule scoring -> role assignment -> 选择 primary analysis dataset”。
- `core/file_analysis_fallback.py`
  - 把 `dataset_roles` / `dataset_role_summary` / `spatial_metadata` / `missing_field_diagnostics` 接入现有 fallback payload。
  - 将 ZIP/GIS fallback 触发条件收紧为“多数据集且 role assignment 仍 ambiguous”。
- `core/router.py`
  - 在 file grounding trace 后补充 file analysis enhancement trace 发射。
  - 更新 fallback prompt，使其在 ambiguous multi-dataset case 中可以返回 bounded `dataset_roles`。
- `core/trace.py`
  - 新增 file analysis enhancement trace types 和 formatter。
- `tests/test_file_analyzer_targeted_enhancements.py`
  - 新增 analyzer 定向测试，覆盖 multi-table roles、missing-field diagnostics、spatial metadata。
- `tests/test_file_analysis_fallback.py`
  - 扩展 fallback 测试，覆盖 ambiguous multi-dataset 才触发 role fallback。
- `tests/test_router_state_loop.py`
  - 扩展 state loop trace 测试，覆盖 file analysis enhancement trace emission。
- `tests/test_trace.py`
  - 扩展 user-friendly formatter 测试。

## 3. Multi-Table Role Recognition

### 角色枚举

本轮把 ZIP/GIS 多数据集角色限制在一个有限集合内：

- `primary_analysis`
- `secondary_analysis`
- `trajectory_candidate`
- `spatial_context`
- `supporting_component`
- `supporting_asset`
- `metadata`

### 规则分配逻辑

核心实现在 `tools/file_analyzer.py`：

- `_collect_zip_candidate_analyses(...)`
  - 只对 `.csv/.xlsx/.xls/.shp` 这些 bounded candidate datasets 做轻量分析。
- `_score_dataset_candidate(...)`
  - 根据 `task_type`、`confidence`、required-field completeness、文件名 hint、是否 shapefile 做 rule score。
- `_build_dataset_roles(...)`
  - 先按 score 选 `selected_primary_table`
  - 再为所有 candidate datasets 和 supporting files 分配 bounded role
  - 同时输出 `dataset_role_summary`

### fallback 触发条件

本轮没有把所有 multi-dataset ZIP 都交给 LLM。`core/file_analysis_fallback.py::_zip_gis_structure_is_complex(...)` 现在要求：

- `format` 是 ZIP 类输入
- `candidate_tables` 多于 1 个
- 且 `dataset_role_summary.ambiguous == True` 或没有稳定 primary selection

也就是说，role fallback 只在 rule scoring 仍不自洽的多数据集 case 上触发。

### 最终输出如何保持兼容

兼容策略是“只加字段，不改旧字段语义”：

- 旧字段仍保留：
  - `task_type`
  - `confidence`
  - `column_mapping`
  - `selected_primary_table`
  - `candidate_tables`
- 新字段作为附加面暴露：
  - `dataset_roles`
  - `dataset_role_summary`

因此后续 planning / continuation / parameter negotiation 不需要重写；它们仍然读取原有 canonical analysis dict，只是现在能拿到更丰富的 grounding 证据。

## 4. Missing-Field Diagnostics

### 诊断结构

实现在 `tools/file_analyzer.py::_build_missing_field_diagnostics(...)`。输出字段是：

- `task_type`
- `status`
- `required_fields`
- `mapped_fields`
- `required_field_statuses`
- `missing_fields`
- `derivable_opportunities`

### status 枚举

顶层 `status` 限制为：

- `complete`
- `partial`
- `insufficient`
- `unknown_task`

field-level `status` 限制为：

- `present`
- `derivable`
- `ambiguous`
- `missing`

### derivable opportunities 如何识别

实现在 `tools/file_analyzer.py::_identify_derivable_candidates(...)`，规则是 bounded 的：

- `speed_kph` / `avg_speed_kph`
  - `possible_vehicle_speed_ms`
  - `possible_link_speed_kmh`
  - `spd/speed/vel` token
- `traffic_flow_vph`
  - `possible_traffic_flow`
  - `flow/vol/aadt/traffic` token
- `link_length_km`
  - `possible_link_length`
  - `len/length/dist/km`
  - `meter/_m` 触发 unit-conversion hint
- `time`
  - `timestamp`
  - `time/timestamp/datetime/date`
- `acceleration_mps2`
  - `possible_acceleration`
  - `acc/accel`
- `grade_pct`
  - `possible_percentage`
  - `possible_fraction`
  - `grade/slope/pct/percent`

这里没有做 automatic field repair，只做 bounded derivation opportunity exposure。

### 为什么这能增强 file-driven grounding 的论文叙事

这让 file grounding 不再是“字段没识别出来就模糊失败”，而是能明确说明：

- 哪些 required fields 已 present
- 哪些仍 missing
- 哪些只是需要 bounded conversion / confirmation 才能继续

这直接强化了论文中的“显式中间表示 + 保守约束 + 可审计 grounding”叙事。

## 5. Spatial Metadata Extraction

### 提取了哪些元数据

实现在 `tools/file_analyzer.py::_extract_spatial_metadata(...)`，输出包括：

- `geometry_column`
- `feature_count`
- `geometry_types`
- `geometry_type_counts`
- `crs`
- `epsg`
- `is_projected`
- `is_geographic`
- `has_z`
- `bounds`

### 放在输出的什么位置

Shapefile / ZIP-shapefile analysis dict 中新增：

- `spatial_metadata`

同时保留旧的：

- `geometry_types`
- `bounds`

这样既兼容旧逻辑，又给后续空间分析足够的 canonical metadata surface。

### 为什么这些信息对后续空间分析有价值

这些信息可以作为后续空间工具选择和空间结果解释的 grounding evidence：

- `geometry_types` 区分 link-like vs point-like spatial layer
- `crs/epsg` 暴露坐标参考信息
- `bounds` 暴露空间覆盖范围
- `feature_count` 和 `geometry_type_counts` 暴露数据规模和几何一致性

本轮没有把这些 metadata 直接接成新的 planner/executor 逻辑，但它已经成为可读、可 trace 的正式输出。

## 6. Trace Extensions

### 新增了哪些 trace

在 `core/trace.py` 中新增：

- `FILE_ANALYSIS_MULTI_TABLE_ROLES`
- `FILE_ANALYSIS_MISSING_FIELDS`
- `FILE_ANALYSIS_SPATIAL_METADATA`

### 在哪些路径写入

写入点在 `core/router.py::_state_handle_input()` 的 file grounding 阶段：

1. 先记录原有 `FILE_GROUNDING`
2. 再调用 `_record_file_analysis_enhancement_traces(...)`
3. 根据 analysis dict 中是否存在：
   - 多 dataset roles
   - 非 complete 的 missing-field diagnostics
   - spatial metadata
   选择性写入新 trace

### 为什么这些 trace 对论文有用

这些 trace 把 file grounding 的增强点从“内部实现细节”变成了正式可审计 artifact：

- 可以展示多表角色是如何被判定的
- 可以展示缺失字段为何是 missing / derivable / ambiguous
- 可以展示空间文件到底抽取了哪些元数据

这对论文中的 case study 截图和 failure analysis 都更有价值。

## 7. Tests

### 跑了哪些测试

执行了：

- `pytest -q tests/test_file_analyzer_targeted_enhancements.py tests/test_file_analysis_fallback.py tests/test_trace.py`
- `pytest -q tests/test_router_state_loop.py tests/test_file_grounding_enhanced.py tests/test_config.py`
- `pytest -q tests/test_file_analyzer_targeted_enhancements.py tests/test_file_analysis_fallback.py tests/test_file_grounding_enhanced.py tests/test_router_state_loop.py tests/test_trace.py tests/test_config.py`
- `python -m py_compile tools/file_analyzer.py core/file_analysis_fallback.py core/router.py core/trace.py`

### 结果如何

- 聚合 pytest 结果：`85 passed, 4 warnings`
- `py_compile` 通过

warnings 是已有 FastAPI `on_event` deprecation warning，不是本轮引入。

### 新增覆盖了哪些关键行为

- `tests/test_file_analyzer_targeted_enhancements.py`
  - multi-table ZIP role recognition
  - structured missing-field diagnostics
  - shapefile spatial metadata extraction
- `tests/test_file_analysis_fallback.py`
  - ambiguous multi-dataset 才触发 role fallback
  - 非 ambiguous multi-dataset 跳过 role fallback
- `tests/test_router_state_loop.py`
  - file analysis enhancement trace emission
- `tests/test_trace.py`
  - enhancement trace formatter 可读性

## 8. Known Limitations

- still rule-first
- role fallback only applies to ambiguous multi-dataset cases
- no general GIS semantic agent
- no automatic field repair
- no planner/executor behavior change was introduced

补充说明：

- 本轮没有引入新的 workflow execution capability
- 也没有引入 persistence / scheduler / auto-completion
- ZIP role assignment 仍然是 bounded heuristic，不是 general semantic package understanding

如果论文叙事需要“完整 GIS 语义理解”，当前实现仍然不够；但对当前论文主线来说，这种 bounded、rule-first、traceable grounding 更合适，也更可控。

## 9. Suggested Next Step

最推荐的下一步是：补一套 **file grounding evaluation harness**，把 rule-only 与 role/diagnostic/spatial-enhanced grounding 放到同一批真实/半真实文件样例上做对比评测。

原因是：

- 当前 file analyzer 的增强已经形成正式 schema 和 trace surface
- 下一步最自然的论文工作不是再加新机制，而是量化：
  - 多表角色识别是否减少 primary-table 误选
  - missing-field diagnostics 是否改善后续澄清路径
  - spatial metadata 是否提升空间类 grounding 稳定性

这比继续扩 planner/executor 语义更符合当前代码现实和论文主线。
