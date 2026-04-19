# Held-out Batch 3 Reference Material

## 1. Auto-Validator Result on 55 Existing Held-out Tasks

### 1.1 Command run

Requested command:

```bash
python evaluation/pipeline_v2/auto_validator.py \
    --candidates evaluation/benchmarks/held_out_tasks.jsonl \
    --skip-llm-review
```

Current CLI requires `--output`, so the requested command failed at argparse before validation. I then ran the validator with a temporary output file:

```bash
python evaluation/pipeline_v2/auto_validator.py \
    --candidates evaluation/benchmarks/held_out_tasks.jsonl \
    --skip-llm-review \
    --output /tmp/heldout_validator_output.json
```

### 1.2 Full stdout/stderr

Requested command stdout:

```text
```

Requested command stderr:

```text
usage: auto_validator.py [-h] --candidates CANDIDATES [--benchmark BENCHMARK]
                         [--mappings MAPPINGS] [--constraints CONSTRAINTS]
                         --output OUTPUT [--model MODEL]
                         [--llm-temperature LLM_TEMPERATURE]
                         [--skip-llm-review]
auto_validator.py: error: the following arguments are required: --output
```

Actual validation command stdout:

```text
{
  "validated": 55,
  "status_counts": {
    "valid": 53,
    "needs_review": 2
  }
}
```

Actual validation command stderr:

```text
```

### 1.3 Pass/Fail summary

| Status | Count |
|---|---:|
| validated | 55 |
| valid | 53 |
| needs_review | 2 |
| invalid/fail | 0 |

No id-prefix incompatibility was reported for `e2e_heldout_*`.

### 1.4 Per-task failures (if any)

No hard validator failures.

Needs-review records:

| task_id | category | check item | message |
|---|---|---|---|
| `e2e_heldout_clarification_002` | `multi_turn_clarification` | dedup | `Potential near-duplicate user_message; normalized edit distance=0.000` |
| `e2e_heldout_revision_001` | `user_revision` | dedup | `Potential near-duplicate user_message; normalized edit distance=0.167` |

Details:

```json
[
  {
    "id": "e2e_heldout_clarification_002",
    "category": "multi_turn_clarification",
    "status": "needs_review",
    "issues": [
      "Potential near-duplicate user_message; normalized edit distance=0.000"
    ],
    "layers": {
      "structure": {
        "status": "pass",
        "issues": [],
        "details": {}
      },
      "params": {
        "status": "pass",
        "issues": [],
        "details": {
          "model_year": 2020
        }
      },
      "constraints": {
        "status": "pass",
        "issues": [],
        "details": {
          "matched_rules": [],
          "declared_constraints": []
        }
      },
      "dedup": {
        "status": "needs_review",
        "issues": [
          "Potential near-duplicate user_message; normalized edit distance=0.000"
        ],
        "details": {
          "min_message_distance": 0.0,
          "existing_signature_count": 0
        }
      },
      "llm_review": {
        "status": "skipped",
        "issues": [],
        "details": {
          "reason": "skip_llm_review=true"
        }
      }
    }
  },
  {
    "id": "e2e_heldout_revision_001",
    "category": "user_revision",
    "status": "needs_review",
    "issues": [
      "Potential near-duplicate user_message; normalized edit distance=0.167"
    ],
    "layers": {
      "structure": {
        "status": "pass",
        "issues": [],
        "details": {}
      },
      "params": {
        "status": "pass",
        "issues": [],
        "details": {
          "model_year": 2020
        }
      },
      "constraints": {
        "status": "pass",
        "issues": [],
        "details": {
          "matched_rules": [],
          "declared_constraints": []
        }
      },
      "dedup": {
        "status": "needs_review",
        "issues": [
          "Potential near-duplicate user_message; normalized edit distance=0.167"
        ],
        "details": {
          "min_message_distance": 0.1667,
          "existing_signature_count": 0
        }
      },
      "llm_review": {
        "status": "skipped",
        "issues": [],
        "details": {
          "reason": "skip_llm_review=true"
        }
      }
    }
  }
]
```

## 2. Cross-Constraints Catalog

### 2.1 File location

`config/cross_constraints.yaml`

### 2.2 Full content dump

```yaml
version: "1.1"

constraints:
  - name: "vehicle_road_compatibility"
    description: "Certain vehicle types cannot legally use specific road types."
    param_a: "vehicle_type"
    param_b: "road_type"
    type: "blocked_combinations"
    rules:
      "Motorcycle":
        blocked:
          - "高速公路"
        reason: "摩托车不允许上高速公路"

  - name: "vehicle_pollutant_relevance"
    description: "Certain vehicle and pollutant combinations are physically atypical or have limited MOVES coverage."
    param_a: "vehicle_type"
    param_b: "pollutants"
    type: "conditional_warning"
    violation_type: "warning"
    rules:
      # unified_mappings.yaml currently exposes MOVES standard source types only.
      # There is no standalone pure battery-electric vehicle standard value yet,
      # so only motorcycle-specific relevance warnings are activated here.
      "Motorcycle":
        warned:
          - "PM2.5"
          - "PM10"
        reason: "摩托车颗粒物排放通常很低，且 MOVES 对摩托车 PM 排放率数据覆盖有限，结果代表性可能较弱"
        suggestions:
          - "如需常规尾气查询，可优先选择 CO、NOx、THC 或 CO2"

  - name: "pollutant_task_applicability"
    description: "Some pollutants have limited applicability for downstream task types such as near-road dispersion."
    param_a: "pollutant"
    param_b: "tool_name"
    type: "conditional_warning"
    violation_type: "warning"
    rules:
      "CO2":
        warned:
          - "calculate_dispersion"
        reason: "CO2 在大气中混合较快，通常不作为近地扩散热点分析的重点污染物"
        suggestions:
          - "若目标是近地浓度热点，请优先考虑 NOx、CO 或 PM2.5"
      "THC":
        warned:
          - "calculate_dispersion"
        reason: "THC 的代理扩散模型支持有限，扩散结果应谨慎解释"
        suggestions:
          - "如需稳定的近地扩散结果，可优先考虑 NOx、CO 或 PM2.5"

  - name: "season_meteorology_consistency"
    description: "Season and meteorology presets should remain broadly consistent."
    param_a: "season"
    param_b: "meteorology"
    type: "consistency_warning"
    rules:
      "冬季":
        inconsistent:
          - "urban_summer_day"
          - "urban_summer_night"
        reason: "冬季使用夏季气象预设可能导致结果不准确"
      "夏季":
        inconsistent:
          - "urban_winter_day"
          - "urban_winter_night"
        reason: "夏季使用冬季气象预设可能导致结果不准确"
```

## 3. Incomplete Category Samples

### 3.1 Sample 1 (subpattern: mentions task/tool but missing key parameter)

This task asks for an emission factor and gives `model_year` + pollutant, but intentionally omits `vehicle_type`.

```json
{
  "id": "e2e_incomplete_001",
  "category": "incomplete",
  "description": "Missing vehicle type for emission-factor query should request more user input",
  "user_message": "查询2020年CO2排放因子",
  "has_file": false,
  "test_file": null,
  "expected_tool_chain": [],
  "expected_params": {},
  "success_criteria": {
    "tool_executed": false,
    "requires_user_response": true,
    "result_has_data": false
  },
  "smoke": true
}
```

### 3.2 Sample 2 (subpattern: downstream analysis requested without prerequisite artifact/context)

This task asks for dispersion analysis but intentionally omits emission/artifact context and file input.

```json
{
  "id": "e2e_incomplete_003",
  "category": "incomplete",
  "description": "Dispersion request without emission context should block for follow-up input",
  "user_message": "帮我做扩散分析",
  "has_file": false,
  "test_file": null,
  "expected_tool_chain": [],
  "expected_params": {},
  "success_criteria": {
    "tool_executed": false,
    "requires_user_response": true,
    "result_has_data": false
  },
  "smoke": false
}
```

## 4. Constraint_Violation Category Samples

### 4.1 Blocked sample

Violates `vehicle_road_compatibility`: `Motorcycle` + `高速公路` is blocked.

```json
{
  "id": "e2e_constraint_001",
  "category": "constraint_violation",
  "description": "Motorcycle plus expressway should be blocked before execution",
  "user_message": "查询2020年摩托车在高速公路上的CO2排放因子",
  "has_file": false,
  "test_file": null,
  "expected_tool_chain": [],
  "expected_params": {
    "vehicle_type": "Motorcycle",
    "road_type": "高速公路",
    "pollutants": [
      "CO2"
    ],
    "model_year": "2020"
  },
  "success_criteria": {
    "tool_executed": false,
    "constraint_blocked": true,
    "result_has_data": false
  },
  "benchmark_metadata": {
    "curation": "constraint_metadata_normalized",
    "expected_constraint_action": "reject",
    "violated_constraints": [
      "vehicle_road_compatibility"
    ],
    "representative_pattern": "motorcycle_highway"
  },
  "smoke": true
}
```

### 4.2 Warning sample

Violates `season_meteorology_consistency`: `冬季` with `urban_summer_day` should warn but can still execute when other prerequisites are available.

```json
{
  "id": "e2e_constraint_005",
  "category": "constraint_violation",
  "description": "Cross-constraint warning should remain visible for inconsistent season and meteorology; if the file lacks geometry, completing emission and halting legally before dispersion is also acceptable",
  "user_message": "请计算这个路网文件冬季条件下的NOx排放，再用urban_summer_day做扩散",
  "has_file": true,
  "test_file": "evaluation/file_tasks/data/macro_direct.csv",
  "expected_tool_chain": [
    "calculate_macro_emission",
    "calculate_dispersion"
  ],
  "expected_params": {
    "pollutants": [
      "NOx"
    ],
    "season": "冬季",
    "meteorology": "urban_summer_day"
  },
  "success_criteria": {
    "tool_executed": true,
    "params_legal": true,
    "constraint_warning": true,
    "result_has_data": true,
    "geometry_gated_halt_acceptable": true
  },
  "benchmark_metadata": {
    "curation": "constraint_metadata_normalized",
    "expected_constraint_action": "warn",
    "violated_constraints": [
      "season_meteorology_consistency"
    ]
  },
  "smoke": false
}
```
