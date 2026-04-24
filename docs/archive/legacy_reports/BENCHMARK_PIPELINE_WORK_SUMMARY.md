# Benchmark 自动生成 Pipeline 升级工作总结

本文记录本次 Benchmark 自动生成 Pipeline 升级的执行过程、关键观察、已完成工作、验证结果和剩余风险。它是对 `BENCHMARK_PIPELINE_DIAGNOSTIC.md` 的工程执行总结。

## 1. 关键观察

### 当前数据集规模与覆盖问题

当前 `evaluation/benchmarks/end2end_tasks.jsonl` 保持 64 条任务，修复后没有删除任何任务。修复后的类别分布为：

- `simple`: 11
- `parameter_ambiguous`: 14
- `multi_step`: 12
- `incomplete`: 14
- `constraint_violation`: 13

覆盖率审计结果显示，当前 benchmark 仍有明显缺口：

- 车型覆盖 `6/13`，缺失 7 个 MOVES source type。
- 污染物覆盖 `5/6`，缺失 `THC`。
- 气象预设覆盖 `4/6`，缺失 `urban_winter_day` 和 `windy_neutral`。
- 纯英文任务为 `0`，无法支撑英文或双语能力 claim。
- 带 geometry 的测试文件只实际覆盖到 `test_data/test_6links.xlsx`，空间链路覆盖偏弱。

### 现有生成 pipeline 的主要问题

现有 `evaluation/generate_e2e_tasks.py` 已经具备基础 LLM 生成和验证能力，但它是按类别盲生成，而不是先审计覆盖缺口再定向生成。因此它容易继续生成已经过度覆盖的任务，例如乘用车、公交、CO2、NOx、摩托车高速约束，而不会主动补齐缺失车型、`THC`、英文任务或缺失气象预设。

### 现有 benchmark 的判定争议

本次发现并修复了几类判定问题：

- `e2e_incomplete_009` 和 `e2e_incomplete_016` 原本标为 `incomplete`，但实际用 `macro_direct.csv + CO2` 可以依靠默认 `model_year=2020`、`season=夏季`、默认 `fleet_mix` 成功执行，因此改为 `simple`。
- `e2e_incomplete_008` 和 `e2e_incomplete_015` 包含“家用车”，但当前标准化器不能稳定标准化这个别名，因此改为需要协商的 `parameter_ambiguous`。
- `e2e_constraint_013` 中“高架”会被当前标准化器映射为 `快速路`，不是 `高速公路`，所以不应作为摩托车高速约束样本，已改为 `parameter_ambiguous`。
- 多条 `constraint_violation` 缺少显式 `expected_params` 和约束元数据，已补齐 `benchmark_metadata.violated_constraints`、`expected_constraint_action` 和冗余模式标记。

## 2. 已完成工作

### 诊断报告

新增：

- `BENCHMARK_PIPELINE_DIAGNOSTIC.md`

该报告记录了修复前基线诊断，包括类别分布、参数覆盖率、语言覆盖、测试文件覆盖、重复模式、现有 pipeline 现状、P0/P1/P2 覆盖缺口，以及判定标准争议清单。

### Pipeline V2 实现

新增和完善 `evaluation/pipeline_v2/`：

- `common.py`: 共享 YAML 解析、catalog 构建、JSONL 读写、参数抽取、ID 分配、约束匹配、去重等基础能力。
- `coverage_audit.py`: Stage 1 覆盖率审计，输出 `gap_report.json`。
- `targeted_generator.py`: Stage 2 定向生成，基于 `gap_report.json` 的 generation targets 调用 qwen3-max。
- `auto_validator.py`: Stage 3 多层自动验证，包括结构验证、参数验证、约束验证、去重验证和 LLM 自检。
- `review_cli.py`: Stage 4 人工审阅 CLI，支持 approve/reject/edit/skip。
- `merge_to_benchmark.py`: 将 valid 或人工批准候选合并入 benchmark，并按 `e2e_{category_prefix}_{NNN}` 分配最终 ID。
- `regression_check.py`: Stage 5 回归验证，调用现有 `eval_end2end.py` 检查新增任务期望是否合理。
- `curate_existing_benchmark.py`: 对已有 benchmark 做确定性修正，且已验证幂等。
- `run_pipeline.sh`: 一键串联 Stage 1 到 Stage 6。

### 当前覆盖报告

生成：

- `evaluation/pipeline_v2/gap_report.json`

当前报告显示剩余关键缺口：

- 车辆：`Passenger Truck`, `Light Commercial Truck`, `Intercity Bus`, `Refuse Truck`, `Single Unit Short-haul Truck`, `Motor Home`, `Combination Short-haul Truck`
- 污染物：`THC`
- 气象：`urban_winter_day`, `windy_neutral`
- 工具链：`calculate_micro_emission -> render_spatial_map`, `calculate_micro_emission -> calculate_dispersion -> render_spatial_map`
- 约束规则：`vehicle_pollutant_relevance:Motorcycle:PM10`, `pollutant_task_applicability:THC:calculate_dispersion`, `season_meteorology_consistency:夏季:urban_winter_day`

## 3. Benchmark 修正详情

本次没有删除任何现有 benchmark 任务，只做判定标准修正和元数据补强。

### 从 incomplete 重分类

- `e2e_incomplete_009`: 改为 `simple`，执行 `calculate_macro_emission`。
- `e2e_incomplete_016`: 改为 `simple`，执行 `calculate_macro_emission`。
- `e2e_incomplete_008`: 改为 `parameter_ambiguous`，因为“家用车”不是当前可靠别名。
- `e2e_incomplete_015`: 改为 `parameter_ambiguous`，同上。

### 从 constraint_violation 重分类

- `e2e_constraint_013`: 改为 `parameter_ambiguous`，因为“高架”当前标准化为 `快速路`，不触发摩托车高速约束。

### 约束元数据补强

对 constraint 任务补充了：

- `benchmark_metadata.curation`
- `benchmark_metadata.expected_constraint_action`
- `benchmark_metadata.violated_constraints`
- `benchmark_metadata.representative_pattern`
- `benchmark_metadata.redundant_pattern`
- `benchmark_metadata.secondary_coverage`

摩托车高速模式超过 5 条后，只保留 3 条代表样本，其余任务不删除，而是标记为 `redundant_pattern=motorcycle_highway`。

## 4. 验证结果

已完成以下验证：

- `python3 -m compileall evaluation/pipeline_v2` 通过。
- `git diff --check` 通过。
- `coverage_audit.py` 能生成当前 `gap_report.json`。
- `curate_existing_benchmark.py` 写回后再次运行，结果为 `changed=0`，证明幂等。
- `auto_validator.py --skip-llm-review` 用临时候选任务 smoke test，输出 `valid=1`。
- `review_cli.py` 对 valid 候选 passthrough smoke test 通过。
- `merge_to_benchmark.py` 写到 `/tmp` 的 smoke test 通过，正确分配 `e2e_simple_019`，未修改主 benchmark。
- `regression_check.py` 空输入 no-op smoke test 通过。
- 对重分类后的 `e2e_incomplete_009` 和 `e2e_incomplete_016` 运行 `eval_end2end.py --mode tool`，结果为：
  - `completion_rate`: 1.0
  - `tool_accuracy`: 1.0
  - `parameter_legal_rate`: 1.0
  - `result_data_rate`: 1.0

验证过程中，宏观文件列映射的 LLM fallback 因网络不可用失败，但工具自动回退到本地语义匹配并成功执行。

## 5. 剩余风险和后续建议

### 尚未运行真实 LLM 生成

本次没有实际运行 `targeted_generator.py` 的 qwen3-max 批量生成，也没有运行 `auto_validator.py` 的真实 LLM self-review。原因是当前环境网络/API 调用不可用或不稳定。相关代码已实现，LLM 不可用时 validator 会保守标记为 `needs_review`，不会静默放行。

### 尚未做全量 router 回归

只对重分类后的宏观 simple 样本做了 tool-mode 局部验证。建议后续在 API/LLM 可用时运行：

```bash
python evaluation/eval_end2end.py \
  --samples evaluation/benchmarks/end2end_tasks.jsonl \
  --output-dir evaluation/results/end2end_pipeline_v2_full \
  --mode router
```

### 下一步建议

建议下一轮优先用 Pipeline V2 补齐 P0 缺口：

- 每个缺失车型至少 1 条 simple + 1 条 parameter_ambiguous。
- `THC` 至少覆盖 query 和 dispersion warning。
- 增加至少 5 条纯英文任务。
- 增加 `urban_winter_day`、`windy_neutral` 覆盖。
- 增加 micro -> render 相关工具链任务。
- 增加 geometry 文件任务，优先使用 `test_data/test_20links.xlsx`、`test_data/test_shanghai_allroads.xlsx` 或 `test_data/test_shanghai_full.xlsx`。

## 6. 当前交付物索引

- 诊断报告：`BENCHMARK_PIPELINE_DIAGNOSTIC.md`
- 工作总结：`BENCHMARK_PIPELINE_WORK_SUMMARY.md`
- 当前覆盖报告：`evaluation/pipeline_v2/gap_report.json`
- Pipeline V2 目录：`evaluation/pipeline_v2/`
- 修正后的 benchmark：`evaluation/benchmarks/end2end_tasks.jsonl`
