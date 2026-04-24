# Phase 2 E-8.1 Completion Report

## Summary

E-8.1 centralizes tool-level conversational fields in
`config/tool_contracts.yaml` and removes `config/unified_mappings.yaml:tools`.

Implementation status:

- E-8.1.1 through E-8.1.9 completed.
- Full pytest passed.
- E-8.1.9 smoke rerun after network fix: PASS (zero behavior drift across all
  9 categories).

## Change List

### E-8.1.1 Analysis

- Added `docs/phase2_e81_yaml_merge_analysis.md`.
- Documented top-level keys in `config/unified_mappings.yaml`, migration
  decisions, reader scan, retained readers, and tool-list drift.
- Added the approved "Tool List Difference Notes" section explaining why
  `analyze_file` and `compare_scenarios` intentionally have empty slot metadata.

### E-8.1.2 Extend `tool_contracts.yaml`

- `config/tool_contracts.yaml:29` migrated fields for `query_emission_factors`.
- `config/tool_contracts.yaml:96` migrated fields for `calculate_micro_emission`.
- `config/tool_contracts.yaml:184` migrated fields for `calculate_macro_emission`.
- `config/tool_contracts.yaml:348` migrated fields for `query_knowledge`.
- `config/tool_contracts.yaml:390` migrated fields for `calculate_dispersion`.
- `config/tool_contracts.yaml:522` migrated fields for `analyze_hotspots`.
- `config/tool_contracts.yaml:615` migrated fields for `render_spatial_map`.

### E-8.1.3 Extend `ToolContractRegistry`

- `tools/contract_loader.py:155` added `get_required_slots`.
- `tools/contract_loader.py:159` added `get_optional_slots`.
- `tools/contract_loader.py:163` added `get_defaults`.
- `tools/contract_loader.py:168` added `get_clarification_followup_slots`.
- `tools/contract_loader.py:172` added `get_confirm_first_slots`.
- `tools/contract_loader.py:176` and `tools/contract_loader.py:185` added
  internal typed field helpers.

### E-8.1.4 Stance Resolution Reader

- `core/contracts/stance_resolution_contract.py:8` now imports
  `get_tool_contract_registry`.
- `core/contracts/stance_resolution_contract.py:173` now resolves required slots
  through `ToolContractRegistry.get_required_slots`.
- Removed direct `unified_mappings.yaml` loading from this contract.

### E-8.1.5 Runtime Defaults Reader

- `core/contracts/runtime_defaults.py:5` now imports
  `get_tool_contract_registry`.
- `core/contracts/runtime_defaults.py:26` now reads YAML defaults from
  `ToolContractRegistry.get_defaults`.
- `_RUNTIME_DEFAULTS` and runtime-over-YAML precedence were preserved.

### E-8.1.6 Other Reader Switches

- `core/contracts/clarification_contract.py:23` now imports
  `get_tool_contract_registry`.
- `core/contracts/clarification_contract.py:1369` builds its tool slot/default
  specs from registry getters.
- `core/contracts/clarification_contract.py:1389` keeps the existing
  `_get_tool_spec` interface for downstream split contracts.
- `services/config_loader.py`, `evaluation/context_extractor.py`,
  `evaluation/build_benchmark.py`, `evaluation/pipeline_v2/common.py`,
  `evaluation/pipeline_v2/coverage_audit.py`, and `core/ao_classifier.py`
  remain unchanged because they read non-`tools` global mappings.

### E-8.1.7 Delete `unified_mappings.yaml:tools`

- Removed the whole `tools:` section from `config/unified_mappings.yaml`.
- `config/unified_mappings.yaml:539` now goes from global `defaults` directly to
  `vsp_bins` at `config/unified_mappings.yaml:556`.

Validation:

```bash
grep -rn "tools\." config/unified_mappings.yaml 2>/dev/null
# no output
```

### E-8.1.8 Tests

- Added `tests/test_yaml_merge.py`.
- `tests/test_yaml_merge.py:25` verifies all registry tool names return stable
  non-`None` values for the 5 getters.
- `tests/test_yaml_merge.py:42` locks the legacy
  `query_emission_factors` slot/default values.
- `tests/test_yaml_merge.py:63` locks empty getter behavior for `analyze_file`
  and `compare_scenarios`.
- `tests/test_yaml_merge.py:73` verifies stance-resolution required-slot
  behavior.
- `tests/test_yaml_merge.py:91` verifies clarification-contract specs come from
  the registry.
- `tests/test_yaml_merge.py:115` verifies runtime defaults still combine YAML
  defaults with `_RUNTIME_DEFAULTS`.

## Deviations From Prompt

- The prompt expected 9 tools under `unified_mappings.yaml:tools`; the actual file
  had 7. `analyze_file` and `compare_scenarios` are intentionally absent there.
- `core/contracts/clarification_contract.py` was added to the reader migration
  scope after analysis. This was approved before implementation.
- Initial E-8.1.9 smoke had network-contaminated pre (4/10 network failures).
  After user network fix, rerun with clean pre and post shows perfect refactor:
  0pp delta across all four metrics, no category flips. See
  `docs/phase2_e81_smoke_comparison.md`.

## Analysis Summary

See `docs/phase2_e81_yaml_merge_analysis.md`.

Core conclusions:

- `unified_mappings.yaml` keeps global mappings:
  `version`, `vehicle_types`, `pollutants`, `seasons`, `road_types`,
  `meteorology`, `stability_classes`, `column_patterns`, `defaults`, `vsp_bins`.
- `unified_mappings.yaml:tools` was the only section removed.
- The migrated 5 fields remain distinct from schema-level
  `parameters.<p>.required`.

## Changed Readers

- `tools/contract_loader.py`: new getter surface for the 5 migrated fields.
- `core/contracts/stance_resolution_contract.py`: `required_slots` reader moved
  to registry.
- `core/contracts/runtime_defaults.py`: tool-specific `defaults` reader moved to
  registry.
- `core/contracts/clarification_contract.py`: `required_slots`,
  `optional_slots`, `defaults`, `clarification_followup_slots`, and
  `confirm_first_slots` reader moved to registry.

## Retained Readers

- `services/config_loader.py`: reads global mappings such as vehicle types,
  pollutants, column patterns, defaults, and VSP bins.
- `evaluation/context_extractor.py`: reads global standardization vocabularies.
- `evaluation/build_benchmark.py`: builds standardization benchmark cases from
  global vocabularies.
- `evaluation/pipeline_v2/common.py`: benchmark catalog helpers for global
  mappings.
- `evaluation/pipeline_v2/coverage_audit.py`: benchmark coverage audit default
  mappings path.
- `core/ao_classifier.py`: scans global list vocabularies for aliases.
- `docs/archive/code_review_snapshots/.../evaluation/pipeline_v2/common.py`:
  historical archive snapshot only; not runtime code.

## Test Results

Focused tests:

```bash
/home/kirito/miniconda3/bin/python -m pytest \
  tests/test_yaml_merge.py tests/test_compare_tool.py \
  tests/test_naive_router.py tests/test_tool_contracts.py -q --tb=line

23 passed in 1.64s
```

Full tests:

```bash
/home/kirito/miniconda3/bin/python -m pytest tests/ -q --tb=line

1210 passed, 40 warnings in 75.76s (0:01:15)
```

## Smoke Result

See `docs/phase2_e81_smoke_comparison.md`.

Final accepted smoke metrics:

| Metric | Pre | Post | Delta |
| --- | ---: | ---: | ---: |
| `run_status` | completed | completed | n/a |
| `data_integrity` | clean | clean | n/a |
| `network_failed` | 0/10 | 0/10 | 0 |
| `completion_rate` | 0.70 | 0.70 | 0.00 |
| `tool_accuracy` | 0.70 | 0.70 | 0.00 |
| `parameter_legal_rate` | 0.60 | 0.60 | 0.00 |
| `result_data_rate` | 0.60 | 0.60 | 0.00 |
| `wall_clock` | 51.57s | 50.31s | -1.26s |
| `cache_hit_rate` | 0.9091 | 0.9091 | 0.0000 |

Per-category completion:

| Category | Pre pass | Post pass | Flip count |
| --- | ---: | ---: | ---: |
| `ambiguous_colloquial` | 0/1 | 0/1 | 0 |
| `code_switch_typo` | 0/1 | 0/1 | 0 |
| `constraint_violation` | 1/1 | 1/1 | 0 |
| `incomplete` | 1/1 | 1/1 | 0 |
| `multi_step` | 1/1 | 1/1 | 0 |
| `multi_turn_clarification` | 0/1 | 0/1 | 0 |
| `parameter_ambiguous` | 1/1 | 1/1 | 0 |
| `simple` | 1/1 | 1/1 | 0 |
| `user_revision` | 2/2 | 2/2 | 0 |

Clarification metrics changed only in instrumentation counts:
`trigger_count` moved from 7 to 9 and `proceed_rate` from 0.5714 to 0.5556.
The four acceptance metrics and all category pass/fail outcomes stayed
identical.

Verdict: PASS. The accepted rerun has clean pre/post infrastructure, 0pp delta
across all four tracked metrics, and no pass/fail flips.

## Downstream Notes

- New `ToolContractRegistry` getter names:
  `get_required_slots`, `get_optional_slots`, `get_defaults`,
  `get_clarification_followup_slots`, `get_confirm_first_slots`.
- Task Packs C+D / A should use these getters for tool-level conversational
  metadata instead of reading `unified_mappings.yaml:tools`.
- `unified_mappings.yaml` now contains only global standardization/default/VSP
  sections and no tool-specific slot metadata.
- `analyze_file` and `compare_scenarios` return empty values from the 5 new
  getters by design.

## Known Issues / TODO

- `analyze_file` and `compare_scenarios` not being in
  `unified_mappings.yaml:tools` is intentional design, not a configuration
  omission. If future work extends `ToolContractRegistry` to use the 5 migrated
  fields for these two tools, first evaluate whether their readiness paths should
  merge with the standard slot-filling mechanism.
