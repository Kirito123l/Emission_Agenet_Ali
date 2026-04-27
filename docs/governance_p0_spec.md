# P0 Task Specification

## 1. Task Summary

**TASK-1 Runtime-Default Optionals Must Not Block Fresh Factor Execution**

Legacy `ClarificationContract` should not treat runtime-defaultable optional
slots as first-turn blockers when the user did not explicitly ask to confirm
parameters. For fresh `query_emission_factors` turns where required slots are
filled and only `model_year` is missing, proceed to snapshot direct execution
and let the governed router inject runtime `model_year=2020`.

## 2. Pre-conditions

- Current branch: same branch that contains `docs/phase2_governance_audit.md`.
- Python: `/home/kirito/miniconda3/bin/python`.
- Provider/env: current `.env` state using Qwen3-Max; do not print or edit
  secrets.
- Working tree: may already be dirty. Inspect `git status --short` before
  editing and do not revert unrelated changes.
- This spec assumes no changes from this documentation round have been applied
  to `.py`, `.env`, or config files.

## 3. Implementation Steps

### Step 1: Import Runtime-Default Awareness

- File: `core/contracts/clarification_contract.py:13-23`
- Current code:

```python
from config import get_config
from core.analytical_objective import IntentConfidence
from core.ao_classifier import AOClassType
from core.contracts.base import BaseContract, ContractContext, ContractInterception
from core.intent_resolver import IntentResolver
from core.router import RouterResponse
from core.stance_resolver import StanceResolution, StanceResolver
from services.llm_client import get_llm_client
from services.standardization_engine import StandardizationEngine
from tools.file_analyzer import FileAnalyzerTool
from tools.contract_loader import get_tool_contract_registry
```

- Proposed change:

```python
from config import get_config
from core.analytical_objective import IntentConfidence
from core.ao_classifier import AOClassType
from core.contracts.base import BaseContract, ContractContext, ContractInterception
from core.contracts.runtime_defaults import has_runtime_default
from core.intent_resolver import IntentResolver
from core.router import RouterResponse
from core.stance_resolver import StanceResolution, StanceResolver
from services.llm_client import get_llm_client
from services.standardization_engine import StandardizationEngine
from tools.file_analyzer import FileAnalyzerTool
from tools.contract_loader import get_tool_contract_registry
```

- Rationale: The split readiness contract already uses
  `has_runtime_default(...)`; legacy clarification should use the same source
  of truth.

### Step 2: Compute Whether Runtime Defaults May Suppress Optional Probes

- File: `core/contracts/clarification_contract.py:325-338`
- Current code:

```python
snapshot, normalizations, rejected_slots = self._run_stage3(
    tool_name=tool_name,
    snapshot=snapshot,
    tool_spec=tool_spec,
    suppress_defaults_for=active_required_slots if (confirm_first_detected or is_resume) else [],
)
telemetry.stage3_normalizations = normalizations
telemetry.stage3_rejected_slots = list(rejected_slots)

missing_required = self._missing_slots(snapshot, active_required_slots)
unfilled_optionals_without_default = self._get_unfilled_optionals_without_default(
    snapshot,
    tool_spec,
)
```

- Proposed change:

```python
snapshot, normalizations, rejected_slots = self._run_stage3(
    tool_name=tool_name,
    snapshot=snapshot,
    tool_spec=tool_spec,
    suppress_defaults_for=active_required_slots if (confirm_first_detected or is_resume) else [],
)
telemetry.stage3_normalizations = normalizations
telemetry.stage3_rejected_slots = list(rejected_slots)

missing_required = self._missing_slots(snapshot, active_required_slots)
skip_runtime_default_optionals = bool(
    getattr(self.runtime_config, "enable_runtime_default_aware_readiness", True)
    and not confirm_first_detected
    and not is_resume
)
unfilled_optionals_without_default = self._get_unfilled_optionals_without_default(
    snapshot,
    tool_spec,
    tool_name=tool_name,
    skip_runtime_default_slots=skip_runtime_default_optionals,
)
```

- Rationale: The change is intentionally narrow. It only affects fresh turns
  where the user did not ask to confirm parameters and no pending collection is
  being resumed.

### Step 3: Exclude Runtime-Defaultable Slots From Fresh Optional Probe Set

- File: `core/contracts/clarification_contract.py:1271-1288`
- Current code:

```python
@staticmethod
def _get_unfilled_optionals_without_default(
    snapshot: Dict[str, Dict[str, Any]],
    tool_spec: Dict[str, Any],
) -> List[str]:
    optional_slots = [str(item) for item in list(tool_spec.get("optional_slots") or []) if str(item).strip()]
    default_slots = {
        str(key)
        for key in dict(tool_spec.get("defaults") or {}).keys()
        if str(key).strip()
    }
    no_default_slots = [slot_name for slot_name in optional_slots if slot_name not in default_slots]
    unfilled: List[str] = []
    for slot_name in no_default_slots:
        slot_payload = snapshot.get(slot_name) or {}
        if not isinstance(slot_payload, dict) or slot_payload.get("value") is None:
            unfilled.append(slot_name)
    return unfilled
```

- Proposed change:

```python
@staticmethod
def _get_unfilled_optionals_without_default(
    snapshot: Dict[str, Dict[str, Any]],
    tool_spec: Dict[str, Any],
    *,
    tool_name: Optional[str] = None,
    skip_runtime_default_slots: bool = False,
) -> List[str]:
    optional_slots = [str(item) for item in list(tool_spec.get("optional_slots") or []) if str(item).strip()]
    default_slots = {
        str(key)
        for key in dict(tool_spec.get("defaults") or {}).keys()
        if str(key).strip()
    }
    unfilled: List[str] = []
    for slot_name in optional_slots:
        if slot_name in default_slots:
            continue
        if skip_runtime_default_slots and tool_name and has_runtime_default(tool_name, slot_name):
            continue
        slot_payload = snapshot.get(slot_name) or {}
        if not isinstance(slot_payload, dict) or slot_payload.get("value") is None:
            unfilled.append(slot_name)
    return unfilled
```

- Rationale: This preserves existing behavior for ordinary no-default optional
  slots while reclassifying runtime-defaultable slots as executable on fresh
  turns.

### Step 4: Update Legacy Clarification Tests

- File: `tests/test_clarification_contract.py:519-558`
- Current expected behavior:

```python
assert interception.proceed is False
assert telemetry["collection_mode"] is True
assert telemetry["probe_optional_slot"] == "model_year"
assert ao.parameter_state.collection_mode is True
assert ao.parameter_state.awaiting_slot == "model_year"
```

- Proposed behavior for explicit confirm-first text:

```python
assert interception.proceed is False
assert telemetry["collection_mode"] is True
assert telemetry["probe_optional_slot"] == "model_year"
assert ao.parameter_state.collection_mode is True
assert ao.parameter_state.awaiting_slot == "model_year"
```

- Rationale: Keep this test as the regression guard for user-requested
  confirmation. It should still pass because the input contains "先帮我确认参数".

### Step 5: Change Fresh Directive Optional-Probe Expectation

- File: `tests/test_clarification_contract.py:675-713`
- Current expected behavior:

```python
assert interception.proceed is False
assert ao.parameter_state.collection_mode is True
assert telemetry["pcm_trigger_reason"] == "unfilled_optional_no_default_at_first_turn"
assert telemetry["probe_optional_slot"] == "model_year"
```

- Proposed behavior:

```python
assert interception.proceed is True
assert telemetry["final_decision"] == "proceed"
assert telemetry["pcm_trigger_reason"] is None
assert telemetry["probe_optional_slot"] is None
assert ao.parameter_state.collection_mode is False
```

- Rationale: This is the direct unit-test expression of L3 remediation.

### Step 6: Add a Direct Runtime Default Argument Check

- File: `tests/test_clarification_contract.py`, near existing snapshot/default
  tests around `:890-927`
- Proposed addition:

```python
def test_runtime_default_model_year_applies_after_fresh_optional_probe_suppression():
    snapshot = {
        "vehicle_type": {"value": "Passenger Car", "source": "user"},
        "pollutants": {"value": ["NOx"], "source": "user"},
        "model_year": {"value": None, "source": "missing"},
    }

    args = GovernedRouter._snapshot_to_tool_args(
        "query_emission_factors",
        snapshot,
        allow_factor_year_default=True,
    )

    assert args["model_year"] == 2020
```

- Rationale: This protects the intended handoff: clarification proceeds, then
  governed router fills the runtime default.

## 4. Test Updates Required

- Update `test_pcm_triggers_on_first_turn_required_met_but_no_default_optional_empty`
  to expect proceed on fresh non-confirm-first factor queries.
- Keep or rename `test_pcm_probes_unfilled_optionals_without_default` as the
  confirm-first guard.
- Review `test_llm_intent_hint_resolves_tool_when_fast_path_misses`; if the
  test input is fresh and non-confirm-first with only missing `model_year`, it
  should also expect proceed.
- No split-readiness tests should need behavior changes; split already has
  runtime-default-aware tests in `tests/test_contract_split.py`.

## 5. Verification Plan

### 5.1 Unit tests

```bash
/home/kirito/miniconda3/bin/python -m pytest tests/test_clarification_contract.py tests/test_contract_split.py -q
/home/kirito/miniconda3/bin/python -m pytest tests/test_ao_classifier.py tests/test_governed_router_reply_integration.py -q
```

Run the full suite if the targeted tests pass:

```bash
/home/kirito/miniconda3/bin/python -m pytest -q
```

### 5.2 Smoke comparison

Suggested pre-change baseline, if no fresh baseline exists:

```bash
/home/kirito/miniconda3/bin/python evaluation/run_oasc_matrix.py \
  --groups E \
  --samples evaluation/benchmarks/end2end_tasks.jsonl \
  --smoke \
  --parallel 4 \
  --qps-limit 10 \
  --cache \
  --output-prefix governance_p0_pre
```

Suggested post-change smoke:

```bash
/home/kirito/miniconda3/bin/python evaluation/run_oasc_matrix.py \
  --groups E \
  --samples evaluation/benchmarks/end2end_tasks.jsonl \
  --smoke \
  --parallel 4 \
  --qps-limit 10 \
  --cache \
  --output-prefix governance_p0_post
```

If task-level filtering is available in the local runner, additionally run a
targeted smoke for `e2e_codeswitch_161`, `e2e_colloquial_141`,
`e2e_ambiguous_001`, and `e2e_clarification_101`. If no task-id filter exists,
use category filters for `code_switch_typo`, `ambiguous_colloquial`,
`parameter_ambiguous`, and `multi_turn_clarification`.

### 5.3 Success criteria

- `e2e_codeswitch_161` should move from clarify/no tool to executed
  `query_emission_factors` with `model_year=2020`.
- Fresh single-turn factor tasks with all required slots filled should not end
  with `pcm_trigger_reason=unfilled_optional_no_default_at_first_turn`.
- Baseline improvement of +5 pp or more counts as effective for P0.
- Confirm-first tasks should not regress: inputs that explicitly ask to
  confirm parameters may still ask for `model_year`.
- No regression in constraint_violation tasks; domain-hard blockers must
  remain authoritative.

## 6. Rollback Plan

Do not use `git revert` as the first rollback mechanism for this uncommitted
implementation. Roll back by applying the inverse of the small patch:

1. Remove `from core.contracts.runtime_defaults import has_runtime_default`.
2. Restore the call at `core/contracts/clarification_contract.py:335-338` to:

```python
unfilled_optionals_without_default = self._get_unfilled_optionals_without_default(
    snapshot,
    tool_spec,
)
```

3. Restore `_get_unfilled_optionals_without_default(...)` to the original
   two-argument static method that filters only declarative defaults.
4. Revert the changed expectations in `tests/test_clarification_contract.py`
   to the previous probe assertions.
5. Re-run:

```bash
/home/kirito/miniconda3/bin/python -m pytest tests/test_clarification_contract.py -q
```

If rollback is needed after smoke regression, keep the failed post-smoke output
directory for comparison and document which task regressed before removing the
patch.

## 7. Open Questions

- Whether `enable_runtime_default_aware_readiness` should formally apply to
  legacy `ClarificationContract` is needs human review, but reusing the flag is
  the least invasive path.
- Whether explicit confirm-first should still ask for `model_year` when a
  runtime default exists is needs human review. This spec preserves the current
  confirm-first behavior to minimize risk.
- Whether `config/tool_contracts.yaml` and `config/unified_mappings.yaml`
  should be reconciled on `model_year` required/optional status is outside P0
  and needs human review.

