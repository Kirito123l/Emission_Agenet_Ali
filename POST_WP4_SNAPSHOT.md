# POST WP4 Snapshot

Snapshot scope: current code and data state after WP1-4 plus the subsequent end-to-end evaluation fixes. This document only describes the current repository state; it does not include change proposals.

Repository root: `~/Agent1/emission_agent/`

---

## 1. Benchmark 数据现状

### 1.1 标准化 benchmark

Source: `evaluation/benchmarks/standardization_benchmark.jsonl` whole file (`825` JSONL lines; statistics computed over the full file, so there is no narrower per-metric line span). The file itself is at `evaluation/benchmarks/standardization_benchmark.jsonl`.

Current totals:

| Metric | Value |
| --- | ---: |
| 总条目数 | 825 |
| easy | 220 |
| medium | 184 |
| hard | 421 |

按 `dimension` 分布:

| dimension | count |
| --- | ---: |
| `vehicle_type` | 231 |
| `pollutant` | 94 |
| `season` | 70 |
| `road_type` | 110 |
| `meteorology` | 168 |
| `stability_class` | 152 |

按 `difficulty` 分布:

| difficulty | count |
| --- | ---: |
| `easy` | 220 |
| `medium` | 184 |
| `hard` | 421 |

`hard` case 中自动生成 vs 手工写入:

| heuristic | count |
| --- | ---: |
| `id` 含 `gen` 或 `generated` | 0 |
| 其他 `hard` 条目 | 421 |

说明:

- 这里的“自动生成”只能按 `id` 字符串启发式判断，因为 benchmark 正式 schema 没有单独的 provenance 字段；该启发式来自 `id` 是否包含 `gen`/`generated`。Source: `evaluation/benchmarks/standardization_benchmark.jsonl` whole file.
- 以该启发式看，当前正式 benchmark 中的 `hard` 样本仍全部表现为“非 generated id”；现有自动生成候选仍在 `evaluation/generated/`，未从 `id` 上体现合并痕迹。Source: `evaluation/benchmarks/standardization_benchmark.jsonl` whole file; `evaluation/generated/hard_cases_summary.json` lines 1-120.

### 1.2 端到端 benchmark

Source: `evaluation/benchmarks/end2end_tasks.jsonl` lines 1-25.

总条目数与类别分布:

| category | count | source lines |
| --- | ---: | --- |
| `simple` | 5 | `evaluation/benchmarks/end2end_tasks.jsonl` lines 1-5 |
| `parameter_ambiguous` | 5 | `evaluation/benchmarks/end2end_tasks.jsonl` lines 6-10 |
| `multi_step` | 5 | `evaluation/benchmarks/end2end_tasks.jsonl` lines 11-15 |
| `incomplete` | 5 | `evaluation/benchmarks/end2end_tasks.jsonl` lines 16-20 |
| `constraint_violation` | 5 | `evaluation/benchmarks/end2end_tasks.jsonl` lines 21-25 |

每条 `multi_step` 任务详情:

| line | id | user_message 前 50 字 | expected_tool | expected_tool_chain | has_file | test_file |
| ---: | --- | --- | --- | --- | --- | --- |
| 11 | `e2e_multistep_001` | `请先计算这个路网文件的CO2排放，再做扩散分析` | `null` | `["calculate_macro_emission","calculate_dispersion"]` | `true` | `evaluation/file_tasks/data/macro_direct.csv` |
| 12 | `e2e_multistep_002` | `先算这份路网文件的NOx排放，再做扩散，然后找热点` | `null` | `["calculate_macro_emission","calculate_dispersion","analyze_hotspots"]` | `true` | `evaluation/file_tasks/data/macro_direct.csv` |
| 13 | `e2e_multistep_003` | `计算这个中文路网文件的CO2排放并在地图上展示` | `null` | `["calculate_macro_emission","render_spatial_map"]` | `true` | `evaluation/file_tasks/data/macro_cn_fleet.csv` |
| 14 | `e2e_multistep_004` | `先算这个非标准列名路网文件的CO2排放，再做扩散图` | `null` | `["calculate_macro_emission","calculate_dispersion"]` | `true` | `evaluation/file_tasks/data/macro_fuzzy.csv` |
| 15 | `e2e_multistep_005` | `帮我计算这份路网的NOx排放，做扩散，并渲染空间结果` | `null` | `["calculate_macro_emission","calculate_dispersion","render_spatial_map"]` | `true` | `test_data/test_6links.xlsx` |

每条 `constraint_violation` 任务详情:

| line | id | user_message 前 50 字 |
| ---: | --- | --- |
| 21 | `e2e_constraint_001` | `查询2020年摩托车在高速公路上的CO2排放因子` |
| 22 | `e2e_constraint_002` | `请用这个路网文件计算摩托车在高速公路上的CO2排放` |
| 23 | `e2e_constraint_003` | `查询2020年motorcycle在motorway上的NOx排放因子` |
| 24 | `e2e_constraint_004` | `请计算这个文件里摩托车在expressway上的CO2排放` |
| 25 | `e2e_constraint_005` | `请计算这个路网文件冬季条件下的NOx排放，再用urban_summer_day做扩散` |

Raw source excerpt for lines 11-25:

Source: `evaluation/benchmarks/end2end_tasks.jsonl` lines 11-25.

```json
{"id":"e2e_multistep_001","category":"multi_step","description":"Macro emission followed by dispersion","user_message":"请先计算这个路网文件的CO2排放，再做扩散分析","has_file":true,"test_file":"evaluation/file_tasks/data/macro_direct.csv","expected_tool_chain":["calculate_macro_emission","calculate_dispersion"],"expected_params":{"pollutants":["CO2"]},"success_criteria":{"tool_executed":true,"params_legal":true,"result_has_data":true}}
{"id":"e2e_multistep_002","category":"multi_step","description":"Macro emission followed by dispersion and hotspot analysis","user_message":"先算这份路网文件的NOx排放，再做扩散，然后找热点","has_file":true,"test_file":"evaluation/file_tasks/data/macro_direct.csv","expected_tool_chain":["calculate_macro_emission","calculate_dispersion","analyze_hotspots"],"expected_params":{"pollutants":["NOx"]},"success_criteria":{"tool_executed":true,"params_legal":true,"result_has_data":true}}
{"id":"e2e_multistep_003","category":"multi_step","description":"Macro emission followed by map rendering","user_message":"计算这个中文路网文件的CO2排放并在地图上展示","has_file":true,"test_file":"evaluation/file_tasks/data/macro_cn_fleet.csv","expected_tool_chain":["calculate_macro_emission","render_spatial_map"],"expected_params":{"pollutants":["CO2"]},"success_criteria":{"tool_executed":true,"params_legal":true,"result_has_data":true}}
{"id":"e2e_multistep_004","category":"multi_step","description":"Macro emission followed by dispersion on a fuzzy-column file","user_message":"先算这个非标准列名路网文件的CO2排放，再做扩散图","has_file":true,"test_file":"evaluation/file_tasks/data/macro_fuzzy.csv","expected_tool_chain":["calculate_macro_emission","calculate_dispersion"],"expected_params":{"pollutants":["CO2"]},"success_criteria":{"tool_executed":true,"params_legal":true,"result_has_data":true}}
{"id":"e2e_multistep_005","category":"multi_step","description":"Macro emission, dispersion, and rendering on a six-link example","user_message":"帮我计算这份路网的NOx排放，做扩散，并渲染空间结果","has_file":true,"test_file":"test_data/test_6links.xlsx","expected_tool_chain":["calculate_macro_emission","calculate_dispersion","render_spatial_map"],"expected_params":{"pollutants":["NOx"]},"success_criteria":{"tool_executed":true,"params_legal":true,"result_has_data":true}}
{"id":"e2e_constraint_001","category":"constraint_violation","description":"Motorcycle plus expressway should be blocked before execution","user_message":"查询2020年摩托车在高速公路上的CO2排放因子","has_file":false,"test_file":null,"expected_tool_chain":[],"expected_params":{},"success_criteria":{"tool_executed":false,"constraint_blocked":true,"result_has_data":false}}
{"id":"e2e_constraint_002","category":"constraint_violation","description":"Macro-emission request should surface the same blocked combination","user_message":"请用这个路网文件计算摩托车在高速公路上的CO2排放","has_file":true,"test_file":"evaluation/file_tasks/data/macro_direct.csv","expected_tool_chain":[],"expected_params":{},"success_criteria":{"tool_executed":false,"constraint_blocked":true,"result_has_data":false}}
{"id":"e2e_constraint_003","category":"constraint_violation","description":"English motorway alias should still trigger the blocked combination","user_message":"查询2020年motorcycle在motorway上的NOx排放因子","has_file":false,"test_file":null,"expected_tool_chain":[],"expected_params":{},"success_criteria":{"tool_executed":false,"constraint_blocked":true,"result_has_data":false}}
{"id":"e2e_constraint_004","category":"constraint_violation","description":"Expressway alias in a macro-file request should still be blocked","user_message":"请计算这个文件里摩托车在expressway上的CO2排放","has_file":true,"test_file":"evaluation/file_tasks/data/macro_fuzzy.csv","expected_tool_chain":[],"expected_params":{},"success_criteria":{"tool_executed":false,"constraint_blocked":true,"result_has_data":false}}
{"id":"e2e_constraint_005","category":"constraint_violation","description":"Cross-constraint warning should remain visible for inconsistent season and meteorology","user_message":"请计算这个路网文件冬季条件下的NOx排放，再用urban_summer_day做扩散","has_file":true,"test_file":"evaluation/file_tasks/data/macro_direct.csv","expected_tool_chain":["calculate_macro_emission","calculate_dispersion"],"expected_params":{"pollutants":["NOx"],"season":"冬季"},"success_criteria":{"tool_executed":true,"params_legal":true,"constraint_warning":true,"result_has_data":true}}
```

### 1.3 生成的候选数据

Directory: `evaluation/generated/`

当前文件列表与大小:

说明: 这里的大小来自文件系统元数据，不对应文件内部行号。

```text
.gitignore                              112 bytes
e2e_tasks_constraint_violation.jsonl  11872 bytes
e2e_tasks_incomplete.jsonl            18667 bytes
e2e_tasks_multi_step.jsonl            10175 bytes
e2e_tasks_parameter_ambiguous.jsonl    8819 bytes
e2e_tasks_simple.jsonl                 8201 bytes
e2e_tasks_summary.json                 1848 bytes
hard_cases_meteorology.jsonl          10008 bytes
hard_cases_pollutant.jsonl            11157 bytes
hard_cases_road_type.jsonl            11045 bytes
hard_cases_season.jsonl                7393 bytes
hard_cases_stability_class.jsonl       7669 bytes
hard_cases_summary.json                2727 bytes
hard_cases_vehicle_type.jsonl         12791 bytes
```

未发现额外的通用 `summary.json`；当前仅有 `hard_cases_summary.json` 和 `e2e_tasks_summary.json`。Source: directory metadata of `evaluation/generated/`.

`hard_cases_summary.json` 完整内容:

Source: `evaluation/generated/hard_cases_summary.json` lines 1-120.

```json
{
  "generated_at": "2026-04-03T22:03:07+08:00",
  "model": "qwen3-max",
  "dimensions": {
    "vehicle_type": {
      "requested_count": 30,
      "total_generated": 30,
      "status_counts": {
        "confirmed_correct": 18,
        "confirmed_abstain": 0,
        "needs_review": 12,
        "invalid": 0
      },
      "confirmed_correct": 18,
      "confirmed_abstain": 0,
      "needs_review": 12,
      "invalid": 0,
      "last_run": {
        "new_usable": 30,
        "new_invalid": 0
      }
    },
    "pollutant": {
      "requested_count": 30,
      "total_generated": 30,
      "status_counts": {
        "confirmed_correct": 16,
        "confirmed_abstain": 2,
        "needs_review": 12,
        "invalid": 0
      },
      "confirmed_correct": 16,
      "confirmed_abstain": 2,
      "needs_review": 12,
      "invalid": 0,
      "last_run": {
        "new_usable": 30,
        "new_invalid": 0
      }
    },
    "season": {
      "requested_count": 20,
      "total_generated": 20,
      "status_counts": {
        "confirmed_correct": 12,
        "confirmed_abstain": 0,
        "needs_review": 8,
        "invalid": 0
      },
      "confirmed_correct": 12,
      "confirmed_abstain": 0,
      "needs_review": 8,
      "invalid": 0,
      "last_run": {
        "new_usable": 20,
        "new_invalid": 0
      }
    },
    "road_type": {
      "requested_count": 25,
      "total_generated": 25,
      "status_counts": {
        "confirmed_correct": 8,
        "confirmed_abstain": 0,
        "needs_review": 17,
        "invalid": 0
      },
      "confirmed_correct": 8,
      "confirmed_abstain": 0,
      "needs_review": 17,
      "invalid": 0,
      "last_run": {
        "new_usable": 25,
        "new_invalid": 0
      }
    },
    "meteorology": {
      "requested_count": 25,
      "total_generated": 25,
      "status_counts": {
        "confirmed_correct": 17,
        "confirmed_abstain": 0,
        "needs_review": 8,
        "invalid": 0
      },
      "confirmed_correct": 17,
      "confirmed_abstain": 0,
      "needs_review": 8,
      "invalid": 0,
      "last_run": {
        "new_usable": 25,
        "new_invalid": 0
      }
    },
    "stability_class": {
      "requested_count": 20,
      "total_generated": 20,
      "status_counts": {
        "confirmed_correct": 9,
        "confirmed_abstain": 0,
        "needs_review": 11,
        "invalid": 0
      },
      "confirmed_correct": 9,
      "confirmed_abstain": 0,
      "needs_review": 11,
      "invalid": 0,
      "last_run": {
        "new_usable": 20,
        "new_invalid": 0
      }
    }
  },
  "status_totals": {
    "confirmed_correct": 80,
    "confirmed_abstain": 2,
    "needs_review": 68,
    "invalid": 0
  }
}
```

`e2e_tasks_summary.json` 完整内容:

Source: `evaluation/generated/e2e_tasks_summary.json` lines 1-91.

```json
{
  "generated_at": "2026-04-04T10:49:42+08:00",
  "model": "qwen3-max",
  "categories": {
    "simple": {
      "requested_count": 10,
      "total_generated": 10,
      "status_counts": {
        "valid": 7,
        "needs_review": 3,
        "invalid": 3
      },
      "valid": 7,
      "needs_review": 3,
      "invalid": 3,
      "last_run": {
        "new_usable": 10,
        "new_invalid": 3
      }
    },
    "parameter_ambiguous": {
      "requested_count": 10,
      "total_generated": 10,
      "status_counts": {
        "valid": 7,
        "needs_review": 3,
        "invalid": 15
      },
      "valid": 7,
      "needs_review": 3,
      "invalid": 15,
      "last_run": {
        "new_usable": 10,
        "new_invalid": 15
      }
    },
    "multi_step": {
      "requested_count": 10,
      "total_generated": 10,
      "status_counts": {
        "valid": 8,
        "needs_review": 2,
        "invalid": 11
      },
      "valid": 8,
      "needs_review": 2,
      "invalid": 11,
      "last_run": {
        "new_usable": 10,
        "new_invalid": 11
      }
    },
    "incomplete": {
      "requested_count": 10,
      "total_generated": 20,
      "status_counts": {
        "valid": 13,
        "needs_review": 7,
        "invalid": 3
      },
      "valid": 13,
      "needs_review": 7,
      "invalid": 3,
      "last_run": {
        "new_usable": 10,
        "new_invalid": 0
      }
    },
    "constraint_violation": {
      "requested_count": 10,
      "total_generated": 10,
      "status_counts": {
        "valid": 9,
        "needs_review": 1,
        "invalid": 3
      },
      "valid": 9,
      "needs_review": 1,
      "invalid": 3,
      "last_run": {
        "new_usable": 10,
        "new_invalid": 3
      }
    }
  },
  "status_totals": {
    "valid": 44,
    "needs_review": 16,
    "invalid": 35
  }
}
```

---

## 2. 评估脚本现状

### 2.1 `eval_standardization_benchmark.py`

File length: `228` lines. Source: `evaluation/eval_standardization_benchmark.py` lines 1-228.

`evaluate_single()` 完整代码:

Source: `evaluation/eval_standardization_benchmark.py` lines 106-146.

```python
def evaluate_single(engine: StandardizationEngine, case: Dict[str, Any]) -> EvalRecord:
    dimension = str(case["dimension"])
    param_type = DIMENSION_TO_PARAM_TYPE.get(dimension)
    if param_type is None:
        return EvalRecord(
            case_id=str(case["id"]),
            dimension=dimension,
            difficulty=str(case.get("difficulty", "unknown")),
            raw_input=str(case.get("raw_input", "")),
            expected=case.get("expected_output"),
            actual=None,
            strategy="unsupported",
            confidence=0.0,
            correct=False,
            abstained=True,
        )

    result: StandardizationResult = engine.standardize(param_type, case.get("raw_input"))
    actual = result.normalized
    strategy = result.strategy
    confidence = float(result.confidence or 0.0)
    abstained = (not result.success) or strategy in {"abstain", "none"}
    expected = case.get("expected_output")

    if expected is None:
        correct = abstained or actual is None
    else:
        correct = actual == expected

    return EvalRecord(
        case_id=str(case["id"]),
        dimension=dimension,
        difficulty=str(case.get("difficulty", "unknown")),
        raw_input=str(case.get("raw_input", "")),
        expected=expected,
        actual=actual,
        strategy=strategy,
        confidence=confidence,
        correct=correct,
        abstained=abstained,
    )
```

`run_evaluation()` 完整代码:

Source: `evaluation/eval_standardization_benchmark.py` lines 203-213.

```python
def run_evaluation(benchmark_path: Path, output_dir: Path, mode: str = "auto") -> Dict[str, Any]:
    apply_mode_overrides(mode)
    resolved_mode = detect_mode() if mode == "auto" else mode
    engine = build_engine()
    records = [evaluate_single(engine, case) for case in load_benchmark(benchmark_path)]
    metrics = compute_metrics(records, resolved_mode)

    output_dir.mkdir(parents=True, exist_ok=True)
    write_jsonl(output_dir / "standardization_eval_logs.jsonl", [asdict(record) for record in records])
    write_json(output_dir / "standardization_eval_metrics.json", metrics)
    return metrics
```

`main()` 完整代码:

Source: `evaluation/eval_standardization_benchmark.py` lines 216-228.

```python
def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate parameter standardization on the benchmark.")
    parser.add_argument("--benchmark", type=Path, default=BENCHMARK_PATH)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--mode", choices=["auto", "rule_only", "rule_fuzzy", "full"], default="auto")
    args = parser.parse_args()

    metrics = run_evaluation(args.benchmark, args.output_dir, mode=args.mode)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

它如何判断 `correct`:

- 若 `expected_output is None`，则 `abstained` 为真或 `actual is None` 即算 `correct`。Source: `evaluation/eval_standardization_benchmark.py` lines 130-131.
- 若 `expected_output` 非空，则仅当 `actual == expected` 时算 `correct`。Source: `evaluation/eval_standardization_benchmark.py` lines 132-133.

### 2.2 `eval_standardization_ablation.py`

File length: `88` lines. Source: `evaluation/eval_standardization_ablation.py` lines 1-88.

三种模式的切换机制:

- 不是 config 对象内的临时开关，也不是代码内部直接改 benchmark；它通过 `subprocess.run()` 调起 `evaluation/eval_standardization_benchmark.py`，并在每个 mode 前覆盖进程环境变量。Source: `evaluation/eval_standardization_ablation.py` lines 18-48.
- `rule_only` 设置 `STANDARDIZATION_FUZZY_ENABLED=false` 和 `ENABLE_LLM_STANDARDIZATION=false`。Source: `evaluation/eval_standardization_ablation.py` lines 22-25.
- `rule_fuzzy` 设置 `STANDARDIZATION_FUZZY_ENABLED=true` 和 `ENABLE_LLM_STANDARDIZATION=false`。Source: `evaluation/eval_standardization_ablation.py` lines 26-28.
- `full` 设置 `STANDARDIZATION_FUZZY_ENABLED=true` 和 `ENABLE_LLM_STANDARDIZATION=true`。Source: `evaluation/eval_standardization_ablation.py` lines 29-31.

相关代码:

Source: `evaluation/eval_standardization_ablation.py` lines 18-48.

```python
def run_mode(mode: str) -> Path:
    output_dir = OUTPUT_BASE / mode
    output_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    if mode == "rule_only":
        env["STANDARDIZATION_FUZZY_ENABLED"] = "false"
        env["ENABLE_LLM_STANDARDIZATION"] = "false"
    elif mode == "rule_fuzzy":
        env["STANDARDIZATION_FUZZY_ENABLED"] = "true"
        env["ENABLE_LLM_STANDARDIZATION"] = "false"
    elif mode == "full":
        env["STANDARDIZATION_FUZZY_ENABLED"] = "true"
        env["ENABLE_LLM_STANDARDIZATION"] = "true"

    result = subprocess.run(
        [sys.executable, str(EVAL_SCRIPT), "--output-dir", str(output_dir), "--mode", mode],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    print(f"=== Mode: {mode} ===")
    print(result.stdout)
    if result.returncode != 0:
        if result.stderr:
            print(result.stderr)
        raise RuntimeError(f"Benchmark ablation mode failed: {mode}")

    return output_dir / "standardization_eval_metrics.json"
```

### 2.3 `eval_end2end.py`（重点）

File length: `572` lines. Source: `evaluation/eval_end2end.py` lines 1-572.

等效的“单任务评估函数”是 `_build_task_result()`。

`_normalize_match_text()` 完整代码:

Source: `evaluation/eval_end2end.py` lines 146-153.

```python
def _normalize_match_text(text: str) -> str:
    return (
        text.lower()
        .replace("₂", "2")
        .replace("₅", "5")
        .replace("ₓ", "x")
        .replace("pm2.₅", "pm2.5")
    )
```

geometry-gated success 判定逻辑完整代码:

Source: `evaluation/eval_end2end.py` lines 156-201.

```python
def _is_geometry_gated_multistep_success(
    task: Dict[str, Any],
    *,
    actual_tool_chain: List[str],
    response_payload: Dict[str, Any],
    file_analysis: Optional[Dict[str, Any]],
    trace_has_error: bool,
) -> bool:
    if task.get("category") != "multi_step":
        return False

    expected_tool_chain = [str(item) for item in task.get("expected_tool_chain", []) if item]
    expected_prefix = _geometry_gate_prefix(expected_tool_chain)
    if not expected_prefix:
        return False
    if actual_tool_chain and actual_tool_chain != expected_prefix:
        return False

    if _file_has_explicit_geometry(file_analysis):
        return False

    missing_field_diagnostics = (file_analysis or {}).get("missing_field_diagnostics")
    if isinstance(missing_field_diagnostics, dict):
        if str(missing_field_diagnostics.get("status") or "").strip().lower() != "complete":
            return False

    if trace_has_error:
        return False

    response_text = str(response_payload.get("text") or "")
    lowered_text = _normalize_match_text(response_text)
    if not any(cue in lowered_text for cue in GEOMETRY_TEXT_CUES):
        return False
    if not any(cue in response_text for cue in FOLLOW_UP_TEXT_CUES):
        return False
    if not any(cue in response_text for cue in EMISSION_COMPLETION_TEXT_CUES):
        return False
    if any(cue in response_text for cue in COMPLETED_DOWNSTREAM_TEXT_CUES):
        return False

    expected_pollutants = task.get("expected_params", {}).get("pollutants", [])
    if expected_pollutants:
        if not any(_normalize_match_text(str(pollutant)) in lowered_text for pollutant in expected_pollutants):
            return False

    return True
```

`_build_task_result()` 完整代码:

Source: `evaluation/eval_end2end.py` lines 245-358.

```python
def _build_task_result(
    task: Dict[str, Any],
    *,
    executed_tool_calls: List[Dict[str, Any]],
    response_payload: Dict[str, Any],
    trace_payload: Optional[Dict[str, Any]],
    error_message: Optional[str],
    duration_ms: float,
    file_analysis: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    trace_steps = _extract_trace_steps(trace_payload)
    trace_step_types = [str(step.get("step_type", "")).lower() for step in trace_steps]
    standardization_records = _collect_standardization_records(trace_steps)
    actual_tool_chain = [str(call.get("name")) for call in executed_tool_calls if call.get("name")]
    actual_arguments = executed_tool_calls[0].get("arguments", {}) if executed_tool_calls else {}
    params_comparison = compare_expected_subset(actual_arguments, task.get("expected_params", {}))

    tool_executed = bool(executed_tool_calls)
    params_legal = params_comparison["matched"] if task.get("expected_params") else tool_executed
    result_has_data = _has_result_payload(response_payload, executed_tool_calls)
    final_stage = str((trace_payload or {}).get("final_stage") or "")
    requires_user_response = (
        final_stage in LEGACY_NEEDS_USER_STAGE
        or any(step_type in {"clarification", "input_completion_required", "parameter_negotiation_required"} for step_type in trace_step_types)
    )
    constraint_blocked = (
        "参数组合不合法" in str(response_payload.get("text", ""))
        or any(
            record.get("record_type") == "cross_constraint_violation"
            for record in standardization_records
        )
    )
    constraint_warning = any(
        record.get("record_type") == "cross_constraint_warning"
        for record in standardization_records
    )
    trace_has_error = any(step.get("error") for step in trace_steps) or any(
        step_type == "error" for step_type in trace_step_types
    )

    criteria_actuals = {
        "tool_executed": tool_executed,
        "params_legal": params_legal,
        "result_has_data": result_has_data,
        "requires_user_response": requires_user_response,
        "constraint_blocked": constraint_blocked,
        "constraint_warning": constraint_warning,
        "trace_has_error": trace_has_error,
    }
    geometry_gated_success = _is_geometry_gated_multistep_success(
        task,
        actual_tool_chain=actual_tool_chain,
        response_payload=response_payload,
        file_analysis=file_analysis,
        trace_has_error=trace_has_error,
    )
    tool_match = (
        _tool_chain_matches(actual_tool_chain, task.get("expected_tool_chain", []))
        or geometry_gated_success
    )

    if task["__legacy_expected_success"] is not None:
        output_check = _check_outputs(response_payload, task.get("expected_outputs", {}))
        success = (
            (tool_executed == task["__legacy_expected_success"])
            and output_check["matched"]
            and tool_match
        )
    else:
        output_check = None
        success = geometry_gated_success or tool_match
        if not geometry_gated_success:
            for key, expected_value in (task.get("success_criteria") or {}).items():
                if key not in criteria_actuals:
                    continue
                success = success and (criteria_actuals[key] == expected_value)

    record = {
        "task_id": task["id"],
        "category": task["category"],
        "description": task["description"],
        "input": {
            "user_message": task["user_message"],
            "test_file": task.get("test_file"),
        },
        "file_analysis": file_analysis,
        "expected": {
            "tool_chain": task.get("expected_tool_chain", []),
            "params": task.get("expected_params", {}),
            "success_criteria": task.get("success_criteria", {}),
            "legacy_expected_success": task["__legacy_expected_success"],
            "legacy_expected_outputs": task.get("expected_outputs", {}),
        },
        "actual": {
            "tool_chain": actual_tool_chain,
            "tool_chain_match": tool_match,
            "geometry_gated_success": geometry_gated_success,
            "tool_calls": executed_tool_calls,
            "params_comparison": params_comparison,
            "criteria": criteria_actuals,
            "response_payload": response_payload,
            "trace_step_types": trace_step_types,
            "standardization_records": standardization_records,
            "final_stage": final_stage or None,
        },
        "success": success,
        "timing_ms": duration_ms,
        "error": error_message,
        "output_check": output_check,
    }
    failure_type = classify_failure(record)
    record["failure_type"] = failure_type
    record["recoverability"] = classify_recoverability(failure_type)
    return record
```

`compute_metrics()` 等效函数为 `_aggregate_metrics()`，完整代码如下:

Source: `evaluation/eval_end2end.py` lines 361-407.

```python
def _aggregate_metrics(logs: List[Dict[str, Any]], mode: str, skipped: int) -> Dict[str, Any]:
    categories = sorted({str(log.get("category", "uncategorized")) for log in logs})
    success_count = sum(1 for log in logs if log.get("success"))
    tool_match_count = sum(
        1
        for log in logs
        if log.get("actual", {}).get("tool_chain_match")
        or not log.get("expected", {}).get("tool_chain")
    )
    params_legal_count = sum(
        1 for log in logs if log.get("actual", {}).get("criteria", {}).get("params_legal")
    )
    result_data_count = sum(
        1 for log in logs if log.get("actual", {}).get("criteria", {}).get("result_has_data")
    )

    by_category: Dict[str, Dict[str, Any]] = {}
    for category in categories:
        bucket = [log for log in logs if log.get("category") == category]
        by_category[category] = {
            "tasks": len(bucket),
            "success_rate": round(safe_div(sum(1 for log in bucket if log.get("success")), len(bucket)), 4),
            "tool_accuracy": round(
                safe_div(
                    sum(
                        1
                        for log in bucket
                        if log.get("actual", {}).get("tool_chain_match")
                        or not log.get("expected", {}).get("tool_chain")
                    ),
                    len(bucket),
                ),
                4,
            ),
        }

    return {
        "task": "end2end",
        "mode": mode,
        "tasks": len(logs),
        "completion_rate": round(safe_div(success_count, len(logs)), 4),
        "tool_accuracy": round(safe_div(tool_match_count, len(logs)), 4),
        "parameter_legal_rate": round(safe_div(params_legal_count, len(logs)), 4),
        "result_data_rate": round(safe_div(result_data_count, len(logs)), 4),
        "skipped_tasks": skipped,
        "by_category": by_category,
    }
```

它如何区分 strict success 和 `geometry_gated_success`:

- `geometry_gated_success` 先单独计算。Source: `evaluation/eval_end2end.py` lines 294-300.
- `tool_match` 被定义成 “严格 tool chain 匹配” 或 `geometry_gated_success` 二者之一。Source: `evaluation/eval_end2end.py` lines 301-304.
- 对非 legacy benchmark，`success` 初始值是 `geometry_gated_success or tool_match`；只有在 `geometry_gated_success == false` 时，才继续逐项按 `success_criteria` 严格比对。Source: `evaluation/eval_end2end.py` lines 314-320.
- 最终日志里同时落两个字段: `actual.tool_chain_match` 和 `actual.geometry_gated_success`。Source: `evaluation/eval_end2end.py` lines 338-345.

### 2.4 `eval_ablation.py`

File length: `103` lines. Source: `evaluation/eval_ablation.py` lines 1-103.

它控制的开关:

- `baseline`: 无环境覆盖。Source: `evaluation/eval_ablation.py` lines 21-25.
- `no_standardization`: `ENABLE_EXECUTOR_STANDARDIZATION=false`。Source: `evaluation/eval_ablation.py` lines 23-25.
- `no_cross_constraint`: `ENABLE_CROSS_CONSTRAINT_VALIDATION=false`。Source: `evaluation/eval_ablation.py` lines 26-28.
- `no_negotiation`: `ENABLE_PARAMETER_NEGOTIATION=false`。Source: `evaluation/eval_ablation.py` lines 29-31.
- `no_readiness`: `ENABLE_READINESS_GATING=false`。Source: `evaluation/eval_ablation.py` lines 32-34.

它跑几轮:

- `ABLATION_CONFIGS` 里有 `5` 个配置，所以 `run_ablation()` 一次完整执行会跑 `5` 轮 `evaluation/eval_end2end.py`。Source: `evaluation/eval_ablation.py` lines 21-35 and 47-84.

它的输出格式:

- 每个 run 目录写自己的 `end2end_metrics.json`。
- 总结文件写成 `ablation_summary.json`，顶层结构是 `{"task":"end2end_ablation","mode":...,"runs":{...}}`，每个 run 下包含 `env_overrides` 和 `metrics`。Source: `evaluation/eval_ablation.py` lines 45-87.

相关代码:

Source: `evaluation/eval_ablation.py` lines 21-88.

```python
ABLATION_CONFIGS: Dict[str, Dict[str, str]] = {
    "baseline": {},
    "no_standardization": {
        "ENABLE_EXECUTOR_STANDARDIZATION": "false",
    },
    "no_cross_constraint": {
        "ENABLE_CROSS_CONSTRAINT_VALIDATION": "false",
    },
    "no_negotiation": {
        "ENABLE_PARAMETER_NEGOTIATION": "false",
    },
    "no_readiness": {
        "ENABLE_READINESS_GATING": "false",
    },
}


def run_ablation(
    output_dir: Path,
    *,
    samples_path: Path = DEFAULT_SAMPLES,
    mode: str = "router",
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {"task": "end2end_ablation", "mode": mode, "runs": {}}

    for name, overrides in ABLATION_CONFIGS.items():
        run_dir = output_dir / name
        run_dir.mkdir(parents=True, exist_ok=True)

        env = os.environ.copy()
        env.update(overrides)

        result = subprocess.run(
            [
                sys.executable,
                str(END2END_SCRIPT),
                "--samples",
                str(samples_path),
                "--output-dir",
                str(run_dir),
                "--mode",
                mode,
            ],
            env=env,
            capture_output=True,
            text=True,
            check=False,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Ablation run '{name}' failed with exit code {result.returncode}: {result.stderr}"
            )

        metrics_path = run_dir / "end2end_metrics.json"
        with metrics_path.open("r", encoding="utf-8") as fh:
            metrics = json.load(fh)

        summary["runs"][name] = {
            "env_overrides": overrides,
            "metrics": metrics,
        }

    comparison_path = output_dir / "ablation_summary.json"
    with comparison_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, ensure_ascii=False, indent=2)
    return summary
```

---

## 3. 最近的实验结果

### 3.1 标准化评估结果

`evaluation/results/standardization/standardization_eval_metrics.json` 完整内容:

Source: `evaluation/results/standardization/standardization_eval_metrics.json` lines 1-206.

```json
{
  "mode": "full",
  "overall": {
    "total": 825,
    "correct": 798,
    "accuracy": 0.9673,
    "coverage": 0.9939,
    "avg_confidence": 0.9225
  },
  "by_dimension": {
    "meteorology": {
      "total": 168,
      "correct": 166,
      "accuracy": 0.9881,
      "coverage": 1.0,
      "avg_confidence": 0.9327
    },
    "pollutant": {
      "total": 94,
      "correct": 88,
      "accuracy": 0.9362,
      "coverage": 0.9468,
      "avg_confidence": 0.8681
    },
    "road_type": {
      "total": 110,
      "correct": 107,
      "accuracy": 0.9727,
      "coverage": 1.0,
      "avg_confidence": 0.9245
    },
    "season": {
      "total": 70,
      "correct": 64,
      "accuracy": 0.9143,
      "coverage": 1.0,
      "avg_confidence": 0.8997
    },
    "stability_class": {
      "total": 152,
      "correct": 147,
      "accuracy": 0.9671,
      "coverage": 1.0,
      "avg_confidence": 0.9216
    },
    "vehicle_type": {
      "total": 231,
      "correct": 226,
      "accuracy": 0.9784,
      "coverage": 1.0,
      "avg_confidence": 0.9439
    }
  },
  "by_difficulty": {
    "easy": {
      "total": 220,
      "correct": 220,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9591
    },
    "hard": {
      "total": 421,
      "correct": 394,
      "accuracy": 0.9359,
      "coverage": 0.9881,
      "avg_confidence": 0.8974
    },
    "medium": {
      "total": 184,
      "correct": 184,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9363
    }
  },
  "by_dimension_difficulty": {
    "meteorology:easy": {
      "total": 40,
      "correct": 40,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9575
    },
    "meteorology:hard": {
      "total": 89,
      "correct": 87,
      "accuracy": 0.9775,
      "coverage": 1.0,
      "avg_confidence": 0.9228
    },
    "meteorology:medium": {
      "total": 39,
      "correct": 39,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9297
    },
    "pollutant:easy": {
      "total": 24,
      "correct": 24,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9625
    },
    "pollutant:hard": {
      "total": 52,
      "correct": 46,
      "accuracy": 0.8846,
      "coverage": 0.9038,
      "avg_confidence": 0.796
    },
    "pollutant:medium": {
      "total": 18,
      "correct": 18,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9506
    },
    "road_type:easy": {
      "total": 27,
      "correct": 27,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9593
    },
    "road_type:hard": {
      "total": 62,
      "correct": 59,
      "accuracy": 0.9516,
      "coverage": 1.0,
      "avg_confidence": 0.9034
    },
    "road_type:medium": {
      "total": 21,
      "correct": 21,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9424
    },
    "season:easy": {
      "total": 17,
      "correct": 17,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9618
    },
    "season:hard": {
      "total": 53,
      "correct": 47,
      "accuracy": 0.8868,
      "coverage": 1.0,
      "avg_confidence": 0.8798
    },
    "stability_class:easy": {
      "total": 38,
      "correct": 38,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9579
    },
    "stability_class:hard": {
      "total": 70,
      "correct": 65,
      "accuracy": 0.9286,
      "coverage": 1.0,
      "avg_confidence": 0.9031
    },
    "stability_class:medium": {
      "total": 44,
      "correct": 44,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9195
    },
    "vehicle_type:easy": {
      "total": 74,
      "correct": 74,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9588
    },
    "vehicle_type:hard": {
      "total": 95,
      "correct": 90,
      "accuracy": 0.9474,
      "coverage": 1.0,
      "avg_confidence": 0.9309
    },
    "vehicle_type:medium": {
      "total": 62,
      "correct": 62,
      "accuracy": 1.0,
      "coverage": 1.0,
      "avg_confidence": 0.9461
    }
  },
  "strategy_distribution": {
    "abstain": 5,
    "alias": 182,
    "default": 6,
    "exact": 40,
    "fuzzy": 497,
    "llm": 95
  }
}
```

`evaluation/results/standardization_ablation/comparison.json` 完整内容:

Source: `evaluation/results/standardization_ablation/comparison.json` lines 1-617.

```json
{
  "rule_only": {
    "mode": "rule_only",
    "overall": {
      "total": 825,
      "correct": 260,
      "accuracy": 0.3152,
      "coverage": 0.4339,
      "avg_confidence": 0.3405
    },
    "by_dimension": {
      "meteorology": {
        "total": 168,
        "correct": 42,
        "accuracy": 0.25,
        "coverage": 0.2381,
        "avg_confidence": 0.228
      },
      "pollutant": {
        "total": 94,
        "correct": 31,
        "accuracy": 0.3298,
        "coverage": 0.2766,
        "avg_confidence": 0.266
      },
      "road_type": {
        "total": 110,
        "correct": 41,
        "accuracy": 0.3727,
        "coverage": 1.0,
        "avg_confidence": 0.6127
      },
      "season": {
        "total": 70,
        "correct": 29,
        "accuracy": 0.4143,
        "coverage": 1.0,
        "avg_confidence": 0.6121
      },
      "stability_class": {
        "total": 152,
        "correct": 40,
        "accuracy": 0.2632,
        "coverage": 0.25,
        "avg_confidence": 0.2395
      },
      "vehicle_type": {
        "total": 231,
        "correct": 77,
        "accuracy": 0.3333,
        "coverage": 0.3203,
        "avg_confidence": 0.3071
      }
    },
    "by_difficulty": {
      "easy": {
        "total": 220,
        "correct": 220,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9591
      },
      "hard": {
        "total": 421,
        "correct": 37,
        "accuracy": 0.0879,
        "coverage": 0.2779,
        "avg_confidence": 0.1411
      },
      "medium": {
        "total": 184,
        "correct": 3,
        "accuracy": 0.0163,
        "coverage": 0.1141,
        "avg_confidence": 0.0571
      }
    },
    "by_dimension_difficulty": {
      "meteorology:easy": {
        "total": 40,
        "correct": 40,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9575
      },
      "meteorology:hard": {
        "total": 89,
        "correct": 2,
        "accuracy": 0.0225,
        "coverage": 0.0,
        "avg_confidence": 0.0
      },
      "meteorology:medium": {
        "total": 39,
        "correct": 0,
        "accuracy": 0.0,
        "coverage": 0.0,
        "avg_confidence": 0.0
      },
      "pollutant:easy": {
        "total": 24,
        "correct": 24,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9625
      },
      "pollutant:hard": {
        "total": 52,
        "correct": 7,
        "accuracy": 0.1346,
        "coverage": 0.0385,
        "avg_confidence": 0.0365
      },
      "pollutant:medium": {
        "total": 18,
        "correct": 0,
        "accuracy": 0.0,
        "coverage": 0.0,
        "avg_confidence": 0.0
      },
      "road_type:easy": {
        "total": 27,
        "correct": 27,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9593
      },
      "road_type:hard": {
        "total": 62,
        "correct": 11,
        "accuracy": 0.1774,
        "coverage": 1.0,
        "avg_confidence": 0.5
      },
      "road_type:medium": {
        "total": 21,
        "correct": 3,
        "accuracy": 0.1429,
        "coverage": 1.0,
        "avg_confidence": 0.5
      },
      "season:easy": {
        "total": 17,
        "correct": 17,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9618
      },
      "season:hard": {
        "total": 53,
        "correct": 12,
        "accuracy": 0.2264,
        "coverage": 1.0,
        "avg_confidence": 0.5
      },
      "stability_class:easy": {
        "total": 38,
        "correct": 38,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9579
      },
      "stability_class:hard": {
        "total": 70,
        "correct": 2,
        "accuracy": 0.0286,
        "coverage": 0.0,
        "avg_confidence": 0.0
      },
      "stability_class:medium": {
        "total": 44,
        "correct": 0,
        "accuracy": 0.0,
        "coverage": 0.0,
        "avg_confidence": 0.0
      },
      "vehicle_type:easy": {
        "total": 74,
        "correct": 74,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9588
      },
      "vehicle_type:hard": {
        "total": 95,
        "correct": 3,
        "accuracy": 0.0316,
        "coverage": 0.0,
        "avg_confidence": 0.0
      },
      "vehicle_type:medium": {
        "total": 62,
        "correct": 0,
        "accuracy": 0.0,
        "coverage": 0.0,
        "avg_confidence": 0.0
      }
    },
    "strategy_distribution": {
      "abstain": 467,
      "alias": 182,
      "default": 136,
      "exact": 40
    }
  },
  "rule_fuzzy": {
    "mode": "rule_fuzzy",
    "overall": {
      "total": 825,
      "correct": 735,
      "accuracy": 0.8909,
      "coverage": 0.9273,
      "avg_confidence": 0.8383
    },
    "by_dimension": {
      "meteorology": {
        "total": 168,
        "correct": 153,
        "accuracy": 0.9107,
        "coverage": 0.8988,
        "avg_confidence": 0.8371
      },
      "pollutant": {
        "total": 94,
        "correct": 84,
        "accuracy": 0.8936,
        "coverage": 0.8617,
        "avg_confidence": 0.7883
      },
      "road_type": {
        "total": 110,
        "correct": 102,
        "accuracy": 0.9273,
        "coverage": 1.0,
        "avg_confidence": 0.8886
      },
      "season": {
        "total": 70,
        "correct": 43,
        "accuracy": 0.6143,
        "coverage": 1.0,
        "avg_confidence": 0.704
      },
      "stability_class": {
        "total": 152,
        "correct": 142,
        "accuracy": 0.9342,
        "coverage": 0.9539,
        "avg_confidence": 0.8782
      },
      "vehicle_type": {
        "total": 231,
        "correct": 211,
        "accuracy": 0.9134,
        "coverage": 0.9004,
        "avg_confidence": 0.85
      }
    },
    "by_difficulty": {
      "easy": {
        "total": 220,
        "correct": 220,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9591
      },
      "hard": {
        "total": 421,
        "correct": 331,
        "accuracy": 0.7862,
        "coverage": 0.8575,
        "avg_confidence": 0.7324
      },
      "medium": {
        "total": 184,
        "correct": 184,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9363
      }
    },
    "by_dimension_difficulty": {
      "meteorology:easy": {
        "total": 40,
        "correct": 40,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9575
      },
      "meteorology:hard": {
        "total": 89,
        "correct": 74,
        "accuracy": 0.8315,
        "coverage": 0.809,
        "avg_confidence": 0.7425
      },
      "meteorology:medium": {
        "total": 39,
        "correct": 39,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9297
      },
      "pollutant:easy": {
        "total": 24,
        "correct": 24,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9625
      },
      "pollutant:hard": {
        "total": 52,
        "correct": 42,
        "accuracy": 0.8077,
        "coverage": 0.75,
        "avg_confidence": 0.6517
      },
      "pollutant:medium": {
        "total": 18,
        "correct": 18,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9506
      },
      "road_type:easy": {
        "total": 27,
        "correct": 27,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9593
      },
      "road_type:hard": {
        "total": 62,
        "correct": 54,
        "accuracy": 0.871,
        "coverage": 1.0,
        "avg_confidence": 0.8397
      },
      "road_type:medium": {
        "total": 21,
        "correct": 21,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9424
      },
      "season:easy": {
        "total": 17,
        "correct": 17,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9618
      },
      "season:hard": {
        "total": 53,
        "correct": 26,
        "accuracy": 0.4906,
        "coverage": 1.0,
        "avg_confidence": 0.6213
      },
      "stability_class:easy": {
        "total": 38,
        "correct": 38,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9579
      },
      "stability_class:hard": {
        "total": 70,
        "correct": 60,
        "accuracy": 0.8571,
        "coverage": 0.9,
        "avg_confidence": 0.8089
      },
      "stability_class:medium": {
        "total": 44,
        "correct": 44,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9195
      },
      "vehicle_type:easy": {
        "total": 74,
        "correct": 74,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9588
      },
      "vehicle_type:hard": {
        "total": 95,
        "correct": 75,
        "accuracy": 0.7895,
        "coverage": 0.7579,
        "avg_confidence": 0.7025
      },
      "vehicle_type:medium": {
        "total": 62,
        "correct": 62,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9461
      }
    },
    "strategy_distribution": {
      "abstain": 60,
      "alias": 182,
      "default": 46,
      "exact": 40,
      "fuzzy": 497
    }
  },
  "full": {
    "mode": "full",
    "overall": {
      "total": 825,
      "correct": 798,
      "accuracy": 0.9673,
      "coverage": 0.9939,
      "avg_confidence": 0.9232
    },
    "by_dimension": {
      "meteorology": {
        "total": 168,
        "correct": 165,
        "accuracy": 0.9821,
        "coverage": 1.0,
        "avg_confidence": 0.9324
      },
      "pollutant": {
        "total": 94,
        "correct": 89,
        "accuracy": 0.9468,
        "coverage": 0.9468,
        "avg_confidence": 0.8681
      },
      "road_type": {
        "total": 110,
        "correct": 107,
        "accuracy": 0.9727,
        "coverage": 1.0,
        "avg_confidence": 0.9282
      },
      "season": {
        "total": 70,
        "correct": 64,
        "accuracy": 0.9143,
        "coverage": 1.0,
        "avg_confidence": 0.9011
      },
      "stability_class": {
        "total": 152,
        "correct": 147,
        "accuracy": 0.9671,
        "coverage": 1.0,
        "avg_confidence": 0.9216
      },
      "vehicle_type": {
        "total": 231,
        "correct": 226,
        "accuracy": 0.9784,
        "coverage": 1.0,
        "avg_confidence": 0.9444
      }
    },
    "by_difficulty": {
      "easy": {
        "total": 220,
        "correct": 220,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9591
      },
      "hard": {
        "total": 421,
        "correct": 394,
        "accuracy": 0.9359,
        "coverage": 0.9881,
        "avg_confidence": 0.8987
      },
      "medium": {
        "total": 184,
        "correct": 184,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9363
      }
    },
    "by_dimension_difficulty": {
      "meteorology:easy": {
        "total": 40,
        "correct": 40,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9575
      },
      "meteorology:hard": {
        "total": 89,
        "correct": 86,
        "accuracy": 0.9663,
        "coverage": 1.0,
        "avg_confidence": 0.9222
      },
      "meteorology:medium": {
        "total": 39,
        "correct": 39,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9297
      },
      "pollutant:easy": {
        "total": 24,
        "correct": 24,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9625
      },
      "pollutant:hard": {
        "total": 52,
        "correct": 47,
        "accuracy": 0.9038,
        "coverage": 0.9038,
        "avg_confidence": 0.796
      },
      "pollutant:medium": {
        "total": 18,
        "correct": 18,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9506
      },
      "road_type:easy": {
        "total": 27,
        "correct": 27,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9593
      },
      "road_type:hard": {
        "total": 62,
        "correct": 59,
        "accuracy": 0.9516,
        "coverage": 1.0,
        "avg_confidence": 0.9098
      },
      "road_type:medium": {
        "total": 21,
        "correct": 21,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9424
      },
      "season:easy": {
        "total": 17,
        "correct": 17,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9618
      },
      "season:hard": {
        "total": 53,
        "correct": 47,
        "accuracy": 0.8868,
        "coverage": 1.0,
        "avg_confidence": 0.8817
      },
      "stability_class:easy": {
        "total": 38,
        "correct": 38,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9579
      },
      "stability_class:hard": {
        "total": 70,
        "correct": 65,
        "accuracy": 0.9286,
        "coverage": 1.0,
        "avg_confidence": 0.9031
      },
      "stability_class:medium": {
        "total": 44,
        "correct": 44,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9195
      },
      "vehicle_type:easy": {
        "total": 74,
        "correct": 74,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9588
      },
      "vehicle_type:hard": {
        "total": 95,
        "correct": 90,
        "accuracy": 0.9474,
        "coverage": 1.0,
        "avg_confidence": 0.932
      },
      "vehicle_type:medium": {
        "total": 62,
        "correct": 62,
        "accuracy": 1.0,
        "coverage": 1.0,
        "avg_confidence": 0.9461
      }
    },
    "strategy_distribution": {
      "abstain": 5,
      "alias": 182,
      "default": 5,
      "exact": 40,
      "fuzzy": 497,
      "llm": 96
    }
  }
}
```

### 3.2 端到端评估结果

最新两次运行目录:

1. `evaluation/results/end2end/end2end_20260404_124523`
2. `evaluation/results/end2end/end2end_20260404_124026`

`end2end_20260404_124026/end2end_metrics.json` 完整内容:

Source: `evaluation/results/end2end/end2end_20260404_124026/end2end_metrics.json` lines 1-38.

```json
{
  "task": "end2end",
  "mode": "router",
  "tasks": 25,
  "completion_rate": 0.2,
  "tool_accuracy": 0.64,
  "parameter_legal_rate": 0.16,
  "result_data_rate": 0.36,
  "skipped_tasks": 0,
  "by_category": {
    "constraint_violation": {
      "tasks": 5,
      "success_rate": 0.6,
      "tool_accuracy": 0.8
    },
    "incomplete": {
      "tasks": 5,
      "success_rate": 0.0,
      "tool_accuracy": 1.0
    },
    "multi_step": {
      "tasks": 5,
      "success_rate": 0.0,
      "tool_accuracy": 0.0
    },
    "parameter_ambiguous": {
      "tasks": 5,
      "success_rate": 0.0,
      "tool_accuracy": 0.4
    },
    "simple": {
      "tasks": 5,
      "success_rate": 0.4,
      "tool_accuracy": 1.0
    }
  },
  "logs_path": "/home/kirito/Agent1/emission_agent/evaluation/results/end2end/end2end_20260404_124026/end2end_logs.jsonl"
}
```

`end2end_20260404_124026/end2end_logs.jsonl` 中所有 `multi_step` 和 `constraint_violation` 条目提取:

Source: `evaluation/results/end2end/end2end_20260404_124026/end2end_logs.jsonl` lines 11-25.

```json
{"line":11,"task_id":"e2e_multistep_001","category":"multi_step","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"✅ 已完成宏观CO₂排放计算（基于 `macro_direct.csv`）：   - **总CO₂排放：318.90 kg/h（≈7.65 吨/天）**   - 路段明细：A1（0.82 km, 960 vph, 38 km/h）、A2（1.15 km, 1240 vph, 46 km/h）、A3（长度/flow/speed 未在 sample 显示，但已参与计算）   - 使用默认参数：车型年份"}
{"line":12,"task_id":"e2e_multistep_002","category":"multi_step","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"已确认文件 `macro_direct.csv` 为宏观路段数据（3条路段），字段完整：`link_id`, `length` (km), `flow` (veh/h), `speed` (km/h)。   ✅ **NOx排放计算已完成**（上一步）：   - 总排放：**67.40 g/小时（NOx）** ≈ **1.62 kg/天**   - 默认参数：车型年份=2020、季节=夏季、污染物="}
{"line":13,"task_id":"e2e_multistep_003","category":"multi_step","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"输入补全 / Input Completion 当前动作 `run_macro_emission` 还不能直接执行。 原因: 当前还不能安全执行macro_emission计算，因为关键输入字段尚未齐备：交通流量(traffic_flow_vph)。 目标字段: `traffic_flow_vph` 任务类型: `macro_emission` 文件上下文: task_type=macro_emi"}
{"line":14,"task_id":"e2e_multistep_004","category":"multi_step","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"输入补全 / Input Completion 当前动作 `run_macro_emission` 还不能直接执行。 原因: 当前还不能安全执行macro_emission计算，因为关键输入字段尚未齐备：平均速度(avg_speed_kph)。 目标字段: `avg_speed_kph` 任务类型: `macro_emission` 文件上下文: task_type=macro_emission,"}
{"line":15,"task_id":"e2e_multistep_005","category":"multi_step","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"✅ 已确认文件 `test_6links.xlsx` 为宏观路段数据（6条路段，含 WKT geometry），且此前已完成 NOx 排放计算（2020年车型、夏季、默认车队组成）。  现在为您执行完整流程：  ---  ### ✅ **1. NOx 排放结果（已计算）**   - **总排放量：74.00 g/h（≈1.78 kg/天）**   - **单路段平均：0.01 kg/h；最高：0."}
{"line":21,"task_id":"e2e_constraint_001","category":"constraint_violation","success":true,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"参数组合不合法: 摩托车不允许上高速公路"}
{"line":22,"task_id":"e2e_constraint_002","category":"constraint_violation","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"已确认文件：`macro_direct.csv`（3个路段，列：`link_id`, `length`, `flow`, `speed`），且您明确指定：  - 车辆类型：**摩托车**（已锁定）   - 道路类型：**高速公路**（已锁定）   - 污染物：**CO₂**   - 车型年份：2020（默认）   - 季节：夏季（默认）  ⚠️ **关键限制说明**：   根据《中华人民共和国道路"}
{"line":23,"task_id":"e2e_constraint_003","category":"constraint_violation","success":true,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"参数组合不合法: 摩托车不允许上高速公路"}
{"line":24,"task_id":"e2e_constraint_004","category":"constraint_violation","success":true,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"参数组合不合法: 摩托车不允许上高速公路"}
{"line":25,"task_id":"e2e_constraint_005","category":"constraint_violation","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"已确认文件 `macro_direct.csv` 为宏观路段数据（3个路段），含 `link_id`, `length`, `flow`, `speed`，无几何字段（如 `geometry`, `wkt`, `x1/y1/x2/y2`），因此**无法直接做空间扩散或地图可视化**——但可先完成排放计算，并为后续扩散分析做好准备。  ---  ### ✅ 第一步：冬季 NOx 排放计算（已完成） "}
```

`end2end_20260404_124523/end2end_metrics.json` 完整内容:

Source: `evaluation/results/end2end/end2end_20260404_124523/end2end_metrics.json` lines 1-38.

```json
{
  "task": "end2end",
  "mode": "router",
  "tasks": 25,
  "completion_rate": 0.24,
  "tool_accuracy": 0.68,
  "parameter_legal_rate": 0.16,
  "result_data_rate": 0.36,
  "skipped_tasks": 0,
  "by_category": {
    "constraint_violation": {
      "tasks": 5,
      "success_rate": 0.6,
      "tool_accuracy": 0.8
    },
    "incomplete": {
      "tasks": 5,
      "success_rate": 0.0,
      "tool_accuracy": 1.0
    },
    "multi_step": {
      "tasks": 5,
      "success_rate": 0.2,
      "tool_accuracy": 0.2
    },
    "parameter_ambiguous": {
      "tasks": 5,
      "success_rate": 0.0,
      "tool_accuracy": 0.4
    },
    "simple": {
      "tasks": 5,
      "success_rate": 0.4,
      "tool_accuracy": 1.0
    }
  },
  "logs_path": "/home/kirito/Agent1/emission_agent/evaluation/results/end2end/end2end_20260404_124523/end2end_logs.jsonl"
}
```

`end2end_20260404_124523/end2end_logs.jsonl` 中所有 `multi_step` 和 `constraint_violation` 条目提取:

Source: `evaluation/results/end2end/end2end_20260404_124523/end2end_logs.jsonl` lines 11-25.

```json
{"line":11,"task_id":"e2e_multistep_001","category":"multi_step","success":true,"geometry_gated_success":true,"actual_tools":[],"response_text_prefix_200":"✅ 已确认文件 `macro_direct.csv` 为宏观路段数据（3条路段），含必要字段：`link_id`, `length` (km), `flow` (vph), `speed` (km/h)。   上一轮已成功完成 **CO₂排放计算**：   - **总排放量：318.90 kg/h CO₂**（≈7.65 吨/天）   - 使用默认参数：车型年份=2020、季节=夏季、污染物=CO"}
{"line":12,"task_id":"e2e_multistep_002","category":"multi_step","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"已确认文件 `macro_direct.csv` 为宏观路段数据（3条路段），字段完整：`link_id`, `length` (km), `flow` (veh/h), `speed` (km/h)。   ✅ **NOx排放计算已完成**（上一步）：   - 总排放：**67.40 g/小时（NOx）** ≈ **1.62 kg/天**   - 默认参数：车型年份=2020、季节=夏季、污染物="}
{"line":13,"task_id":"e2e_multistep_003","category":"multi_step","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"输入补全 / Input Completion 当前动作 `run_macro_emission` 还不能直接执行。 原因: 当前还不能安全执行macro_emission计算，因为关键输入字段尚未齐备：交通流量(traffic_flow_vph)。 目标字段: `traffic_flow_vph` 任务类型: `macro_emission` 文件上下文: task_type=macro_emi"}
{"line":14,"task_id":"e2e_multistep_004","category":"multi_step","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"输入补全 / Input Completion 当前动作 `run_macro_emission` 还不能直接执行。 原因: 当前还不能安全执行macro_emission计算，因为关键输入字段尚未齐备：平均速度(avg_speed_kph)。 目标字段: `avg_speed_kph` 任务类型: `macro_emission` 文件上下文: task_type=macro_emission,"}
{"line":15,"task_id":"e2e_multistep_005","category":"multi_step","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"✅ 已确认文件 `test_6links.xlsx` 为宏观路段数据（6条路段，含 geometry），且此前已完成 NOx 排放计算（2020年车型、夏季、默认车队组成）。  现在为您执行完整流程：  ---  ### ✅ **1. NOx 排放结果（已计算）**   - **总排放量：74.00 g/h（≈1.78 kg/天）**   - **单路段平均：0.01 kg/h；最高：0.04 k"}
{"line":21,"task_id":"e2e_constraint_001","category":"constraint_violation","success":true,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"参数组合不合法: 摩托车不允许上高速公路"}
{"line":22,"task_id":"e2e_constraint_002","category":"constraint_violation","success":true,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"参数组合不合法: 摩托车不允许上高速公路"}
{"line":23,"task_id":"e2e_constraint_003","category":"constraint_violation","success":true,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"参数组合不合法: 摩托车不允许上高速公路"}
{"line":24,"task_id":"e2e_constraint_004","category":"constraint_violation","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"已确认： - 文件：`macro_fuzzy.csv`（宏观路段数据，3条路段） - 车辆类型：Motorcycle（用户多次明确） - 道路类型：expressway（即高速公路） - 目标污染物：CO₂  ⚠️ 但需再次说明：**摩托车在中国禁止驶入高速公路**，排放模型（如MOVES、CMEM）默认不支持 motorcycle + expressway 组合，强行计算将导致结果无物理/法规意"}
{"line":25,"task_id":"e2e_constraint_005","category":"constraint_violation","success":false,"geometry_gated_success":false,"actual_tools":[],"response_text_prefix_200":"已确认文件 `macro_direct.csv` 为宏观路段数据（3个路段），含 `link_id`, `length`, `flow`, `speed`，无几何字段（如 `geometry`, `wkt`, `x1/y1/x2/y2`），因此**无法直接做空间扩散或地图可视化**——但可先完成排放计算，并为后续扩散分析做好准备。  ---  ### ✅ 第一步：冬季 NOx 排放计算（已完成） "}
```

---

## 4. Router 最近的修改

### 4.1 最近的 git 改动

`git log --oneline -15`:

Source: git history at snapshot time.

```text
80a9f2a fix(eval): accept geometry-gated multi-step success in constrained evaluation
2884acc fix: 气象确认改为markdown格式，移除误触发卡片
1d44f60 feat: 对话标题LLM自动总结 + 删除对话内联确认
b80ca30 feat: 去掉重复进度提示 + 气象确认结构化卡片
af63c78 feat: 进度提示/友好错误/导出缓存/热点解释面板
81c572e fix(evaluation): align incomplete and constraint-violation e2e generation with validation
78e5a80 fix: export chart title overlap, colorbar noise, road/hotspot style
fe03778 fix: export timeout + async executor + basemap fast-fail + deploy font install
b2fe60f feat: contour visualization, map export, session persistence, visual polish
9afb886 feat(evaluation): upgrade qwen3-max data generation pipeline
a172531 feat: contour visualization + boundary mask + server-side map export (round 1-3)
bb9a1f8 feat: contour visualization for dispersion results (round 1+2)
3daa75c fix: include dispersion model coefficient files for deployment
df7debe feat: parameter governance normalization, declarative tool contracts, and experiment infrastructure
9ffe326 WP1: parameter governance normalization + cross-constraint validation
```

`git diff --stat HEAD~5 -- core/router.py`:

Source: git diff stat at snapshot time.

```text
 core/router.py | 583 ++++++++++++++++++++++++++++++++++++++++++++++++++++++++-
 1 file changed, 579 insertions(+), 4 deletions(-)
```

### 4.2 `router.py` 中与端到端修复相关的代码段

#### 4.2.1 incomplete 状态错配相关代码

位置 1: 显式参数锁定和直接用户响应状态设置。Source: `core/router.py` lines 749-804.

```python
def _seed_explicit_message_parameter_locks(self, state: TaskState) -> None:
    hints = self._extract_message_execution_hints(state)
    lockable_fields = {
        "vehicle_type": ("vehicle_type", "vehicle_type_raw"),
        "road_type": ("road_type", "road_type_raw"),
        "season": ("season", "season_raw"),
        "meteorology": ("meteorology", "meteorology_raw"),
        "stability_class": ("stability_class", "stability_class_raw"),
    }
    for param_name, (normalized_key, raw_key) in lockable_fields.items():
        normalized_value = hints.get(normalized_key)
        if not normalized_value:
            continue
        state.apply_parameter_lock(
            parameter_name=param_name,
            normalized_value=str(normalized_value),
            raw_value=str(hints.get(raw_key) or normalized_value),
            lock_source="explicit_user_message",
        )

def _set_direct_user_response_state(
    self,
    state: TaskState,
    text: str,
    *,
    stage: TaskStage,
    stage_before: TaskStage,
    reason: str,
    trace_obj: Optional[Trace] = None,
    trace_step_type: Optional[TraceStepType] = None,
) -> None:
    state.control.needs_user_input = stage in {
        TaskStage.NEEDS_CLARIFICATION,
        TaskStage.NEEDS_INPUT_COMPLETION,
        TaskStage.NEEDS_PARAMETER_CONFIRMATION,
    }
    state.control.clarification_question = text if stage == TaskStage.NEEDS_CLARIFICATION else None
    state.control.input_completion_prompt = text if stage == TaskStage.NEEDS_INPUT_COMPLETION else None
    state.control.parameter_confirmation_prompt = (
        text if stage == TaskStage.NEEDS_PARAMETER_CONFIRMATION else None
    )
    setattr(state, "_final_response_text", text)
    self._transition_state(
        state,
        stage,
        reason=reason,
        trace_obj=trace_obj,
    )
    if trace_obj and trace_step_type is not None:
        trace_obj.record(
            step_type=trace_step_type,
            stage_before=stage_before.value,
            stage_after=stage.value,
            reasoning=text,
        )
```

位置 2: 缺参澄清和 no-tool fallback。Source: `core/router.py` lines 805-953.

```python
def _build_missing_input_clarification(self, state: TaskState) -> Optional[str]:
    hints = self._extract_message_execution_hints(state)
    desired_chain = list(hints.get("desired_tool_chain") or [])
    if not desired_chain:
        return None

    next_tool = desired_chain[0]
    if next_tool == "query_emission_factors":
        if not hints.get("vehicle_type"):
            return "要查询排放因子，我还需要车型。请告诉我是 Passenger Car、Transit Bus、Motorcycle 等哪一类车辆。"
        if not hints.get("pollutants"):
            return "要查询排放因子，我还需要污染物类型。请说明是 CO2、NOx、PM2.5，还是其它污染物。"
        if hints.get("model_year") is None:
            return "要查询排放因子，我还需要车型年份。请告诉我例如 2020、2021 这样的年份。"
        return None

    completed_tools = list(state.execution.completed_tools or [])
    if next_tool == "calculate_dispersion" and "calculate_macro_emission" not in completed_tools:
        if state.file_context.has_file and str(state.file_context.task_type or "").strip() == "macro_emission":
            return None
        return "做扩散分析前，我需要路网排放结果。你可以上传路网文件让我先算排放，或直接说明要基于哪一份排放结果继续。"
    if next_tool == "analyze_hotspots" and "calculate_dispersion" not in completed_tools:
        return "做热点分析前，我需要一份扩散结果。你可以先让我运行扩散分析，或告诉我你要使用的已有浓度场结果。"
    if next_tool == "render_spatial_map" and not completed_tools and not state.file_context.has_file:
        return "画地图前，我需要一份可视化对象。请告诉我要渲染排放结果、扩散结果还是热点结果，或者先上传对应数据文件。"
    return None

def _maybe_recover_missing_tool_call(
    self,
    state: TaskState,
    *,
    stage_before: TaskStage,
    trace_obj: Optional[Trace] = None,
) -> bool:
    clarification = self._build_missing_input_clarification(state)
    if clarification:
        self._set_direct_user_response_state(
            state,
            clarification,
            stage=TaskStage.NEEDS_CLARIFICATION,
            stage_before=stage_before,
            reason="Deterministic clarification applied after a no-tool LLM reply",
            trace_obj=trace_obj,
            trace_step_type=TraceStepType.CLARIFICATION,
        )
        return True

    fallback_response = self._build_deterministic_fallback_tool_call(state)
    if fallback_response is None or not fallback_response.tool_calls:
        return False

    state._llm_response = fallback_response
    state.execution.selected_tool = fallback_response.tool_calls[0].name
    self._capture_tool_call_parameters(state, fallback_response.tool_calls)
    if trace_obj:
        tool_names = [tool_call.name for tool_call in fallback_response.tool_calls]
        trace_obj.record(
            step_type=TraceStepType.TOOL_SELECTION,
            stage_before=stage_before.value,
            stage_after=TaskStage.GROUNDED.value if stage_before == TaskStage.INPUT_RECEIVED else TaskStage.EXECUTING.value,
            action=", ".join(tool_names),
            reasoning=(
                "Deterministic fallback selected tool(s) after the LLM replied without tool calls: "
                + ", ".join(tool_names)
            ),
        )
    if stage_before == TaskStage.INPUT_RECEIVED:
        self._transition_state(
            state,
            TaskStage.GROUNDED,
            reason="Recovered execution path after no-tool LLM reply",
            trace_obj=trace_obj,
        )
    return True
```

位置 3: query factor 缺参 preflight。Source: `core/router.py` lines 2909-2954.

```python
def _evaluate_missing_parameter_preflight(
    self,
    state: TaskState,
    tool_name: str,
    *,
    effective_arguments: Optional[Dict[str, Any]] = None,
    trace_obj: Optional[Trace] = None,
) -> bool:
    hints = self._extract_message_execution_hints(state)
    explicit_arguments = effective_arguments if isinstance(effective_arguments, dict) else {}
    if tool_name != "query_emission_factors" or (not hints.get("wants_factor") and not explicit_arguments):
        return False

    resolved_vehicle_type = explicit_arguments.get("vehicle_type") or hints.get("vehicle_type")
    resolved_model_year = (
        explicit_arguments.get("model_year")
        if explicit_arguments.get("model_year") is not None
        else hints.get("model_year")
    )
    resolved_pollutants = (
        explicit_arguments.get("pollutants")
        or explicit_arguments.get("pollutant")
        or hints.get("pollutants")
    )

    clarification: Optional[str] = None
    if not resolved_vehicle_type:
        clarification = "要查询排放因子，我还需要车型。请告诉我是 Passenger Car、Transit Bus、Motorcycle 等哪一类车辆。"
    elif resolved_model_year is None:
        clarification = "要查询排放因子，我还需要车型年份。请告诉我例如 2020、2021 这样的年份。"
    elif not explicit_arguments and not resolved_pollutants:
        clarification = "要查询排放因子，我还需要污染物类型。请说明是 CO2、NOx、PM2.5，还是其它污染物。"

    if clarification is None:
        return False

    self._set_direct_user_response_state(
        state,
        clarification,
        stage=TaskStage.NEEDS_CLARIFICATION,
        stage_before=TaskStage.EXECUTING,
        reason="Missing required factor-query parameter detected before tool execution",
        trace_obj=trace_obj,
        trace_step_type=TraceStepType.CLARIFICATION,
    )
    return True
```

当前作用说明:

- 这些代码把“追问/补问”直接落到 `TaskStage.NEEDS_CLARIFICATION` 或其他 need-user-input stage，而不是只生成文本后继续走 `DONE`。Source: `core/router.py` lines 769-804 and 2945-2954.

#### 4.2.2 multi_step 契约错配相关代码

位置 1: 输入阶段无 tool call 时的恢复。Source: `core/router.py` lines 9289-9322.

```python
if response.tool_calls:
    state._llm_response = response
    state.execution.selected_tool = response.tool_calls[0].name
    self._capture_tool_call_parameters(state, response.tool_calls)
    if trace_obj:
        tool_names = [tc.name for tc in response.tool_calls]
        trace_obj.record(
            step_type=TraceStepType.TOOL_SELECTION,
            stage_before=TaskStage.INPUT_RECEIVED.value,
            stage_after=TaskStage.GROUNDED.value,
            action=", ".join(tool_names),
            reasoning=f"LLM selected tool(s): {', '.join(tool_names)}",
        )
    self._transition_state(
        state,
        TaskStage.GROUNDED,
        reason="LLM selected tool(s)",
        trace_obj=trace_obj,
    )
else:
    if not str(response.content or "").strip():
        if self._maybe_recover_missing_tool_call(
            state,
            stage_before=TaskStage.INPUT_RECEIVED,
            trace_obj=trace_obj,
        ):
            return
    state.execution.tool_results = [{"text": response.content, "no_tool": True}]
    self._transition_state(
        state,
        TaskStage.DONE,
        reason="LLM responded without tool calls",
        trace_obj=trace_obj,
    )
```

位置 2: `render_spatial_map` 的“already provided”不再一律短路。Source: `core/router.py` lines 9495-9507.

```python
force_explicit_execution = (
    readiness_affordance is not None
    and readiness_affordance.status == ReadinessStatus.ALREADY_PROVIDED
    and self._should_force_explicit_tool_execution(
        state,
        tool_call.name,
    )
)
if (
    readiness_affordance is not None
    and self._should_short_circuit_readiness(readiness_affordance)
    and not force_explicit_execution
):
```

位置 3: 执行轮次中 follow-up 无 tool call 时再次恢复。Source: `core/router.py` lines 9807-9837.

```python
if follow_up_response.tool_calls:
    state.execution.selected_tool = follow_up_response.tool_calls[0].name
    self._capture_tool_call_parameters(state, follow_up_response.tool_calls)
    if trace_obj:
        tool_names = [tc.name for tc in follow_up_response.tool_calls]
        reason = "LLM selected next tool(s) after tool results"
        if has_error:
            reason = "LLM selected tool(s) after tool error feedback"
        trace_obj.record(
            step_type=TraceStepType.TOOL_SELECTION,
            stage_before=TaskStage.EXECUTING.value,
            stage_after=TaskStage.EXECUTING.value,
            action=", ".join(tool_names),
            reasoning=f"{reason}: {', '.join(tool_names)}",
        )
    current_response = follow_up_response
    rounds_used += 1
    continue

if follow_up_response.content:
    setattr(state, "_final_response_text", follow_up_response.content)
elif self._maybe_recover_missing_tool_call(
    state,
    stage_before=TaskStage.EXECUTING,
    trace_obj=trace_obj,
):
    if state.stage == TaskStage.EXECUTING and state._llm_response and state._llm_response.tool_calls:
        current_response = state._llm_response
        rounds_used += 1
        continue
    return
elif has_error and state.execution.last_error and not getattr(state, "_final_response_text", None):
    setattr(state, "_final_response_text", state.execution.last_error)
break
```

当前作用说明:

- 这些代码共同定义了当前 multi-step 执行链路中的“补回工具调用”和“允许显式 render 继续执行”的行为。Source: `core/router.py` lines 907-953, 955-966, 9495-9507, 9807-9837.

#### 4.2.3 constraint_violation 真实绕过相关代码

位置 1: 显式用户参数锁先在输入阶段写入。Source: `core/router.py` line 9082 and lines 749-767.

```python
self._seed_explicit_message_parameter_locks(state)
```

位置 2: cross-constraint preflight。Source: `core/router.py` lines 985-1091.

```python
def _evaluate_cross_constraint_preflight(
    self,
    state: TaskState,
    tool_name: str,
    effective_arguments: Dict[str, Any],
    *,
    trace_obj: Optional[Trace] = None,
) -> bool:
    standardizer = self._get_message_standardizer()
    hints = self._extract_message_execution_hints(state)

    standardized_params: Dict[str, Any] = {}
    if effective_arguments.get("vehicle_type") or hints.get("vehicle_type"):
        vehicle_raw = str(
            effective_arguments.get("vehicle_type")
            or hints.get("vehicle_type_raw")
            or hints.get("vehicle_type")
        )
        vehicle_result = standardizer.standardize_vehicle_detailed(vehicle_raw)
        if vehicle_result.success and vehicle_result.normalized:
            standardized_params["vehicle_type"] = vehicle_result.normalized

    if effective_arguments.get("road_type") or hints.get("road_type"):
        road_raw = str(
            effective_arguments.get("road_type")
            or hints.get("road_type_raw")
            or hints.get("road_type")
        )
        road_result = standardizer.standardize_road_type(road_raw)
        if road_result.success and road_result.normalized:
            standardized_params["road_type"] = road_result.normalized

    if effective_arguments.get("season") or hints.get("season"):
        season_raw = str(
            effective_arguments.get("season")
            or hints.get("season_raw")
            or hints.get("season")
        )
        season_result = standardizer.standardize_season(season_raw)
        if season_result.success and season_result.normalized:
            standardized_params["season"] = season_result.normalized

    if effective_arguments.get("meteorology") or hints.get("meteorology"):
        meteorology_raw = str(
            effective_arguments.get("meteorology")
            or hints.get("meteorology_raw")
            or hints.get("meteorology")
        )
        meteorology_result = standardizer.standardize_meteorology(meteorology_raw)
        if meteorology_result.success and meteorology_result.normalized:
            standardized_params["meteorology"] = meteorology_result.normalized

    if not standardized_params:
        return False

    constraint_result = get_cross_constraint_validator().validate(standardized_params)
    if constraint_result.warnings and trace_obj:
        trace_obj.record(
            step_type=TraceStepType.CROSS_CONSTRAINT_WARNING,
            stage_before=TaskStage.EXECUTING.value,
            action=tool_name,
            input_summary={"standardized_params": dict(standardized_params)},
            standardization_records=[
                self._build_cross_constraint_record(warning, success=True)
                for warning in constraint_result.warnings
            ],
            reasoning="Cross-parameter warning detected during router preflight.",
        )

    if not constraint_result.violations:
        return False

    violation = constraint_result.violations[0]
    suggestions = list(violation.suggestions or [])
    suggestion_text = (
        "\n\nDid you mean one of these? " + ", ".join(suggestions[:5])
        if suggestions
        else ""
    )
    message = f"参数组合不合法: {violation.reason}{suggestion_text}"
    state.execution.blocked_info = {
        "message": message,
        "constraint_name": violation.constraint_name,
        "suggestions": suggestions,
    }
    state.execution.last_error = violation.reason
    setattr(state, "_final_response_text", message)
    self._transition_state(
        state,
        TaskStage.DONE,
        reason=f"Cross constraint blocked execution before {tool_name}",
        trace_obj=trace_obj,
    )
    if trace_obj:
        trace_obj.record(
            step_type=TraceStepType.CROSS_CONSTRAINT_VIOLATION,
            stage_before=TaskStage.EXECUTING.value,
            stage_after=TaskStage.DONE.value,
            action=tool_name,
            input_summary={"standardized_params": dict(standardized_params)},
            standardization_records=[
                self._build_cross_constraint_record(violation, success=False)
            ],
            reasoning=violation.reason,
            error=violation.reason,
        )
    return True
```

位置 3: preflight 调用点在真正执行工具前。Source: `core/router.py` lines 9472-9485.

```python
if self._evaluate_missing_parameter_preflight(
    state,
    tool_call.name,
    effective_arguments=effective_arguments,
    trace_obj=trace_obj,
):
    return
if self._evaluate_cross_constraint_preflight(
    state,
    tool_call.name,
    effective_arguments,
    trace_obj=trace_obj,
):
    return
```

当前作用说明:

- 当前代码在工具执行前就把用户原话锁定的参数标准化并送入 cross-constraint validator；若违规，直接进入 `DONE` 并返回阻断文本。Source: `core/router.py` lines 1040-1091 and 9479-9485.

---

## 5. WP4 Pipeline 现状

### 5.1 生成脚本

`evaluation/llm_generator.py`

- 总行数: `139`。Source: `evaluation/llm_generator.py` lines 1-139.
- 主要接口:
  - `LLMGenerator.__init__()` at line 31
  - `LLMGenerator.resolve_model()` at line 53
  - `LLMGenerator._wait_for_rate_limit()` at line 66
  - `LLMGenerator._extract_json_object()` at line 72
  - `LLMGenerator.generate_json()` at line 81
  - `LLMGenerator.generate_batch()` at line 128

`evaluation/context_extractor.py`

- 总行数: `239`。Source: `evaluation/context_extractor.py` lines 1-239.
- 主要函数:
  - `_dedupe_preserve_order()` at line 26
  - `_load_yaml()` at line 38
  - `load_unified_mappings()` at line 45
  - `load_tool_contracts()` at line 50
  - `extract_standardization_context()` at line 54
  - `extract_all_standardization_contexts()` at line 142
  - `extract_tool_contracts()` at line 146
  - `extract_system_capabilities()` at line 150
  - `load_existing_cases()` at line 203
  - `load_existing_user_messages()` at line 230

`evaluation/generate_hard_cases.py`

- 总行数: `474`。Source: `evaluation/generate_hard_cases.py` lines 1-474.
- 主要函数:
  - `build_engine()` at line 117
  - `parse_args()` at line 124
  - `_build_prompt()` at line 180
  - `_normalize_case()` at line 198
  - `_validate_case()` at line 220
  - `_build_record()` at line 255
  - `_resolve_count()` at line 315
  - `generate_for_dimension()` at line 321
  - `main()` at line 449

`evaluation/generate_e2e_tasks.py`

- 总行数: `944`。Source: `evaluation/generate_e2e_tasks.py` lines 1-944.
- 主要函数:
  - `parse_args()` at line 153
  - `_load_cross_constraints()` at line 261
  - `_constraint_prompt_context()` at line 276
  - `_category_specific_requirements()` at line 293
  - `_build_prompt()` at line 328
  - `_derive_success_criteria()` at line 370
  - `_normalize_incomplete_expected_params()` at line 384
  - `_normalize_constraint_expected_params()` at line 400
  - `_validate_task()` at line 557
  - `_resolve_count()` at line 780
  - `generate_for_category()` at line 795
  - `main()` at line 916

`evaluation/merge_generated_cases.py`

- 总行数: `120`。Source: `evaluation/merge_generated_cases.py` lines 1-120.
- 主要函数:
  - `parse_args()` at line 26
  - `_load_generated_records()` at line 41
  - `_benchmark_record()` at line 50
  - `_count_by_dimension_and_difficulty()` at line 62
  - `main()` at line 72

`evaluation/merge_generated_e2e_tasks.py`

- 总行数: `160`。Source: `evaluation/merge_generated_e2e_tasks.py` lines 1-160.
- 主要函数:
  - `parse_args()` at line 31
  - `_load_generated_records()` at line 46
  - `_next_id_map()` at line 55
  - `_count_by_category()` at line 70
  - `_benchmark_record()` at line 78
  - `main()` at line 107

### 5.2 生成质量

hard case 随机抽样 5 条:

Source records:

- `evaluation/generated/hard_cases_pollutant.jsonl` line 4
- `evaluation/generated/hard_cases_meteorology.jsonl` line 7
- `evaluation/generated/hard_cases_road_type.jsonl` lines 16, 8, 3

```json
{"id":"pollutant_hard_gen_004","dimension":"pollutant","difficulty":"hard","raw_input":"pm二点五","expected_output":"PM2.5","language":"zh","notes":"中文数字表达+英文缩写混用，非标准但可推断","category":"中英混杂","validation":{"status":"confirmed_correct","actual_output":"PM2.5","actual_strategy":"llm","actual_confidence":0.95}}
{"id":"meteorology_hard_gen_007","dimension":"meteorology","difficulty":"hard","raw_input":"冬天 urban night","expected_output":"urban_winter_night","language":"mixed","notes":"混合语言，需正确解析季节和时段","category":"中英混杂","validation":{"status":"confirmed_correct","actual_output":"urban_winter_night","actual_strategy":"llm","actual_confidence":0.95}}
{"id":"road_type_hard_gen_016","dimension":"road_type","difficulty":"hard","raw_input":"local expy","expected_output":null,"language":"mixed","notes":"'local' 指支路，'expy'（expressway 缩写）指快速路，矛盾组合，无法映射","category":"多义歧义","validation":{"status":"needs_review","actual_output":"支路","actual_strategy":"llm","actual_confidence":0.95}}
{"id":"road_type_hard_gen_008","dimension":"road_type","difficulty":"hard","raw_input":"collector arterial","expected_output":null,"language":"en","notes":"术语混合：collector 属次干道，arterial 属主干道，行业术语冲突，无法确定归属","category":"多义歧义","validation":{"status":"needs_review","actual_output":"主干道","actual_strategy":"llm","actual_confidence":0.95}}
{"id":"road_type_hard_gen_003","dimension":"road_type","difficulty":"hard","raw_input":"主干道 expressway","expected_output":null,"language":"mixed","notes":"中英混杂且语义冲突：主干道 vs expressway（应为快速路），存在多义歧义","category":"多义歧义","validation":{"status":"needs_review","actual_output":"快速路","actual_strategy":"fuzzy","actual_confidence":0.83}}
```

e2e 候选随机抽样 5 条:

Source records:

- `evaluation/generated/e2e_tasks_incomplete.jsonl` lines 16, 15, 3, 2
- `evaluation/generated/e2e_tasks_multi_step.jsonl` line 9

```json
{"category":"incomplete","description":"有文件但未指定 pollutants 和 vehicle_type，macro/micro 路径不确定","user_message":"用这个文件算 CO2 排放","has_file":true,"test_file":"evaluation/file_tasks/data/macro_direct.csv","expected_tool_chain":[],"expected_params":{"target_tool":"calculate_macro_emission","known_params":{"pollutants":["CO2"]},"missing_required_params":["vehicle_type"],"negotiable_params":["model_year","season","fleet_mix"]},"success_criteria":{"tool_executed":false,"requires_user_response":true,"result_has_data":false},"validation":{"status":"valid","issues":[],"auto_fixes":["Assigned default test_file: evaluation/file_tasks/data/macro_direct.csv"],"expected_behavior":"系统应确认文件内容（路段 or 轨迹），并追问车型，例如：‘您上传的是路段流量数据吗？请确认车型（如公交车、出租车等），以便计算 CO2 排放。’","notes":"覆盖文件驱动分流 + 参数协商"},"id":"e2e_incomplete_gen_016"}
{"category":"incomplete","description":"指定 vehicle_type 为模糊口语‘家用车’，且缺 model_year","user_message":"查家用车的 NOx 排放因子","has_file":false,"test_file":null,"expected_tool_chain":[],"expected_params":{"target_tool":"query_emission_factors","known_params":{"vehicle_type":"家用车","pollutants":["NOx"]},"missing_required_params":["model_year"],"negotiable_params":["season","road_type"]},"success_criteria":{"tool_executed":false,"requires_user_response":true,"result_has_data":false},"validation":{"status":"valid","issues":[],"auto_fixes":[],"expected_behavior":"系统应将‘家用车’映射为候选（如 Passenger Car），并追问年份，例如：‘“家用车”通常对应“乘用车”，请问是哪一年的车型？还需要季节和道路类型吗？’","notes":"覆盖参数协商（模糊术语 + 缺必填参数）"},"id":"e2e_incomplete_gen_015"}
{"category":"incomplete","description":"请求扩散但未提供排放源，且无历史结果可引用","user_message":"做一次NOx的扩散模拟","has_file":false,"test_file":null,"expected_tool_chain":[],"expected_params":{"target_tool":"calculate_dispersion","known_params":{"pollutant":"NOx"},"missing_required_params":["emission_source"],"negotiable_params":["meteorology"]},"success_criteria":{"tool_executed":false,"requires_user_response":true,"result_has_data":false},"validation":{"status":"valid","issues":[],"auto_fixes":[],"expected_behavior":"系统应回复‘请先提供排放数据（如通过路网或轨迹计算得到），或确认使用最近一次的排放结果’","notes":"覆盖工具依赖链中断场景，强调 emission -> dispersion 依赖"},"id":"e2e_incomplete_gen_003"}
{"category":"multi_step","description":"测试文件驱动分流 + 约束检查：轨迹文件含低速段，micro 计算正常，但 dispersion 需合理 meteorology","user_message":"这是拥堵路段的出租车轨迹，算CO排放，用 calm_stable 气象做扩散","has_file":true,"test_file":"evaluation/file_tasks/data/micro_time_speed.csv","expected_tool_chain":["calculate_micro_emission","calculate_dispersion"],"expected_params":{"vehicle_type":"Passenger Car","pollutants":["CO"],"meteorology":"calm_stable"},"success_criteria":{"tool_executed":true,"params_legal":true,"result_has_data":true},"validation":{"status":"valid","issues":[],"auto_fixes":["Assigned default test_file: evaluation/file_tasks/data/micro_time_speed.csv"],"expected_behavior":"成功执行两步；calm_stable 适用于低风速拥堵场景，无冲突","notes":"验证 micro + dispersion 合理性"},"expected_tool":"calculate_micro_emission","id":"e2e_multistep_gen_009"}
{"category":"incomplete","description":"未指定污染物种类，无法确定计算目标","user_message":"用这个路网文件算排放","has_file":true,"test_file":"evaluation/file_tasks/data/macro_direct.csv","expected_tool_chain":[],"expected_params":{"target_tool":"calculate_macro_emission","known_params":{},"missing_required_params":["pollutants"],"negotiable_params":["vehicle_type","season","model_year"]},"success_criteria":{"tool_executed":false,"requires_user_response":true,"result_has_data":false},"validation":{"status":"needs_review","issues":["negotiable_params contains names that are not valid params for the target tool."],"auto_fixes":["Assigned default test_file: evaluation/file_tasks/data/macro_direct.csv"],"expected_behavior":"系统应询问需要计算哪些污染物（如CO2、NOx等），并可进一步确认车型构成或季节等可选参数","notes":"覆盖文件驱动分流 + 参数协商"},"id":"e2e_incomplete_gen_002"}
```

---

## 6. Config 开关现状

说明:

- 这里列的是 `config.py` 中与实验、评估、标准化/路由行为直接相关的开关或相关参数。Source: `config.py` lines 44-245.
- `.env` 是否覆盖只判断 key 是否存在，不展示 value。`.env` 当前可读范围是 lines 1-78；其中与本节直接相关的 key 只有 `ENABLE_LLM_STANDARDIZATION`、`USE_LOCAL_STANDARDIZER`、`LOCAL_STANDARDIZER_MODE` 出现。Source: `.env` lines 1-78.

| Config 字段 / 参数 | 默认值 | `.env` 覆盖 | source |
| --- | --- | --- | --- |
| `enable_llm_standardization` | `true` | `yes` (`.env` line 29) | `config.py` line 44 |
| `enable_standardization_cache` | `true` | `yes` (`.env` line 30) | `config.py` line 45 |
| `enable_data_collection` | `true` | `yes` (`.env` line 31) | `config.py` line 46 |
| `enable_file_analyzer` | `true` | `no` | `config.py` line 47 |
| `enable_file_context_injection` | `true` | `no` | `config.py` line 48 |
| `ENABLE_EXECUTOR_STANDARDIZATION` / `enable_executor_standardization` | `true` | `no` | `config.py` line 49 |
| `enable_state_orchestration` | `true` | `no` | `config.py` line 50 |
| `ENABLE_TRACE` / `enable_trace` | `true` | `no` | `config.py` line 51 |
| `PERSIST_TRACE` / `persist_trace` | `false` | `no` | `config.py` line 52 |
| `enable_contour_output` | `true` | `no` | `config.py` line 53 |
| `STANDARDIZATION_FUZZY_ENABLED` / `standardization_fuzzy_enabled` | `true` | `no` | `config.py` lines 68-70 |
| `enable_lightweight_planning` | `false` | `no` | `config.py` line 71 |
| `enable_bounded_plan_repair` | `false` | `no` | `config.py` line 72 |
| `enable_repair_aware_continuation` | `false` | `no` | `config.py` line 73 |
| `ENABLE_CROSS_CONSTRAINT_VALIDATION` / `enable_cross_constraint_validation` | `true` | `no` | `config.py` lines 74-76 |
| `ENABLE_PARAMETER_NEGOTIATION` / `enable_parameter_negotiation` | `false` | `no` | `config.py` line 77 |
| `enable_file_analysis_llm_fallback` | `false` | `no` | `config.py` line 78 |
| `enable_workflow_templates` | `false` | `no` | `config.py` line 79 |
| `enable_capability_aware_synthesis` | `true` | `no` | `config.py` lines 80-82 |
| `ENABLE_READINESS_GATING` / `enable_readiness_gating` | `true` | `no` | `config.py` line 83 |
| `readiness_repairable_enabled` | `true` | `no` | `config.py` lines 84-86 |
| `readiness_already_provided_dedup_enabled` | `true` | `no` | `config.py` lines 87-89 |
| `enable_input_completion_flow` | `true` | `no` | `config.py` lines 90-92 |
| `enable_geometry_recovery_path` | `true` | `no` | `config.py` lines 102-104 |
| `enable_file_relationship_resolution` | `true` | `no` | `config.py` lines 105-107 |
| `file_relationship_resolution_require_new_upload` | `true` | `no` | `config.py` lines 108-110 |
| `file_relationship_resolution_allow_llm_fallback` | `true` | `no` | `config.py` lines 111-113 |
| `enable_supplemental_column_merge` | `true` | `no` | `config.py` lines 114-116 |
| `supplemental_merge_allow_alias_keys` | `true` | `no` | `config.py` lines 117-119 |
| `supplemental_merge_require_readiness_refresh` | `true` | `no` | `config.py` lines 120-122 |
| `enable_intent_resolution` | `true` | `no` | `config.py` lines 123-125 |
| `intent_resolution_allow_llm_fallback` | `true` | `no` | `config.py` lines 126-128 |
| `intent_resolution_bias_followup_suggestions` | `true` | `no` | `config.py` lines 129-131 |
| `intent_resolution_bias_continuation` | `true` | `no` | `config.py` lines 132-134 |
| `enable_artifact_memory` | `true` | `no` | `config.py` lines 135-137 |
| `artifact_memory_track_textual_summary` | `true` | `no` | `config.py` lines 138-140 |
| `artifact_memory_dedup_by_family` | `true` | `no` | `config.py` lines 141-143 |
| `artifact_memory_bias_followup` | `true` | `no` | `config.py` lines 144-146 |
| `enable_summary_delivery_surface` | `true` | `no` | `config.py` lines 147-149 |
| `summary_delivery_enable_bar_chart` | `true` | `no` | `config.py` lines 150-152 |
| `summary_delivery_allow_text_fallback` | `true` | `no` | `config.py` lines 156-158 |
| `enable_residual_reentry_controller` | `true` | `no` | `config.py` lines 170-172 |
| `residual_reentry_require_ready_target` | `true` | `no` | `config.py` lines 173-175 |
| `residual_reentry_prioritize_recovery_target` | `true` | `no` | `config.py` lines 176-178 |
| `enable_policy_based_remediation` | `true` | `no` | `config.py` lines 179-181 |
| `enable_default_typical_profile_policy` | `true` | `no` | `config.py` lines 182-184 |
| `ENABLE_BUILTIN_MAP_DATA` / `enable_builtin_map_data` | `false` | `no` | `config.py` line 221 |
| `enable_skill_injection` | `true` | `no` | `config.py` line 222 |
| `MACRO_COLUMN_MAPPING_MODES` / `macro_column_mapping_modes` | `direct,ai,fuzzy` | `no` | `config.py` lines 223-228 |
| `standardization_config["llm_enabled"]` | derived: if `ENABLE_LLM_STANDARDIZATION` true then default `true` | `no` (`STANDARDIZATION_LLM_ENABLED` absent) | `config.py` lines 229-233 |
| `standardization_config["fuzzy_enabled"]` | same as `standardization_fuzzy_enabled` (`true`) | `no` (`STANDARDIZATION_FUZZY_ENABLED` absent) | `config.py` line 234 |
| `standardization_config["llm_backend"]` | `api` | `no` | `config.py` line 235 |
| `standardization_config["llm_model"]` | `None` | `no` | `config.py` line 236 |
| `standardization_config["llm_timeout"]` | `5.0` | `no` | `config.py` line 237 |
| `standardization_config["llm_max_retries"]` | `1` | `no` | `config.py` line 238 |
| `standardization_config["fuzzy_threshold"]` | `0.7` | `no` | `config.py` line 239 |
| `standardization_config["enable_cross_constraint_validation"]` | same as `enable_cross_constraint_validation` (`true`) | follows parent; no direct `.env` key present | `config.py` line 240 |
| `standardization_config["parameter_negotiation_enabled"]` | same as `enable_parameter_negotiation` (`false`) | follows parent; no direct `.env` key present | `config.py` line 241 |
| `USE_LOCAL_STANDARDIZER` / `use_local_standardizer` | `false` | `yes` (`.env` line 46) | `config.py` line 262 |
| `local_standardizer_config["mode"]` | `direct` | `yes` (`.env` line 49) | `config.py` lines 264-273 |

特别关注项的当前状态:

- `ENABLE_EXECUTOR_STANDARDIZATION`: 默认 `true`，`.env` 无覆盖。Source: `config.py` line 49; `.env` lines 1-78.
- `ENABLE_CROSS_CONSTRAINT_VALIDATION`: 默认 `true`，`.env` 无覆盖。Source: `config.py` lines 74-76; `.env` lines 1-78.
- `ENABLE_PARAMETER_NEGOTIATION`: 默认 `false`，`.env` 无覆盖。Source: `config.py` line 77; `.env` lines 1-78.
- `ENABLE_READINESS_GATING`: 默认 `true`，`.env` 无覆盖。Source: `config.py` line 83; `.env` lines 1-78.
- `PERSIST_TRACE`: 默认 `false`，`.env` 无覆盖。Source: `config.py` line 52; `.env` lines 1-78.
- `ENABLE_LLM_STANDARDIZATION`: 默认 `true`，`.env` 已覆盖且仍为显式存在。Source: `config.py` line 44; `.env` line 29.
- `STANDARDIZATION_FUZZY_ENABLED`: 默认 `true`，`.env` 无覆盖。Source: `config.py` lines 68-70; `.env` lines 1-78.
- `STANDARDIZATION_LLM_ENABLED`: 默认跟随 `ENABLE_LLM_STANDARDIZATION` 推导，`.env` 无覆盖。Source: `config.py` lines 229-233; `.env` lines 1-78.

---

## 7. 测试状态

Command run:

```bash
pytest tests/ -x --tb=no -q
```

结果摘要:

- `932 passed`
- `0 failed`
- `32 warnings`

Source: live command output at snapshot time.

当前没有失败测试名称可列，因为本次运行无失败项。

Warnings family observed in the run:

- FastAPI `on_event` deprecation warnings from `api/main.py`. Source: live test output referencing `api/main.py` lines 75 and 90.
- `shared.standardizer` deprecation warning from `skills/macro_emission/skill.py`. Source: live test output referencing `skills/macro_emission/skill.py` line 11.
- `datetime.utcnow()` deprecation warnings from `api/logging_config.py`. Source: live test output referencing `api/logging_config.py` line 28.

---

## 自检

- [x] 标准化 benchmark 的维度/难度分布已统计
- [x] 端到端 benchmark 的类别分布已统计
- [x] 每条 multi_step 任务的详细信息已列出
- [x] `eval_end2end.py` 的 geometry-gated 逻辑已完整贴出
- [x] 最近两次端到端评估的 metrics 和关键 logs 已贴出
- [x] `router` 最近修改已追踪
- [x] WP4 pipeline 文件已确认存在
- [x] 功能开关现状已列出
- [x] 测试状态已确认
