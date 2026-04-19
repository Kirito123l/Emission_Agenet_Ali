# Benchmark Schema Recon

Scope: this recon is aligned to `evaluation/benchmarks/end2end_tasks.jsonl` plus the evaluator/runtime code paths that consume it. I sampled the first 3 benchmark rows and one row per current category. I did not rely on held-out task content.

## 1. Task Schema

### 1.1 Field dictionary (complete)

The canonical main benchmark reader is `evaluation/eval_end2end.py::_normalize_task()`. It accepts both current rows and legacy rows with `sample_id`, but the 180-row main benchmark uses the current schema below.

| Field | Type | Required | Meaning / evaluator behavior |
|---|---|---:|---|
| `id` | string | yes | Canonical task identifier. The field is `id`, not `task_id`. Logs write it as `task_id`. Current naming convention is `e2e_<category-prefix>_<NNN>`, for example `e2e_simple_001`, `e2e_clarification_101`, `e2e_codeswitch_180`. Pipeline v2 prefixes are `simple`, `ambiguous`, `multistep`, `incomplete`, `constraint`, `clarification`, `revision`, `colloquial`, `codeswitch`. `compute_next_task_id()` uses the maximum numeric suffix across existing records, then emits `e2e_<prefix>_<next>`. |
| `category` | string enum | yes | Legal values: `simple`, `parameter_ambiguous`, `multi_step`, `incomplete`, `constraint_violation`, `multi_turn_clarification`, `user_revision`, `ambiguous_colloquial`, `code_switch_typo`. Defined in `evaluation/pipeline_v2/common.py::VALID_CATEGORIES`. |
| `description` | string | yes | Human-readable test intent. Logged but not used for scoring. |
| `user_message` | string | yes | Initial user turn. There is no `dialogue`, `messages`, `turns`, or `initial_message` field in the main schema. |
| `has_file` | boolean | yes | Whether the task should run with a benchmark fixture file. Validator requires `test_file` when true. Evaluator mostly derives the actual path from `test_file`; `has_file` also affects generator/pipeline success-criteria defaults. |
| `test_file` | string or null | yes | Repo-relative or absolute path to fixture file. Evaluator resolves relative paths via `PROJECT_ROOT / test_file`. No URL/base64 indirection. |
| `expected_tool` | string or null | optional | Single primary tool. Present on many single-step rows, absent on some multi-step rows. Evaluator keeps it but scoring is driven by `expected_tool_chain`. If current rows omit `expected_tool`, no problem. |
| `expected_tool_chain` | list of strings | yes | Expected executed tools in order. Empty list means no tool should run before clarification/blocking. Evaluator treats tool-chain match as strict equality, except `user_revision` may have extra earlier tools if the actual chain suffix equals the expected chain. |
| `expected_params` | object | yes | Expected parameter subset. Current main rows use a flat dict such as `{"pollutants": ["CO2"]}`. Pipeline helpers also understand `known_params` for generated incomplete/constraint candidates, but evaluator compares the object it receives directly. It is not per-tool nested in the current main benchmark. |
| `success_criteria` | object of boolean checks | yes | Boolean scoring contract. Recognized keys are `tool_executed`, `params_legal`, `result_has_data`, `requires_user_response`, `constraint_blocked`, `constraint_warning`, `trace_has_error`, and `geometry_gated_halt_acceptable`. Unknown keys are ignored by evaluator. |
| `smoke` | boolean | optional | Included in current main rows. `--smoke` filters to rows where this is true. |
| `benchmark_metadata` | object | optional | Metadata for curation/provenance/adversarial semantics. Evaluator preserves neither this field in `_normalize_task()` nor scoring logic, but pipeline validators/coverage tools use metadata-like fields in candidates. Current examples include `phase0_adversarial`, `generation_flow`, `human_review`, `expected_param_source`, `curation`, `expected_constraint_action`, and `violated_constraints`. |
| `follow_up_messages` | list of strings | optional | Scripted follow-up user turns for multi-turn categories. Evaluator sends them in the same router session after the initial `user_message`. |
| `expected_outputs` | object | legacy optional | Only used for legacy `sample_id` rows. `_check_outputs()` supports `has_chart_data`, `has_table_data`, `has_map_data`, and `has_download_file`. Not part of current main rows sampled. |
| `expected_behavior` | string | generator/intermediate only | Used by `evaluation/generate_e2e_tasks.py` before merge; not consumed by the main evaluator after final benchmark normalization. |
| `notes`, `validation`, `candidate_metadata`, `provenance`, `review_decision` | mixed | intermediate optional | Used by generation/review pipeline. `merge_to_benchmark.py` strips `validation`, `candidate_metadata`, and `review_decision`; `common.canonicalize_benchmark_task()` preserves `notes`, `benchmark_metadata`, and `provenance` if present. |

Fields searched and not present in the main benchmark: `task_id`, `dialogue`, `messages`, `turns`, `expected_response_checks`, `file_context`, `uploaded_files`, `attachments`, `setup`, `session_id`, `expected_stance`, `expected_stance_confidence`. Grep terms used included those exact field names against `evaluation/benchmarks/end2end_tasks.jsonl`.

### 1.2 Category-specific variations

`simple`: direct single-step task; should normally have exactly one tool and direct success criteria.

`parameter_ambiguous`: direct single-step task where wording requires alias/standardization; expected params should use normalized values.

`multi_step`: `expected_tool_chain` has two or more tools. File-backed spatial chains may set `geometry_gated_halt_acceptable` to allow legal halt after upstream emission if the input file lacks usable geometry.

`incomplete`: `expected_tool_chain` is normally empty, `expected_params` may be empty, and `success_criteria` expects `tool_executed=false`, `requires_user_response=true`, `result_has_data=false`.

`constraint_violation`: can be block/reject (`expected_tool_chain=[]`, `constraint_blocked=true`) or warning-only (`expected_tool_chain` runnable, `constraint_warning=true`). Current sampled main task stores constraint detail in `benchmark_metadata`, not a special top-level marker field.

`multi_turn_clarification`: initial `user_message` is incomplete; `follow_up_messages` supplies answers in later turns. Expected params describe the final completed task.

`user_revision`: initial task is revised by `follow_up_messages`; expected params describe the final user revision. Evaluator compares actual params from the last executed tool call and allows the expected tool chain to match the suffix of actual calls.

`ambiguous_colloquial`: Phase0 adversarial colloquial expression tasks. Uses normal direct fields plus optional `benchmark_metadata.colloquial_expression`.

`code_switch_typo`: mixed-language/typo tasks. Some are executable, some are incomplete and expect clarification with empty tool chain.

### 1.3 Annotated sample (simple category)

Strict JSON sample, pretty-printed from a current `simple` task:

```json
{
  "id": "e2e_simple_001",
  "category": "simple",
  "description": "Basic emission-factor lookup for a passenger-car synonym",
  "user_message": "查询2020年网约车的CO2排放因子",
  "has_file": false,
  "test_file": null,
  "expected_tool": "query_emission_factors",
  "expected_tool_chain": [
    "query_emission_factors"
  ],
  "expected_params": {
    "vehicle_type": "Passenger Car",
    "pollutants": [
      "CO2"
    ]
  },
  "success_criteria": {
    "tool_executed": true,
    "params_legal": true,
    "result_has_data": true
  },
  "smoke": true
}
```

旁注:

- `id`: canonical benchmark identifier; evaluator logs it as `task_id`.
- `category`: one of the nine legal category strings.
- `user_message`: the only initial-user-message field in the current schema.
- `has_file=false` and `test_file=null`: no fixture file will be passed.
- `expected_tool_chain`: ordered list used for tool accuracy.
- `expected_params`: flat expected subset, normalized to system canonical values.
- `success_criteria`: boolean checks evaluator applies after tool-chain matching.

### 1.4 Multi-turn encoding

Multi-turn tasks are encoded as one JSONL row with:

- `user_message`: first turn.
- `follow_up_messages`: ordered list of follow-up user turns.

There is no `dialogue`, `messages`, `turns`, `initial_message`, or `follow_up_messages` split into role/message objects. Evaluator behavior:

- Router mode builds `session_id=f"eval_{task['id']}"`.
- It sends `user_message`, then consumes scripted `follow_up_messages` before auto-generating continuation prompts.
- `max_turns = min(len(expected_chain) + len(follow_up_messages) + 2, 8)`.
- Actual tool calls and trace telemetry are merged across turns.

Sample shapes:

- `multi_turn_clarification`: `user_message="帮我查一下排放因子"`, `follow_up_messages=["乘用车", "NOx", "2022年"]`, final expected params include vehicle, pollutant, and year.
- `user_revision`: `user_message="查2021年乘用车冬季NOx排放因子"`, `follow_up_messages=["算了改成夏天吧"]`, final expected params use `season="夏季"` and metadata may include `expected_param_source="final_user_revision"`.

### 1.5 Stance-related fields (if any)

Main benchmark fields `expected_stance` and `expected_stance_confidence` are field not present. Grep terms used: `expected_stance`, `expected_stance_confidence`, `stance_value`, `stance_confidence` against the main benchmark and evaluator code.

Phase 2R Wave 1 adds runtime AO/telemetry fields, not benchmark schema fields:

- AO persists `stance`, `stance_confidence`, `stance_resolved_by`, and `stance_history`.
- Clarification telemetry can contain `stance_value`, `stance_confidence`, `stance_resolved_by`, `stance_evidence`, `stance_reversal_detected`, `stance_llm_hint_raw`, and `stance_llm_hint_parse_success`.
- `evaluation/eval_end2end.py` copies `clarification_telemetry` into logs and computes clarification-contract metrics, but does not read expected stance fields or score stance match.

## 2. Evaluator

### 2.1 Success criteria chain

Task loading:

1. `load_jsonl(samples_path)` reads rows.
2. `_normalize_task()` maps current rows to a fixed internal dict and drops unrecognized fields.
3. `_load_benchmark_tasks()` optionally filters by `--only-task`, `--category`, `--filter-categories`, and `--smoke`.

Tool execution:

- `router`: uses `build_router(session_id=f"eval_{id}")`, same-session multi-turn flow, file path passed as `file_path`.
- `naive`: uses `NaiveRouter(session_id=f"eval_naive_{id}")`.
- `tool`: only supports single-step rows and calls `ToolExecutor.execute()` directly.

Tool-chain comparison:

- Default: `actual_tool_chain == expected_tool_chain`; order-sensitive, no extra tools allowed.
- Empty expected chain matches.
- `user_revision`: if actual has extra earlier calls, the evaluator accepts `actual[-len(expected):] == expected`.
- Text fallback: if no actual tool call, a single expected tool can be inferred from response text cues for known tools.
- Geometry-gated fallback: for criteria that allow it, a prefix before the first geometry-required tool can be accepted when the file lacks explicit geometry and the response legally halts after upstream emission.

Parameter legality:

- Actual args are merged across executed calls; duplicate keys with different values become lists.
- For `user_revision`, only the last executed tool call's arguments are compared.
- `compare_expected_subset(actual, expected)` checks that every expected key exists in actual. Actual may contain extra keys.
- Parameter names support aliases such as `vehicle` -> `vehicle_type` and `pollutant` -> `pollutants`.
- Lists are subset-style, not exact equality; expected list items must be found in actual, order is not strict.
- Dicts compare recursively as expected subsets.
- Strings compare case-insensitively and can use standardizer alias matching for known dimensions.
- Numeric values are coerced and compared exactly.
- If expected params are not found in args, evaluator may mark them matched if the expected values appear in tool result or response payload text.

`completion_rate`:

- A row `success` starts as `tool_match` or `geometry_gated_success`.
- If not geometry-gated, evaluator ANDs each recognized `success_criteria` key against actual criteria.
- For current rows, `completion_rate = success_count / task_count`.
- For legacy rows with `sample_id`, success additionally checks legacy `expected_outputs`.

`tool_accuracy`:

- Counted when `actual.tool_chain_match` is true or the expected tool chain is empty.
- Aggregated overall and per category.

`parameter_legal_rate`:

- Counted when `actual.criteria.params_legal` is true.
- If `expected_params` is empty, `params_legal` falls back to `tool_executed`.

`result_data_rate`:

- Counted when `actual.criteria.result_has_data` is true.
- `result_has_data` is true if response has `chart_data`, `table_data`, `map_data`, `download_file`, tool result `summary`/`data`, or response text implies the expected tool result.

Partial credit:

- No row-level partial credit. Metrics are independent binary rates (`completion_rate`, `tool_accuracy`, `parameter_legal_rate`, `result_data_rate`).
- Unknown `success_criteria` keys are silently ignored because `_build_task_result()` continues when a key is not in `criteria_actuals`.

### 2.2 Response check functions (enumerated)

`expected_response_checks` is not implemented in `evaluation/eval_end2end.py` and is field not present in the main benchmark. Grep terms used: `expected_response_checks`, `response_checks`, `def check_`, `check_`.

Available check-like evaluator functions:

| Function | File | Purpose |
|---|---|---|
| `_check_outputs(result_like, expected_outputs)` | `evaluation/eval_end2end.py` | Legacy output checks for `has_chart_data`, `has_table_data`, `has_map_data`, `has_download_file`. |
| `_has_result_payload(response_payload, executed_tool_calls)` | `evaluation/eval_end2end.py` | Determines whether response/tool calls carry result data. |
| `_response_text_has_expected_tool_result(text, expected_tool_chain)` | `evaluation/eval_end2end.py` | Text fallback cues for macro/micro emission, emission factors, knowledge, dispersion, hotspot, and map rendering. |
| `_response_text_is_asking_user(text)` | `evaluation/eval_end2end.py` | Detects clarification/user-response prompts. |
| `_response_text_has_constraint_warning(text)` | `evaluation/eval_end2end.py` | Detects warning semantics in response text. |
| `_response_text_has_constraint_block(text)` | `evaluation/eval_end2end.py` | Detects blocking semantics for known constraint patterns. |
| `_is_geometry_gated_multistep_success(...)` | `evaluation/eval_end2end.py` | Allows legal halt before geometry-dependent downstream tools under explicit criteria. |
| `compare_expected_subset(actual, expected)` | `evaluation/utils.py` | Flexible expected-parameter subset matcher. |

If a held-out task includes `expected_response_checks`, current evaluator behavior is silent ignore: `_normalize_task()` does not preserve the field, no check registry exists, and no error is raised.

### 2.3 Stance support status

Evaluator support is telemetry-only:

- `expected_stance` is not read.
- `expected_stance_confidence` is not read.
- There is no stance-match success criterion.
- `clarification_telemetry` is merged across router turns and copied into each log record.
- Aggregated `clarification_contract_metrics` currently include trigger count/rate, Stage 2 hit rate/latency, Stage 3 rejection rate, short-circuit rate, and proceed rate.
- There is no evaluator aggregation for `stance_value`, `stance_confidence`, stance distribution, or stance match. Phase 2R Wave 1 report computed stance sanity externally from logs, not through a built-in metric in `eval_end2end.py`.

## 3. File Upload

### 3.1 Field declaration

Main benchmark file declaration uses only:

```json
{
  "has_file": true,
  "test_file": "repo-relative/path/to/file"
}
```

Field names not present in main benchmark: `file_context`, `uploaded_files`, `attachments`. Grep terms used: those exact names plus `test_file`, `.zip`, `.xlsx`, `shapefile`.

The field value is a path, not a URL or base64 payload. Type is inferred from extension/runtime analyzer:

- `.csv`, `.xlsx`, `.xls`: tabular input.
- `.zip`: ZIP containing `.shp` or `.csv/.xlsx/.xls`; runtime treats `.shp` first if present and `geopandas` is available.
- `.shp`, `.geojson`, `.json`: supported by `FileAnalyzerTool`; macro-emission direct input primarily handles tabular paths or ZIP paths.

### 3.2 Samples (GIS + Excel)

Excel true main benchmark sample:

```json
{
  "id": "e2e_multistep_005",
  "category": "multi_step",
  "has_file": true,
  "test_file": "test_data/test_6links.xlsx",
  "expected_tool_chain": [
    "calculate_macro_emission",
    "calculate_dispersion",
    "render_spatial_map"
  ],
  "expected_params": {
    "pollutants": [
      "NOx"
    ]
  }
}
```

GIS ZIP true main benchmark sample: field not present. Grep terms against `evaluation/benchmarks/end2end_tasks.jsonl`: `.zip`, `shapefile`, `test_file.*zip`. No hits.

Runtime GIS fixture sample that can be used by the same benchmark fields if added:

```json
{
  "has_file": true,
  "test_file": "test_data/test_6links.zip"
}
```

This is not currently a main benchmark row; it is a fixture path supported by `FileAnalyzerTool` and `MacroEmissionTool`.

### 3.3 Stub directory contents

Main benchmark file fixtures are spread across `evaluation/file_tasks/data/` and `test_data/`, not a dedicated `evaluation/benchmarks/fixtures/` directory.

Core tabular fixtures:

- `evaluation/file_tasks/data/macro_cn_fleet.csv`
- `evaluation/file_tasks/data/macro_direct.csv`
- `evaluation/file_tasks/data/macro_fuzzy.csv`
- `evaluation/file_tasks/data/micro_cn.csv`
- `evaluation/file_tasks/data/micro_full.csv`
- `evaluation/file_tasks/data/micro_speed_only.csv`
- `evaluation/file_tasks/data/micro_time_sec_speed_kmh.csv`
- `evaluation/file_tasks/data/micro_time_speed.csv`
- `test_data/test_20links.xlsx`
- `test_data/test_6links.xlsx`
- `test_data/test_no_geometry.xlsx`
- `test_data/test_shanghai_allroads.xlsx`
- `test_data/test_shanghai_full.xlsx`

Core GIS ZIP/Shapefile fixtures:

- `test_data/test_20links.zip`
- `test_data/test_20links/test_20links.{shp,shx,dbf,prj,cpg}`
- `test_data/test_6links.zip`
- `test_data/test_shanghai_allroads.zip`
- `test_data/test_shanghai_allroads/test_shanghai_allroads/test_shanghai_allroads.{shp,shx,dbf,prj,cpg}`
- `test_data/test_shanghai_full.zip`
- `test_data/1km_hd_irregular_changning_02.zip`
- `test_data/1km_hd_irregular_changning_02/1km_hd_irregular_changning_02/1km_hd_irregular_changning_02.{shp,shx,dbf,prj,cpg}`
- `test_data/test_subnets/*/{links,nodes}.{shp,shx,dbf,prj,cpg}`
- `test_data/test_subnets/*/*.zip`
- `test_data/精简文件/*/*.{shp,shx,dbf,prj,cpg}`

### 3.4 Runtime loading path

API upload:

1. `api/routes.py::chat()` and `chat_stream()` accept `file: Optional[UploadFile] = File(None)`.
2. The API reads bytes with `await file.read()` into `UploadedFileInput`.
3. `ChatSessionService._stage_upload()` sanitizes the filename, preserves only the suffix, and writes bytes to `/tmp/emission_agent/{session_id}_input{suffix}`.
4. `build_router_user_message()` appends `文件已上传，路径: <path>` and, outside naive mode, `请使用 input_file 参数处理此文件。`
5. `session.chat()` receives both the message and `file_path`.

Benchmark runtime:

1. `_run_single_task_async()` resolves `test_file` with `resolve_project_path()`.
2. If file analyzer is enabled, `FileAnalyzerTool.execute(file_path=...)` produces file analysis.
3. Router/naive mode passes `file_path=str(file_path)` into chat.
4. Tool mode passes `file_path` into `ToolExecutor.execute()`.

Tool consumption:

- `FileAnalyzerTool`: reads CSV/Excel directly; reads `.zip` by extracting candidate `.shp/.csv/.xlsx/.xls` entries to a temp dir; reads shapefile candidates with `geopandas`; annotates `format` as `zip_shapefile`, `zip_tabular`, or `zip_multi_dataset`.
- `MacroEmissionTool`: maps `file_path` to `input_file`; if suffix is `.zip`, `_read_from_zip()` looks for `.shp` first and falls back to `.xlsx/.xls/.csv`; shapefile ZIP is extracted and read with `geopandas`, converting geometry into link dictionaries.
- `MicroEmissionTool`: maps `file_path` to `input_file` and reads trajectory tabular files via its Excel handler.
- `DispersionTool`: does not read uploaded ZIP/Excel directly in normal chain; it consumes upstream emission data (`_last_result`/emission source) and requires geometry in emission results.
- `SpatialRendererTool`/`HotspotTool`: consume upstream emission/dispersion/hotspot data rather than upload declarations directly.

### 3.5 Minimal add-a-stub procedure

For an Excel held-out fixture:

1. Place the file under `test_data/` or `evaluation/file_tasks/data/`.
2. Add a task row with `has_file=true` and `test_file="<repo-relative path>.xlsx"`.
3. Ensure columns satisfy macro/micro required mappings (`length/flow/speed/link_id` for macro, `time/speed` for micro) or expected completion/remediation behavior.
4. No config change is required unless new aliases/columns need standardization support.

For a Shapefile ZIP held-out fixture:

1. Put a ZIP under `test_data/` containing a complete shapefile component set: `.shp`, `.shx`, `.dbf`, `.prj`, and ideally `.cpg`.
2. Ensure the ZIP contains exactly one intended primary road `.shp`, or make the intended primary score highest; `FileAnalyzerTool` and macro-emission currently select candidate datasets heuristically/first-match.
3. Add a task row with `has_file=true` and `test_file="test_data/<fixture>.zip"`.
4. For macro-emission, ensure attributes can map or be repaired to required fields: `link_id`, length, flow, speed; geometry is read from the shapefile.
5. No config change is required for ordinary shapefile ZIP support. Add config only if the new file uses unmapped column names or new parameter aliases.
6. Because main benchmark currently has no `.zip` row, add at least one smoke task if GIS ZIP coverage should be verified routinely.

## 4. Task Addition Workflow

### 4.1 Validator (if any)

There is no validator automatically invoked by `eval_end2end.py` before running. The evaluator normalizes rows permissively and ignores unknown fields.

Available validation tools:

- `evaluation/pipeline_v2/auto_validator.py`: five-layer validator for generated candidates.
- `evaluation/pipeline_v2/coverage_audit.py`: audits coverage and emits gap reports.
- `evaluation/pipeline_v2/regression_check.py`: runs approved candidates through evaluator as a regression check.

`auto_validator.py` checks:

- Required fields: `id`, `category`, `user_message`, `expected_tool_chain`, `expected_params`, `success_criteria`.
- Category membership in `VALID_CATEGORIES`.
- Non-empty `user_message`.
- `expected_tool_chain` list type.
- `expected_params` dict type.
- `success_criteria` dict type.
- `has_file=true` requires `test_file`.
- `follow_up_messages`, when present, must be a list of non-empty strings.
- Parameter values against mappings catalog: vehicle type, pollutants, season, road type, meteorology, stability class, model year range.
- Constraint consistency against `config/cross_constraints.yaml`.
- Dedup via normalized edit distance against existing messages and repeated task signatures.
- Optional LLM quality review unless `--skip-llm-review`.

### 4.2 Generator (if any)

Generators/tools found:

- `evaluation/generate_e2e_tasks.py`: older category-based Qwen generator. CLI flags include `--category`, `--all`, `--count`, `--model`, `--temperature`, `--max-rounds`, `--replace-existing`.
- `evaluation/pipeline_v2/targeted_generator.py`: gap-driven generator. CLI flags: `--gaps`, `--existing`, `--output`, `--count-per-gap`, `--limit-targets`, `--model`, `--temperature`.
- `evaluation/pipeline_v2/run_pipeline.sh`: pipeline wrapper: coverage audit -> targeted generation -> auto validation -> human review -> regression check -> merge -> final coverage report.
- `evaluation/pipeline_v2/review_cli.py`: manual review/edit surface for `needs_review` candidates.
- `evaluation/pipeline_v2/merge_to_benchmark.py`: merges reviewed/valid candidates and assigns final IDs.

### 4.3 Checklist

Add one new task:

1. Choose a legal `category`.
2. Assign `id` using `e2e_<prefix>_<NNN>`; prefer `merge_to_benchmark.py` for canonical ID assignment.
3. Write a natural `description`.
4. Put the first user turn in `user_message`.
5. For multi-turn clarification/revision, put later user turns in `follow_up_messages`.
6. Set `has_file` and `test_file`; use repo-relative paths.
7. Set `expected_tool_chain` in exact intended order; use `[]` for block/clarification-before-tool cases.
8. Set `expected_tool` only as convenience for single-step rows; do not rely on it for scoring.
9. Set flat normalized `expected_params` unless deliberately using generator/intermediate `known_params`.
10. Set `success_criteria` using recognized evaluator keys.
11. Add `smoke=true` only for a small, representative subset.
12. Add `benchmark_metadata` for curation/adversarial rationale, not scoring.
13. Run `auto_validator.py --skip-llm-review` for structural checks; run without skip if LLM review is intended.
14. Use `coverage_audit.py`/`merge_to_benchmark.py` for uniqueness and canonical merge. Uniqueness checks include exact message duplicate skip and near-duplicate edit distance review.
15. For held-out, additionally check content non-overlap manually or with a separate dedup script against main benchmark user messages and task signatures.

## 5. Matrix Runner

### 5.1 CLI flags

`evaluation/run_oasc_matrix.py` flags:

| Flag | Meaning |
|---|---|
| `--samples` | Path to benchmark JSONL. Defaults to `evaluation/benchmarks/end2end_tasks.jsonl`. |
| `--results-root` | Root output directory. Defaults to `evaluation/results`. |
| `--preflight-count` | Number of simple tasks selected for preflight. Defaults to 5. |
| `--groups` | Comma-separated group names. Defaults to `A,B,C,D,E,F,G`; names are uppercased. |
| `--parallel` | Worker count passed to `eval_end2end.py`. Defaults to 8. |
| `--qps-limit` | Request rate limit passed to evaluator. Defaults to 15.0. |
| `--smoke` | Restrict evaluator to `smoke=true` tasks. |
| `--cache` | Enable tool-result cache. Default true. |
| `--no-cache` | Disable tool-result cache. |
| `--output-prefix` | Per-group result directory prefix. Defaults to `end2end_full_v5_oasc`. |
| `--filter-categories` | Comma-separated category filter string passed through to evaluator. |

### 5.2 Custom benchmark file support

There is custom benchmark support via `--samples`; there is no flag literally named `--benchmark-file`.

To add a `--benchmark-file` alias with minimal change:

1. In `run_oasc_matrix.py::main()`, add `parser.add_argument("--benchmark-file", dest="samples", type=Path)`, or add it as an alias to the existing `--samples` argument.
2. No downstream changes are needed because `run_matrix(samples_path=args.samples, ...)` already passes the path to preflight and group runs.

### 5.3 Filter category conventions

`--filter-categories` is comma-separated. It is case-sensitive for category names:

- Matrix runner passes the raw string to evaluator.
- Evaluator splits on comma and strips whitespace.
- `_load_benchmark_tasks()` compares `task.get("category") in allowed` without lowercasing.

Use exact lowercase category names such as `multi_turn_clarification,ambiguous_colloquial`.

### 5.4 Session isolation

Preflight/session clearing:

- `run_matrix()` runs `run_preflight(samples_path=..., count=...)` first.
- If preflight passes, `_clear_eval_session_history()` deletes `data/sessions/history/eval_*.json` and `eval_naive_*.json`.
- It also clears eval session history before each group.
- `eval_end2end.py` uses session IDs `eval_<task id>` and `eval_naive_<task id>`.

Held-out runs should keep this isolation. If held-out task IDs overlap main IDs or previous held-out IDs, stale eval session state can contaminate multi-turn/AO behavior. The current matrix runner clears only `eval_*.json` and `eval_naive_*.json`, not arbitrary non-eval user sessions.

## 6. Open Questions / Recommendations

- Main benchmark currently has no `.zip`/Shapefile task despite runtime support. If held-out must test GIS ZIP upload, add a new `.zip` task and run it explicitly; otherwise GIS upload remains covered only by runtime fixtures/logs, not main end-to-end benchmark rows.
- `expected_response_checks` and `expected_stance` are not supported by current evaluator. If held-out schema wants those fields, add evaluator support first or they will be silently ignored.
- Current evaluator ignores unknown `success_criteria` keys. This is useful for forward compatibility but risky for held-out authoring because misspelled checks silently reduce test strength.
- `expected_params` is flat in current main benchmark. Per-tool nested params would not match current evaluator semantics unless `eval_end2end.py` is changed to compare params by tool call.
- `compute_next_task_id()` uses the maximum numeric suffix across all categories, not per-category suffix. This matches current global numbering after Phase0 rows but can surprise authors expecting `e2e_simple_006` after simple row 005.
- `run_oasc_matrix.py` already supports custom files through `--samples`; adding `--benchmark-file` would be an alias/UX improvement only.
- For held-out construction, run `auto_validator.py --skip-llm-review` for deterministic checks, then a separate non-overlap check against main benchmark `user_message` and task signature. Do not put held-out rows in repo root where broad `rg .` searches can accidentally expose them.
