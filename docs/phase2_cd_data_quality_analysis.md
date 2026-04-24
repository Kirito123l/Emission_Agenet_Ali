# Phase 2 Task Pack C+D Data Quality Pipeline Analysis

## Scope

Task Pack C+D adds a governed-only `clean_dataframe` tool and a stable `CleanDataFrameReport` schema. The initial implementation is intentionally read-only and CSV-only: inspect `df.info()`-equivalent structure, `df.describe()`-equivalent numeric summary, and missing-value counts. It must not fill missing values, flag outliers, repair encodings, or touch constraint-writer / clarification / OASC logic.

## 1. Existing Tool Registration Path

### `config/tool_contracts.yaml` contract shape

Top-level keys currently loaded by `ToolContractRegistry`:

- `version`
- `tool_definition_order`
- `readiness_action_order`
- `tools`
- `artifact_actions`

Pre-C+D `tool_definition_order`:

1. `query_emission_factors`
2. `calculate_micro_emission`
3. `calculate_macro_emission`
4. `analyze_file`
5. `query_knowledge`
6. `calculate_dispersion`
7. `analyze_hotspots`
8. `render_spatial_map`
9. `compare_scenarios`

`query_emission_factors` is the normal user-facing contract reference. Its entry includes:

- `display_name`
- `description`
- E-8.1 conversational fields:
  - `required_slots`
  - `optional_slots`
  - `defaults`
  - `clarification_followup_slots`
  - `confirm_first_slots`
- `parameters`
- `dependencies`
- `readiness`
- `continuation_keywords`

`analyze_file` is the file-path/internal-support reference. Its entry currently includes:

- `display_name`
- `description`
- `parameters.file_path.required`
- `dependencies.provides: [file_analysis]`
- `readiness`
- `continuation_keywords: []`

It does not currently define the five E-8.1 conversational fields, and E-8.1 tests intentionally lock empty getter behavior for `analyze_file` / `compare_scenarios`. For `clean_dataframe`, the prompt explicitly asks to add all five fields as empty list/dict values to make the new tool contract self-contained.

### `ToolContractRegistry` generated runtime surfaces

`tools/contract_loader.py::ToolContractRegistry` is the canonical YAML reader.

- `get_tool_definitions()` builds OpenAI function-calling schemas from `tool_definition_order`, `description`, and `parameters`.
- `get_tool_graph()` builds the canonical dependency graph from `dependencies.requires` / `dependencies.provides`.
- `get_action_catalog_entries()` builds readiness/action catalog entries from tool `action_variants`, top-level `artifact_actions`, and `readiness_action_order`.
- E-8.1 getters expose `required_slots`, `optional_slots`, `defaults`, `clarification_followup_slots`, and `confirm_first_slots`.

Downstream imports:

- `tools/definitions.py` exposes `TOOL_DEFINITIONS = get_tool_contract_registry().get_tool_definitions()`.
- `core/tool_dependencies.py` exposes `TOOL_GRAPH = get_tool_contract_registry().get_tool_graph()`.
- `core/readiness.py::get_action_catalog()` builds `ActionCatalogEntry` objects from `get_action_catalog_entries()`.

Conclusion: adding `clean_dataframe` to `tool_contracts.yaml` and `tool_definition_order` is sufficient for the LLM-visible schema, dependency graph, and readiness metadata to see the new tool. If no `action_variants` are added, the tool still appears in tool definitions and `TOOL_GRAPH`, but it will not add a readiness action catalog item.

### Runtime tool instance registration

Pre-C+D `tools/registry.py::init_tools()` manually imports and registers executable tool instances:

- `register_tool("query_emission_factors", EmissionFactorsTool())`
- `register_tool("calculate_micro_emission", MicroEmissionTool())`
- `register_tool("calculate_macro_emission", MacroEmissionTool())`
- `register_tool("analyze_file", FileAnalyzerTool())`
- `register_tool("query_knowledge", KnowledgeTool())`
- `register_tool("calculate_dispersion", DispersionTool())`
- `register_tool("analyze_hotspots", HotspotTool())`
- `register_tool("render_spatial_map", SpatialRendererTool())`
- `register_tool("compare_scenarios", ScenarioCompareTool())`

Conclusion: C+D needs one runtime line: import `CleanDataFrameTool` and `register_tool("clean_dataframe", CleanDataFrameTool())`.

### Tool implementation base class

All tools subclass `tools.base.BaseTool` and return `tools.base.ToolResult`.

`ToolResult` supports:

- `success`
- `data`
- `error`
- `summary`
- `chart_data`
- `table_data`
- `download_file`
- `map_data`

`BaseTool` provides helper methods:

- `_success(data, summary, ...) -> ToolResult`
- `_error(message, suggestions=None) -> ToolResult`
- `_validate_required_params(...)`

Conclusion: `CleanDataFrameTool.execute(...)` should return `ToolResult`, not a raw dict. Error details can live in `ToolResult.data` with stable `error_type` values while `success=False` and `error` carries a human-readable message.

## 2. Existing File-Path Parameter Tools

### `analyze_file`

`tools/file_analyzer.py::FileAnalyzerTool.execute(file_path: str, **kwargs)` is the closest reference:

- validates that `Path(file_path)` exists
- reads `.csv`, Excel, ZIP, GeoJSON/JSON, and shapefile inputs
- returns `ToolResult` via `_success(...)` / `_error(...)`
- writes file structure fields into `data`, including file analysis / task-type metadata

`clean_dataframe` should reuse only the tool shape, not `FileAnalyzerTool` behavior. The new tool is narrower: CSV only and data-quality report only.

### How `file_path` reaches tools

File path enters through API/session:

- `services/chat_session_service.py::build_router_user_message(...)` appends uploaded path text to the user message. For governed/full mode it currently says: `请使用 input_file 参数处理此文件。`
- `api/session.py::chat(...)` passes `file_path` into `agent_router.chat(...)`.
- `core/governed_router.py` forwards `file_path` into `UnifiedRouter.chat(...)`.
- `core/task_state.py::TaskState.initialize(...)` sets `state.file_context.has_file=True` and `state.file_context.file_path`.
- `core/router.py` passes `state.file_context.file_path` into `executor.execute(...)`.
- `core/executor.py` auto-injects `file_path` into standardized arguments when a file path exists and the tool call did not already provide `file_path`.

Important compatibility note: the API message says `input_file`, while the executor auto-injection uses `file_path`. Existing macro/micro tools accept `file_path -> input_file` compatibility internally. For `clean_dataframe`, the contract should expose `file_path`, and the executor will supply it when the user uploaded a file.

### `analyze_file` as internal support tool

`analyze_file` is filtered out of generated execution plans in `core/router.py` and omitted from the plan-repair allowed-tool set. This matches previous Phase 2 decisions: it is file grounding support, not a user-facing plan step.

`clean_dataframe` should not inherit that filtering. It is a user-facing governed tool, so it should be visible in full-mode tool definitions and `TOOL_GRAPH`.

## 3. Schema Placement Recommendation

Existing structured schema modules are mostly under `core/` when they are cross-cutting router/runtime contracts:

- `core/constraint_violation_writer.py` defines `ViolationRecord`.
- `core/coverage_assessment.py` defines `CoverageAssessment`.
- `core/file_analysis_fallback.py` defines file-analysis fallback schema objects.
- `core/task_state.py`, `core/plan.py`, `core/readiness.py`, and related modules define dataclasses used outside a single tool.

Recommendation: define `ColumnInfo` and `CleanDataFrameReport` in `core/data_quality.py`.

Rationale:

- The report is not only an implementation detail of `tools/clean_dataframe.py`; Task Pack A will consume its serialized shape.
- Keeping schema in `core/` matches the Phase 2 pattern for stable inter-component contracts.
- The tool can import the schema without creating registry/config-loader coupling.

## 4. Downstream Consumption Path

### Current result flow

Successful tool execution flows through:

1. `core/executor.py::execute(...)` returns a dict converted from `ToolResult`.
2. `core/router.py` appends that dict into `state.execution.tool_results`.
3. `core/router.py::_save_result_to_session_context(...)` calls `SessionContextStore.add_current_turn_result(...)`.
4. `SessionContextStore.add_current_turn_result(...)` records a current-turn entry and calls `store_result(...)` for successful results.
5. `store_result(...)` persists by semantic `result_type`, using `SessionContextStore.TOOL_TO_RESULT_TYPE`.

Current `SessionContextStore.TOOL_TO_RESULT_TYPE` does not include `clean_dataframe`. If left unchanged, successful `clean_dataframe` results would be stored as `unknown`.

### Required context-store key

Add:

```python
"clean_dataframe": "data_quality_report"
```

to:

- `core/context_store.py::SessionContextStore.TOOL_TO_RESULT_TYPE`
- `core/memory.py::FactMemory.TOOL_TO_RESULT_TYPE` for AO/tool-call artifact refs

The YAML contract should also declare:

```yaml
dependencies:
  requires: []
  provides:
    - data_quality_report
```

This gives downstream Task Pack A two stable consumption paths:

- latest/current execution payload: `state.execution.tool_results[*].result.data.report`
- persisted semantic payload: `context_store.get_by_type("data_quality_report")`

The latter is the preferred long-lived path because it survives the immediate execution turn and matches Phase 2 result-token design.

### Reply parser expectation

Task Pack A should read the structured report from:

```python
result["data"]["report"]
```

where `report` is exactly `CleanDataFrameReport.to_dict()`. It can also consult `context_store.get_by_type("data_quality_report").data["data"]["report"]` when parsing from persisted context-store state.

**Task Pack A consumption contract**: Task Pack A's reply parser should use `CleanDataFrameReport.from_dict()` for strict deserialization. Schema drift must raise `ValueError` immediately instead of silently dropping fields. If the schema evolves, Task Pack A must be upgraded in the same codebase change to understand the new core fields; this is an explicit refactoring-phase contract, not an optional forward-compatibility path. Non-core extensions such as future fill suggestions or outlier statistics should be read from `report.extra["<field>"]`; keys inside `extra` are not constrained by the strict top-level schema.

## 5. `CleanDataFrameReport` Schema Draft

Recommended module: `core/data_quality.py`.

```python
@dataclass
class ColumnInfo:
    name: str
    dtype: str
    non_null_count: int
    unique_count: int
    sample_values: List[Any]
    mean: Optional[float] = None
    std: Optional[float] = None
    min: Optional[float] = None
    max: Optional[float] = None


@dataclass
class CleanDataFrameReport:
    file_path: str
    row_count: int
    column_count: int
    columns: List[ColumnInfo]
    missing_summary: Dict[str, int]
    encoding_detected: str
    generated_at: str
    extra: Dict[str, Any] = field(default_factory=dict)
```

Serialization contract:

- `to_dict()` returns JSON-safe primitives.
- `from_dict()` is strict: unknown top-level fields raise `ValueError` because they indicate schema drift or a developer typo.
- `ColumnInfo.from_dict()` uses the same strict unknown-field rejection.
- `from_dict()` tolerates omitted `extra` by defaulting it to `{}`, but all other core fields must be present.
- Numeric describe fields are populated only for numeric columns; non-numeric columns keep `mean/std/min/max = None`.
- Future core field changes must update the dataclass definition plus all `to_dict()` / `from_dict()` producers and consumers in the same codebase change.
- Future non-core features such as fill recommendations, outlier summaries, encoding repairs, duplicate detection, and type-correction suggestions should go under `extra`.
- `extra` is an explicit extension outlet, not a silent forward-compatibility channel; `extra` itself is a normal schema field while its internal keys are intentionally unconstrained.

Encoding detection:

- `requirements.txt` already includes `pandas`, but no `chardet` / `charset-normalizer` dependency is declared.
- To avoid adding dependencies, initial implementation should try a small deterministic encoding list such as `utf-8-sig`, `utf-8`, `gbk`, and `latin1`; record the encoding that successfully reads.
- If all attempts fail, return `error_type="read_failed"`.

## 6. Test Strategy

Unit tests in `tests/test_clean_dataframe.py` should cover:

1. Schema round-trip: `CleanDataFrameReport.to_dict()` then `from_dict()` preserves core fields.
2. Strict schema rejection: `from_dict()` raises `ValueError` when unknown top-level fields are present, and the error message names the rejected field.
3. Explicit extension outlet: `from_dict()` accepts arbitrary key-value pairs inside the `extra` dict.
4. Normal CSV: a small fixture returns correct `row_count`, `column_count`, `columns[*].dtype`, and sample values.
5. Missing values: `missing_summary` is exact for columns with blank/NaN values.
6. Numeric describe: numeric columns have `mean`, `std`, `min`, and `max`; non-numeric columns keep those fields as `None`.
7. Error handling:
   - non-CSV suffix returns `success=False`, `error_type="unsupported_format"`
   - nonexistent path returns `success=False`, `error_type="read_failed"`
   - empty CSV with only headers is valid and returns `row_count=0`
8. Chinese field names: CSV headers and sample string values with Chinese characters survive read/serialize.
9. Large-file guard: a moderately sized CSV should not include unbounded sample payloads; `sample_values` remains capped at 3 non-null values per column.

Integration tests in `tests/test_clean_dataframe_integration.py` should cover:

1. Governed/full path can call `clean_dataframe` with a CSV upload and store `data_quality_report` in `context_store`.
2. `NaiveRouter` does not expose `clean_dataframe`; assert it is absent from `NAIVE_TOOL_NAMES` and `_load_naive_tool_definitions()`.

Regression focus:

- `tests/test_naive_router.py`: add/confirm `clean_dataframe` is not in the naive whitelist.
- `tests/test_tool_contracts.py`: generated `TOOL_DEFINITIONS` and `TOOL_GRAPH` still match registry output after YAML change.
- `tests/test_yaml_merge.py`: `ToolContractRegistry` E-8.1 getters should return empty values for `clean_dataframe` if all five fields are empty.

## 7. Proposed Implementation Plan After Approval

1. Add `core/data_quality.py` with `ColumnInfo`, `CleanDataFrameReport`, and robust `to_dict()` / `from_dict()`.
2. Add `tools/clean_dataframe.py` implementing CSV-only `CleanDataFrameTool`.
3. Update `config/tool_contracts.yaml`:
   - add `clean_dataframe` to `tool_definition_order`
   - add the `tools.clean_dataframe` contract with `provides: [data_quality_report]`
   - keep `required_slots: []` because `file_path` is injected from uploaded-file context
4. Register runtime tool in `tools/registry.py::init_tools()`.
5. Add `clean_dataframe -> data_quality_report` mappings in `core/context_store.py` and `core/memory.py`.
6. Keep `core/naive_router.py::NAIVE_TOOL_NAMES` unchanged and add a test assertion that `clean_dataframe` is absent.
7. Add unit and integration tests.
8. Run full `pytest tests/ -q --tb=line`.
9. Generate and run C+D post smoke; document post-only result and user-local pre command.

## 8. Risks and Guardrails

- Tool-list drift risk: adding a new LLM-visible tool can cause existing tasks to misselect it. The C+D smoke set should watch `simple`, `parameter_ambiguous`, `multi_step`, `incomplete`, and `constraint_violation`.
- Description ambiguity risk: keep `clean_dataframe` description clearly scoped to uploaded CSV inspection/data-quality reporting, not emission/dispersion calculation.
- File-path naming risk: API message still says `input_file`; executor injects `file_path`. The `clean_dataframe` tool should only require `file_path`; no `input_file` alias is needed unless tests show LLM calls it directly with `input_file`.
- Payload-size risk: do not include full DataFrame rows in the report. Cap `sample_values` at 3 non-null values per column.
- Dependency risk: do not add `chardet`; use deterministic encoding attempts with existing dependencies.
- Governance boundary risk: do not touch GovernedRouter writer/clarification/OASC components. This tool should integrate through existing registry, executor, and context-store paths.
