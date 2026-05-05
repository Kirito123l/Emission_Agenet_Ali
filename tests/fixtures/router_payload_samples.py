"""Realistic smoke-test fixtures for router_payload_utils tests.

Each fixture is annotated with its data-source provenance so that
future tool-output drift can be traced back to the originating code.

Top-level keys and nested structure are verified against eval-log
response_payload shapes from Phase 8.2.2.C-1.3 Run 1 (Full Architecture),
task IDs noted per fixture.  Only the *interior* of data arrays is
abbreviated (3-5 representative points instead of the full 73-point
MOVES curve, etc.) since smoke tests validate shape, not precise values.
"""

# ---------------------------------------------------------------------------
# Source: tools/emission_factors.py:91-127  (execute output schema)
#         + evaluation/results/phase8_2_2_c1_3/run1_governance_full/rep1
#           task e2e_ambiguous_001  (response_payload shape reference)
# ---------------------------------------------------------------------------
EF_QUERY_TOOL_RESULT = {
    "name": "query_emission_factors",
    "result": {
        "success": True,
        "data": {
            "vehicle_type": "Passenger Car",
            "model_year": 2020,
            "pollutants": {
                "CO2": {
                    "speed_curve": [
                        {"speed_mph": 5, "speed_kph": 8.0, "emission_rate": 860.987, "unit": "g/mile"},
                        {"speed_mph": 25, "speed_kph": 40.2, "emission_rate": 301.414, "unit": "g/mile"},
                        {"speed_mph": 50, "speed_kph": 80.5, "emission_rate": 241.171, "unit": "g/mile"},
                    ],
                    "unit": "g/mile",
                },
                "NOx": {
                    "speed_curve": [
                        {"speed_mph": 5, "speed_kph": 8.0, "emission_rate": 12.345, "unit": "g/mile"},
                        {"speed_mph": 25, "speed_kph": 40.2, "emission_rate": 4.567, "unit": "g/mile"},
                        {"speed_mph": 50, "speed_kph": 80.5, "emission_rate": 3.210, "unit": "g/mile"},
                    ],
                    "unit": "g/mile",
                },
            },
            "metadata": {
                "data_source": "MOVES (Atlanta)",
                "speed_range": {"min_kph": 8.0, "max_kph": 117.5},
                "data_points": 73,
                "season": "夏季",
                "road_type": "快速路",
            },
        },
    },
}

# ---------------------------------------------------------------------------
# Source: tools/emission_factors.py:91-127  (single-pollutant fallback)
#         + evaluation/results/phase8_2_2_c1_3/run1_governance_full/rep1
#           task e2e_ambiguous_004  (response_payload shape reference)
# ---------------------------------------------------------------------------
EF_SINGLE_POLLUTANT_TOOL_RESULT = {
    "name": "query_emission_factors",
    "result": {
        "success": True,
        "data": {
            "query_summary": {
                "vehicle_type": "Transit Bus",
                "model_year": 2019,
                "pollutant": "NOx",
                "season": "夏季",
                "road_type": "快速路",
            },
            "speed_curve": [
                {"speed_mph": 5, "speed_kph": 8.0, "emission_rate": 46.295, "unit": "g/mile"},
                {"speed_mph": 25, "speed_kph": 40.2, "emission_rate": 20.576, "unit": "g/mile"},
                {"speed_mph": 50, "speed_kph": 80.5, "emission_rate": 15.402, "unit": "g/mile"},
            ],
            "unit": "g/mile",
            "data_source": "MOVES (Atlanta)",
            "speed_range": {"min_kph": 8.0, "max_kph": 117.5},
            "data_points": 73,
        },
    },
}

# ---------------------------------------------------------------------------
# Source: tools/macro_emission.py:614-670  (execute output schema)
#         + evaluation/results/phase8_2_2_c1_3/run1_governance_full/rep1
#           task e2e_ambiguous_003  (response_payload shape reference)
# ---------------------------------------------------------------------------
MACRO_EMISSION_TOOL_RESULT = {
    "name": "calculate_macro_emission",
    "result": {
        "success": True,
        "data": {
            "query_info": {
                "model_year": 2020,
                "pollutants": ["CO2", "NOx"],
                "season": "夏季",
                "links_count": 3,
            },
            "summary": {
                "total_links": 3,
                "total_emissions_kg_per_hr": {"CO2": 479.73, "NOx": 0.11},
            },
            "results": [
                {
                    "link_id": "Link_A1",
                    "total_emissions_kg_per_hr": {"CO2": 142.46, "NOx": 0.03},
                    "emission_rates_g_per_veh_km": {"CO2": 123.02, "NOx": 0.03},
                    "link_length_km": 2.5,
                    "avg_speed_kph": 60.0,
                    "traffic_flow_vph": 5000,
                },
                {
                    "link_id": "Link_B2",
                    "total_emissions_kg_per_hr": {"CO2": 195.81, "NOx": 0.05},
                    "emission_rates_g_per_veh_km": {"CO2": 156.65, "NOx": 0.04},
                    "link_length_km": 1.8,
                    "avg_speed_kph": 45.0,
                    "traffic_flow_vph": 3500,
                },
                {
                    "link_id": "Link_C3",
                    "total_emissions_kg_per_hr": {"CO2": 141.46, "NOx": 0.03},
                    "emission_rates_g_per_veh_km": {"CO2": 98.24, "NOx": 0.02},
                    "link_length_km": 3.2,
                    "avg_speed_kph": 80.0,
                    "traffic_flow_vph": 6000,
                },
            ],
            "download_file": {
                "path": "outputs/macro_results.xlsx",
                "filename": "macro_results.xlsx",
            },
            "scenario_label": "baseline",
            "fleet_mix_fill": {},
        },
    },
}

# ---------------------------------------------------------------------------
# Source: tools/micro_emission.py:46-95  (execute output schema)
#         + evaluation/results/phase8_2_2_c1_3/run1_governance_full/rep1
#           task e2e_ambiguous_002  (response_payload shape reference)
# ---------------------------------------------------------------------------
MICRO_EMISSION_TOOL_RESULT = {
    "name": "calculate_micro_emission",
    "result": {
        "success": True,
        "data": {
            "query_info": {
                "model_year": 2020,
                "pollutants": ["NOx"],
                "season": "夏季",
            },
            "summary": {
                "total_distance_km": 5.2,
                "total_time_s": 300,
                "total_emissions_g": {"NOx": 0.89},
            },
            "results": [
                {"t": 1, "speed_kph": 30.5, "VSP": 2.35, "emissions": {"NOx": 0.0012}},
                {"t": 2, "speed_kph": 32.1, "VSP": 2.78, "emissions": {"NOx": 0.0014}},
                {"t": 3, "speed_kph": 33.8, "VSP": 3.12, "emissions": {"NOx": 0.0015}},
                {"t": 4, "speed_kph": 35.0, "VSP": 3.45, "emissions": {"NOx": 0.0017}},
                {"t": 5, "speed_kph": 36.2, "VSP": 3.80, "emissions": {"NOx": 0.0018}},
            ],
        },
    },
}

# ---------------------------------------------------------------------------
# Source: tools/macro_emission.py:614-670  (summary-only, no results array)
#         + evaluation/results/phase8_2_2_c1_3/run1_governance_full/rep1
#           (extract_table_data lines 185-196: summary-only fallback path)
# ---------------------------------------------------------------------------
MACRO_EMISSION_SUMMARY_ONLY = {
    "name": "calculate_macro_emission",
    "result": {
        "success": True,
        "data": {
            "query_info": {"model_year": 2020, "pollutants": ["CO2"], "season": "夏季", "links_count": 1},
            "summary": {
                "total_links": 1,
                "total_emissions": {"CO2": 318.90},
            },
            "results": [],
            "scenario_label": "baseline",
        },
    },
}

# ---------------------------------------------------------------------------
# Source: tools/spatial_renderer.py:121-200  (emission map output)
#         + evaluation/results/phase8_2_2_c1_3/run1_governance_full/rep1
#           task e2e_codeswitch_174  (response_payload shape reference)
#   Key shape verified: center/zoom/pollutant/scenario_label/unit/color_scale/links/summary
# ---------------------------------------------------------------------------
MAP_EMISSION_PAYLOAD = {
    "type": "macro_emission_map",
    "center": [31.23, 121.47],
    "zoom": 12,
    "pollutant": "CO2",
    "scenario_label": "baseline",
    "unit": "kg/(h·km)",
    "color_scale": {
        "min": 0.05,
        "max": 142.46,
        "colors": ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"],
    },
    "links": [
        {
            "link_id": "Link_A1",
            "geometry": [[121.47, 31.23], [121.48, 31.24]],
            "emissions": {"CO2": 142.46},
            "emission_rate": {"CO2": 123.02},
            "link_length_km": 1.2,
            "avg_speed_kph": 40.5,
            "traffic_flow_vph": 500,
        },
    ],
    "summary": {"total_links": 1, "total_emissions_kg_per_hr": {"CO2": 142.46}},
}

# ---------------------------------------------------------------------------
# Source: tools/hotspot.py:38-85  (output structure)
#         + tools/spatial_renderer.py (hotspot map render path)
#         + evaluation/results/phase8_2_2_c1_3/run1_governance_full/rep1
#           task e2e_multistep_049  (response_payload shape reference)
#   Key shape verified: NO center/zoom fields — hotspot map has pollutant/unit/hotspots/summary/interpretation
# ---------------------------------------------------------------------------
MAP_HOTSPOT_PAYLOAD = {
    "type": "hotspot",
    "pollutant": "NOx",
    "unit": "μg/m³",
    "hotspots": [
        {
            "rank": 1,
            "center": [121.47, 31.23],
            "area_m2": 12500,
            "max_conc": 932.88,
            "contributing_roads": [{"link_id": "Link_A1", "contribution_pct": 45.2}],
        },
    ],
    "summary": {
        "total_hotspot_area_m2": 25000,
        "area_fraction_pct": 2.1,
        "max_concentration": 932.88,
    },
    "interpretation": "识别出 2 个热点区域...",
    "scenario_label": "baseline",
}

# ---------------------------------------------------------------------------
# Source: tools/spatial_renderer.py  (contour map output)
#         + evaluation/results/phase8_2_2_c1_3/run1_governance_full/rep1
#           task e2e_multistep_005  (response_payload shape reference)
# ---------------------------------------------------------------------------
MAP_CONTOUR_PAYLOAD = {
    "type": "contour",
    "center": [31.22, 121.47],
    "zoom": 13,
    "pollutant": "NOx",
    "scenario_label": "baseline",
    "unit": "μg/m³",
    "layers": [],
    "summary": {"max_concentration": 932.88},
}

# ---------------------------------------------------------------------------
# Source: core/router_payload_utils.py:300-334  (_collect_map_payloads + extract_map_data)
#         + evaluation/results/phase8_2_2_c1_3/run1_governance_full/rep1
#           task e2e_multistep_049  (response_payload shape reference: map_collection)
# ---------------------------------------------------------------------------
MAP_COLLECTION_TOOL_RESULTS = [
    {
        "name": "calculate_macro_emission",
        "result": {
            "success": True,
            "data": {"map_data": MAP_EMISSION_PAYLOAD},
        },
    },
    {
        "name": "calculate_dispersion",
        "result": {
            "success": True,
            "data": {"map_data": MAP_CONTOUR_PAYLOAD},
        },
    },
    {
        "name": "analyze_hotspots",
        "result": {
            "success": True,
            "data": {"map_data": MAP_HOTSPOT_PAYLOAD},
        },
    },
]

# Single-map tool result (emission only)
SINGLE_MAP_TOOL_RESULT = [
    {
        "name": "render_spatial_map",
        "result": {
            "success": True,
            "map_data": MAP_EMISSION_PAYLOAD,
        },
    },
]

# ---------------------------------------------------------------------------
# Source: core/router_payload_utils.py:259-297  (extract_download_file)
#         + evaluation/results/phase8_2_2_c1_3/run1_governance_full/rep1
#           task e2e_ambiguous_003  (download_file shape reference: {path, filename})
# ---------------------------------------------------------------------------
DOWNLOAD_FILE_DICT = {
    "path": "outputs/macro_results.xlsx",
    "filename": "macro_results.xlsx",
}

DOWNLOAD_FILE_STR_TOOL_RESULT = [
    {
        "name": "calculate_macro_emission",
        "result": {
            "success": True,
            "download_file": "outputs/result_20260503_221753.xlsx",
        },
    },
]

DOWNLOAD_FILE_DICT_TOOL_RESULT = [
    {
        "name": "calculate_macro_emission",
        "result": {
            "success": True,
            "data": {"download_file": DOWNLOAD_FILE_DICT},
        },
    },
]

DOWNLOADS_MULTIPLE_RESULTS = [
    {
        "name": "analyze_file",
        "result": {"success": True},
    },
    {
        "name": "calculate_macro_emission",
        "result": {
            "success": True,
            "data": {"download_file": {"path": "outputs/macro.xlsx", "filename": "macro.xlsx"}},
        },
    },
    {
        "name": "render_spatial_map",
        "result": {
            "success": True,
            "map_data": MAP_EMISSION_PAYLOAD,
        },
    },
]
