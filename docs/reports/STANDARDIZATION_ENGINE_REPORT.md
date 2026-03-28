# Standardization Engine Report

## Architecture

```text
Tool arguments / declarative param registry
    |
    v
StandardizationEngine
    |
    +-- RuleBackend
    |     |
    |     +-- legacy UnifiedStandardizer
    |
    +-- LLMBackend
          |
          +-- services.llm_client.LLMClientService (purpose="standardizer")
    |
    v
StandardizationResult
```

Compatibility-first implementation details:

- `services/standardizer.py` is unchanged and remains the rule source of truth.
- `RuleBackend` delegates to the legacy standardizer by default to preserve exact output.
- `LLMBackend` only runs after rule failure, or after a non-empty input would otherwise fall back to a default.
- `ToolExecutor.standardizer` still points to a `UnifiedStandardizer` instance for backward compatibility.

## Six-Stage Cascade

1. `exact`
   Trigger: raw input is already the canonical value.
2. `alias`
   Trigger: raw input matches a declared alias or case-insensitive canonical key.
3. `fuzzy`
   Trigger: best fuzzy match crosses the configured threshold.
4. `llm`
   Trigger: rule backend abstains, or returns `default` for a non-empty input and LLM fallback is enabled.
5. `default`
   Trigger: type has a default and rule/LLM resolution still fails.
6. `abstain`
   Trigger: no exact/alias/fuzzy/LLM/default resolution is available.

Special handling:

- `meteorology=.sfc` and `meteorology=custom` are treated as `passthrough`.
- `pollutants` is standardized element-wise and preserves unknown items instead of raising.
- `None` and non-string scalar values are passed through unchanged in batch mode.

## PARAM_TYPE_REGISTRY

```python
PARAM_TYPE_REGISTRY = {
    "vehicle_type": "vehicle_type",
    "pollutant": "pollutant",
    "pollutants": "pollutant_list",
    "season": "season",
    "road_type": "road_type",
    "meteorology": "meteorology",
    "stability_class": "stability_class",
}
```

Current compatibility notes for type config:

- `road_type` default remains `快速路`, because that is the current project default in `config/unified_mappings.yaml`.
- `pollutant` fuzzy matching remains enabled by default to preserve current behavior in `services/standardizer.py`.
- Legacy optional `local_model` behavior inside `UnifiedStandardizer` is preserved inside `RuleBackend`.

## LLM Prompt Template

```text
将以下{参数语义描述}参数值映射到标准值。
输入："{raw_value}"
标准值列表：
- 标准值1（别名1, 别名2, 别名3）
- 标准值2（别名1, 别名2）
...

只返回 JSON：{"value": "匹配的标准值或null", "confidence": 0.0到1.0}
```

Guardrails:

- only canonical candidates are accepted
- invalid JSON / timeout / network failure / unsupported candidate all degrade gracefully
- LLM confidence is capped at `0.95`

## Configuration

Added to `config.py` runtime config:

```python
self.standardization_config = {
    "llm_enabled": ...,
    "llm_backend": "api",
    "llm_model": None,
    "llm_timeout": 5.0,
    "llm_max_retries": 1,
    "fuzzy_threshold": 0.7,
    "local_model_path": None,
}
```

Environment variables:

- `STANDARDIZATION_LLM_ENABLED`
- `STANDARDIZATION_LLM_BACKEND`
- `STANDARDIZATION_LLM_MODEL`
- `STANDARDIZATION_LLM_TIMEOUT`
- `STANDARDIZATION_LLM_MAX_RETRIES`
- `STANDARDIZATION_FUZZY_THRESHOLD`
- `STANDARDIZATION_LOCAL_MODEL_PATH`

## Backward Compatibility Guarantees

Guaranteed unchanged:

- `services/standardizer.py` remains untouched
- `StandardizationResult` structure is unchanged
- executor error text and suggestion formatting remain unchanged
- `_standardization_records` stays as `{"param", ...result.to_dict()}`
- `meteorology=.sfc` and `meteorology=custom` still produce no executor record
- `pollutants` list behavior remains tolerant: unresolved items are kept, not raised
- `llm_enabled=False` reproduces the legacy pure-rule behavior

Additions:

- new strategies: `llm`, `passthrough`
- new module: `services/standardization_engine.py`
- new batch error type: `BatchStandardizationError` (internal to engine, converted back to executor `StandardizationError`)

## Performance Considerations

- Rule path remains in-process and synchronous.
- LLM client is lazily initialized.
- LLM calls are skipped entirely when rules succeed.
- LLM calls are bounded by `llm_timeout` and `llm_max_retries`.
- Rule parity is preserved by reusing the legacy lookup tables and methods.

Mitigations for latency:

- default config keeps fast deterministic rule matching first
- LLM fallback is only used on unresolved values
- LLM failures never block the main flow beyond configured retry/timeout limits

## Roadmap

1. Current phase: API-backed LLM fallback using the existing OpenAI-compatible client.
2. Next phase: move the inference contract behind `LLMBackend` to a fine-tuned 7B model.
3. Deployment phase: switch `llm_backend` from `api` to `local` without executor changes.
4. Schema phase: optionally add explicit `standardization_type` metadata into tool schemas.

## Files Changed

- `services/standardization_engine.py`
- `core/executor.py`
- `config.py`
- `tests/test_standardization_engine.py`

## Test Results

Executed:

- `pytest tests/test_standardization_engine.py tests/test_standardizer.py tests/test_standardizer_enhanced.py tests/test_dispersion_integration.py -q`
  Result: `138 passed`
- `pytest tests/test_router_contracts.py tests/test_router_state_loop.py tests/test_dispersion_tool.py -q`
  Result: `46 passed`
- `pytest -q`
  Result: `623 passed`
- `python main.py health`
  Result: `9/9 tools OK`

Rule-mode validation sample:

```text
pollutant            | NOx                  -> NOx                       | exact       | 1.00
pollutant            | 氮氧化物                 -> NOx                       | alias       | 0.95
vehicle_type         | Passenger Car        -> Passenger Car             | exact       | 1.00
vehicle_type         | 小汽车                  -> Passenger Car             | alias       | 0.95
season               | 夏天                   -> 夏季                        | alias       | 0.95
season               | winter               -> 冬季                        | alias       | 0.95
stability_class      | C                    -> N2                        | alias       | 0.95
stability_class      | 不稳定                  -> U                         | alias       | 0.95
meteorology          | urban_summer_day     -> urban_summer_day          | exact       | 1.00
meteorology          | 城市夏季白天               -> urban_summer_day          | alias       | 0.95
meteorology          | /path/to/met.sfc     -> /path/to/met.sfc          | passthrough | 1.00
meteorology          | custom               -> custom                    | passthrough | 1.00
```

Live API-backed LLM integration was not executed in this run. LLM behavior is covered by unit tests with mocked backend responses and error paths.
