# Phase 2 A Smoke Comparison

## Overview

Task Pack A adds an LLM-based reply parser over the existing governed router output. This smoke is run by the user locally because Codex sandbox LLM/network behavior is not reliable enough for acceptance evidence.

The goal is not to prove new tool capability. It is to verify that reply generation improves final text quality without destabilizing routing, tool execution, parameter legality, or clarification flow.

## Subset

- Sample file: `evaluation/results/a_smoke/smoke_10.jsonl`
- Nominal target: 10 tasks.
- Current benchmark resolution: 11 tasks, because the benchmark has 9 categories and both configured sensitivity duplicates exist.
- Coverage: first task by task ID from each of 9 categories, plus second `multi_turn_clarification` and second `user_revision` tasks for reply-quality sensitivity.
- Selection prefers each category's native task-ID prefix before sorting by task ID, so reclassified tasks such as `e2e_incomplete_*` inside `simple` do not displace the canonical `e2e_simple_*` smoke case.

Build command:

```bash
/home/kirito/miniconda3/bin/python evaluation/results/a_smoke/build_smoke_10.py
```

Expected current task IDs:

| Task ID | Category | Selection Reason |
|---|---|---|
| e2e_simple_001 | simple | first by ID |
| e2e_ambiguous_001 | parameter_ambiguous | first by ID |
| e2e_multistep_001 | multi_step | first by ID |
| e2e_clarification_101 | multi_turn_clarification | first by ID |
| e2e_constraint_001 | constraint_violation | first by ID |
| e2e_incomplete_001 | incomplete | first by ID |
| e2e_codeswitch_161 | code_switch_typo | first by ID |
| e2e_colloquial_141 | ambiguous_colloquial | first by ID |
| e2e_revision_121 | user_revision | first by ID |
| e2e_clarification_102 | multi_turn_clarification | second by ID, reply-sensitive |
| e2e_revision_122 | user_revision | second by ID, reply-sensitive |

## Pre/Post Commands

Run these locally. Do not run the LLM smoke inside the Codex sandbox.

```bash
# sampling
/home/kirito/miniconda3/bin/python evaluation/results/a_smoke/build_smoke_10.py

# pre: main HEAD before Task Pack A changes
git stash push -u -m "a-wip-smoke"
/home/kirito/miniconda3/bin/python evaluation/eval_end2end.py \
  --samples evaluation/results/a_smoke/smoke_10.jsonl \
  --output-dir evaluation/results/a_smoke/pre \
  --mode full

# post: restore Task Pack A changes
git stash pop
/home/kirito/miniconda3/bin/python evaluation/eval_end2end.py \
  --samples evaluation/results/a_smoke/smoke_10.jsonl \
  --output-dir evaluation/results/a_smoke/post \
  --mode full
```

## Three-Layer Verdict Rules

### Signal 1 - Structural

Zero drift expected:

- `tool_accuracy`: 0pp
- `infrastructure.network_failed`: same pre vs post
- `clarification_contract_metrics.trigger_count`: within +/-2

### Signal 2 - Completion

Small drift allowed:

- `completion_rate`: <= 5pp drift
- `result_data_rate`: <= 5pp drift
- `parameter_legal_rate`: <= 5pp drift

### Signal 3 - Qualitative Reply Diff

Compare final assistant text for five sampled tasks:

- `simple`
- `multi_step`
- `constraint_violation`
- `multi_turn_clarification`
- `user_revision`

Rate each as `Better`, `Equal`, or `Worse`, with a one-line reason covering information completeness, naturalness, structure, and duplicated-section behavior.

## Pre Metrics

TODO after user-local smoke:

```json
{
  "run_status": "TODO",
  "data_integrity": "TODO",
  "network_failed": "TODO",
  "completion_rate": "TODO",
  "tool_accuracy": "TODO",
  "parameter_legal_rate": "TODO",
  "result_data_rate": "TODO",
  "clarification_contract_metrics": "TODO"
}
```

## Post Metrics

TODO after user-local smoke:

```json
{
  "run_status": "TODO",
  "data_integrity": "TODO",
  "network_failed": "TODO",
  "completion_rate": "TODO",
  "tool_accuracy": "TODO",
  "parameter_legal_rate": "TODO",
  "result_data_rate": "TODO",
  "clarification_contract_metrics": "TODO"
}
```

## Per-Category

TODO after user-local smoke:

| Category | Pre Pass/Total | Post Pass/Total | Delta | Notes |
|---|---:|---:|---:|---|
| simple | TODO | TODO | TODO | TODO |
| parameter_ambiguous | TODO | TODO | TODO | TODO |
| multi_step | TODO | TODO | TODO | TODO |
| multi_turn_clarification | TODO | TODO | TODO | TODO |
| constraint_violation | TODO | TODO | TODO | TODO |
| incomplete | TODO | TODO | TODO | TODO |
| code_switch_typo | TODO | TODO | TODO | TODO |
| ambiguous_colloquial | TODO | TODO | TODO | TODO |
| user_revision | TODO | TODO | TODO | TODO |

## Qualitative Reply Diff

TODO after user-local smoke. Fill from `evaluation/results/a_smoke/{pre,post}/end2end_logs.jsonl`.

### simple

- Task ID: TODO
- Rating: TODO
- Reason: TODO

Pre:

```text
TODO
```

Post:

```text
TODO
```

### multi_step

- Task ID: TODO
- Rating: TODO
- Reason: TODO

Pre:

```text
TODO
```

Post:

```text
TODO
```

### constraint_violation

- Task ID: TODO
- Rating: TODO
- Reason: TODO

Pre:

```text
TODO
```

Post:

```text
TODO
```

### multi_turn_clarification

- Task ID: TODO
- Rating: TODO
- Reason: TODO

Pre:

```text
TODO
```

Post:

```text
TODO
```

### user_revision

- Task ID: TODO
- Rating: TODO
- Reason: TODO

Pre:

```text
TODO
```

Post:

```text
TODO
```

## Verdict

TODO after user-local pre/post smoke.

PASS requires all three layers to satisfy their criteria. Any `Worse` qualitative reply needs investigation even if structural metrics are stable.
