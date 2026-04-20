# Phase 2 Slot Analysis

## Method

Source files:

- `evaluation/benchmarks/end2end_tasks.jsonl`
- `config/tool_contracts.yaml`

Rules used in this analysis:

1. Primary tool = first item in `expected_tool_chain`, else `expected_tool`.
2. `incomplete` tasks are excluded from primary-tool frequency tables because they intentionally have no expected tool; they are used only as auxiliary evidence for clarification behavior.
3. Tool ownership is constrained by `config/tool_contracts.yaml`. Task-level params that belong to downstream tools are not counted as slots of the first tool.
4. Review heuristic:
   - `required_slots`: parameter appears in `> 80%` of tasks for that tool.
   - `optional_slots`: parameter appears in `1-80%` of tasks for that tool.
   - `defaults`: only proposed when the parameter is often omitted and benchmark still expects the task to succeed without asking for it.

## Primary Tool Coverage

| Tool | Primary-task count |
|---|---:|
| `query_emission_factors` | 89 |
| `calculate_macro_emission` | 41 |
| `calculate_micro_emission` | 16 |
| `query_knowledge` | 2 |

Downstream-only in benchmark chains:

| Tool | Chain-task count | Note |
|---|---:|---|
| `calculate_dispersion` | 27 | Mostly artifact-driven; few user-owned slots |
| `render_spatial_map` | 10 | Artifact-driven |
| `analyze_hotspots` | 5 | Artifact-driven |

## Tool-Owned Parameter Frequency

### `query_emission_factors` (89 tasks)

| Param | Count | Share |
|---|---:|---:|
| `vehicle_type` | 88 | 98.9% |
| `pollutants` | 88 | 98.9% |
| `model_year` | 45 | 50.6% |
| `road_type` | 29 | 32.6% |
| `season` | 5 | 5.6% |

Category detail that matters:

- `multi_turn_clarification`: `model_year` appears in `11/11` factor tasks.
- `user_revision`: `model_year` appears in `15/15` factor tasks.
- `ambiguous_colloquial`: `model_year` appears in `2/20`; `road_type` appears in `2/20`.

Review proposal:

- `required_slots`: `vehicle_type`, `pollutants`
- `optional_slots`: `model_year`, `road_type`, `season`
- `default candidates`: `season`, `road_type`
- `no default proposed`: `model_year`

Reason:

- `vehicle_type` and `pollutants` are near-universal.
- `season` is omitted in `84/89` tasks and benchmark still expects direct success.
- `road_type` is omitted in `60/89` tasks and benchmark still expects direct success.
- `model_year` is only `50.6%` overall, but it is concentrated in the two categories most relevant to Clarification Contract (`multi_turn_clarification`, `user_revision`), so the data does not support silently defaulting it.

### `calculate_micro_emission` (16 tasks)

| Param | Count | Share |
|---|---:|---:|
| `pollutants` | 16 | 100.0% |
| `vehicle_type` | 13 | 81.2% |
| `season` | 8 | 50.0% |
| `model_year` | 1 | 6.2% |

Review proposal:

- `required_slots`: `vehicle_type`, `pollutants`
- `optional_slots`: `season`, `model_year`
- `default candidates`: `season` (weak candidate; exactly 50%)

Reason:

- `pollutants` is universal.
- `vehicle_type` crosses the `>80%` threshold.
- `season` is evenly split; benchmark allows success when omitted, so it can remain optional.
- `model_year` has almost no benchmark evidence.

### `calculate_macro_emission` (41 tasks)

Tool-owned params from benchmark:

| Param | Count | Share |
|---|---:|---:|
| `pollutants` | 40 | 97.6% |
| `season` | 9 | 22.0% |
| `scenario_label` | 1 | 2.4% |

Important exclusion:

- `meteorology` appears at task level in some macro-first chains, but it is not a `calculate_macro_emission` slot in `config/tool_contracts.yaml`; it belongs to downstream dispersion.

Review proposal:

- `required_slots`: `pollutants`
- `optional_slots`: `season`, `scenario_label`
- `default candidates`: `season`

Reason:

- `pollutants` is near-universal.
- `season` is omitted in most macro tasks and benchmark still expects success.
- `scenario_label` is scenario-specific, not baseline clarification material.

### `calculate_dispersion` (27 chain tasks)

Tool-owned params from benchmark:

| Param | Count | Share |
|---|---:|---:|
| `meteorology` | 12 | 44.4% |
| `pollutant` | 1 | 3.7% |
| `scenario_label` | 1 | 3.7% |

Review proposal:

- `required_slots`: none from benchmark evidence
- `optional_slots`: `meteorology`, `pollutant`, `scenario_label`
- `default candidates`: `meteorology`

Reason:

- Benchmark evidence says dispersion is primarily dependency-driven, not slot-driven.
- The missing critical input is usually upstream emission artifact, which is outside Phase 2 scope and belongs to Phase 3 Dependency Contract.
- `meteorology` is the only recurring user-owned slot.

### `analyze_hotspots` (5 chain tasks)

Tool-owned params from benchmark:

| Param | Count | Share |
|---|---:|---:|
| `method` | 1 | 20.0% |
| `percentile` | 1 | 20.0% |

Review proposal:

- `required_slots`: none from benchmark evidence
- `optional_slots`: `method`, `percentile`
- `default candidates`: `method`, `percentile`

Reason:

- Sample is small.
- Hotspot analysis is artifact-driven in benchmark design.

### `render_spatial_map` (10 chain tasks)

Tool-owned params from benchmark:

| Param | Count | Share |
|---|---:|---:|
| `pollutant` | 1 | 10.0% |
| `scenario_label` | 1 | 10.0% |

Review proposal:

- `required_slots`: none from benchmark evidence
- `optional_slots`: `pollutant`, `scenario_label`
- `default candidates`: none

Reason:

- Rendering is almost entirely dependency-driven.
- Benchmark does not support asking users for many render-specific slots up front.

### `query_knowledge` (2 tasks)

No structured benchmark params map to `query_knowledge`'s tool-owned fields (`query`, `top_k`, `expectation`).

Review proposal:

- `required_slots`: none
- `optional_slots`: none from benchmark evidence
- `default candidates`: none

Reason:

- Current benchmark treats knowledge requests as free-form text, not structured slot filling.

## Auxiliary Evidence from `incomplete`

`incomplete` has 18 tasks and all require `requires_user_response=true`.

Notable patterns:

- pollutant-only prompts exist (`查一下 CO2 的排放因子`, `PM2.5 的排放因子是多少？`)
- dispersion prompts missing artifact/context exist (`帮我做扩散分析`, `做一次 PM2.5 的扩散模拟`)
- explicit missing-param templates exist:
  - `calculate_macro_emission`: missing `file_path`, `links_data`, `pollutants`
  - `compare_scenarios`: missing `baseline_result`, `scenario_result`, `scenario_labels`
  - `render_spatial_map`: missing `dispersion_result`

Implication for review:

- A pollutant-only factor request is already benchmarked as a clarification case, not a proceed case.
- Phase 2 slot design should therefore avoid treating `pollutants` alone as sufficient for factor lookup.

## Review Cut

Proposed tool block for review before coding:

```yaml
tools:
  query_emission_factors:
    required_slots: [vehicle_type, pollutants]
    optional_slots: [model_year, road_type, season]
    defaults:
      season: <keep current default>
      road_type: <keep current default>

  calculate_micro_emission:
    required_slots: [vehicle_type, pollutants]
    optional_slots: [season, model_year]
    defaults:
      season: <review; weak candidate>

  calculate_macro_emission:
    required_slots: [pollutants]
    optional_slots: [season, scenario_label]
    defaults:
      season: <keep current default>

  calculate_dispersion:
    required_slots: []
    optional_slots: [meteorology, pollutant, scenario_label]
    defaults:
      meteorology: <keep current default>

  analyze_hotspots:
    required_slots: []
    optional_slots: [method, percentile]

  render_spatial_map:
    required_slots: []
    optional_slots: [pollutant, scenario_label]

  query_knowledge:
    required_slots: []
    optional_slots: []
```

Open points for review:

1. Whether `model_year` for `query_emission_factors` should remain optional overall, while still being a high-priority clarification target in factor-related clarification/revision turns.
2. Whether `calculate_micro_emission.season` should stay optional-with-default or be promoted to explicit clarification in some categories.
3. Whether downstream tools should declare any user-required slots at all in Phase 2, or stay dependency-first until Phase 3.

## Source Paths

- `evaluation/benchmarks/end2end_tasks.jsonl`
- `config/tool_contracts.yaml`
- `evaluation/results/clean_baseline_v8_A/end2end_logs.jsonl`
- `evaluation/results/clean_baseline_v8_A/end2end_metrics.json`
