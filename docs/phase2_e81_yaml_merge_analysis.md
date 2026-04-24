# Phase 2 E-8.1 YAML Merge Analysis

## Scope

Task Pack E-8.1 merges tool-level conversational fields from
`config/unified_mappings.yaml:tools.<name>` into
`config/tool_contracts.yaml:tools.<name>`.

The non-`tools` sections of `config/unified_mappings.yaml` stay in place.

## Current Repository State

- Branch at analysis time: `e-8-1-yaml-merge`
- Starting HEAD: `51556b2 chore: untrack evaluation/tool_cache/ (already in .gitignore)`
- Worktree before this document: clean

## `config/unified_mappings.yaml` Top-Level Keys

The current top-level keys are:

1. `version`
2. `vehicle_types`
3. `pollutants`
4. `seasons`
5. `road_types`
6. `meteorology`
7. `stability_classes`
8. `column_patterns`
9. `defaults`
10. `tools`
11. `vsp_bins`

## Migration Decisions By Top-Level Key

| Key | Decision | Reason |
| --- | --- | --- |
| `version` | Keep in `unified_mappings.yaml` | Version for the remaining global mappings file. |
| `vehicle_types` | Keep | Global standardization vocabulary, used by config and benchmark readers. |
| `pollutants` | Keep | Global standardization vocabulary, used by config and benchmark readers. |
| `seasons` | Keep | Global standardization vocabulary, used by config and benchmark readers. |
| `road_types` | Keep | Global standardization vocabulary, used by config and benchmark readers. |
| `meteorology` | Keep | Global standardization vocabulary, used by clarification legal values and benchmark readers. |
| `stability_classes` | Keep | Global standardization vocabulary, used by clarification legal values and benchmark readers. |
| `column_patterns` | Keep | File analysis / standardization config, not tool-level conversational metadata. |
| `defaults` | Keep | Global defaults remain part of unified mappings. Tool-specific `tools.<name>.defaults` migrates. |
| `tools` | Delete after reader migration | Its tool-level fields move to `tool_contracts.yaml:tools.<name>`. |
| `vsp_bins` | Keep | Global VSP configuration, not tool-level conversational metadata. |

## Tool Field Migration Plan

For every tool currently present under `config/unified_mappings.yaml:tools`, move these fields into
`config/tool_contracts.yaml:tools.<name>`:

- `required_slots`
- `optional_slots`
- `defaults`
- `clarification_followup_slots`
- `confirm_first_slots`

Actual tool names currently present in `config/unified_mappings.yaml:tools`:

1. `query_emission_factors`
2. `calculate_micro_emission`
3. `calculate_macro_emission`
4. `calculate_dispersion`
5. `analyze_hotspots`
6. `render_spatial_map`
7. `query_knowledge`

Prompt drift: the task prompt expected 9 tools including `process_traffic_data` and
`clean_dataframe`. Current `unified_mappings.yaml:tools` has 7 tools. Current
`tool_contracts.yaml:tools` has 9 tools, but the two additional contract tools are
`analyze_file` and `compare_scenarios`, not `process_traffic_data` / `clean_dataframe`.
Those tools have no matching migrated fields in `unified_mappings.yaml`.

## Tool List Difference Notes

`config/unified_mappings.yaml:tools` currently contains 7 tools:

- `query_emission_factors`
- `calculate_micro_emission`
- `calculate_macro_emission`
- `calculate_dispersion`
- `analyze_hotspots`
- `render_spatial_map`
- `query_knowledge`

`config/tool_contracts.yaml:tools` contains those 7 plus 2 additional tools:

- `analyze_file`
- `compare_scenarios`

These two extra tools are intentionally absent from `unified_mappings.yaml:tools`:

- `analyze_file` is an internal support tool. The router prompt explicitly forbids
  placing it in plan steps (`core/router.py:213`), and it does not participate in
  the user-facing slot-filling clarification path.
- `compare_scenarios` is user-facing, but its parameter semantics (`result_types`
  enum plus `scenario` / `scenarios` alternatives) do not fit the standard
  slot-filling model. It uses an independent readiness special case in
  `core/readiness.py:776`.

Therefore E-8.1 migrates the 5 fields for the 7 tools currently present in
`unified_mappings.yaml:tools`. Returning empty values from the new registry getters
for `analyze_file` and `compare_scenarios` is the intended behavior, not a
configuration gap.

## Current Tool Field Values

| Tool | required_slots | optional_slots | defaults | clarification_followup_slots | confirm_first_slots |
| --- | --- | --- | --- | --- | --- |
| `query_emission_factors` | `vehicle_type`, `pollutants` | `model_year`, `season`, `road_type` | `season: 夏季`, `road_type: 快速路` | `model_year` | `road_type` |
| `calculate_micro_emission` | `vehicle_type`, `pollutants` | `season`, `model_year` | `season: 夏季` | empty | `season` |
| `calculate_macro_emission` | `pollutants` | `season`, `scenario_label` | `season: 夏季` | empty | `season` |
| `calculate_dispersion` | empty | `meteorology`, `pollutant`, `scenario_label` | empty | empty | empty |
| `analyze_hotspots` | empty | `method`, `percentile` | empty | empty | empty |
| `render_spatial_map` | empty | `pollutant`, `scenario_label` | empty | empty | empty |
| `query_knowledge` | empty | empty | empty | empty | empty |

## Python `unified_mappings` Reader Scan

Command:

```bash
rg -n "unified_mappings" --glob "*.py"
```

Results and decisions:

| File | Reference | Decision |
| --- | --- | --- |
| `services/config_loader.py:15` | `MAPPINGS_FILE = CONFIG_DIR / "unified_mappings.yaml"` | Keep. This loader serves global mappings (`vehicle_types`, `pollutants`, `column_patterns`, `defaults`, `vsp_bins`). It does not directly read `tools.<name>` fields. |
| `evaluation/context_extractor.py:45-56` | Loads unified mappings for prompt-generation context. | Keep. It reads global standardization vocabularies; tool contracts are already read from `tool_contracts.yaml`. |
| `evaluation/build_benchmark.py:13` | Standardization benchmark source mappings. | Keep. It builds benchmark cases from global standardization vocabularies, not `tools`. |
| `evaluation/pipeline_v2/coverage_audit.py:33` | Default mappings path for benchmark coverage audit. | Keep. It consumes global vocabularies through `pipeline_v2.common`. |
| `evaluation/pipeline_v2/common.py:17` | Default mappings path and helpers. | Keep. It builds mapping catalogs from global vocabularies and keeps hard-coded tool-chain benchmark constants separate. |
| `core/contracts/stance_resolution_contract.py:12` | Reads `unified_mappings.yaml`. | Change. `_required_slots_for_tool` reads `tools.<name>.required_slots`; this must move to `ToolContractRegistry.get_required_slots`. |
| `core/contracts/clarification_contract.py:27` | Reads `unified_mappings.yaml`. | Change. This contract reads `required_slots`, `optional_slots`, `defaults`, `clarification_followup_slots`, and `confirm_first_slots` from `tools.<name>`. It must switch to `ToolContractRegistry` getters. |
| `core/contracts/runtime_defaults.py:8` | Reads `unified_mappings.yaml`. | Change. It reads `tools.<name>.defaults`; this must move to `ToolContractRegistry.get_defaults`. `_RUNTIME_DEFAULTS` and runtime-over-YAML precedence stay unchanged. |
| `core/ao_classifier.py:308` | Loads unified mappings aliases. | Keep. It scans top-level list vocabularies for aliases and does not read the `tools` section. |
| `docs/archive/code_review_snapshots/tmp_for_chatgpt_code_review/evaluation/pipeline_v2/common.py:17` | Archived code-review snapshot reference surfaced by `grep -rn`. | Keep. This is not runtime code and reads global benchmark mappings in an archived snapshot. |

Additional local scan:

```bash
rg -n "load_mappings\(|ConfigLoader\.load_mappings|ConfigLoader\.get_defaults|get_config_loader\(|get_defaults\(" --glob "*.py"
```

Relevant result: callers of `ConfigLoader.load_mappings()` use global mapping data
for standardization, defaults, file analysis, or smoke/integration checks. No current
caller was found that depends on `ConfigLoader.load_mappings()["tools"]`.

## YAML `unified_mappings` Reference Scan

Command:

```bash
rg -n "unified_mappings" --glob "*.yaml"
```

Results and decisions:

| File | Reference | Decision |
| --- | --- | --- |
| `config/cross_constraints.yaml:22` | Comment: `unified_mappings.yaml currently exposes MOVES standard source types only.` | Keep. Comment references global mappings, not `tools.<name>` fields. |

## Reader Changes Required In E-8.1.2+

Change these readers:

1. `tools/contract_loader.py`
   - Add support for the 5 migrated fields.
   - Add getters:
     - `get_required_slots(tool_name)`
     - `get_optional_slots(tool_name)`
     - `get_defaults(tool_name)`
     - `get_clarification_followup_slots(tool_name)`
     - `get_confirm_first_slots(tool_name)`
   - Missing fields return `[]` or `{}`.

2. `core/contracts/stance_resolution_contract.py`
   - Remove direct `unified_mappings.yaml` tool reader.
   - Use `get_tool_contract_registry().get_required_slots(tool_name)`.

3. `core/contracts/clarification_contract.py`
   - Remove direct `unified_mappings.yaml` tool reader.
   - Use `ToolContractRegistry` for the tool slot/default/follow-up/confirm-first spec.
   - Continue using existing global standardization engines for legal values.

4. `core/contracts/runtime_defaults.py`
   - Replace `tools.<name>.defaults` YAML lookup with
     `get_tool_contract_registry().get_defaults(tool_name)`.
   - Preserve `_RUNTIME_DEFAULTS` and runtime-over-YAML precedence.

## Readers Intentionally Kept

Keep these `unified_mappings.yaml` readers because they consume non-`tools` global mappings:

- `services/config_loader.py`
- `evaluation/context_extractor.py`
- `evaluation/build_benchmark.py`
- `evaluation/pipeline_v2/common.py`
- `evaluation/pipeline_v2/coverage_audit.py`
- `core/ao_classifier.py`
- `docs/archive/code_review_snapshots/tmp_for_chatgpt_code_review/evaluation/pipeline_v2/common.py`
  (historical snapshot only)

## Pre-Implementation Notes

- `unified_mappings.yaml:defaults.model_year` currently exists, while
  `unified_mappings.yaml:tools.query_emission_factors.defaults` does not include
  `model_year`.
- `core/contracts/runtime_defaults.py` also has `_RUNTIME_DEFAULTS["query_emission_factors"]["model_year"] = 2020`.
  After switching the YAML reader to `ToolContractRegistry`, the runtime hard-coded
  default still preserves the effective runtime value.
- Do not merge `required_slots` with `parameters.<p>.required`; they remain separate
  conversation-layer and schema-layer concepts.
