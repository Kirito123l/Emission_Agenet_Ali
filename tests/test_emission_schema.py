"""Unit tests for core.contracts.emission_schema (Phase 5.2 Round 2).

Tests verify the schema reader correctly loads emission_domain_schema.yaml
and provides dimension defaults, ranges, standard names, and display names.
"""

from __future__ import annotations

import pytest

from core.contracts.emission_schema import (
    get_default,
    get_dimension,
    get_display_name_zh,
    get_range,
    get_standard_names,
)


def test_get_dimension_vehicle_type():
    dim = get_dimension("vehicle_type")
    assert dim["field_type"] == "categorical"
    assert dim["value_type"] == "string"
    assert dim["required"] is True
    assert "Passenger Car" in dim["standard_names"]
    assert "Motorcycle" in dim["standard_names"]
    assert len(dim["standard_names"]) == 13


def test_get_dimension_model_year():
    dim = get_dimension("model_year")
    assert dim["field_type"] == "integer_range"
    assert dim["value_type"] == "integer"
    assert dim["default"] == 2020
    assert dim["default_policy"] == "default"


def test_get_default():
    assert get_default("model_year") == 2020
    assert get_default("season") == "夏季"
    assert get_default("road_type") == "快速路"
    assert get_default("vehicle_type") is None  # optional_no_default
    assert get_default("pollutant") is None      # optional_no_default


def test_get_range():
    r = get_range("model_year")
    assert r is not None
    assert r["min"] == 1995
    assert r["max"] == 2025
    assert r["step"] == 5

    assert get_range("vehicle_type") is None  # categorical
    assert get_range("season") is None        # categorical


def test_get_standard_names():
    vehicles = get_standard_names("vehicle_type")
    assert len(vehicles) == 13
    assert "Passenger Car" in vehicles

    pollutants = get_standard_names("pollutant")
    assert len(pollutants) == 6
    assert "CO2" in pollutants

    seasons = get_standard_names("season")
    assert len(seasons) == 4
    assert "夏季" in seasons


def test_get_display_name_zh():
    assert get_display_name_zh("model_year") == "车型年份"
    assert get_display_name_zh("vehicle_type") == "车辆类型"
    assert get_display_name_zh("nonexistent") == "nonexistent"


def test_missing_dimension_returns_empty():
    dim = get_dimension("nonexistent_dimension")
    assert dim == {}
    assert get_default("nonexistent_dimension") is None
    assert get_range("nonexistent_dimension") is None
    assert get_standard_names("nonexistent_dimension") == []
