# Phase 2 Task Pack B Constraint Violation Writer Analysis

## Scope

Task Pack B introduces a single router-layer persistence entry point for cross-constraint violations while keeping the constraint validator pure. This document is the B.1 read-only analysis and does not change engine, AO, or context-store behavior.

Current branch at analysis time: `task-pack-b-constraint-writer`.

## Naming Drift From Prompt

The prompt refers to `core/cross_constraint_engine.py`, `CrossConstraintEngine`, and `detect_violations`. Current `main` does not contain those production symbols. The active implementation is:

- `services/cross_constraints.py::CrossConstraintValidator.validate(...)`
- singleton accessor: `services/cross_constraints.py::get_cross_constraint_validator()`
- result types: `CrossConstraintResult` and `CrossConstraintViolation`

The only `CrossConstraintEngine` match is a test class name in `tests/test_cross_constraints.py`.

## Existing Engine Call Points

Command used:

```bash
rg -n "cross_constraint_engine|CrossConstraintEngine|detect_violations" --glob "*.py" .
rg -n "get_cross_constraint_validator\(\)\.validate|CrossConstraintValidator\(|CrossConstraintViolation|CrossConstraintResult|_last_constraint_result|get_last_constraint_trace|cross_constraint_validation" --glob "*.py" .
```

### Production Calls

| Location | Caller | Current Handling |
|---|---|---|
| `services/standardization_engine.py:643-666` | `StandardizationEngine.standardize_batch(...)` | Calls validator after individual standardization. Warnings are appended to `records`; blocking violations append one `cross_constraint_violation` record and raise `BatchStandardizationError(negotiation_eligible=True, trigger_reason="cross_constraint_violation:<constraint_name>")`. No AO write. No context-store write. |
| `core/router.py:2241-2295` | `UnifiedRouter._evaluate_cross_constraint_preflight(...)` | Calls validator during router pre-execution preflight after local standardization of selected params. Warnings are trace-only (`CROSS_CONSTRAINT_WARNING`). Blocking violations set `state.execution.blocked_info`, set `_final_response_text`, transition task to `DONE`, and write trace (`CROSS_CONSTRAINT_VIOLATION`). No AO write. No context-store write. |

### Indirect Production Consumers

| Location | Consumer | Current Handling |
|---|---|---|
| `core/executor.py:230,247,285,301,317` | `ToolExecutor.execute(...)` | Copies `StandardizationEngine.get_last_constraint_trace()` into `_trace["cross_constraint_validation"]` for success and error results. This is trace telemetry only, not persistent AO/context state. |
| `core/contracts/oasc_contract.py:353-379` | `OASCContract._sync_persistent_session_facts(...)` | Copies legacy `FactMemory.constraint_violations_seen` entries into `current_ao.constraint_violations` and `FactMemory.cumulative_constraint_violations`. The current production grep did not find router/engine code appending to `constraint_violations_seen`; existing writes appear test-only. |

### Tests And Fixtures

| Location | Purpose |
|---|---|
| `tests/test_cross_constraints.py:11-109` | Direct validator tests for valid, blocked, warning, missing-param cases. |
| `tests/test_cross_constraints.py:111-192` | Standardization integration tests for cross-constraint errors/warnings and disable flag. |
| `tests/test_state_contract.py` | Tests legacy `FactMemory.constraint_violations_seen` and `cumulative_constraint_violations` formatting/limits. |

## Current Violation Schema

### Engine Return Objects

`services/cross_constraints.py:26-49`:

```python
@dataclass
class CrossConstraintViolation:
    constraint_name: str
    description: str
    param_a_name: str
    param_a_value: str
    param_b_name: str
    param_b_value: Any
    violation_type: str
    reason: str
    suggestions: List[str] = field(default_factory=list)
```

`to_dict()` currently emits:

- `constraint_name`
- `description`
- `param_a` as `"name=value"`
- `param_b` as `"name=value"`
- `violation_type`
- `reason`
- `suggestions`

`services/cross_constraints.py:52-65`:

```python
@dataclass
class CrossConstraintResult:
    all_valid: bool
    violations: List[CrossConstraintViolation]
    warnings: List[CrossConstraintViolation]
```

### Configured Rule Types

`config/cross_constraints.yaml` currently defines:

- `vehicle_road_compatibility`: `blocked_combinations`, current violation type defaults to `blocked`.
- `vehicle_pollutant_relevance`: `conditional_warning`, explicit `violation_type: warning`.
- `pollutant_task_applicability`: `conditional_warning`, explicit `violation_type: warning`.
- `season_meteorology_consistency`: `consistency_warning`, current violation type defaults to `inconsistent`.

### Gap To Task Pack B Schema

Task Pack B requires a new persistent schema:

- `violation_type`: rule ID, for example `motorcycle_highway`.
- `severity`: `reject` / `negotiate` / `warn`.
- `involved_params`: dict of triggering parameters and values.
- `suggested_resolution`: string or empty string.
- `timestamp`: ISO 8601 string.
- `source_turn`: int.

Current engine uses `constraint_name` as the rule ID and uses `violation_type` for broad engine category (`blocked`, `warning`, `inconsistent`). The writer should normalize engine objects into the B schema without changing `services/cross_constraints.py` detection logic.

Proposed normalization:

- `violation_type = violation.constraint_name`.
- `involved_params = {violation.param_a_name: violation.param_a_value, violation.param_b_name: violation.param_b_value}`.
- `suggested_resolution = "; ".join(violation.suggestions)` if suggestions exist, otherwise `violation.reason` or empty string.
- `severity = "warn"` for `constraint_result.warnings`.
- `severity = "negotiate"` for `StandardizationEngine.standardize_batch` violations that currently raise `BatchStandardizationError(negotiation_eligible=True)`.
- `severity = "reject"` for router preflight violations that currently block execution in `_evaluate_cross_constraint_preflight`.

This preserves current control-flow differences: the same underlying rule can be negotiated in the executor-standardization path and rejected in router preflight because those paths already behave differently today.

## AO And Context Store Persistence State

### AO

`core/analytical_objective.py:199-325` currently has:

- `constraint_violations: List[Dict[str, Any]] = field(default_factory=list)` at line 214.
- `to_dict()` persists `constraint_violations` at line 244.
- `from_dict()` restores `constraint_violations` at lines 316-320.

There is no exact AO field named `violations`.

Implication for B.3:

- Option A: reuse existing `AnalyticalObjective.constraint_violations` as the AO violation list. This minimizes schema churn and preserves current OASC/assembler expectations.
- Option B: add a new exact `violations` field as the prompt wording says. This creates two AO-level violation lists unless the old `constraint_violations` field is migrated or deprecated.

Recommendation for B.2-B.7, pending user confirmation: reuse `constraint_violations` as the current AO's violation target and store B-schema dicts there. This gives Task Pack A a stable writer API (`ConstraintViolationWriter.get_latest()`) while avoiding a duplicate AO schema field.

### Legacy Fact Memory

`core/memory.py` currently has legacy/session-level fields:

- `constraint_violations_seen: List[Dict[str, Any]]` at line 84.
- `cumulative_constraint_violations: List[Dict[str, Any]]` at line 89.
- `append_constraint_violation(...)` at lines 195-212.
- `append_cumulative_constraint_violation(...)` at lines 262-282.

These store compact records:

```python
{
    "turn": int,
    "constraint": str,
    "values": dict,
    "blocked": bool,
}
```

Production grep found no current router/engine caller of `append_constraint_violation(...)`; tests call it directly. `OASCContract._sync_persistent_session_facts(...)` still reads these legacy entries and copies them into `current_ao.constraint_violations`.

### Context Store

`core/context_store.py` currently has:

- result storage (`_store`, `_history`, current-turn results)
- serialization via `to_persisted_dict()` / `from_persisted_dict()`
- no `latest_constraint_violations` key or dedicated getter/setter.

Implication for B.4:

- Add a small dedicated storage slot and read/write interface, for example:
  - `set_latest_constraint_violations(records: List[Dict[str, Any]]) -> None`
  - `get_latest_constraint_violations() -> List[Dict[str, Any]]`
- Include it in `to_dict()`, `to_persisted_dict()`, `from_dict()`, and `from_persisted_dict()` so session resume keeps the latest writer state.

## Current Control Flow

### Reject / Block

Current reject-like path is router preflight:

- `core/router.py:2165-2295` (`_evaluate_cross_constraint_preflight`)
- `core/router.py:10782-10788` calls this before readiness/tool execution and returns immediately if it blocks.

Behavior:

- sets `state.execution.blocked_info`
- sets `state.execution.last_error`
- sets `_final_response_text`
- transitions state to `DONE`
- records `TraceStepType.CROSS_CONSTRAINT_VIOLATION`
- returns `True` to stop execution

This control flow must remain unchanged.

### Negotiate / Clarify

Current negotiate-like path is executor standardization:

- `services/standardization_engine.py:643-666` raises `BatchStandardizationError(..., negotiation_eligible=True, trigger_reason="cross_constraint_violation:<constraint_name>")`.
- `core/executor.py:349-359` converts it to `StandardizationError` while preserving `negotiation_eligible` and `trigger_reason`.
- `core/executor.py:231-251` returns an error result containing `negotiation_eligible`, `trigger_reason`, `_standardization_records`, and `_trace.cross_constraint_validation`.
- `core/router.py:5937-5995` can build `ParameterNegotiationRequest` from error results when `negotiation_eligible` is true.
- `core/router.py:11639-11681` older tool-call path lets the LLM handle tool errors/retry.

The writer should record the normalized violation before this error is returned upward, but must not change negotiation eligibility or retry/clarification behavior.

### Warn / Proceed

Current warn path:

- `services/standardization_engine.py:649` appends warning records and proceeds.
- `services/standardization_engine.py:979-985` builds warning records.
- `core/router.py:2245-2256` records router-preflight warnings to trace only and proceeds.

The writer should record warnings as `severity="warn"` and must not block execution.

## Proposed Writer API

File: `core/constraint_violation_writer.py`

```python
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

@dataclass
class ViolationRecord:
    violation_type: str
    severity: str
    involved_params: Dict[str, Any]
    suggested_resolution: str
    timestamp: str
    source_turn: int

    def to_dict(self) -> Dict[str, Any]: ...

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ViolationRecord": ...

class ConstraintViolationWriter:
    def __init__(self, ao_manager: AOManager, context_store: SessionContextStore):
        ...

    def record(self, violation: ViolationRecord) -> None:
        """Append to current AO and replace context_store.latest_constraint_violations."""
        ...

    def get_latest(self) -> List[ViolationRecord]:
        """Return violations for the current AO only."""
        ...
```

Recommended helper surface for router integration:

```python
def normalize_cross_constraint_violation(
    violation: CrossConstraintViolation,
    *,
    severity: str,
    source_turn: int,
    timestamp: Optional[str] = None,
) -> ViolationRecord:
    ...
```

This keeps `services/cross_constraints.py` pure and avoids adding persistence behavior to `StandardizationEngine`.

## Proposed Integration Points For B.6

All persistence should go through `ConstraintViolationWriter.record(...)`.

| Location | Proposed Change | Control Flow |
|---|---|---|
| `core/router.py:_evaluate_cross_constraint_preflight(...)` | After `constraint_result` is returned, record all warnings with `severity="warn"` and all violations with `severity="reject"` before existing trace/block handling. | unchanged |
| `core/executor.py` or `core/router.py` around executor result handling | When executor returns a standardization error with `_trace.cross_constraint_validation`, record contained violations with `severity="negotiate"` and warnings with `severity="warn"` before existing retry/clarification handling. | unchanged |
| `services/standardization_engine.py` | Keep detection and error generation unchanged. Do not inject AO/context_store dependencies. | unchanged |
| `core/contracts/oasc_contract.py:_sync_persistent_session_facts(...)` | After writer is active, this legacy copy path should not be the primary writer path. It can remain for older `constraint_violations_seen` state unless tests show duplication. | unchanged unless dedupe is needed |

Implementation note: `UnifiedRouter` does not currently own an `AOManager`; `GovernedRouter` does (`core/governed_router.py:39`) and delegates to `inner_router`. To let preflight code in `UnifiedRouter` write to the current AO, B.6 likely needs one of these non-engine approaches:

- inject a `ConstraintViolationWriter` into `inner_router` from `GovernedRouter.__init__` / `restore_persisted_state`, or
- lazily construct a writer inside `UnifiedRouter` from `AOManager(self.memory.fact_memory)` and `self._ensure_context_store()`.

Injection from `GovernedRouter` is clearer for production `mode="full"` after F-main. Tests using `object.__new__(UnifiedRouter)` will need the writer access path to be optional/lazy.

## Risks To Verify In B.7

- AO field naming mismatch: current field is `constraint_violations`, not exact `violations`.
- Potential duplicate persistence if OASC legacy sync copies `constraint_violations_seen` into the same AO after the writer records new B-schema records.
- Executor-standardization violations can be recorded from trace/error payloads rather than from live `CrossConstraintViolation` objects; conversion must handle both object and dict forms.
- Warning persistence should not change behavior: warnings currently proceed in both standardization and router-preflight paths.
- Router white-box tests instantiate `UnifiedRouter` without `__init__`; writer lookup must not assume initialized attributes beyond existing lazy helpers.

## B.1 Conclusion

The engine is currently pure with respect to AO/context-store persistence. The two active validation paths already centralize detection through `get_cross_constraint_validator().validate(...)`, but persistence is inconsistent or absent:

- router preflight blocks and traces, but does not persist;
- standardization records warnings/errors in execution traces, but does not persist to AO/context-store;
- OASC has a legacy sync path from `FactMemory.constraint_violations_seen`, but no current production caller writes that list.

Task Pack B can proceed by adding `ConstraintViolationWriter` in `core/`, normalizing current `CrossConstraintViolation` outputs into the B schema, and routing both preflight and executor-standardization violation records through the writer before preserving existing reject/negotiate/warn control flow.

## Architecture Decision: Event-Based Via TraceStep

Approved implementation path for B.2-B.8 is option 3a: `UnifiedRouter` remains an execution kernel and does not know about `ConstraintViolationWriter`, AO persistence, or governance-layer state. Constraint validation paths emit complete violation evidence into trace payloads, and `GovernedRouter` consumes those trace events after `inner_router.chat(...)` returns.

Rationale:

- The Phase 2 production path is now `GovernedRouter` after F-main, so governance persistence belongs in the governance wrapper rather than in `UnifiedRouter`.
- `UnifiedRouter._evaluate_cross_constraint_preflight(...)` already records `CROSS_CONSTRAINT_VIOLATION` / `CROSS_CONSTRAINT_WARNING` trace steps. Extending those trace records with full violation payloads gives the governance layer a stable event stream without introducing writer imports into the execution kernel.
- Executor-standardization already exposes `cross_constraint_validation` in tool-result traces. `GovernedRouter` can scan these trace payloads and record negotiate/warn events without changing executor control flow.
- Keeping `UnifiedRouter` writer-free preserves existing white-box fixtures that instantiate `UnifiedRouter` without `__init__` and supports the paper narrative that governance is a wrapper layer over an execution core.

Implementation implications:

- `core/constraint_violation_writer.py` defines the persistent `ViolationRecord`, a pure `normalize_cross_constraint_violation(...)` helper, and `ConstraintViolationWriter`.
- `core/router.py` may enrich trace payloads with full cross-constraint violation dicts, but it must not import or call the writer.
- `core/governed_router.py` owns `ConstraintViolationWriter(self.ao_manager, self.inner_router._ensure_context_store())`, scans the current turn's trace after inner execution, normalizes events, and calls `writer.record(...)`.
- `restore_persisted_state(...)` must recreate the writer after rebuilding `AOManager` and restoring the inner router context store.
- AO persistence reuses `AnalyticalObjective.constraint_violations`; no separate `violations` field is added.
- Legacy `FactMemory.constraint_violations_seen` and OASC sync remain unchanged in this task.
