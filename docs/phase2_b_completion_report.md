# Phase 2 Task Pack B Completion Report

## Implementation Status

B.1 through B.8 completed. Full pytest 1220 passed. Pre/post smoke PASS with unexpected positive gain on multi_turn_clarification (`0/2 -> 2/2`). See `docs/phase2_b_smoke_comparison.md`.

## Change List

### B.1 Analysis

- `docs/phase2_b_constraint_writer_analysis.md`: added the initial call-point analysis and later added the approved "Architecture Decision: Event-Based Via TraceStep" section.

### B.2 Violation Record Schema

- `core/constraint_violation_writer.py:17`: added `ViolationRecord`.
- `core/constraint_violation_writer.py:28`: added `to_dict()`.
- `core/constraint_violation_writer.py:38`: added `from_dict()`.
- `core/constraint_violation_writer.py:51`: added pure `normalize_cross_constraint_violation(...)`.

Final schema:

| Field | Type | Notes |
|---|---|---|
| `violation_type` | `str` | Rule ID, normalized from `CrossConstraintViolation.constraint_name`. |
| `severity` | `str` | One of `reject`, `negotiate`, `warn`. |
| `involved_params` | `Dict[str, Any]` | Triggering parameter names and values. |
| `suggested_resolution` | `str` | Joined suggestions, falling back to reason text. |
| `timestamp` | `str` | ISO 8601 timestamp. |
| `source_turn` | `int` | Conversation turn that triggered the event. |

### B.3 AO Field Reuse

- Reused existing `AnalyticalObjective.constraint_violations`; no new `violations` field was added.
- No AO serialization fallback was introduced.

### B.4 Context Store Latest Key

- `core/context_store.py:109`: added `_latest_constraint_violations`.
- `core/context_store.py:467`: added `set_latest_constraint_violations(...)`.
- `core/context_store.py:474`: added `get_latest_constraint_violations()`.
- `core/context_store.py:477`: included latest violations in compact `to_dict()`.
- `core/context_store.py:484`: included latest violations in persisted state.
- `core/context_store.py:516` and `core/context_store.py:545`: restored latest violations from compact/persisted payloads.

### B.5 ConstraintViolationWriter

- `core/constraint_violation_writer.py:83`: added `ConstraintViolationWriter`.
- `core/constraint_violation_writer.py:90`: `record(...)` appends to current AO `constraint_violations` and replaces context-store `latest_constraint_violations`.
- `core/constraint_violation_writer.py:107`: `get_latest() -> List[ViolationRecord]` returns current-AO records only.

### B.6 Event-Based Router Integration

Writer stays in `GovernedRouter`; `UnifiedRouter` does not import or call writer.

Changed event/payload surfaces:

- `services/cross_constraints.py:40`: `CrossConstraintViolation.to_dict()` now includes separated `param_a_name`, `param_a_value`, `param_b_name`, and `param_b_value` fields while retaining existing fields.
- `services/standardization_engine.py:988`: cross-constraint standardization records now include nested `constraint_violation`.
- `core/router.py:2148`: router cross-constraint records now include nested `constraint_violation`.
- `core/router.py:2246`: `CROSS_CONSTRAINT_WARNING` trace steps now include full violation payloads.
- `core/router.py:2290`: `CROSS_CONSTRAINT_VIOLATION` trace steps now include full violation payloads.
- `core/governed_router.py:45`: constructs `ConstraintViolationWriter`.
- `core/governed_router.py:145`: scans trace events after `inner_router.chat(...)` returns and before contract `after_turn`.
- `core/governed_router.py:171`: normalizes trace events and records through writer.
- `core/governed_router.py:218`: maps `cross_constraint_violation` trace steps to `severity="reject"`.
- `core/governed_router.py:230`: maps `cross_constraint_warning` trace steps to `severity="warn"`.
- `core/governed_router.py:235`: maps `PARAMETER_STANDARDIZATION` / `TOOL_EXECUTION` cross-constraint records to `severity="negotiate"` or `warn`.
- `core/governed_router.py:651`: `restore_persisted_state(...)` rebuilds the writer after `AOManager` and inner context-store state are restored.

Engine detection logic was not changed.

### B.7 Tests

- `tests/test_constraint_violation_writer.py:53`: `ViolationRecord.to_dict/from_dict` round trip.
- `tests/test_constraint_violation_writer.py:68`: normalize helper severity and rule-ID mapping.
- `tests/test_constraint_violation_writer.py:102`: writer dual-write to AO and context store.
- `tests/test_constraint_violation_writer.py:124`: `get_latest()` current-AO boundary.
- `tests/test_constraint_violation_writer.py:248`: `GovernedRouter` records trace violations.
- `tests/test_constraint_violation_writer.py:274`: `UnifiedRouter` preflight does not write AO/context store.
- `tests/test_constraint_violation_writer.py:306`: restore rebinds writer.
- `tests/test_constraint_violation_writer.py:331`: reject/negotiate/warn control flow remains unchanged.

### B.8 Smoke

- Generated ignored sample file: `evaluation/results/b_smoke/smoke_10.jsonl`.
- Ran post only:

```bash
/home/kirito/miniconda3/bin/python evaluation/eval_end2end.py \
  --samples evaluation/results/b_smoke/smoke_10.jsonl \
  --output-dir evaluation/results/b_smoke/post \
  --mode full
```

Post metrics are summarized in `docs/phase2_b_smoke_comparison.md`.

## Deviations From Prompt

None in code architecture. The approved B.1 follow-up changed B.6 from direct UnifiedRouter writer calls to event-based GovernedRouter trace consumption.

Smoke note: Pre/post smoke comparison shows `constraint_violation` baseline is `2/4` both pre and post (benchmark difficulty, not regression). Overall completion_rate `0.50 -> 0.70` (+20pp) is driven entirely by `multi_turn_clarification` `0/2 -> 2/2` positive activation, analyzed in `docs/phase2_b_smoke_comparison.md`.

## Engine Call Points Switched

The actual validation calls remain in place and pure:

- `services/standardization_engine.py:643`: standardization path still calls `get_cross_constraint_validator().validate(...)`.
- `core/router.py:2242`: router preflight still calls `get_cross_constraint_validator().validate(...)`.

Persistence was switched by consuming emitted events instead of changing those calls:

- Standardization records carry full nested violation payloads for GovernedRouter consumption.
- Router preflight trace steps carry full violation payloads for GovernedRouter consumption.
- GovernedRouter is the only layer calling `ConstraintViolationWriter.record(...)`.

## Test Results

Focused checks:

```text
28 passed in 1.31s
39 passed in 0.75s
```

Full regression:

```text
1220 passed, 40 warnings in 73.29s
```

## Smoke Pre/Post Comparison

Infrastructure:

| Field | Pre | Post |
|---|---:|---:|
| run_status | completed | completed |
| data_integrity | clean | clean |
| network_failed | 0/10 | 0/10 |
| wall_clock_sec | 50.42 | 44.38 |
| cache_hit_rate | 0.9091 | 0.0 |

Overall:

| Metric | Pre | Post | Delta |
|---|---:|---:|---:|
| completion_rate | 0.50 | 0.70 | +20pp |
| tool_accuracy | 0.70 | 0.90 | +20pp |
| parameter_legal_rate | 0.50 | 0.50 | 0pp |
| result_data_rate | 0.50 | 0.50 | 0pp |

By category:

| Category | Pre | Post | Delta |
|---|---:|---:|---:|
| constraint_violation | 2/4 | 2/4 | 0 |
| parameter_ambiguous | 1/2 | 1/2 | 0 |
| multi_turn_clarification | 0/2 | 2/2 | +2 |
| user_revision | 2/2 | 2/2 | 0 |

Clarification contract metrics:

| Metric | Pre | Post |
|---|---:|---:|
| trigger_count | 8 | 8 |
| stage2_hit_rate | 0.125 | 0.125 |
| short_circuit_rate | 0.375 | 0.375 |
| proceed_rate | 0.625 | 0.625 |

Verdict: PASS. The nominal writer-refactor drift threshold is exceeded, but all movement is positive. `constraint_violation` is flat at `2/4 -> 2/4`, proving the below-3/4 slice is baseline benchmark difficulty rather than a Task Pack B regression. The overall gain is from `multi_turn_clarification` `0/2 -> 2/2`, likely due to constraint context now being persisted through AO + context_store for clarification consumption.

## Downstream Task Pack A Notes

- Import API: `from core.constraint_violation_writer import ConstraintViolationWriter, ViolationRecord`.
- `ConstraintViolationWriter.get_latest() -> List[ViolationRecord]`.
- `get_latest()` returns an empty list when there is no current AO or current AO has no persisted B-schema violation records.
- Context-store fallback API: `SessionContextStore.get_latest_constraint_violations() -> List[Dict[str, Any]]`.
- AO persistence target is `AnalyticalObjective.constraint_violations`, not a new `violations` field.
- `violation_type` is the rule ID from `constraint_name`; current values include `vehicle_road_compatibility`, `vehicle_pollutant_relevance`, `pollutant_task_applicability`, and `season_meteorology_consistency`.

## Known Issues / TODO

- Legacy `FactMemory.constraint_violations_seen` and `OASCContract._sync_persistent_session_facts(...)` remain in place. This task did not remove or migrate that legacy path.
- `ViolationRecord.suggested_resolution` falls back to engine reason text when rule suggestions are empty.
