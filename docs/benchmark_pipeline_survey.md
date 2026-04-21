# Benchmark Pipeline Survey

## 1. Pipeline Components

### `evaluation/pipeline_v2/__init__.py`
This file is only a package marker. It does not implement pipeline behavior, does not parse inputs, and does not produce outputs. Its practical role is to make the other `pipeline_v2` modules importable as a package.

- Inputs: none
- Outputs: none
- LLM dependency: none

### `evaluation/pipeline_v2/common.py`
This module is the shared utility layer for the whole pipeline. It centralizes default paths, category/tool-chain constants, JSONL/YAML loading, canonicalization helpers, parameter flattening, language and geometry detection, constraint-rule matching, and benchmark-task normalization. It does not orchestrate a stage by itself, but almost every other `pipeline_v2` module depends on it for canonical I/O and rule interpretation.

- Inputs: benchmark JSONL paths, mappings YAML, constraints YAML, candidate task dicts
- Outputs: normalized in-memory task dicts; JSON/JSONL writes via `save_json()` and `save_jsonl()`
- LLM dependency: none

### `evaluation/pipeline_v2/coverage_audit.py`
This is the deterministic audit stage. It reads the current benchmark and produces a structured gap report across supported parameter dimensions, tool-chain combos, cross-constraint coverage, language mix, test files, duplicates, and invalid expected values. It also synthesizes `generation_targets`, which are the direct input for the targeted generator. This is the stage that decides what the pipeline thinks is missing.

- Inputs: `evaluation/benchmarks/end2end_tasks.jsonl` by default, `config/unified_mappings.yaml`, `config/cross_constraints.yaml`
- Outputs: a JSON report such as `evaluation/pipeline_v2/gap_report.json` or `final_coverage_report.json`
- LLM dependency: none

### `evaluation/pipeline_v2/targeted_generator.py`
This is the only true candidate-generation stage in `pipeline_v2`. It takes the structured `generation_targets` from the gap report and asks an LLM to produce benchmark candidate tasks in strict JSON format. The prompt is capability-aware: it injects a system capability summary, target gap description, suggested category/template, and a block of existing user messages to reduce duplicates. It then normalizes each raw candidate into benchmark-task schema and fills in default success criteria and default test files where possible.

- Inputs: gap report JSON (`--gaps`), existing benchmark JSONL (`--existing`), system capability summary from `evaluation.context_extractor.extract_system_capabilities()`
- Outputs: candidate JSONL, typically `evaluation/pipeline_v2/candidates.jsonl`
- LLM dependency:
  - model: default `qwen3-max`
  - prompt shape:
    - system prompt: capability summary + hard rules
    - user prompt: one target gap at a time + suggested category/template + existing messages + strict JSON schema
    - expected JSON payload: `{"tasks": [{"category", "description", "user_message", "has_file", "test_file", "expected_tool", "expected_tool_chain", "expected_params", "success_criteria", "candidate_metadata"}]}`

### `evaluation/pipeline_v2/auto_validator.py`
This module validates generated candidates with five layers: structure, parameter legality, cross-constraint consistency, deduplication, and an LLM review. The first four layers are deterministic and grounded in mappings/constraints and existing benchmark content. The fifth layer is a lightweight qualitative reviewer that scores naturalness and flags parameter or criteria inconsistencies. The validator writes a `validation` block onto each candidate rather than mutating the candidate into final benchmark form.

- Inputs: candidate JSONL, existing benchmark JSONL, mappings YAML, constraints YAML
- Outputs: validated candidate JSONL, typically `evaluation/pipeline_v2/validated_candidates.jsonl`
- LLM dependency:
  - model: default `qwen3-max`
  - prompt shape:
    - system prompt: “return strict JSON only”
    - user prompt: category, user message, expected tool chain, expected params, success criteria, description, plus system background
    - expected JSON payload: `{"naturalness": 1-5, "params_consistency": true, "criteria_reasonable": "yes", "controversial_reason": "", "testing_capability": "...", "suggested_fix": null}`

### `evaluation/pipeline_v2/review_cli.py`
This is the human review gate. It loads validated candidates, filters to those with `validation.status == "needs_review"`, prints the task plus validator issues and embedded LLM review, and requires an interactive reviewer to approve, reject, skip, or edit. The editable fields are limited to `user_message`, `description`, `expected_params`, `expected_tool_chain`, and `success_criteria`.

- Inputs: validated candidate JSONL
- Outputs: reviewed candidate JSONL with `review_decision` and optional edits
- LLM dependency: none directly; it only displays the LLM review produced earlier by `auto_validator.py`

### `evaluation/pipeline_v2/regression_check.py`
This is the post-review system check. It extracts approved candidates, canonicalizes them, writes a regression input JSONL, and runs the full end-to-end evaluator against the current system. It then summarizes abnormal tasks and a narrow class of “judgement disputes”, mainly where the benchmark expected clarification but the system executed tools or returned data. In other words, it is the only stage that runs the system under test against the candidate tasks before merge.

- Inputs: reviewed candidate JSONL
- Outputs: `regression_input.jsonl`, `regression_report.json`, and the evaluator output directory under `evaluation/pipeline_v2/regression_results/`
- LLM dependency: none inside this module; it executes the agent system through `evaluation.eval_end2end.run_end2end_evaluation()`

### `evaluation/pipeline_v2/merge_to_benchmark.py`
This is the final merge step for approved candidates. It reads reviewed candidates, filters to approved or auto-valid tasks, canonicalizes them, assigns new benchmark IDs with `compute_next_task_id()`, strips pipeline-only fields such as `validation` and `review_decision`, skips exact duplicate user messages, and writes the merged benchmark JSONL.

- Inputs: reviewed candidate JSONL, canonical benchmark JSONL
- Outputs: merged benchmark JSONL, usually back into `evaluation/benchmarks/end2end_tasks.jsonl`
- LLM dependency: none

### `evaluation/pipeline_v2/curate_existing_benchmark.py`
This is a deterministic maintenance pass over the existing main benchmark, not a candidate generator. It rewrites specific known task IDs to better match current system semantics: e.g. reclassifying tasks, normalizing constraint metadata, and correcting expectations about defaults or missing parameters. It is effectively a curated patch layer over the benchmark rather than part of the default `run_pipeline.sh` generation loop.

- Inputs: existing benchmark JSONL
- Outputs: curated benchmark JSONL (same schema as input)
- LLM dependency: none

## 2. Pipeline Flow

`run_pipeline.sh` wires the main loop together as follows:

```text
existing main benchmark
evaluation/benchmarks/end2end_tasks.jsonl
        |
        v
+----------------------+
| 1. coverage_audit.py |
| deterministic        |
+----------------------+
        |
        v
evaluation/pipeline_v2/gap_report.json
        |
        v
+---------------------------+
| 2. targeted_generator.py  |
| LLM generation            |
| model: qwen3-max          |
+---------------------------+
        |
        v
evaluation/pipeline_v2/candidates.jsonl
        |
        v
+-----------------------+
| 3. auto_validator.py  |
| 4 deterministic layers|
| + 1 LLM review layer  |
| model: qwen3-max      |
+-----------------------+
        |
        v
evaluation/pipeline_v2/validated_candidates.jsonl
        |
        +---------------------------+
        | any needs_review?         |
        |                           |
        | yes                       | no
        v                           v
+-------------------+      copy validated -> reviewed
| 4. review_cli.py  |
| manual review     |
+-------------------+
        |
        v
evaluation/pipeline_v2/reviewed_candidates.jsonl
        |
        v
+---------------------------+
| 5. regression_check.py    |
| run end2end eval on       |
| approved candidates       |
+---------------------------+
        |
        v
evaluation/pipeline_v2/regression_results/
        |
        v
+--------------------------+
| 6. merge_to_benchmark.py |
| merge approved tasks     |
+--------------------------+
        |
        v
updated evaluation/benchmarks/end2end_tasks.jsonl
        |
        v
+----------------------+
| final coverage_audit |
+----------------------+
        |
        v
evaluation/pipeline_v2/final_coverage_report.json
```

Other observed side lanes in the repo:

- `manual_candidates.jsonl` / `validated_manual.jsonl`: manual candidate preparation that still goes through validator-style schema.
- `phase0_adversarial_candidates.jsonl` / `phase0_validated_adversarial.jsonl` / `phase0_reviewed_adversarial.jsonl`: a historical batch that clearly followed the same validate-review-merge shape, but outside the shell script.
- `curate_existing_benchmark.py`: a separate deterministic patch pass over the benchmark, not part of the shell-script loop.

## 3. Main Benchmark Composition

Current main benchmark size: **180 tasks**.

For counting, the source buckets below use explicit provenance fields in `benchmark_metadata` with the following precedence:

1. `phase0_adversarial=true` → `phase0_adversarial`
2. `curation=manual_pipeline_v2` → `pipeline_v2_manual_review`
3. other non-null `curation` values → `manual`
4. no `generation_flow` and no `curation` → `other`

### Summary Table

| Source bucket | Rule used | Count | Share |
|---|---|---:|---:|
| `phase0_adversarial` | `benchmark_metadata.phase0_adversarial=true` | 80 | 44.4% |
| `pipeline_v2_manual_review` | `benchmark_metadata.curation=manual_pipeline_v2` | 4 | 2.2% |
| `manual` | other non-null `benchmark_metadata.curation` | 18 | 10.0% |
| `other` | none of the above | 78 | 43.3% |

### Raw provenance fields

`benchmark_metadata.generation_flow` counts:

| generation_flow | Count |
|---|---:|
| `<none>` | 100 |
| `pipeline_v2_coverage_audit_targeted_manual_review` | 80 |

`benchmark_metadata.curation` counts:

| curation | Count |
|---|---:|
| `<none>` | 158 |
| `constraint_metadata_normalized` | 13 |
| `manual_pipeline_v2` | 4 |
| `reclassified_from_incomplete` | 4 |
| `reclassified_from_constraint_violation` | 1 |

Interpretation:

- The main benchmark is not a single-source artifact.
- The largest explicit generated tranche is the **80-task `phase0_adversarial` batch**, which already records `generation_flow=pipeline_v2_coverage_audit_targeted_manual_review`.
- Only **4 tasks** currently look like direct manual-pipeline additions marked as `manual_pipeline_v2`.
- Another **18 tasks** were manually curated or reclassified in place rather than generated.
- **78 tasks** have no explicit `generation_flow` or `curation` provenance and therefore predate the current provenance scheme or were added outside it.

## 4. Held-out Benchmark Construction Method

Current held-out benchmark size: **75 tasks**.

### Batch breakdown

| Batch | Count |
|---|---:|
| Batch 1 (`heldout_batch1`) | 30 |
| Batch 2 (`heldout_batch2`) | 25 |
| Batch 3 (`heldout_batch3`) | 20 |

### Provenance and curation fields

`benchmark_metadata.provenance` counts:

| provenance | Count |
|---|---:|
| `heldout_batch1` | 30 |
| `heldout_batch2` | 25 |
| `heldout_batch3` | 20 |

`benchmark_metadata.curation` counts:

| curation | Count |
|---|---:|
| `<none>` | 75 |

`benchmark_metadata.generation_flow` counts:

| generation_flow | Count |
|---|---:|
| `<none>` | 75 |

### Observed batch signatures

- **Batch 1** carries fields such as `colloquial_expression`, `chain_type`, `criteria_note`, `fixture_note`, and free-form `notes`.
- **Batch 2** carries fields such as `deliberative_signal`, `ambiguity_note`, `expected_param_source`, `revision_signal`, `revision_target`, and one `adversarial_level`.
- **Batch 3** carries fields such as `code_switch_pattern`, `incomplete_subpattern`, `violated_constraints`, `expected_constraint_action`, and `typo_pattern`.

### Does held-out go through `pipeline_v2`?

Based on the current repo state, **no**:

- all 75 held-out tasks have `generation_flow=<none>`
- all 75 held-out tasks have `curation=<none>`
- `evaluation/pipeline_v2/` contains **no references** to `held_out_tasks.jsonl` or any held-out-specific path
- `run_pipeline.sh` hardcodes the main benchmark path `evaluation/benchmarks/end2end_tasks.jsonl`

So the held-out benchmark appears to be a **separate, batch-authored benchmark track** with provenance tags, not an output of the current `pipeline_v2` automation.

## 5. Current Gaps

The current `pipeline_v2` is useful, but its coverage is narrower than the full benchmark space. Based on the code, the main gaps are:

### 1. It does not actually generate full multi-turn tasks

Evidence:

- `targeted_generator.py`'s output schema does **not** include `follow_up_messages`
- `_normalize_candidate()` in `targeted_generator.py` does not preserve or write `follow_up_messages`
- `auto_validator.py` only type-checks `follow_up_messages` if they are already present; it does not synthesize them

Result: the current automated path cannot author realistic `multi_turn_clarification` tasks with a full follow-up turn sequence.

### 2. It only prompts for 5 of the 9 benchmark categories

Evidence:

- `VALID_CATEGORIES` in `common.py` contains 9 categories
- but `TARGETED_GENERATION_USER_PROMPT` in `targeted_generator.py` constrains output `category` to:
  `simple|parameter_ambiguous|multi_step|incomplete|constraint_violation`

Missing from the generation prompt are:

- `multi_turn_clarification`
- `user_revision`
- `ambiguous_colloquial`
- `code_switch_typo`

Result: even before validation, the current generator is structurally biased toward the simpler half of the benchmark taxonomy.

### 3. Coverage auditing does not enforce category balance

Evidence:

- `coverage_audit.py` measures parameter dimensions, tool-chain combos, language, test files, duplicates, invalid expected values, and cross-constraints
- it does **not** compute per-category counts or target per-category quotas
- `_generation_targets()` emits gaps for dimensions such as missing vehicle types, pollutants, meteorology, tool chains, English coverage, and low-count seasons/road types, but not category imbalance

Result: the pipeline can close dimension gaps while still drifting badly on category mix.

### 4. The LLM review is shallow candidate QA, not a realism or judge layer for full benchmark quality

Evidence:

- `auto_validator.py`'s LLM review prompt only asks for `naturalness`, `params_consistency`, `criteria_reasonable`, `testing_capability`, and `suggested_fix`
- there is no prompt for multi-turn realism, dialog progression quality, adversarial hardness calibration, or held-out leakage risk
- `regression_check.py` adds execution evidence, but only after approval, and its “judgement dispute” logic is narrow

Result: the current LLM involvement is enough for coarse candidate QA, but not for richer benchmark-judge work.

### 5. There is no held-out construction lane in `pipeline_v2`

Evidence:

- default benchmark path across the pipeline is the main benchmark, not held-out
- `run_pipeline.sh` reads and writes `evaluation/benchmarks/end2end_tasks.jsonl`
- `rg` over `evaluation/pipeline_v2/` finds no held-out references

Result: `pipeline_v2` today is a **main-benchmark augmentation pipeline**, not a complete held-out construction pipeline.

## 6. Capability Summary

`pipeline_v2` can already generate and validate new benchmark candidates for the **main** benchmark in a partially automated way: it can audit gaps, call an LLM to propose targeted tasks, run deterministic and LLM-based validation, support manual review, regression-check approved candidates, and merge them back into the canonical main benchmark. It is **not** sufficient today to automatically produce a new held-out benchmark end to end. The main shortfalls are structural: no held-out-specific path or provenance model, no automatic multi-turn/follow-up generation, no coverage over all 9 benchmark categories, and no category-balance or realism-judge layer strong enough to replace the current batch-authored held-out process.
