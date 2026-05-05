"""Smoke tests for core.router_payload_utils — chart/table/map/download extraction.

Fixtures are traceable real-structure samples from eval logs; see
tests/fixtures/router_payload_samples.py for provenance comments.
"""

import pytest

from core.router_payload_utils import (
    extract_chart_data,
    extract_download_file,
    extract_map_data,
    extract_table_data,
    format_emission_factors_chart,
)

from tests.fixtures.router_payload_samples import (
    DOWNLOADS_MULTIPLE_RESULTS,
    DOWNLOAD_FILE_DICT_TOOL_RESULT,
    DOWNLOAD_FILE_STR_TOOL_RESULT,
    EF_QUERY_TOOL_RESULT,
    EF_SINGLE_POLLUTANT_TOOL_RESULT,
    MACRO_EMISSION_SUMMARY_ONLY,
    MACRO_EMISSION_TOOL_RESULT,
    MAP_COLLECTION_TOOL_RESULTS,
    MAP_EMISSION_PAYLOAD,
    MAP_HOTSPOT_PAYLOAD,
    MICRO_EMISSION_TOOL_RESULT,
    SINGLE_MAP_TOOL_RESULT,
)


def _tool_result(name, success=True, data=None, chart_data=None, table_data=None, map_data=None, download_file=None):
    """Tiny helper to build a single-element tool_results list inline."""
    result = {"success": success}
    if data is not None:
        result["data"] = data
    if chart_data is not None:
        result["chart_data"] = chart_data
    if table_data is not None:
        result["table_data"] = table_data
    if map_data is not None:
        result["map_data"] = map_data
    if download_file is not None:
        result["download_file"] = download_file
    return [{"name": name, "result": result}]


# ============================================================================
# extract_chart_data
# ============================================================================

class TestExtractChartData:
    def test_emission_factors_multi_pollutant_from_raw_data(self):
        """EF query with multi-pollutant data dict → chart built via format_emission_factors_chart."""
        result = extract_chart_data([EF_QUERY_TOOL_RESULT])
        assert result is not None
        assert result["type"] == "emission_factors"
        assert result["vehicle_type"] == "Passenger Car"
        assert result["model_year"] == 2020
        assert set(result["pollutants"].keys()) == {"CO2", "NOx"}
        for pol_data in result["pollutants"].values():
            assert "curve" in pol_data
            assert "unit" in pol_data
            assert isinstance(pol_data["curve"], list)
            assert len(pol_data["curve"]) == 3
        assert "metadata" in result

    def test_emission_factors_single_pollutant_from_raw_data(self):
        """EF query with single-pollutant speed_curve → chart via query_summary fallback."""
        result = extract_chart_data([EF_SINGLE_POLLUTANT_TOOL_RESULT])
        assert result is not None
        assert result["type"] == "emission_factors"
        assert result["vehicle_type"] == "Transit Bus"
        assert result["model_year"] == 2019
        assert list(result["pollutants"].keys()) == ["NOx"]
        assert len(result["pollutants"]["NOx"]["curve"]) == 3

    def test_returns_none_for_empty_list(self):
        assert extract_chart_data([]) is None

    def test_returns_none_when_no_chart_tool(self):
        result = extract_chart_data([
            {"name": "calculate_macro_emission", "result": {"success": True, "data": {}}}
        ])
        assert result is None


# ============================================================================
# extract_table_data
# ============================================================================

class TestExtractTableData:
    def test_ef_multi_pollutant_table(self):
        result = extract_table_data([EF_QUERY_TOOL_RESULT])
        assert result is not None
        assert result["type"] == "query_emission_factors"
        assert "速度 (km/h)" in result["columns"]
        assert len(result["preview_rows"]) <= 4
        assert result["total_rows"] == 3  # 3 points in fixture
        assert "summary" in result
        assert result["summary"]["vehicle_type"] == "Passenger Car"

    def test_ef_single_pollutant_table(self):
        result = extract_table_data([EF_SINGLE_POLLUTANT_TOOL_RESULT])
        assert result is not None
        assert result["type"] == "query_emission_factors"
        assert result["total_columns"] == 2
        assert "query_summary" in result["summary"] or "vehicle_type" in str(result["summary"])

    def test_micro_emission_table(self):
        result = extract_table_data([MICRO_EMISSION_TOOL_RESULT])
        assert result is not None
        assert result["type"] == "calculate_micro_emission"
        assert "t" in result["columns"]
        assert "speed_kph" in result["columns"]
        assert result["total_rows"] == 5
        for row in result["preview_rows"]:
            assert "t" in row
            assert "speed_kph" in row

    def test_macro_emission_table(self):
        result = extract_table_data([MACRO_EMISSION_TOOL_RESULT])
        assert result is not None
        assert result["type"] == "calculate_macro_emission"
        assert "link_id" in result["columns"]
        assert "CO2_kg_h" in result["columns"]
        assert result["total_rows"] == 3
        assert "total_emissions" in result

    def test_macro_emission_summary_only_fallback(self):
        """When results array is empty but summary has total_emissions, produce a fallback table."""
        result = extract_table_data([MACRO_EMISSION_SUMMARY_ONLY])
        assert result is not None
        assert result["type"] == "calculate_macro_emission"
        assert "指标" in result["columns"]
        assert len(result["preview_rows"]) > 0

    def test_returns_none_for_empty_list(self):
        assert extract_table_data([]) is None


# ============================================================================
# extract_download_file
# ============================================================================

class TestExtractDownloadFile:
    def test_str_download_file_converts_to_dict(self):
        result = extract_download_file(DOWNLOAD_FILE_STR_TOOL_RESULT)
        assert result is not None
        assert result["filename"] == "result_20260503_221753.xlsx"
        assert "path" in result

    def test_dict_download_file_passthrough(self):
        result = extract_download_file(DOWNLOAD_FILE_DICT_TOOL_RESULT)
        assert result is not None
        assert result["filename"] == "macro_results.xlsx"
        assert result["path"] == "outputs/macro_results.xlsx"

    def test_skips_results_without_download(self):
        """First result has no download_file; second does — should find it."""
        result = extract_download_file(DOWNLOADS_MULTIPLE_RESULTS)
        assert result is not None
        assert result["filename"] == "macro.xlsx"

    def test_returns_none_when_no_download(self):
        assert extract_download_file([]) is None


# ============================================================================
# extract_map_data
# ============================================================================

class TestExtractMapData:
    def test_single_emission_map_passthrough(self):
        result = extract_map_data(SINGLE_MAP_TOOL_RESULT)
        assert result is not None
        assert result["type"] == "macro_emission_map"
        assert "center" in result
        assert "zoom" in result
        assert "pollutant" in result
        assert result["pollutant"] == "CO2"

    def test_map_collection_wraps_multiple_maps(self):
        result = extract_map_data(MAP_COLLECTION_TOOL_RESULTS)
        assert result is not None
        assert result["type"] == "map_collection"
        assert len(result["items"]) == 3
        assert result["summary"]["map_count"] == 3
        types = [item["type"] for item in result["items"]]
        assert "macro_emission_map" in types
        assert "contour" in types
        assert "hotspot" in types

    def test_hotspot_subtype_omits_center_zoom(self):
        """Hotspot map has no center/zoom — extraction must not crash on missing geo fields."""
        hotspot_tool_result = _tool_result(
            "analyze_hotspots", success=True, map_data=MAP_HOTSPOT_PAYLOAD
        )
        result = extract_map_data(hotspot_tool_result)
        assert result is not None
        assert result["type"] == "hotspot"
        assert "center" not in result
        assert "zoom" not in result
        # Fields that hotspot does have
        assert "pollutant" in result
        assert "hotspots" in result
        assert isinstance(result["hotspots"], list)
        assert len(result["hotspots"]) == 1

    def test_emission_subtype_has_full_geo_fields(self):
        """Emission map has center/zoom/unit/color_scale — verify extraction preserves them."""
        emission_tool_result = _tool_result(
            "render_spatial_map", success=True, map_data=MAP_EMISSION_PAYLOAD
        )
        result = extract_map_data(emission_tool_result)
        assert result is not None
        assert result["type"] == "macro_emission_map"
        assert isinstance(result["center"], list)
        assert len(result["center"]) == 2
        assert isinstance(result["zoom"], int)
        assert "unit" in result
        assert "color_scale" in result
        assert "links" in result

    def test_returns_none_for_empty_list(self):
        assert extract_map_data([]) is None


# ============================================================================
# format_emission_factors_chart (public, called by extract_chart_data)
# ============================================================================

class TestFormatEmissionFactorsChart:
    def test_returns_none_for_empty_data(self):
        assert format_emission_factors_chart({}) is None


# ============================================================================
# Cross-cutting
# ============================================================================

class TestCrossCutting:
    def test_all_extract_functions_return_none_for_empty_list(self):
        """Every public extract_* function tolerates an empty tool_results list."""
        assert extract_chart_data([]) is None
        assert extract_table_data([]) is None
        assert extract_download_file([]) is None
        assert extract_map_data([]) is None
