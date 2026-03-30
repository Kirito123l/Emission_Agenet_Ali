"""Tests for the pluggable standardization engine."""

from __future__ import annotations

import pytest

from services.standardization_engine import (
    BatchStandardizationError,
    NoModelBackend,
    PARAM_TYPE_REGISTRY,
    StandardizationEngine,
)
from services.standardizer import StandardizationResult, get_standardizer


def _assert_result_matches(actual: StandardizationResult, expected: StandardizationResult):
    assert actual.success == expected.success
    assert actual.original == expected.original
    assert actual.normalized == expected.normalized
    assert actual.strategy == expected.strategy
    assert actual.confidence == expected.confidence
    assert actual.suggestions == expected.suggestions


class TestEngineRuleBackendParity:
    """Verify RuleBackend produces identical results to current standardizer."""

    @pytest.fixture
    def engine(self):
        return StandardizationEngine({"llm_enabled": False})

    @pytest.fixture
    def standardizer(self):
        return get_standardizer()

    def test_vehicle_type_exact(self, engine, standardizer):
        _assert_result_matches(
            engine.standardize("vehicle_type", "Passenger Car"),
            standardizer.standardize_vehicle_detailed("Passenger Car"),
        )

    def test_vehicle_type_alias_chinese(self, engine, standardizer):
        _assert_result_matches(
            engine.standardize("vehicle_type", "小汽车"),
            standardizer.standardize_vehicle_detailed("小汽车"),
        )

    def test_vehicle_type_fuzzy(self, engine, standardizer):
        _assert_result_matches(
            engine.standardize("vehicle_type", "小客车"),
            standardizer.standardize_vehicle_detailed("小客车"),
        )

    def test_pollutant_exact(self, engine, standardizer):
        _assert_result_matches(
            engine.standardize("pollutant", "NOx"),
            standardizer.standardize_pollutant_detailed("NOx"),
        )

    def test_pollutant_alias_chinese(self, engine, standardizer):
        _assert_result_matches(
            engine.standardize("pollutant", "氮氧化物"),
            standardizer.standardize_pollutant_detailed("氮氧化物"),
        )

    def test_season_default(self, engine, standardizer):
        _assert_result_matches(
            engine.standardize("season", "monsoon"),
            standardizer.standardize_season("monsoon"),
        )

    def test_stability_pasquill_c(self, engine, standardizer):
        _assert_result_matches(
            engine.standardize("stability_class", "C"),
            standardizer.standardize_stability_class("C"),
        )

    def test_meteorology_preset(self, engine, standardizer):
        _assert_result_matches(
            engine.standardize("meteorology", "城市夏季白天"),
            standardizer.standardize_meteorology("城市夏季白天"),
        )

    def test_meteorology_sfc_passthrough(self, engine):
        result = engine.standardize("meteorology", "/path/to/met.sfc")
        assert result.success is True
        assert result.normalized == "/path/to/met.sfc"
        assert result.strategy == "passthrough"

    def test_meteorology_custom_passthrough(self, engine):
        result = engine.standardize("meteorology", "custom")
        assert result.success is True
        assert result.normalized == "custom"
        assert result.strategy == "passthrough"

    def test_abstain_with_suggestions(self, engine):
        result = engine.standardize("vehicle_type", "飞机")
        assert result.success is False
        assert result.strategy == "abstain"
        assert len(result.suggestions) > 0

    def test_all_existing_test_cases_pass(self, engine, standardizer):
        cases = [
            ("vehicle_type", "Passenger Car", standardizer.standardize_vehicle_detailed),
            ("vehicle_type", "乘用车", standardizer.standardize_vehicle_detailed),
            ("vehicle_type", "小汽车", standardizer.standardize_vehicle_detailed),
            ("vehicle_type", "passenger car", standardizer.standardize_vehicle_detailed),
            ("vehicle_type", "飞机", standardizer.standardize_vehicle_detailed),
            ("pollutant", "CO2", standardizer.standardize_pollutant_detailed),
            ("pollutant", "co2", standardizer.standardize_pollutant_detailed),
            ("pollutant", "氮氧化物", standardizer.standardize_pollutant_detailed),
            ("pollutant", "oxygen", standardizer.standardize_pollutant_detailed),
            ("season", "夏天", standardizer.standardize_season),
            ("season", "winter", standardizer.standardize_season),
            ("season", "monsoon", standardizer.standardize_season),
            ("road_type", "高速", standardizer.standardize_road_type),
            ("road_type", "local road", standardizer.standardize_road_type),
            ("meteorology", "urban_summer_day", standardizer.standardize_meteorology),
            ("meteorology", "summer day", standardizer.standardize_meteorology),
            ("meteorology", "hurricane", standardizer.standardize_meteorology),
            ("stability_class", "Pasquill C", standardizer.standardize_stability_class),
            ("stability_class", "class D", standardizer.standardize_stability_class),
            ("stability_class", "very stable", standardizer.standardize_stability_class),
        ]
        for param_type, raw_value, legacy_method in cases:
            _assert_result_matches(engine.standardize(param_type, raw_value), legacy_method(raw_value))


class TestEngineLLMBackend:
    """Tests for LLM fallback behavior."""

    def test_llm_fires_when_rules_fail(self, monkeypatch):
        engine = StandardizationEngine({"llm_enabled": True})
        monkeypatch.setattr(
            engine._llm_backend,
            "_call_llm",
            lambda *args, **kwargs: {"value": "Passenger Car", "confidence": 0.88},
        )
        result = engine.standardize("vehicle_type", "Tesla Model 3")
        assert result.success is True
        assert result.normalized == "Passenger Car"
        assert result.strategy == "llm"

    def test_llm_skipped_when_rules_succeed(self, monkeypatch):
        engine = StandardizationEngine({"llm_enabled": True})
        called = {"value": False}

        def _fake_standardize(*args, **kwargs):
            called["value"] = True
            return None

        monkeypatch.setattr(engine._llm_backend, "standardize", _fake_standardize)
        result = engine.standardize("pollutant", "NOx")
        assert result.success is True
        assert result.normalized == "NOx"
        assert called["value"] is False

    def test_llm_failure_falls_through_to_abstain(self, monkeypatch):
        engine = StandardizationEngine({"llm_enabled": True})
        monkeypatch.setattr(engine._llm_backend, "_call_llm", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("boom")))
        result = engine.standardize("vehicle_type", "Tesla Model 3")
        assert result.success is False
        assert result.strategy == "abstain"

    def test_llm_timeout_falls_through(self, monkeypatch):
        engine = StandardizationEngine({"llm_enabled": True})
        monkeypatch.setattr(engine._llm_backend, "_call_llm", lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timeout")))
        result = engine.standardize("vehicle_type", "Tesla Model 3")
        assert result.success is False
        assert result.strategy == "abstain"

    def test_llm_invalid_response_ignored(self, monkeypatch):
        engine = StandardizationEngine({"llm_enabled": True})
        monkeypatch.setattr(engine._llm_backend, "_call_llm", lambda *args, **kwargs: {"foo": "bar"})
        result = engine.standardize("vehicle_type", "Tesla Model 3")
        assert result.success is False
        assert result.strategy == "abstain"

    def test_llm_returns_value_not_in_candidates(self, monkeypatch):
        engine = StandardizationEngine({"llm_enabled": True})
        monkeypatch.setattr(
            engine._llm_backend,
            "_call_llm",
            lambda *args, **kwargs: {"value": "Sports Car", "confidence": 0.9},
        )
        result = engine.standardize("vehicle_type", "Tesla Model 3")
        assert result.success is False
        assert result.strategy == "abstain"

    def test_llm_confidence_capped(self, monkeypatch):
        engine = StandardizationEngine({"llm_enabled": True})
        monkeypatch.setattr(
            engine._llm_backend,
            "_call_llm",
            lambda *args, **kwargs: {"value": "Passenger Car", "confidence": 1.0},
        )
        result = engine.standardize("vehicle_type", "Tesla Model 3")
        assert result.success is True
        assert result.confidence == 0.95

    def test_llm_disabled_skips_llm(self):
        engine = StandardizationEngine({"llm_enabled": False})

        class DummyBackend:
            def __init__(self):
                self.called = False

            def standardize(self, *args, **kwargs):
                self.called = True
                return None

        dummy = DummyBackend()
        engine._llm_backend = dummy
        result = engine.standardize("vehicle_type", "Tesla Model 3")
        assert result.success is False
        assert result.strategy == "abstain"
        assert dummy.called is False

    def test_llm_backend_diesel_truck(self, monkeypatch):
        engine = StandardizationEngine({"llm_enabled": True})
        monkeypatch.setattr(
            engine._llm_backend,
            "_call_llm",
            lambda *args, **kwargs: {"value": "Combination Long-haul Truck", "confidence": 0.85},
        )
        result = engine.standardize("vehicle_type", "柴油大卡车")
        assert result.success is True
        assert result.normalized == "Combination Long-haul Truck"
        assert result.strategy == "llm"

    def test_llm_backend_tesla_model3(self, monkeypatch):
        engine = StandardizationEngine({"llm_enabled": True})
        monkeypatch.setattr(
            engine._llm_backend,
            "_call_llm",
            lambda *args, **kwargs: {"value": "Passenger Car", "confidence": 0.83},
        )
        result = engine.standardize("vehicle_type", "Tesla Model 3")
        assert result.success is True
        assert result.normalized == "Passenger Car"
        assert result.strategy == "llm"


class TestEngineBatchStandardization:
    """Tests for standardize_batch."""

    def test_batch_mixed_params(self):
        engine = StandardizationEngine({"llm_enabled": False})
        standardized, records = engine.standardize_batch(
            {
                "vehicle_type": "小汽车",
                "season": "冬天",
                "model_year": 2020,
                "return_curve": True,
            },
            tool_name="query_emission_factors",
        )
        assert standardized["vehicle_type"] == "Passenger Car"
        assert standardized["season"] == "冬季"
        assert standardized["model_year"] == 2020
        assert standardized["return_curve"] is True
        assert {record["param"] for record in records} == {"vehicle_type", "season"}

    def test_batch_records_format(self):
        engine = StandardizationEngine({"llm_enabled": False})
        _, records = engine.standardize_batch(
            {"vehicle_type": "小汽车", "pollutant": "氮氧化物"},
            tool_name="query_emission_factors",
        )
        assert len(records) == 2
        for record in records:
            assert set(record.keys()) >= {"param", "success", "original", "normalized", "strategy", "confidence"}

    def test_batch_passthrough_numeric(self):
        engine = StandardizationEngine({"llm_enabled": False})
        standardized, records = engine.standardize_batch(
            {"wind_speed": 3.0, "roughness_height": 0.5},
            tool_name="calculate_dispersion",
        )
        assert standardized == {"wind_speed": 3.0, "roughness_height": 0.5}
        assert records == []

    def test_batch_pollutant_list(self):
        engine = StandardizationEngine({"llm_enabled": False})
        standardized, records = engine.standardize_batch(
            {"pollutants": ["co2", "氮氧化物", "oxygen"]},
            tool_name="query_emission_factors",
        )
        assert standardized["pollutants"] == ["CO2", "NOx", "oxygen"]
        assert [record["param"] for record in records] == [
            "pollutants[co2]",
            "pollutants[氮氧化物]",
            "pollutants[oxygen]",
        ]
        assert records[-1]["success"] is False

    def test_batch_raises_on_abstain(self):
        engine = StandardizationEngine({"llm_enabled": False})
        with pytest.raises(BatchStandardizationError) as exc_info:
            engine.standardize_batch(
                {"vehicle_type": "飞机", "model_year": 2020},
                tool_name="query_emission_factors",
            )
        assert exc_info.value.param_name == "vehicle_type"
        assert len(exc_info.value.suggestions) > 0


class TestEngineConfiguration:
    """Tests for engine configuration."""

    def test_default_config(self):
        engine = StandardizationEngine()
        result = engine.standardize("pollutant", "NOx")
        assert result.success is True
        assert result.normalized == "NOx"

    def test_llm_disabled_config(self):
        engine = StandardizationEngine({"llm_enabled": False})
        assert engine._is_llm_enabled_for("vehicle_type") is False

    def test_custom_fuzzy_threshold(self):
        default_engine = StandardizationEngine({"llm_enabled": False})
        strict_engine = StandardizationEngine({"llm_enabled": False, "fuzzy_threshold": 0.95})
        assert default_engine.standardize("vehicle_type", "小客车").success is True
        strict_result = strict_engine.standardize("vehicle_type", "小客车")
        assert strict_result.success is False
        assert strict_result.strategy == "abstain"

    def test_fuzzy_disabled_config(self):
        engine = StandardizationEngine({"llm_enabled": False, "fuzzy_enabled": False})
        result = engine.standardize("vehicle_type", "小客车")
        assert result.success is False
        assert result.strategy == "abstain"

    def test_local_backend_disabled_when_model_switch_off(self):
        engine = StandardizationEngine(
            {
                "llm_enabled": False,
                "use_local_standardizer": True,
                "local_standardizer_config": {"enabled": True},
            }
        )
        assert isinstance(engine._model_backend, NoModelBackend)


class TestDeclarativeRegistry:
    """Tests for the parameter type registry."""

    def test_all_known_params_registered(self):
        expected = {
            "vehicle_type",
            "pollutant",
            "pollutants",
            "season",
            "road_type",
            "meteorology",
            "stability_class",
        }
        assert expected.issubset(PARAM_TYPE_REGISTRY.keys())

    def test_unregistered_param_passthrough(self):
        engine = StandardizationEngine({"llm_enabled": False})
        standardized, records = engine.standardize_batch({"foo": "winter"}, tool_name="query_emission_factors")
        assert standardized["foo"] == "winter"
        assert records == []

    def test_register_new_param(self):
        engine = StandardizationEngine({"llm_enabled": False})
        engine.register_param_type("weather_season", "season")
        standardized, records = engine.standardize_batch(
            {"weather_season": "winter"},
            tool_name="query_emission_factors",
        )
        assert standardized["weather_season"] == "冬季"
        assert records[0]["param"] == "weather_season"
