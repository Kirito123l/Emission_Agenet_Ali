# README_COPY_USE

Temporary directory path:
- `/home/kirito/Agent1/emission_agent/tmp_for_chatgpt_code_review`

Copied file count:
- `10`

Suggested first 5 files to read:
- `evaluation/eval_end2end.py`
- `core/router.py`
- `core/task_state.py`
- `core/readiness.py`
- `core/context_store.py`

Quick terminal view:

```bash
less tmp_for_chatgpt_code_review/evaluation/eval_end2end.py
less tmp_for_chatgpt_code_review/core/router.py
less tmp_for_chatgpt_code_review/core/task_state.py
```

List all copied files:

```bash
find tmp_for_chatgpt_code_review -type f | sort
```

Count total lines across copied source files:

```bash
wc -l \
  tmp_for_chatgpt_code_review/evaluation/eval_end2end.py \
  tmp_for_chatgpt_code_review/core/router.py \
  tmp_for_chatgpt_code_review/core/task_state.py \
  tmp_for_chatgpt_code_review/core/input_completion.py \
  tmp_for_chatgpt_code_review/core/parameter_negotiation.py \
  tmp_for_chatgpt_code_review/core/readiness.py \
  tmp_for_chatgpt_code_review/core/context_store.py \
  tmp_for_chatgpt_code_review/evaluation/pipeline_v2/common.py \
  tmp_for_chatgpt_code_review/evaluation/pipeline_v2/auto_validator.py \
  tmp_for_chatgpt_code_review/evaluation/pipeline_v2/targeted_generator.py
```

Open the bundle root:

```bash
cd /home/kirito/Agent1/emission_agent/tmp_for_chatgpt_code_review
```
