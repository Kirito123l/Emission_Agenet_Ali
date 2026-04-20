# Dispersion Grid Guard Follow-up Notes

## Evaluator Behavior

Checked `evaluation/eval_end2end.py` after adding the dispersion preflight guard.

- Tool-level `ToolResult(success=False, data={...})` does not populate `execution_error`,
  `execution_error_type`, or `execution_traceback`.
- Those fields are only populated when `_execute_task_payload()` raises and
  `_run_with_infrastructure_failsafe()` returns an execution error payload.
- A `DISPERSION_GRID_TOO_LARGE` result returned through `tools/dispersion.py`
  is therefore an expected tool refusal, not an infrastructure or production
  exception.

## Evaluation Semantics Caveat

Current `_has_result_payload()` treats any non-empty failed tool `data` as
`result_has_data=True`. A grid-too-large refusal carries diagnostic `data`
(`error_code`, `estimated_pairs`, `limit`) so the evaluator may count
`result_has_data=True` even though no dispersion artifact was produced.

This note is observational only. The evaluator was not changed in this guard
patch.
