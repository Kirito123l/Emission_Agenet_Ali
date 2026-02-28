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
    }
]
