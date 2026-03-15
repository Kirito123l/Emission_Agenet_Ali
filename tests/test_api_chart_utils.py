"""Regression coverage for the second safe extraction from ``api.routes``."""
from api import routes
from api.chart_utils import _pick_key_points, build_emission_chart_data, extract_key_points


def test_build_emission_chart_data_single_pollutant_preserves_curve_shape():
    data = {
        "query_summary": {
            "vehicle_type": "Passenger Car",
            "model_year": 2022,
            "pollutant": "CO2",
        },
        "speed_curve": [
            {"speed_kph": 28, "emission_rate": 1.1},
            {"speed_kph": 61, "emission_rate": 2.2},
            {"speed_kph": 88, "emission_rate": 3.3},
        ],
        "unit": "g/mile",
        "data_source": "test-source",
        "speed_range": {"min_kph": 0, "max_kph": 120},
        "data_points": 3,
    }

    result = build_emission_chart_data("query_emission_factors", data)

    assert result["type"] == "emission_factors"
    assert result["vehicle_type"] == "Passenger Car"
    assert result["pollutants"]["CO2"]["curve"] == data["speed_curve"]
    assert [point["speed"] for point in result["key_points"]] == [28, 61, 88]


def test_build_emission_chart_data_multi_pollutant_converts_speed_curve_to_curve():
    data = {
        "vehicle_type": "Passenger Car",
        "model_year": 2020,
        "metadata": {"season": "summer"},
        "pollutants": {
            "CO2": {
                "speed_curve": [
                    {"speed_kph": 30, "emission_rate": 1.60934},
                ]
            },
            "NOx": {
                "curve": [
                    {"speed_kph": 30, "emission_rate": 0.4},
                ],
                "unit": "g/km",
            },
        },
    }

    result = build_emission_chart_data("query_emission_factors", data)

    assert result["pollutants"]["CO2"] == {
        "curve": [{"speed_kph": 30, "emission_rate": 1.0}],
        "unit": "g/km",
    }
    assert result["pollutants"]["NOx"] == {
        "curve": [{"speed_kph": 30, "emission_rate": 0.4}],
        "unit": "g/km",
    }


def test_extract_key_points_supports_direct_and_legacy_formats():
    curve = [
        {"speed_kph": 29, "emission_rate": 0.9},
        {"speed_kph": 58, "emission_rate": 1.8},
        {"speed_kph": 91, "emission_rate": 2.7},
    ]

    direct_points = extract_key_points({"pollutant": "CO2", "curve": curve})
    legacy_points = extract_key_points({"NOx": {"curve": curve}})

    assert direct_points[0]["pollutant"] == "CO2"
    assert [point["label"] for point in legacy_points] == ["City Congestion", "City Cruise", "Highway"]
    assert _pick_key_points(curve, "PM2.5")[2]["pollutant"] == "PM2.5"


def test_routes_module_keeps_chart_helper_names():
    assert routes.build_emission_chart_data is build_emission_chart_data
    assert routes.extract_key_points is extract_key_points
    assert routes._pick_key_points is _pick_key_points
