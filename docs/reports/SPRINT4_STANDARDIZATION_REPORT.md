# Sprint 4: Parameter Standardization Enhancement Report

## 1. Files Created or Modified

- `services/standardizer.py`: added `StandardizationResult`, detailed vehicle/pollutant standardization, season and road type standardization, and robust lookup handling.
- `config/unified_mappings.yaml`: added the new `road_types` alias section.
- `core/executor.py`: changed `_standardize_arguments()` to return `(args, records)`, preserved backward behavior, and attached structured standardization records to execution results.
- `core/router.py`: added `PARAMETER_STANDARDIZATION` trace recording before `TOOL_EXECUTION`.
- `tests/test_standardizer_enhanced.py`: added Sprint 4 regression coverage for detailed results, season/road type standardization, and executor standardization records.
- `SPRINT4_STANDARDIZATION_REPORT.md`: this implementation report.

## 2. `StandardizationResult` Dataclass

```python
@dataclass
class StandardizationResult:
    """Structured result of a parameter standardization operation."""

    success: bool
    original: str
    normalized: Optional[str] = None
    strategy: str = "none"  # exact / alias / fuzzy / abstain / default
    confidence: float = 0.0
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "success": self.success,
            "original": self.original,
            "normalized": self.normalized,
            "strategy": self.strategy,
            "confidence": self.confidence,
        }
        if self.suggestions:
            result["suggestions"] = self.suggestions
        return result
```

## 3. `standardize_vehicle_detailed()` and `standardize_pollutant_detailed()`

```python
def standardize_vehicle_detailed(self, raw_input: str) -> StandardizationResult:
    """Standardize vehicle type with full result details."""
    if raw_input is None or not str(raw_input).strip():
        return StandardizationResult(success=False, original=raw_input or "", strategy="none")

    cleaned = str(raw_input).strip()
    cleaned_lower = cleaned.lower()

    if cleaned_lower in self.vehicle_lookup:
        normalized = self.vehicle_lookup[cleaned_lower]
        strategy = "exact" if cleaned == normalized else "alias"
        confidence = 1.0 if strategy == "exact" else 0.95
        logger.debug(f"Vehicle {strategy} match: '{cleaned}' -> '{normalized}'")
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=normalized,
            strategy=strategy,
            confidence=confidence,
        )

    best_match = None
    best_score = 0
    for alias, standard_name in self.vehicle_lookup.items():
        score = self._fuzzy_ratio(cleaned, alias)
        if score > best_score:
            best_score = score
            best_match = standard_name

    if best_score >= 70 and best_match:
        logger.debug(f"Vehicle fuzzy match: '{cleaned}' -> '{best_match}' (score: {best_score})")
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=best_match,
            strategy="fuzzy",
            confidence=round(best_score / 100, 2),
        )

    local_result = self._try_local_standardization(cleaned, self.vehicle_lookup, "standardize_vehicle")
    if local_result:
        logger.info(
            "Vehicle local model: '%s' -> '%s' (confidence: %s)",
            cleaned,
            local_result.normalized,
            local_result.confidence,
        )
        return local_result

    suggestions = self.get_vehicle_suggestions(cleaned, top_k=5)
    logger.warning(f"Cannot standardize vehicle: '{cleaned}'")
    return StandardizationResult(
        success=False,
        original=cleaned,
        strategy="abstain",
        confidence=0.0,
        suggestions=suggestions,
    )

def standardize_pollutant_detailed(self, raw_input: str) -> StandardizationResult:
    """Standardize pollutant with full result details."""
    if raw_input is None or not str(raw_input).strip():
        return StandardizationResult(success=False, original=raw_input or "", strategy="none")

    cleaned = str(raw_input).strip()
    cleaned_lower = cleaned.lower()

    if cleaned_lower in self.pollutant_lookup:
        normalized = self.pollutant_lookup[cleaned_lower]
        strategy = "exact" if cleaned == normalized else "alias"
        confidence = 1.0 if strategy == "exact" else 0.95
        logger.debug(f"Pollutant {strategy} match: '{cleaned}' -> '{normalized}'")
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=normalized,
            strategy=strategy,
            confidence=confidence,
        )

    best_match = None
    best_score = 0
    for alias, standard_name in self.pollutant_lookup.items():
        score = self._fuzzy_ratio(cleaned, alias)
        if score > best_score:
            best_score = score
            best_match = standard_name

    if best_score >= 80 and best_match:
        logger.debug(f"Pollutant fuzzy match: '{cleaned}' -> '{best_match}' (score: {best_score})")
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=best_match,
            strategy="fuzzy",
            confidence=round(best_score / 100, 2),
        )

    local_result = self._try_local_standardization(cleaned, self.pollutant_lookup, "standardize_pollutant")
    if local_result:
        logger.info(
            "Pollutant local model: '%s' -> '%s' (confidence: %s)",
            cleaned,
            local_result.normalized,
            local_result.confidence,
        )
        return local_result

    suggestions = self.get_pollutant_suggestions(cleaned, top_k=5)
    logger.warning(f"Cannot standardize pollutant: '{cleaned}'")
    return StandardizationResult(
        success=False,
        original=cleaned,
        strategy="abstain",
        confidence=0.0,
        suggestions=suggestions,
    )
```

## 4. `standardize_season()` and `standardize_road_type()`

```python
def standardize_season(self, raw_input: str) -> StandardizationResult:
    """Standardize season parameter."""
    if raw_input is None or not str(raw_input).strip():
        return StandardizationResult(
            success=True,
            original=raw_input or "",
            normalized=self.season_default,
            strategy="default",
            confidence=1.0,
        )

    cleaned = str(raw_input).strip()
    cleaned_lower = cleaned.lower()

    if cleaned_lower in self.season_lookup:
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=self.season_lookup[cleaned_lower],
            strategy="alias",
            confidence=0.95,
        )

    best_match = None
    best_score = 0
    for alias, standard_name in self.season_lookup.items():
        score = self._fuzzy_ratio(cleaned_lower, alias)
        if score > best_score:
            best_score = score
            best_match = standard_name

    if best_score >= 60 and best_match:
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=best_match,
            strategy="fuzzy",
            confidence=round(best_score / 100, 2),
        )

    return StandardizationResult(
        success=True,
        original=cleaned,
        normalized=self.season_default,
        strategy="default",
        confidence=0.5,
        suggestions=sorted(set(self.season_lookup.values())),
    )

def standardize_road_type(self, raw_input: str) -> StandardizationResult:
    """Standardize road type parameter."""
    if raw_input is None or not str(raw_input).strip():
        return StandardizationResult(
            success=True,
            original=raw_input or "",
            normalized=self.road_type_default,
            strategy="default",
            confidence=1.0,
        )

    cleaned = str(raw_input).strip()
    cleaned_lower = cleaned.lower()

    if cleaned_lower in self.road_type_lookup:
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=self.road_type_lookup[cleaned_lower],
            strategy="alias",
            confidence=0.95,
        )

    best_match = None
    best_score = 0
    for alias, standard_name in self.road_type_lookup.items():
        score = self._fuzzy_ratio(cleaned_lower, alias)
        if score > best_score:
            best_score = score
            best_match = standard_name

    if best_score >= 60 and best_match:
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=best_match,
            strategy="fuzzy",
            confidence=round(best_score / 100, 2),
        )

    return StandardizationResult(
        success=True,
        original=cleaned,
        normalized=self.road_type_default,
        strategy="default",
        confidence=0.5,
        suggestions=sorted(set(self.road_type_lookup.values())),
    )
```

## 5. `road_types` Section Added to `unified_mappings.yaml`

```yaml
road_types:
  快速路:
    aliases:
      - 城市快速路
      - 快速路
      - urban expressway
      - expressway
  高速公路:
    aliases:
      - 高速
      - freeway
      - highway
      - motorway
      - interstate
  主干道:
    aliases:
      - 主干路
      - 干道
      - arterial
      - major road
      - arterial road
  次干道:
    aliases:
      - 次干路
      - minor arterial
      - secondary road
      - collector road
  支路:
    aliases:
      - 地方道路
      - 支路
      - local road
      - local
      - residential
      - 居民区道路
```

## 6. Rewritten `_standardize_arguments()` in `executor.py`

```python
def _standardize_arguments(
    self,
    tool_name: str,
    arguments: Dict[str, Any],
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Standardize tool arguments using domain-specific rules.

    Args:
        tool_name: Tool name (for context)
        arguments: Raw arguments from LLM

    Returns:
        Tuple of (standardized_arguments, standardization_records).

    Raises:
        StandardizationError: If standardization fails
    """
    if not self.runtime_config.enable_executor_standardization:
        return dict(arguments or {}), []

    standardized: Dict[str, Any] = {}
    records: List[Dict[str, Any]] = []

    for key, value in dict(arguments or {}).items():
        if value is None:
            standardized[key] = value
            continue

        if key == "vehicle_type":
            result = self.standardizer.standardize_vehicle_detailed(value)
            record = {"param": "vehicle_type", **result.to_dict()}
            records.append(record)
            if result.success:
                standardized[key] = result.normalized
                logger.debug(f"Standardized vehicle: '{value}' -> '{result.normalized}'")
            else:
                raise StandardizationError(
                    f"Cannot standardize vehicle type '{value}'. "
                    f"Suggestions: {', '.join(result.suggestions[:5])}",
                    suggestions=result.suggestions,
                    records=records,
                )

        elif key == "pollutant":
            result = self.standardizer.standardize_pollutant_detailed(value)
            record = {"param": "pollutant", **result.to_dict()}
            records.append(record)
            if result.success:
                standardized[key] = result.normalized
                logger.debug(f"Standardized pollutant: '{value}' -> '{result.normalized}'")
            else:
                raise StandardizationError(
                    f"Cannot standardize pollutant '{value}'. "
                    f"Suggestions: {', '.join(result.suggestions[:5])}",
                    suggestions=result.suggestions,
                    records=records,
                )

        elif key == "pollutants" and isinstance(value, list):
            std_list = []
            for pol in value:
                result = self.standardizer.standardize_pollutant_detailed(pol)
                records.append({"param": f"pollutants[{pol}]", **result.to_dict()})
                if result.success:
                    std_list.append(result.normalized)
                else:
                    std_list.append(pol)
                    logger.warning(f"Could not standardize pollutant: '{pol}'")
            standardized[key] = std_list

        elif key == "season":
            result = self.standardizer.standardize_season(value)
            records.append({"param": "season", **result.to_dict()})
            standardized[key] = result.normalized

        elif key == "road_type":
            result = self.standardizer.standardize_road_type(value)
            records.append({"param": "road_type", **result.to_dict()})
            standardized[key] = result.normalized

        else:
            standardized[key] = value

    return standardized, records
```

## 7. Trace Integration Code in `router.py`

```python
if trace_obj:
    std_records = result.get("_standardization_records", [])
    if std_records:
        std_summary_parts = []
        for rec in std_records:
            if rec.get("original") != rec.get("normalized") and rec.get("normalized"):
                std_summary_parts.append(
                    f"{rec.get('param', '?')}: '{rec.get('original')}' -> "
                    f"'{rec.get('normalized')}' "
                    f"({rec.get('strategy', '?')}, conf={rec.get('confidence', 0):.2f})"
                )

        if std_summary_parts:
            trace_obj.record(
                step_type=TraceStepType.PARAMETER_STANDARDIZATION,
                stage_before=TaskStage.EXECUTING.value,
                action="standardize_parameters",
                reasoning="; ".join(std_summary_parts),
                standardization_records=std_records,
            )
    trace_obj.record(
        step_type=TraceStepType.TOOL_EXECUTION,
        stage_before=TaskStage.EXECUTING.value,
        action=tool_call.name,
        input_summary={
            "arguments": {
                key: str(value)[:100]
                for key, value in tool_call.arguments.items()
            }
        },
        output_summary={
            "success": result.get("success", False),
            "message": str(result.get("message", ""))[:200],
        },
        confidence=None,
        reasoning=result.get("summary", ""),
        duration_ms=elapsed_ms,
        standardization_records=std_records or None,
        error=result.get("message") if result.get("error") else None,
    )
```

## 8. Full Content of `tests/test_standardizer_enhanced.py`

```python
"""Tests for enhanced standardization: season, road_type, detailed results."""

import json

import pytest


class TestStandardizationResult:
    def test_vehicle_detailed_exact(self):
        """Exact vehicle match returns strategy='exact', confidence=1.0."""
        from services.standardizer import get_standardizer

        std = get_standardizer()
        result = std.standardize_vehicle_detailed("Passenger Car")
        assert result.success is True
        assert result.normalized == "Passenger Car"
        assert result.strategy == "exact"
        assert result.confidence == 1.0

    def test_vehicle_detailed_alias(self):
        """Chinese alias returns strategy='alias'."""
        from services.standardizer import get_standardizer

        std = get_standardizer()
        result = std.standardize_vehicle_detailed("小汽车")
        assert result.success is True
        assert result.normalized == "Passenger Car"
        assert result.strategy in ("exact", "alias")

    def test_vehicle_detailed_abstain(self):
        """Unknown input returns success=False with suggestions."""
        from services.standardizer import get_standardizer

        std = get_standardizer()
        result = std.standardize_vehicle_detailed("飞机")
        assert result.success is False
        assert result.strategy == "abstain"
        assert len(result.suggestions) > 0

    def test_vehicle_detailed_to_dict(self):
        """to_dict produces JSON-serializable output."""
        from services.standardizer import get_standardizer

        std = get_standardizer()
        result = std.standardize_vehicle_detailed("公交")
        data = result.to_dict()
        json.dumps(data)
        assert "strategy" in data


class TestSeasonStandardization:
    def test_chinese_summer(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_season("夏天")
        assert result.success is True
        assert "夏" in result.normalized

    def test_english_winter(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_season("winter")
        assert result.success is True
        assert "冬" in result.normalized

    def test_empty_returns_default(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_season("")
        assert result.success is True
        assert result.strategy == "default"

    def test_unknown_returns_default(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_season("monsoon")
        assert result.success is True


class TestRoadTypeStandardization:
    def test_chinese_freeway(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_road_type("高速公路")
        assert result.success is True
        assert result.normalized is not None

    def test_english_freeway(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_road_type("freeway")
        assert result.success is True

    def test_chinese_expressway(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_road_type("城市快速路")
        assert result.success is True

    def test_empty_returns_default(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_road_type("")
        assert result.success is True
        assert result.strategy == "default"

    def test_english_local(self):
        from services.standardizer import get_standardizer

        result = get_standardizer().standardize_road_type("local road")
        assert result.success is True


class TestExecutorStandardizationRecords:
    def test_standardize_returns_tuple(self):
        """_standardize_arguments must return (args, records) tuple."""
        from core.executor import ToolExecutor

        executor = ToolExecutor()
        args, records = executor._standardize_arguments(
            "query_emission_factors",
            {"vehicle_type": "小汽车", "pollutant": "CO2", "model_year": 2020},
        )
        assert isinstance(args, dict)
        assert isinstance(records, list)
        assert len(records) >= 2
        assert args["vehicle_type"] == "Passenger Car"

    def test_season_standardized(self):
        """Season parameter should be standardized."""
        from core.executor import ToolExecutor

        executor = ToolExecutor()
        args, records = executor._standardize_arguments(
            "query_emission_factors",
            {"vehicle_type": "Passenger Car", "season": "冬天", "model_year": 2020},
        )
        assert "冬" in args["season"]
        season_records = [record for record in records if record.get("param") == "season"]
        assert len(season_records) == 1

    def test_road_type_standardized(self):
        """Road type parameter should be standardized."""
        from core.executor import ToolExecutor

        executor = ToolExecutor()
        args, records = executor._standardize_arguments(
            "query_emission_factors",
            {"vehicle_type": "Passenger Car", "road_type": "高速", "model_year": 2020},
        )
        road_records = [record for record in records if record.get("param") == "road_type"]
        assert len(road_records) == 1
        assert road_records[0]["success"] is True
        assert args["road_type"] == "高速公路"

    def test_abstain_raises_with_suggestions(self):
        """Unknown vehicle should raise StandardizationError with suggestions."""
        from core.executor import ToolExecutor, StandardizationError

        executor = ToolExecutor()
        with pytest.raises(StandardizationError) as exc_info:
            executor._standardize_arguments(
                "query_emission_factors",
                {"vehicle_type": "飞机", "model_year": 2020},
            )
        assert len(exc_info.value.suggestions) > 0
```

## 9. Test Results

### `pytest tests/test_standardizer.py -v`

```text
============================= test session starts ==============================
platform linux -- Python 3.13.9, pytest-9.0.2, pluggy-1.5.0 -- /home/kirito/miniconda3/bin/python3.13
cachedir: .pytest_cache
rootdir: /home/kirito/Agent1/emission_agent
configfile: pyproject.toml
plugins: anyio-4.12.1
collecting ... collected 14 items

tests/test_standardizer.py::TestVehicleStandardization::test_exact_english PASSED [  7%]
tests/test_standardizer.py::TestVehicleStandardization::test_exact_chinese PASSED [ 14%]
tests/test_standardizer.py::TestVehicleStandardization::test_alias_chinese PASSED [ 21%]
tests/test_standardizer.py::TestVehicleStandardization::test_case_insensitive PASSED [ 28%]
tests/test_standardizer.py::TestVehicleStandardization::test_unknown_returns_none PASSED [ 35%]
tests/test_standardizer.py::TestVehicleStandardization::test_empty_returns_none PASSED [ 42%]
tests/test_standardizer.py::TestVehicleStandardization::test_suggestions_non_empty PASSED [ 50%]
tests/test_standardizer.py::TestPollutantStandardization::test_exact_english PASSED [ 57%]
tests/test_standardizer.py::TestPollutantStandardization::test_case_insensitive PASSED [ 64%]
tests/test_standardizer.py::TestPollutantStandardization::test_chinese_name PASSED [ 71%]
tests/test_standardizer.py::TestPollutantStandardization::test_unknown_returns_none PASSED [ 78%]
tests/test_standardizer.py::TestPollutantStandardization::test_suggestions_non_empty PASSED [ 85%]
tests/test_standardizer.py::TestColumnMapping::test_micro_speed_column PASSED [ 92%]
tests/test_standardizer.py::TestColumnMapping::test_empty_columns PASSED [100%]

============================== 14 passed in 0.07s ==============================
```

### `pytest tests/test_standardizer_enhanced.py -v`

```text
============================= test session starts ==============================
platform linux -- Python 3.13.9, pytest-9.0.2, pluggy-1.5.0 -- /home/kirito/miniconda3/bin/python3.13
cachedir: .pytest_cache
rootdir: /home/kirito/Agent1/emission_agent
configfile: pyproject.toml
plugins: anyio-4.12.1
collecting ... collected 17 items

tests/test_standardizer_enhanced.py::TestStandardizationResult::test_vehicle_detailed_exact PASSED [  5%]
tests/test_standardizer_enhanced.py::TestStandardizationResult::test_vehicle_detailed_alias PASSED [ 11%]
tests/test_standardizer_enhanced.py::TestStandardizationResult::test_vehicle_detailed_abstain PASSED [ 17%]
tests/test_standardizer_enhanced.py::TestStandardizationResult::test_vehicle_detailed_to_dict PASSED [ 23%]
tests/test_standardizer_enhanced.py::TestSeasonStandardization::test_chinese_summer PASSED [ 29%]
tests/test_standardizer_enhanced.py::TestSeasonStandardization::test_english_winter PASSED [ 35%]
tests/test_standardizer_enhanced.py::TestSeasonStandardization::test_empty_returns_default PASSED [ 41%]
tests/test_standardizer_enhanced.py::TestSeasonStandardization::test_unknown_returns_default PASSED [ 47%]
tests/test_standardizer_enhanced.py::TestRoadTypeStandardization::test_chinese_freeway PASSED [ 52%]
tests/test_standardizer_enhanced.py::TestRoadTypeStandardization::test_english_freeway PASSED [ 58%]
tests/test_standardizer_enhanced.py::TestRoadTypeStandardization::test_chinese_expressway PASSED [ 64%]
tests/test_standardizer_enhanced.py::TestRoadTypeStandardization::test_empty_returns_default PASSED [ 70%]
tests/test_standardizer_enhanced.py::TestRoadTypeStandardization::test_english_local PASSED [ 76%]
tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_standardize_returns_tuple PASSED [ 82%]
tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_season_standardized PASSED [ 88%]
tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_road_type_standardized PASSED [ 94%]
tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_abstain_raises_with_suggestions PASSED [100%]

=============================== warnings summary ===============================
tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_standardize_returns_tuple
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyPacked has no __module__ attribute

tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_standardize_returns_tuple
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyObject has no __module__ attribute

tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_standardize_returns_tuple
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type swigvarlink has no __module__ attribute

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================== 17 passed, 3 warnings in 2.12s ========================
```

### `pytest tests/test_task_state.py tests/test_trace.py tests/test_router_state_loop.py -v`

```text
============================= test session starts ==============================
platform linux -- Python 3.13.9, pytest-9.0.2, pluggy-1.5.0 -- /home/kirito/miniconda3/bin/python3.13
cachedir: .pytest_cache
rootdir: /home/kirito/Agent1/emission_agent
configfile: pyproject.toml
plugins: anyio-4.12.1
collecting ... collected 27 items

tests/test_task_state.py::test_initialize_without_file PASSED            [  3%]
tests/test_task_state.py::test_initialize_with_file PASSED               [  7%]
tests/test_task_state.py::test_initialize_with_memory PASSED             [ 11%]
tests/test_task_state.py::test_valid_transitions PASSED                  [ 14%]
tests/test_task_state.py::test_invalid_transition_raises PASSED          [ 18%]
tests/test_task_state.py::test_should_stop_at_terminal[DONE] PASSED      [ 22%]
tests/test_task_state.py::test_should_stop_at_terminal[NEEDS_CLARIFICATION] PASSED [ 25%]
tests/test_task_state.py::test_should_stop_at_max_steps PASSED           [ 29%]
tests/test_task_state.py::test_to_dict_serializable PASSED               [ 33%]
tests/test_task_state.py::test_update_file_context PASSED                [ 37%]
tests/test_trace.py::TestTraceStep::test_to_dict_excludes_none PASSED    [ 40%]
tests/test_trace.py::TestTraceStep::test_to_dict_includes_set_fields PASSED [ 44%]
tests/test_trace.py::TestTrace::test_start_creates_with_timestamp PASSED [ 48%]
tests/test_trace.py::TestTrace::test_record_appends_step PASSED          [ 51%]
tests/test_trace.py::TestTrace::test_record_auto_increments_index PASSED [ 55%]
tests/test_trace.py::TestTrace::test_finish_sets_end_time_and_duration PASSED [ 59%]
tests/test_trace.py::TestTrace::test_to_dict_serializable PASSED         [ 62%]
tests/test_trace.py::TestTrace::test_to_user_friendly_file_grounding PASSED [ 66%]
tests/test_trace.py::TestTrace::test_to_user_friendly_tool_execution_success PASSED [ 70%]
tests/test_trace.py::TestTrace::test_to_user_friendly_tool_execution_error PASSED [ 74%]
tests/test_trace.py::TestTrace::test_to_user_friendly_skips_state_transition PASSED [ 77%]
tests/test_trace.py::TestTrace::test_to_user_friendly_clarification PASSED [ 81%]
tests/test_trace.py::TestTrace::test_full_workflow_trace PASSED          [ 85%]
tests/test_router_state_loop.py::test_legacy_loop_unchanged[asyncio] PASSED [ 88%]
tests/test_router_state_loop.py::test_state_loop_no_tool_call[asyncio] PASSED [ 92%]
tests/test_router_state_loop.py::test_state_loop_with_tool_call[asyncio] PASSED [ 96%]
tests/test_router_state_loop.py::test_state_loop_produces_trace[asyncio] PASSED [100%]

============================== 27 passed in 0.56s ==============================
```

### `pytest`

```text
============================= test session starts ==============================
platform linux -- Python 3.13.9, pytest-9.0.2, pluggy-1.5.0 -- /home/kirito/miniconda3/bin/python3.13
cachedir: .pytest_cache
rootdir: /home/kirito/Agent1/emission_agent
configfile: pyproject.toml
testpaths: tests
plugins: anyio-4.12.1
collecting ... 
collected 141 items

tests/test_api_chart_utils.py::test_build_emission_chart_data_single_pollutant_preserves_curve_shape PASSED [  0%]
tests/test_api_chart_utils.py::test_build_emission_chart_data_multi_pollutant_converts_speed_curve_to_curve PASSED [  1%]
tests/test_api_chart_utils.py::test_extract_key_points_supports_direct_and_legacy_formats PASSED [  2%]
tests/test_api_chart_utils.py::test_routes_module_keeps_chart_helper_names PASSED [  2%]
tests/test_api_response_utils.py::test_clean_reply_text_removes_json_blocks_and_extra_blank_lines PASSED [  3%]
tests/test_api_response_utils.py::test_friendly_error_message_handles_connection_failures PASSED [  4%]
tests/test_api_response_utils.py::test_normalize_and_attach_download_metadata_preserve_existing_shape PASSED [  4%]
tests/test_api_response_utils.py::test_routes_module_keeps_helper_names_and_health_route_registration PASSED [  5%]
tests/test_api_route_contracts.py::test_api_status_routes_return_expected_top_level_shape[asyncio] PASSED [  6%]
tests/test_api_route_contracts.py::test_file_preview_route_detects_trajectory_csv_with_expected_warnings[asyncio] PASSED [  7%]
tests/test_api_route_contracts.py::test_session_routes_create_list_and_history_backfill_legacy_download_metadata[asyncio] PASSED [  7%]
tests/test_calculators.py::TestVSPCalculator::test_idle_opmode PASSED    [  8%]
tests/test_calculators.py::TestVSPCalculator::test_low_speed_opmode PASSED [  9%]
tests/test_calculators.py::TestVSPCalculator::test_medium_speed_opmode PASSED [  9%]
tests/test_calculators.py::TestVSPCalculator::test_high_speed_opmode PASSED [ 10%]
tests/test_calculators.py::TestVSPCalculator::test_vsp_calculation_passenger_car PASSED [ 11%]
tests/test_calculators.py::TestVSPCalculator::test_vsp_with_acceleration PASSED [ 12%]
tests/test_calculators.py::TestVSPCalculator::test_vsp_bin_range PASSED  [ 12%]
tests/test_calculators.py::TestVSPCalculator::test_trajectory_vsp_batch PASSED [ 13%]
tests/test_calculators.py::TestVSPCalculator::test_invalid_vehicle_type_raises PASSED [ 14%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_simple_trajectory_calculation PASSED [ 14%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_summary_statistics PASSED [ 15%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_unknown_vehicle_type_error PASSED [ 16%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_empty_trajectory_error PASSED [ 17%]
tests/test_calculators.py::TestMicroEmissionCalculator::test_year_to_age_group PASSED [ 17%]
tests/test_calculators.py::TestMacroEmissionCalculator::test_load_emission_matrix_reuses_cached_dataframe PASSED [ 18%]
tests/test_calculators.py::TestMacroEmissionCalculator::test_query_emission_rate_matches_legacy_scan PASSED [ 19%]
tests/test_calculators.py::TestMacroEmissionCalculator::test_query_emission_rate_rebuilds_lookup_for_external_matrix PASSED [ 19%]
tests/test_calculators.py::TestMacroEmissionCalculator::test_calculate_matches_legacy_lookup_path PASSED [ 20%]
tests/test_calculators.py::TestEmissionFactorCalculator::test_vehicle_type_mapping_complete PASSED [ 21%]
tests/test_calculators.py::TestEmissionFactorCalculator::test_pollutant_mapping_complete PASSED [ 21%]
tests/test_config.py::TestConfigLoading::test_config_creates_successfully PASSED [ 22%]
tests/test_config.py::TestConfigLoading::test_config_singleton PASSED    [ 23%]
tests/test_config.py::TestConfigLoading::test_config_reset PASSED        [ 24%]
tests/test_config.py::TestConfigLoading::test_feature_flags_default_true PASSED [ 24%]
tests/test_config.py::TestConfigLoading::test_feature_flag_override PASSED [ 25%]
tests/test_config.py::TestConfigLoading::test_directories_created PASSED [ 26%]
tests/test_config.py::TestJWTSecretLoading::test_jwt_secret_from_env PASSED [ 26%]
tests/test_config.py::TestJWTSecretLoading::test_auth_module_loads_dotenv_before_reading_secret PASSED [ 27%]
tests/test_config.py::TestJWTSecretLoading::test_jwt_default_is_not_production_safe PASSED [ 28%]
tests/test_file_grounding_enhanced.py::TestValueFeatureAnalysis::test_vehicle_speed_detection PASSED [ 29%]
tests/test_file_grounding_enhanced.py::TestValueFeatureAnalysis::test_link_speed_detection PASSED [ 29%]
tests/test_file_grounding_enhanced.py::TestValueFeatureAnalysis::test_acceleration_detection PASSED [ 30%]
tests/test_file_grounding_enhanced.py::TestValueFeatureAnalysis::test_traffic_flow_detection PASSED [ 31%]
tests/test_file_grounding_enhanced.py::TestValueFeatureAnalysis::test_fraction_detection PASSED [ 31%]
tests/test_file_grounding_enhanced.py::TestValueFeatureAnalysis::test_negative_column_excluded PASSED [ 32%]
tests/test_file_grounding_enhanced.py::TestValueFeatureAnalysis::test_non_numeric_column_skipped PASSED [ 33%]
tests/test_file_grounding_enhanced.py::TestValueFeatureAnalysis::test_empty_dataframe PASSED [ 34%]
tests/test_file_grounding_enhanced.py::TestValueFeatureAnalysis::test_all_nan_column PASSED [ 34%]
tests/test_file_grounding_enhanced.py::TestMultiSignalTaskIdentification::test_standard_micro_file PASSED [ 35%]
tests/test_file_grounding_enhanced.py::TestMultiSignalTaskIdentification::test_standard_macro_file PASSED [ 36%]
tests/test_file_grounding_enhanced.py::TestMultiSignalTaskIdentification::test_ambiguous_column_names_resolved_by_values PASSED [ 36%]
tests/test_file_grounding_enhanced.py::TestMultiSignalTaskIdentification::test_unknown_columns_with_value_hints PASSED [ 37%]
tests/test_file_grounding_enhanced.py::TestMultiSignalTaskIdentification::test_evidence_contains_all_signal_types PASSED [ 38%]
tests/test_file_grounding_enhanced.py::TestMultiSignalTaskIdentification::test_no_signals_returns_unknown PASSED [ 39%]
tests/test_file_grounding_enhanced.py::TestMultiSignalTaskIdentification::test_evidence_output_is_list_of_strings PASSED [ 39%]
tests/test_file_grounding_enhanced.py::TestAnalyzeStructureIntegration::test_structure_output_includes_evidence PASSED [ 40%]
tests/test_file_grounding_enhanced.py::TestAnalyzeStructureIntegration::test_structure_output_backward_compatible PASSED [ 41%]
tests/test_micro_excel_handler.py::test_read_trajectory_from_excel_strips_columns_without_stdout_noise PASSED [ 41%]
tests/test_phase1b_consolidation.py::test_sync_llm_package_export_uses_purpose_assignment PASSED [ 42%]
tests/test_phase1b_consolidation.py::test_async_llm_service_uses_purpose_assignment PASSED [ 43%]
tests/test_phase1b_consolidation.py::test_async_llm_factory_uses_purpose_default_model PASSED [ 43%]
tests/test_phase1b_consolidation.py::test_async_llm_factory_preserves_explicit_model_override PASSED [ 44%]
tests/test_phase1b_consolidation.py::test_legacy_micro_skill_import_path_remains_available PASSED [ 45%]
tests/test_router_contracts.py::test_build_memory_tool_calls_compacts_large_payloads_for_follow_up_turns PASSED [ 46%]
tests/test_router_contracts.py::test_router_memory_utils_match_core_router_compatibility_wrappers PASSED [ 46%]
tests/test_router_contracts.py::test_router_payload_utils_match_core_router_compatibility_wrappers PASSED [ 47%]
tests/test_router_contracts.py::test_router_render_utils_match_core_router_compatibility_wrappers PASSED [ 48%]
tests/test_router_contracts.py::test_router_synthesis_utils_match_core_router_compatibility_wrappers PASSED [ 48%]
tests/test_router_contracts.py::test_maybe_short_circuit_synthesis_covers_knowledge_failure_and_single_tool_paths PASSED [ 49%]
tests/test_router_contracts.py::test_build_synthesis_request_and_keyword_detection_preserve_llm_input_contract PASSED [ 50%]
tests/test_router_contracts.py::test_render_single_tool_success_formats_micro_results_with_key_sections PASSED [ 51%]
tests/test_router_contracts.py::test_filter_results_and_error_formatting_keep_retry_and_synthesis_signal PASSED [ 51%]
tests/test_router_contracts.py::test_extract_chart_data_prefers_explicit_chart_payload PASSED [ 52%]
tests/test_router_contracts.py::test_extract_chart_data_formats_emission_factor_curves_for_frontend PASSED [ 53%]
tests/test_router_contracts.py::test_extract_table_data_formats_macro_results_preview_for_frontend PASSED [ 53%]
tests/test_router_contracts.py::test_extract_table_data_formats_emission_factor_preview_for_frontend PASSED [ 54%]
tests/test_router_contracts.py::test_extract_table_data_formats_micro_results_preview_for_frontend PASSED [ 55%]
tests/test_router_contracts.py::test_extract_download_and_map_payloads_support_current_and_legacy_locations PASSED [ 56%]
tests/test_router_contracts.py::test_format_results_as_fallback_preserves_success_and_error_sections PASSED [ 56%]
tests/test_router_contracts.py::test_synthesize_results_calls_llm_with_built_request_and_returns_content[asyncio] PASSED [ 57%]
tests/test_router_contracts.py::test_synthesize_results_short_circuits_failures_without_calling_llm[asyncio] PASSED [ 58%]
tests/test_router_state_loop.py::test_legacy_loop_unchanged[asyncio] PASSED [ 58%]
tests/test_router_state_loop.py::test_state_loop_no_tool_call[asyncio] PASSED [ 59%]
tests/test_router_state_loop.py::test_state_loop_with_tool_call[asyncio] PASSED [ 60%]
tests/test_router_state_loop.py::test_state_loop_produces_trace[asyncio] PASSED [ 60%]
tests/test_smoke_suite.py::test_run_smoke_suite_writes_summary_with_expected_defaults PASSED [ 61%]
tests/test_standardizer.py::TestVehicleStandardization::test_exact_english PASSED [ 62%]
tests/test_standardizer.py::TestVehicleStandardization::test_exact_chinese PASSED [ 63%]
tests/test_standardizer.py::TestVehicleStandardization::test_alias_chinese PASSED [ 63%]
tests/test_standardizer.py::TestVehicleStandardization::test_case_insensitive PASSED [ 64%]
tests/test_standardizer.py::TestVehicleStandardization::test_unknown_returns_none PASSED [ 65%]
tests/test_standardizer.py::TestVehicleStandardization::test_empty_returns_none PASSED [ 65%]
tests/test_standardizer.py::TestVehicleStandardization::test_suggestions_non_empty PASSED [ 66%]
tests/test_standardizer.py::TestPollutantStandardization::test_exact_english PASSED [ 67%]
tests/test_standardizer.py::TestPollutantStandardization::test_case_insensitive PASSED [ 68%]
tests/test_standardizer.py::TestPollutantStandardization::test_chinese_name PASSED [ 68%]
tests/test_standardizer.py::TestPollutantStandardization::test_unknown_returns_none PASSED [ 69%]
tests/test_standardizer.py::TestPollutantStandardization::test_suggestions_non_empty PASSED [ 70%]
tests/test_standardizer.py::TestColumnMapping::test_micro_speed_column PASSED [ 70%]
tests/test_standardizer.py::TestColumnMapping::test_empty_columns PASSED [ 71%]
tests/test_standardizer_enhanced.py::TestStandardizationResult::test_vehicle_detailed_exact PASSED [ 72%]
tests/test_standardizer_enhanced.py::TestStandardizationResult::test_vehicle_detailed_alias PASSED [ 73%]
tests/test_standardizer_enhanced.py::TestStandardizationResult::test_vehicle_detailed_abstain PASSED [ 73%]
tests/test_standardizer_enhanced.py::TestStandardizationResult::test_vehicle_detailed_to_dict PASSED [ 74%]
tests/test_standardizer_enhanced.py::TestSeasonStandardization::test_chinese_summer PASSED [ 75%]
tests/test_standardizer_enhanced.py::TestSeasonStandardization::test_english_winter PASSED [ 75%]
tests/test_standardizer_enhanced.py::TestSeasonStandardization::test_empty_returns_default PASSED [ 76%]
tests/test_standardizer_enhanced.py::TestSeasonStandardization::test_unknown_returns_default PASSED [ 77%]
tests/test_standardizer_enhanced.py::TestRoadTypeStandardization::test_chinese_freeway PASSED [ 78%]
tests/test_standardizer_enhanced.py::TestRoadTypeStandardization::test_english_freeway PASSED [ 78%]
tests/test_standardizer_enhanced.py::TestRoadTypeStandardization::test_chinese_expressway PASSED [ 79%]
tests/test_standardizer_enhanced.py::TestRoadTypeStandardization::test_empty_returns_default PASSED [ 80%]
tests/test_standardizer_enhanced.py::TestRoadTypeStandardization::test_english_local PASSED [ 80%]
tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_standardize_returns_tuple PASSED [ 81%]
tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_season_standardized PASSED [ 82%]
tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_road_type_standardized PASSED [ 82%]
tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_abstain_raises_with_suggestions PASSED [ 83%]
tests/test_task_state.py::test_initialize_without_file PASSED            [ 84%]
tests/test_task_state.py::test_initialize_with_file PASSED               [ 85%]
tests/test_task_state.py::test_initialize_with_memory PASSED             [ 85%]
tests/test_task_state.py::test_valid_transitions PASSED                  [ 86%]
tests/test_task_state.py::test_invalid_transition_raises PASSED          [ 87%]
tests/test_task_state.py::test_should_stop_at_terminal[DONE] PASSED      [ 87%]
tests/test_task_state.py::test_should_stop_at_terminal[NEEDS_CLARIFICATION] PASSED [ 88%]
tests/test_task_state.py::test_should_stop_at_max_steps PASSED           [ 89%]
tests/test_task_state.py::test_to_dict_serializable PASSED               [ 90%]
tests/test_task_state.py::test_update_file_context PASSED                [ 90%]
tests/test_trace.py::TestTraceStep::test_to_dict_excludes_none PASSED    [ 91%]
tests/test_trace.py::TestTraceStep::test_to_dict_includes_set_fields PASSED [ 92%]
tests/test_trace.py::TestTrace::test_start_creates_with_timestamp PASSED [ 92%]
tests/test_trace.py::TestTrace::test_record_appends_step PASSED          [ 93%]
tests/test_trace.py::TestTrace::test_record_auto_increments_index PASSED [ 94%]
tests/test_trace.py::TestTrace::test_finish_sets_end_time_and_duration PASSED [ 95%]
tests/test_trace.py::TestTrace::test_to_dict_serializable PASSED         [ 95%]
tests/test_trace.py::TestTrace::test_to_user_friendly_file_grounding PASSED [ 96%]
tests/test_trace.py::TestTrace::test_to_user_friendly_tool_execution_success PASSED [ 97%]
tests/test_trace.py::TestTrace::test_to_user_friendly_tool_execution_error PASSED [ 97%]
tests/test_trace.py::TestTrace::test_to_user_friendly_skips_state_transition PASSED [ 98%]
tests/test_trace.py::TestTrace::test_to_user_friendly_clarification PASSED [ 99%]
tests/test_trace.py::TestTrace::test_full_workflow_trace PASSED          [100%]

=============================== warnings summary ===============================
api/main.py:73
  /home/kirito/Agent1/emission_agent/api/main.py:73: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    @app.on_event("startup")

../../miniconda3/lib/python3.13/site-packages/fastapi/applications.py:4573
../../miniconda3/lib/python3.13/site-packages/fastapi/applications.py:4573
  /home/kirito/miniconda3/lib/python3.13/site-packages/fastapi/applications.py:4573: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    return self.router.on_event(event_type)

api/main.py:88
  /home/kirito/Agent1/emission_agent/api/main.py:88: DeprecationWarning: 
          on_event is deprecated, use lifespan event handlers instead.
  
          Read more about it in the
          [FastAPI docs for Lifespan Events](https://fastapi.tiangolo.com/advanced/events/).
          
    @app.on_event("shutdown")

tests/test_api_route_contracts.py: 12 warnings
  /home/kirito/Agent1/emission_agent/api/logging_config.py:28: DeprecationWarning: datetime.datetime.utcnow() is deprecated and scheduled for removal in a future version. Use timezone-aware objects to represent datetimes in UTC: datetime.datetime.now(datetime.UTC).
    "timestamp": datetime.utcnow().isoformat() + "Z",

tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_standardize_returns_tuple
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyPacked has no __module__ attribute

tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_standardize_returns_tuple
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type SwigPyObject has no __module__ attribute

tests/test_standardizer_enhanced.py::TestExecutorStandardizationRecords::test_standardize_returns_tuple
  <frozen importlib._bootstrap>:488: DeprecationWarning: builtin type swigvarlink has no __module__ attribute

-- Docs: https://docs.pytest.org/en/stable/how-to/capture-warnings.html
======================= 141 passed, 19 warnings in 5.09s =======================
```

## 10. Output of `python main.py health`

```text
WARNING:skills.knowledge.retriever:FlagEmbedding 未安装，本地embedding功能不可用
╭───────────────────╮
│ Tool Health Check │
╰───────────────────╯
OK query_emission_factors
OK calculate_micro_emission
OK calculate_macro_emission
OK analyze_file
OK query_knowledge

Total tools: 5
```

## 11. Issues Encountered and How They Were Resolved

- `seasons` in the current YAML is a list of `{standard_name, aliases}` objects, while the Sprint 4 pseudocode assumed a dict. I made `UnifiedStandardizer` accept both shapes, so Sprint 4 works without changing existing season config structure.
- `_standardize_arguments()` now needs to return records even when it raises. To preserve partial standardization history, I extended `StandardizationError` with a `records` attribute and returned those records in executor error payloads.
- The existing local standardizer client still returns raw strings in some paths. I added `_try_local_standardization()` to normalize either dict or string responses into canonical names and keep the fallback behavior intact.
