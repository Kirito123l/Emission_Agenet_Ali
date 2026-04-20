# Code Review Bundle

| file | original path | copied path | lines | note |
|---|---|---|---:|---|
| `eval_end2end.py` | `evaluation/eval_end2end.py` | `tmp_for_chatgpt_code_review/evaluation/eval_end2end.py` | 1647 | End-to-end benchmark runner and scoring logic. |
| `router.py` | `core/router.py` | `tmp_for_chatgpt_code_review/core/router.py` | 11964 | Main agent/router execution loop, state orchestration, and tool flow. |
| `task_state.py` | `core/task_state.py` | `tmp_for_chatgpt_code_review/core/task_state.py` | 971 | Central task-state model for stages, continuation, clarification, and memory hooks. |
| `input_completion.py` | `core/input_completion.py` | `tmp_for_chatgpt_code_review/core/input_completion.py` | 607 | Structured missing-input completion request and reply parsing logic. |
| `parameter_negotiation.py` | `core/parameter_negotiation.py` | `tmp_for_chatgpt_code_review/core/parameter_negotiation.py` | 435 | Parameter confirmation request and deterministic reply parsing logic. |
| `readiness.py` | `core/readiness.py` | `tmp_for_chatgpt_code_review/core/readiness.py` | 1360 | Action readiness, dependency gating, repairable blocking, and geometry gating logic. |
| `context_store.py` | `core/context_store.py` | `tmp_for_chatgpt_code_review/core/context_store.py` | 731 | Session-scoped result store used for multi-step dependency continuity. |
| `common.py` | `evaluation/pipeline_v2/common.py` | `tmp_for_chatgpt_code_review/evaluation/pipeline_v2/common.py` | 484 | Shared benchmark schema, category list, canonicalization, and success-criteria helpers. |
| `auto_validator.py` | `evaluation/pipeline_v2/auto_validator.py` | `tmp_for_chatgpt_code_review/evaluation/pipeline_v2/auto_validator.py` | 352 | Multi-layer validator for benchmark candidates before merge. |
| `targeted_generator.py` | `evaluation/pipeline_v2/targeted_generator.py` | `tmp_for_chatgpt_code_review/evaluation/pipeline_v2/targeted_generator.py` | 267 | Gap-driven benchmark candidate generator for pipeline v2. |
