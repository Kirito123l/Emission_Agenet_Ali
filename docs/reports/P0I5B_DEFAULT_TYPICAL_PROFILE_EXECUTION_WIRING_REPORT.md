# P0-I5b: Wire `default_typical_profile` into `macro_emission` Execution

## 1. Summary

This implementation closes the execution-side loop for policy-based remediation. Previously, `apply_default_typical_profile` was recognized conversationally and recorded in state/trace, but was not materialized into actual numeric field values that `macro_emission` could consume.

**What was implemented:**
- Extended `_apply_input_completion_overrides_to_links()` in `MacroEmissionTool` to recognize and handle `mode == "default_typical_profile"`
- Added `_apply_default_typical_profile_to_link()` helper that calls `resolve_traffic_flow_vph()` and `resolve_avg_speed_kph()` from `core.remediation_policy`
- Each link is now processed row-by-row, with policy-driven values generated from available road attributes (highway, lanes, maxspeed)
- Comprehensive test suite (20 tests) covering materialization, execution success, field preservation, edge cases, and coexistence with other override modes

**Status:** ✅ All objectives met. The system now translates policy decisions into execution-ready numeric inputs.

---

## 2. Files Changed

### Modified Files

| File | Changes |
|------|---------|
| `tools/macro_emission.py` | Extended `_apply_input_completion_overrides_to_links()` to handle `mode == "default_typical_profile"` by calling new `_apply_default_typical_profile_to_link()` helper. Helper resolves numeric values per-row using `resolve_traffic_flow_vph()` and `resolve_avg_speed_kph()` from `core.remediation_policy`. |

### New Files

| File | Purpose |
|------|---------|
| `tests/test_macro_typical_profile_execution.py` | 20 comprehensive tests covering policy materialization, execution success, field preservation, insufficient-support cases, and coexistence with other override modes. All passing. |

---

## 3. Execution Wiring Design

### 3.1 The Execution Flow

When `macro_emission` tool executes:

1. **Input preparation** (line 676-679 in `macro_emission.py`):
   ```python
   links_data = self._apply_input_completion_overrides_to_links(
       links_data,
       completion_overrides,
   )
   ```

2. **Override application loop** (lines 576-591):
   - For each link in links_data
   - For each field in completion_overrides
   - Check override mode:
     - `uniform_scalar`: Apply fixed value
     - `source_column_derivation`: Copy from source column
     - `default_typical_profile`: Call `_apply_default_typical_profile_to_link()`

3. **Policy materialization** (new `_apply_default_typical_profile_to_link()`):
   ```python
   if field_name == "traffic_flow_vph":
       highway = link.get("highway")
       lanes = link.get("lanes")
       link[field_name] = resolve_traffic_flow_vph(highway=highway, lanes=lanes)
   elif field_name == "avg_speed_kph":
       maxspeed = link.get("maxspeed")
       highway = link.get("highway")
       link[field_name] = resolve_avg_speed_kph(maxspeed=maxspeed, highway=highway)
   ```

4. **Result**: Each link now has numeric `traffic_flow_vph` and/or `avg_speed_kph` values, ready for emission calculation.

### 3.2 Why This Is the Minimal Closure

- **No new state layer**: Reuses existing `input_completion_overrides` mechanism
- **No new trace types**: Uses existing `REMEDIATION_POLICY_APPLIED` trace
- **No router changes**: Policy decision already written to state by `_apply_remediation_policy_decision()`
- **Execution-side only**: All changes localized to `macro_emission.py`
- **Row-level resolution**: Each link independently resolves values from its own attributes, no global assumptions

---

## 4. Interaction with Existing Overrides

### 4.1 Override Mode Hierarchy

The `_apply_input_completion_overrides_to_links()` method now handles three modes:

1. **`uniform_scalar`**: Apply same value to all rows
   - Highest priority (checked first)
   - Overwrites any existing field value

2. **`source_column_derivation`**: Copy from another column
   - Second priority
   - Only applies if source column exists and target field missing

3. **`default_typical_profile`**: Generate per-row from road attributes
   - Third priority
   - Always applies (generates value even if field exists)
   - Uses bounded lookup tables

### 4.2 Field Preservation

The policy **does overwrite** existing fields when explicitly selected by user. This is correct behavior because:
- User explicitly chose "use default typical values"
- System should honor that choice
- If user wants to preserve existing values, they should not select the policy

Test case confirms this: `test_preserve_existing_traffic_flow()` shows policy overwrites existing field.

### 4.3 Coexistence

Different fields can use different override modes in the same execution:
```python
overrides = {
    "traffic_flow_vph": {
        "mode": "default_typical_profile",
        ...
    },
    "avg_speed_kph": {
        "mode": "source_column_derivation",
        "source_column": "speed_from_osm",
    }
}
```

Test `test_mixed_override_modes()` confirms this works correctly.

---

## 5. Trace

### 5.1 Trace Flow

The trace already captures policy lifecycle (from P0-I5):

```
INPUT_COMPLETION_REQUIRED
  ↓
REMEDIATION_POLICY_OPTION_OFFERED
  (policy_type: apply_default_typical_profile,
   target_fields: [traffic_flow_vph, avg_speed_kph],
   context_signals_present: [highway, lanes, maxspeed])
  ↓
INPUT_COMPLETION_CONFIRMED
  (user_reply: "用默认典型值模拟吧")
  ↓
REMEDIATION_POLICY_CONFIRMED
  (policy_type: apply_default_typical_profile)
  ↓
REMEDIATION_POLICY_APPLIED
  (field_overrides: [{field: traffic_flow_vph, mode: default_typical_profile, ...},
                     {field: avg_speed_kph, mode: default_typical_profile, ...}])
  ↓
INPUT_COMPLETION_APPLIED
  (overrides written to state)
  ↓
TOOL_EXECUTION (macro_emission)
  (links_data with materialized numeric values)
```

### 5.2 Materialization Auditability

When `macro_emission` executes with policy-filled fields:
- Each link's `traffic_flow_vph` and `avg_speed_kph` are generated from road attributes
- The override payload contains `lookup_basis` (e.g., "highway, lanes") for traceability
- Execution logs show which fields were filled by policy

---

## 6. Tests

### 6.1 Test Coverage

**File**: `tests/test_macro_typical_profile_execution.py` (20 tests, all passing)

#### A. Policy Materialization (4 tests)
- ✅ `traffic_flow_vph` from highway + lanes → 1600 vph (motorway, 2 lanes)
- ✅ `avg_speed_kph` from maxspeed → 85 kph (100 * 0.85)
- ✅ `avg_speed_kph` from highway → 30 kph (residential)
- ✅ Both fields materialized in single execution

#### B. Execution Path Success (2 tests)
- ✅ Links with policy-filled flow are valid for calculation
- ✅ Policy applies to all links in dataset (3 links, different highway classes)

#### C. Field Preservation (3 tests)
- ✅ Policy overwrites existing `traffic_flow_vph` (as intended)
- ✅ Policy overwrites existing `avg_speed_kph` (as intended)
- ✅ Mixed scenario: some links have field, others don't; policy applies to all

#### D. Insufficient Support (3 tests)
- ✅ Missing highway → uses fallback (300 vph)
- ✅ Missing maxspeed → uses highway default (60 kph for primary)
- ✅ All signals missing → uses global fallback (300 vph, 40 kph)

#### E. Other Override Modes (3 tests)
- ✅ `uniform_scalar` still works
- ✅ `source_column_derivation` still works
- ✅ Mixed modes on different fields work together

#### F. Edge Cases (5 tests)
- ✅ Empty links list
- ✅ No overrides
- ✅ Empty overrides dict
- ✅ Unknown override mode silently ignored
- ✅ Malformed override payload safely ignored

### 6.2 Test Results

```
============================== 20 passed in 1.46s ==============================
```

All tests pass. No failures or warnings.

### 6.3 Regression Testing

Existing tests still pass:
- `tests/test_remediation_policy.py`: 47 tests ✅
- Policy eligibility, parsing, application, trace types all verified

---

## 7. Known Limitations

### 7.1 Still a Bounded Default Profile

This is **not** a real traffic estimation model:
- Lookup tables are hardcoded, conservative defaults
- Based on HCM 6th edition and OSM highway wiki
- Deliberately under-estimates rather than over-estimates
- Suitable for rapid prototyping, not calibrated traffic analysis

### 7.2 No Scheduler or Persistence

- Policy decisions apply **within current task context only**
- No automatic replay across sessions
- No persistence of policy choices for future workflows

### 7.3 No LLM Fallback

- Policy eligibility and application are **deterministic only**
- If road attributes insufficient, system falls back to basic options (uniform scalar, upload, pause)
- No LLM inference for "should we apply this policy?"

### 7.4 Limited to macro_emission

- Policy currently only applicable to `macro_emission` task type
- Extending to other tools requires:
  1. Adding task type to `DEFAULT_PROFILE_ALLOWED_TASK_TYPES`
  2. Implementing similar override application in that tool's execution layer

---

## 8. Suggested Next Step

**Recommended**: Integrate policy-based remediation into **micro_emission** tool execution layer.

The micro_emission tool likely has similar missing-field scenarios (e.g., missing `avg_speed_kph` for individual vehicle segments). Applying the same pattern:

1. Extend `micro_emission` tool's input preparation to recognize `mode == "default_typical_profile"`
2. Call same `resolve_traffic_flow_vph()` and `resolve_avg_speed_kph()` helpers
3. Add micro_emission to `DEFAULT_PROFILE_ALLOWED_TASK_TYPES` in config
4. Test with similar coverage

This would complete the policy-based remediation story across both macro and micro emission workflows.

---

## 9. Implementation Notes

### 9.1 Why Not Modify Router?

The router already handles policy decision correctly in `_apply_remediation_policy_decision()`:
- Reconstructs policy from option requirements
- Calls `apply_default_typical_profile()` to get field overrides
- Writes overrides to `state.input_completion_overrides`
- Records trace

No router changes needed. Execution layer just consumes what router prepared.

### 9.2 Why Row-Level Resolution?

Each link resolves values independently from its own attributes:
- Motorway with 2 lanes → 1600 vph
- Residential with 1 lane → 120 vph
- Unknown highway → 300 vph fallback

This is more realistic than applying a single global value, and matches the policy's design intent.

### 9.3 Import Strategy

The `_apply_default_typical_profile_to_link()` method imports `resolve_traffic_flow_vph` and `resolve_avg_speed_kph` locally:
```python
from core.remediation_policy import resolve_traffic_flow_vph, resolve_avg_speed_kph
```

This avoids circular imports and keeps the dependency explicit at the point of use.

---

## 10. Conclusion

This implementation successfully closes the execution-side loop for policy-based remediation:

1. ✅ **Policy becomes execution-effective**: `apply_default_typical_profile` now materializes into numeric field values
2. ✅ **Row-level resolution**: Each link independently generates values from its road attributes
3. ✅ **Bounded and rule-first**: No LLM inference, deterministic lookup tables
4. ✅ **Traceable**: Override payload contains lookup basis for auditability
5. ✅ **Coexists with other modes**: `uniform_scalar` and `source_column_derivation` still work
6. ✅ **Comprehensive tests**: 20 tests cover materialization, success paths, edge cases, and coexistence
7. ✅ **Minimal changes**: Only `macro_emission.py` modified, no router/state/trace changes needed

The system now truly closes the loop: from user saying "use default typical values" → policy recognized → field overrides written → execution layer materializes numeric values → calculation succeeds.

