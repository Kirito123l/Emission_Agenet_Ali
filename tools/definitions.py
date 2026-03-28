"""
Tool Definitions for Tool Use Mode
Defines all tools in OpenAI function calling format
"""

TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_emission_factors",
            "description": "Query vehicle emission factor curves by speed. Returns chart and data table.",
            "parameters": {
                "type": "object",
                "properties": {
                    "vehicle_type": {
                        "type": "string",
                        "description": "Vehicle type. Pass user's original expression (e.g., '小汽车', '公交车', 'SUV'). System will automatically recognize it."
                    },
                    "pollutants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of pollutants to query (e.g., ['CO2', 'NOx', 'PM2.5']). Single pollutant also uses this array."
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "Vehicle model year (e.g., 2020). Range: 1995-2025."
                    },
                    "season": {
                        "type": "string",
                        "description": "Season (春季/夏季/秋季/冬季). Optional, defaults to summer if not provided."
                    },
                    "road_type": {
                        "type": "string",
                        "description": "Road type (快速路/地面道路). Optional, defaults to expressway if not provided."
                    },
                    "return_curve": {
                        "type": "boolean",
                        "description": "Whether to return full curve data. Default false."
                    }
                },
                "required": ["vehicle_type", "model_year"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_micro_emission",
            "description": "Calculate second-by-second emissions from vehicle trajectory data (time + speed). Use file_path for uploaded files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to trajectory data file. REQUIRED when user uploaded a file. You will see this path in the file context."
                    },
                    "trajectory_data": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Trajectory data array. Each point should have 't' (time in seconds) and 'speed_kph' (speed in km/h). Use this if user provides data directly."
                    },
                    "vehicle_type": {
                        "type": "string",
                        "description": "Vehicle type. Pass user's original expression. REQUIRED."
                    },
                    "pollutants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of pollutants to calculate. Defaults to [CO2, NOx, PM2.5] if not provided."
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "Vehicle model year. Defaults to 2020 if not provided."
                    },
                    "season": {
                        "type": "string",
                        "description": "Season. Optional."
                    }
                },
                "required": ["vehicle_type"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_macro_emission",
            "description": "Calculate road link emissions from traffic data (length + flow + speed). Use file_path for uploaded files.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to road link data file."
                    },
                    "links_data": {
                        "type": "array",
                        "items": {"type": "object"},
                        "description": "Road link data array. Each link should have 'link_length_km', 'traffic_flow_vph', 'avg_speed_kph'. Use this if user provides data directly."
                    },
                    "pollutants": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of pollutants to calculate."
                    },
                    "fleet_mix": {
                        "type": "object",
                        "description": "Fleet composition (vehicle type percentages). Optional, uses default if not provided."
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "Vehicle model year."
                    },
                    "season": {
                        "type": "string",
                        "description": "Season. Optional."
                    },
                    "overrides": {
                        "type": "array",
                        "description": "Parameter overrides for scenario simulation. Each override modifies one input column.",
                        "items": {
                            "type": "object",
                            "properties": {
                                "column": {
                                    "type": "string",
                                    "enum": ["avg_speed_kph", "traffic_flow_vph", "link_length_km", "fleet_mix"],
                                    "description": "Column to override"
                                },
                                "value": {
                                    "description": "Fixed value to set, or a fleet_mix object when column=fleet_mix"
                                },
                                "transform": {
                                    "type": "string",
                                    "enum": ["set", "multiply", "add"],
                                    "description": "Transform type. Default: set"
                                },
                                "factor": {
                                    "type": "number",
                                    "description": "Multiplication factor for transform=multiply"
                                },
                                "offset": {
                                    "type": "number",
                                    "description": "Additive offset for transform=add"
                                },
                                "where": {
                                    "type": "object",
                                    "description": "Condition to filter affected rows",
                                    "properties": {
                                        "column": {"type": "string"},
                                        "op": {
                                            "type": "string",
                                            "enum": [">", ">=", "<", "<=", "==", "!=", "in", "not_in"]
                                        },
                                        "value": {}
                                    }
                                }
                            },
                            "required": ["column"]
                        }
                    },
                    "scenario_label": {
                        "type": "string",
                        "description": "Short scenario label such as 'speed_30kmh' or 'bus_15pct'."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_file",
            "description": "Analyze uploaded file structure. Returns columns, data type, and preview.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Path to the file to analyze"
                    }
                },
                "required": ["file_path"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "query_knowledge",
            "description": "Search emission knowledge base for standards, regulations, and technical concepts.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The question or topic to search for in the knowledge base"
                    },
                    "top_k": {
                        "type": "integer",
                        "description": "Number of knowledge entries to retrieve. Optional, defaults to 5."
                    },
                    "expectation": {
                        "type": "string",
                        "description": "Expected type of information (e.g., 'standard definition', 'regulation details'). Optional."
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "calculate_dispersion",
            "description": (
                "Calculate pollutant dispersion/concentration distribution from vehicle emissions "
                "using the PS-XGB-RLINE surrogate model. Requires emission results (typically from "
                "calculate_macro_emission). Produces a spatial concentration raster field. "
                "Supports meteorology presets, custom parameters, or .sfc files."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "emission_source": {
                        "type": "string",
                        "description": "Source of emission data. 'last_result' or a file path.",
                        "default": "last_result"
                    },
                    "meteorology": {
                        "type": "string",
                        "description": "Meteorology preset name, 'custom', or .sfc file path. Default: urban_summer_day.",
                        "default": "urban_summer_day"
                    },
                    "wind_speed": {
                        "type": "number",
                        "description": "Wind speed in m/s. Use with 'custom' or to override a preset."
                    },
                    "wind_direction": {
                        "type": "number",
                        "description": "Wind direction in degrees (0=N, 90=E, 180=S, 270=W). Use with 'custom' or to override a preset."
                    },
                    "stability_class": {
                        "type": "string",
                        "description": "Atmospheric stability: VS, S, N1, N2, U, VU.",
                        "enum": ["VS", "S", "N1", "N2", "U", "VU"]
                    },
                    "mixing_height": {
                        "type": "number",
                        "description": "Mixing layer height in meters. Default: 800."
                    },
                    "roughness_height": {
                        "type": "number",
                        "description": "Surface roughness: 0.05 (open), 0.5 (suburban), 1.0 (urban). Default: 0.5.",
                        "enum": [0.05, 0.5, 1.0]
                    },
                    "grid_resolution": {
                        "type": "number",
                        "description": "Display grid resolution in meters: 50, 100, or 200. Default: 50.",
                        "enum": [50, 100, 200],
                        "default": 50
                    },
                    "pollutant": {
                        "type": "string",
                        "description": "Pollutant name. Currently only NOx.",
                        "default": "NOx"
                    },
                    "scenario_label": {
                        "type": "string",
                        "description": "Scenario label used to resolve/store scenario-specific emission and dispersion results."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_hotspots",
            "description": (
                "Identify pollution hotspot areas and trace contributing road sources from "
                "dispersion results. Supports percentile or threshold methods. "
                "Does not re-run dispersion - analyzes stored results instantly."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "method": {
                        "type": "string",
                        "description": "Identification method: 'percentile' (top N%) or 'threshold' (above value).",
                        "enum": ["percentile", "threshold"],
                        "default": "percentile"
                    },
                    "threshold_value": {
                        "type": "number",
                        "description": "Concentration threshold in ug/m3. Required when method='threshold'."
                    },
                    "percentile": {
                        "type": "number",
                        "description": "Top N percent to identify as hotspots. Default: 5.",
                        "default": 5
                    },
                    "min_hotspot_area_m2": {
                        "type": "number",
                        "description": "Minimum cluster area in m2. Default: 2500.",
                        "default": 2500
                    },
                    "max_hotspots": {
                        "type": "integer",
                        "description": "Max hotspot areas to return. Default: 10.",
                        "default": 10
                    },
                    "source_attribution": {
                        "type": "boolean",
                        "description": "Compute road contribution per hotspot. Default: true.",
                        "default": True
                    },
                    "scenario_label": {
                        "type": "string",
                        "description": "Scenario label used to resolve/store scenario-specific hotspot results."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "render_spatial_map",
            "description": "Render spatial data as an interactive map. Use this to visualize emission results, dispersion results, or any geo-referenced data on a map. Can use data from the previous calculation step.",
            "parameters": {
                "type": "object",
                "properties": {
                    "data_source": {
                        "type": "string",
                        "description": "Data to render. Use 'last_result' to visualize the previous calculation output.",
                        "default": "last_result"
                    },
                    "pollutant": {
                        "type": "string",
                        "description": "Which pollutant to visualize (e.g., CO2, NOx, PM2.5). If not specified, uses the first available."
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional map title"
                    },
                    "layer_type": {
                        "type": "string",
                        "enum": ["emission", "raster", "hotspot", "concentration", "points"],
                        "description": "Type of spatial layer. Auto-detected if not specified."
                    },
                    "scenario_label": {
                        "type": "string",
                        "description": "Optional scenario label to render a stored scenario-specific result instead of baseline."
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "compare_scenarios",
            "description": (
                "Compare baseline analysis results with one or more scenario variants. "
                "Shows metric deltas, percentage changes, and per-link differences using data already stored in the session."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "result_types": {
                        "type": "array",
                        "items": {"type": "string", "enum": ["emission", "dispersion", "hotspot"]},
                        "description": "Which result types to compare"
                    },
                    "baseline": {
                        "type": "string",
                        "default": "baseline",
                        "description": "Label of baseline results"
                    },
                    "scenario": {
                        "type": "string",
                        "description": "Single scenario label to compare against baseline"
                    },
                    "scenarios": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Multiple scenario labels to compare against baseline"
                    },
                    "metrics": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Optional metric names to focus on"
                    }
                },
                "required": ["result_types"]
            }
        }
    }
]
