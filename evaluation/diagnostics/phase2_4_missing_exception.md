# Phase 2.4 Missing Exception Diagnosis

## Scope

Inputs:

- Gate 1 log: `evaluation/results/end2end_full_v5_oasc_E/end2end_logs.jsonl`
- Phase 2.3 log: `evaluation/results/phase2_pcm_clarification_E/end2end_logs.jsonl`
- Gate 1 summary: `PHASE2_4_GATE1_DIAGNOSIS.md`

Affected Gate 1 tasks:

`e2e_clarification_102`, `e2e_clarification_107`, `e2e_clarification_108`, `e2e_clarification_109`, `e2e_clarification_110`, `e2e_clarification_117`

No production, evaluator, or test code was modified.

## Task 1: Exception Root Cause

### Q1.1 Phase 2.3 vs Phase 2.4 Status

| task_id | Phase 2.3 status | Phase 2.4 status | 差异 |
|---|---|---|---|
| e2e_clarification_102 | `infra=ok`, no exception, failed by duplicate `query_emission_factors x3` | `infra=unknown`, `invalid literal for int() with base 10: 'missing'`, no tools | Phase 2.4 regression |
| e2e_clarification_107 | `infra=ok`, no exception, failed by duplicate `query_emission_factors x3` | same exception, no tools | Phase 2.4 regression |
| e2e_clarification_108 | `infra=ok`, no exception, failed by duplicate `query_emission_factors x4` | same exception, no tools | Phase 2.4 regression |
| e2e_clarification_109 | `infra=ok`, no exception, failed by duplicate `query_emission_factors x5` | same exception, no tools | Phase 2.4 regression |
| e2e_clarification_110 | `infra=ok`, success, `query_emission_factors x1` | same exception, no tools | Phase 2.4 regression |
| e2e_clarification_117 | `infra=ok`, no exception, failed by duplicate `query_emission_factors x3` | same exception, no tools | Phase 2.4 regression |

Conclusion: the exception is not pre-existing in the Phase 2.3 run. It appears after Phase 2.4 LLM-assisted intent/slot schema changes.

### Q1.2 Exception Layer

Gate 1 persisted log shape for all 6 tasks:

| task_id | last persisted trace step | eval_router_turn | tool_call before exception | retry_count |
|---|---|---:|---|---:|
| e2e_clarification_102 | none (`trace_step_types=[]`) | null | none (`tool_calls=[]`) | 0 |
| e2e_clarification_107 | none | null | none | 0 |
| e2e_clarification_108 | none | null | none | 0 |
| e2e_clarification_109 | none | null | none | 0 |
| e2e_clarification_110 | none | null | none | 0 |
| e2e_clarification_117 | none | null | none | 0 |

The log does not persist a Python traceback. The evaluator catches the exception in `_run_with_infrastructure_failsafe()` and stores only `str(exc)`:

- `evaluation/eval_end2end.py:303-309`
- `evaluation/eval_end2end.py:1398-1406`

Dry-run reproduction for `e2e_clarification_102` produced the traceback:

```text
File "core/governed_router.py", line 157, in _execute_from_snapshot
  arguments = self._snapshot_to_tool_args(...)
File "core/governed_router.py", line 321, in _snapshot_to_tool_args
  args["model_year"] = int(read("model_year"))
ValueError: invalid literal for int() with base 10: 'missing'
```

Code evidence:

- `core/governed_router.py:305-311` `read()` returns `payload.get("value")` unless source is `rejected`.
- `core/governed_router.py:320-321` converts non-`None` `model_year` to `int(...)`.

Therefore the exception is thrown in the snapshot-direct execution path before any tool execution. Because the exception happens before `after_turn()`, classifier/clarification telemetry is not written into the final eval record.

### Q1.3 Source of the `"missing"` String

Dry-run contract inspection for `e2e_clarification_102` turn 1 showed `ClarificationContract.before_turn()` returned `final_decision=proceed` with `direct_execution.parameter_snapshot` containing:

```json
{
  "model_year": {"value": "missing", "source": "missing", "confidence": 0.0, "raw_text": null},
  "season": {"value": "missing", "source": "missing", "confidence": 0.0, "raw_text": null},
  "road_type": {"value": "missing", "source": "missing", "confidence": 0.0, "raw_text": null}
}
```

Source chain:

1. Stage 2 prompt says user-unspecified `model_year` should remain missing and allows `source=missing`.
   - `core/contracts/clarification_contract.py:654`
   - `core/contracts/clarification_contract.py:663`
2. Stage 2 LLM returned string value `"missing"` instead of JSON `null`.
3. `_merge_stage2_snapshot()` copies `value` verbatim.
   - `core/contracts/clarification_contract.py:695-709`
4. `_run_stage3()` skips `source in {"missing", "default"}` without normalizing or nulling the value.
   - `core/contracts/clarification_contract.py:781-786`
5. `_missing_slots()` only treats `value in (None, "", [])` as missing; it does not treat `source="missing"` with `value="missing"` as missing.
   - `core/contracts/clarification_contract.py:855-867`
6. `_snapshot_to_tool_args()` accepts the value because only `source="rejected"` is filtered, then calls `int("missing")`.
   - `core/governed_router.py:305-321`

Relevant `"missing"` literal locations from grep:

| Location | Role |
|---|---|
| `core/contracts/clarification_contract.py:498` | empty snapshot creates `source="missing"` with `value=None` |
| `core/contracts/clarification_contract.py:654` | Stage 2 prompt says keep `model_year` missing |
| `core/contracts/clarification_contract.py:663` | Stage 2 prompt permits `source=missing` |
| `core/contracts/clarification_contract.py:706` | merge defaults absent source to `"missing"` |
| `core/contracts/clarification_contract.py:774-786` | Stage 3 skips `source=missing` |
| `core/contracts/clarification_contract.py:855-867` | missing-slot detector checks value emptiness, not `source=missing` |
| `core/contracts/clarification_contract.py:1188-1196` | context injection excludes `source=missing`, so this path is safe |
| `core/governed_router.py:305-321` | snapshot-direct reads `value` and converts `model_year` to int |
| `tools/emission_factors.py:131` | tool-level missing param marker, not the crashing path here |
| `evaluation/benchmarks/end2end_tasks.jsonl:45,52,63` | unrelated benchmark metadata in parameter_ambiguous tasks, not the six failing tasks |
| `tests/test_clarification_contract.py` multiple | test fixtures only |

The six benchmark task definitions do not contain `"missing"` in their `user_message`, `expected_params`, or `follow_up_messages`.

## Task 2: e2e_clarification_102 Phase 2.3 vs Phase 2.4

### Phase 2.3 run (`phase2_pcm_clarification_E`)

- `infrastructure_status`: `ok`
- `classifier_telemetry`: exists, 4 entries
- `clarification_telemetry`: exists, 2 entries
- `actual.tool_calls`:
  - `query_emission_factors({"vehicle_type": "公交车", "pollutants": ["CO2"], "model_year": 2020})`
  - `query_emission_factors({"vehicle_type": "Transit Bus", "pollutants": ["CO2"], "model_year": 2020, "season": "夏季", "road_type": "主干道"})`
  - `query_emission_factors({"vehicle_type": "Transit Bus", "pollutants": ["CO2"], "model_year": 2021, "season": "夏季", "road_type": "主干道"})`
- conclusion: Phase 2.3 failed by duplicate tool chain / premature execution, not by exception.

### Phase 2.4 Gate 1 run (`end2end_full_v5_oasc_E`)

- `infrastructure_status`: `unknown`
- `classifier_telemetry`: absent
- `clarification_telemetry`: absent
- `actual.tool_calls`: `[]`
- `exception message`: `invalid literal for int() with base 10: 'missing'`
- conclusion: exception occurs before persisted telemetry/tool execution. Dry-run stack locates it at `core/governed_router.py:321`.

### Difference Diagnosis

- Phase 2.4 introduced the new Stage 2 `slots + intent` schema and generic tool-intent fallback.
- On turn 1, the slot filler resolved `query_emission_factors` and filled known slots, but represented unfilled optionals with string `"missing"` values.
- Because the missing detector does not classify `source=missing/value="missing"` as missing, ClarificationContract proceeded to snapshot-direct execution.
- Snapshot-direct then attempted `int("missing")` for `model_year`.

Layer classification:

- Not benchmark data: task 102 contains no `"missing"` placeholder.
- Not evaluator-only: evaluator merely catches and mislabels the production exception as infrastructure `unknown`.
- Production bug: yes, in the Phase 2.4 ClarificationContract/GovernedRouter snapshot-direct boundary.
- Evaluator bug: secondary, because `ValueError` is classified as infrastructure `unknown` and no traceback is persisted.

## Task 3: Latency +1.6s Static Check

Commit 16 system prompt changed from about 870 chars to about 1417 chars, delta `+547` chars.

Static observations:

- `max_tokens`: no explicit setting before or after.
- `temperature`: unchanged (`temperature=0.0`).
- `asyncio.wait_for(... timeout=clarification_llm_timeout_sec)`: unchanged.
- No extra retry loop was added in the JSON parsing path.
- New prompt adds `available_tools` to Stage 2 payload and requires an `intent` object in addition to slots.

Static grep cannot explain the full `+1.6s` latency delta. Need runtime profiling to attribute it precisely.

## One-Sentence Conclusion

`'missing'` 异常是 **生产代码 bug**：Phase 2.4 slot filler accepted string `"missing"` as a slot value and snapshot-direct execution converted it with `int()`, while evaluator classification as `infra_status=unknown` is a secondary evaluator observability bug.
