"""
Tool: calculate_dispersion

Computes pollutant concentration distribution using the PS-XGB-RLINE surrogate model.
Bridges macro emission results -> DispersionCalculator -> spatial concentration field.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, Optional

import yaml
from shapely.geometry import mapping

from config import get_config
from core.coverage_assessment import assess_coverage
from tools.base import BaseTool, PreflightCheckResult, ToolResult

logger = logging.getLogger(__name__)

PRESET_METEOROLOGY = {
    "urban_summer_day",
    "urban_summer_night",
    "urban_winter_day",
    "urban_winter_night",
    "windy_neutral",
    "calm_stable",
}
CUSTOM_STABILITY_TO_L = {
    "VS": 100.0,
    "S": 500.0,
    "N1": 2000.0,
    "N2": -2000.0,
    "U": -500.0,
    "VU": -100.0,
}
CUSTOM_STABILITY_TO_H = {
    "VS": 0.0,
    "S": 0.0,
    "N1": 0.0,
    "N2": 50.0,
    "U": 100.0,
    "VU": 150.0,
}
MET_OVERRIDE_KEYS = ("wind_speed", "wind_direction", "stability_class", "mixing_height")


@lru_cache(maxsize=1)
def _load_meteorology_presets() -> Dict[str, Dict[str, Any]]:
    presets_path = Path(__file__).resolve().parent.parent / "config" / "meteorology_presets.yaml"
    with presets_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data.get("presets", {})


class DispersionTool(BaseTool):
    """
    Dispersion calculation tool.

    Wraps DispersionCalculator and EmissionToDispersionAdapter to provide
    a tool-layer interface compatible with the agent's executor framework.
    """

    def __init__(self):
        super().__init__()
        from calculators.dispersion import DispersionCalculator, DispersionConfig
        from calculators.dispersion_adapter import EmissionToDispersionAdapter

        self.runtime_config = get_config()
        self.name = "calculate_dispersion"
        self.description = "Calculate pollutant dispersion using PS-XGB-RLINE surrogate model"
        self._calculator_class = DispersionCalculator
        self._config_class = DispersionConfig
        self._adapter = EmissionToDispersionAdapter
        self._calculator_cache: Dict[float, Any] = {}

    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute dispersion calculation.

        Expected kwargs:
            emission_source: "last_result" or a file path
            meteorology: preset name | "custom" | .sfc path
            wind_speed / wind_direction / stability_class / mixing_height for custom met
            roughness_height: 0.05 | 0.5 | 1.0
            pollutant: primary pollutant to disperse; defaults to NOx
            _last_result: injected upstream previous tool result payload
            _spatial_emission_layer: Phase 7.5B spatial emission layer dict (optional)
        """
        try:
            emission_source = kwargs.get("emission_source", "last_result")
            meteorology = kwargs.get("meteorology", "urban_summer_day")
            roughness = float(kwargs.get("roughness_height", 0.5))
            pollutant = str(kwargs.get("pollutant") or "NOx")
            grid_resolution = float(kwargs.get("grid_resolution", 50))
            contour_resolution = float(
                kwargs.get(
                    "contour_resolution",
                    getattr(self.runtime_config, "contour_interp_resolution_m", 10.0),
                )
            )
            spatial_layer = kwargs.get("_spatial_emission_layer")

            # Track which parameters used defaults
            defaults_used = {}
            if "meteorology" not in kwargs:
                defaults_used["meteorology"] = "urban_summer_day"
            if "roughness_height" not in kwargs:
                defaults_used["roughness_height"] = 0.5
            if "pollutant" not in kwargs:
                defaults_used["pollutant"] = "NOx"
            if "grid_resolution" not in kwargs:
                defaults_used["grid_resolution"] = 50
            if "contour_resolution" not in kwargs and getattr(
                self.runtime_config,
                "enable_contour_output",
                True,
            ):
                defaults_used["contour_resolution"] = contour_resolution

            emission_data = self._resolve_emission_source(emission_source, kwargs, spatial_layer)
            if emission_data is None:
                return ToolResult(
                    success=False,
                    error="No emission data available. Please run calculate_macro_emission first.",
                    data=None,
                )

            inferred_label = self._extract_scenario_label(emission_data)
            scenario_label = str(kwargs.get("scenario_label") or inferred_label or "baseline")

            # Phase 7.5B: load direct geometry from spatial emission layer
            geometry_source = None
            if isinstance(spatial_layer, dict) and spatial_layer.get("layer_available"):
                geometry_source = _load_geometry_from_spatial_layer(spatial_layer)
                if geometry_source is not None:
                    logger.info(
                        "Loaded %d geometry records from spatial_emission_layer (source=%s, geom_col=%s)",
                        len(geometry_source),
                        spatial_layer.get("source_file_path"),
                        spatial_layer.get("geometry_column"),
                    )

            roads_gdf, emissions_df = self._adapter.adapt(
                emission_data,
                geometry_source=geometry_source,
                pollutant=pollutant,
            )
            if roads_gdf.empty:
                return ToolResult(
                    success=False,
                    error="No road geometry found in emission results. Cannot compute dispersion without spatial data.",
                    data=None,
                )

            coverage = assess_coverage(roads_gdf)
            logger.info(
                "Coverage assessment: %s, density=%.1f km/km²",
                coverage.level,
                coverage.road_density_km_per_km2,
            )

            met_input = self._build_met_input(meteorology, kwargs)
            calculator = self._get_calculator(roughness)
            if hasattr(calculator, "config"):
                calculator.config.display_grid_resolution_m = grid_resolution
                calculator.config.contour_enabled = bool(
                    getattr(self.runtime_config, "enable_contour_output", True)
                )
                calculator.config.contour_interp_resolution_m = contour_resolution
                calculator.config.contour_n_levels = int(
                    getattr(self.runtime_config, "contour_n_levels", 12)
                )
                calculator.config.contour_smooth_sigma = float(
                    getattr(self.runtime_config, "contour_smooth_sigma", 1.0)
                )
            result = calculator.calculate(
                roads_gdf=roads_gdf,
                emissions_df=emissions_df,
                met_input=met_input,
                pollutant=pollutant,
                coverage_assessment=coverage,
            )

            if result.get("status") != "success":
                error_data = result.copy()
                error_data.pop("failure_detail", None)
                error_code = str(result.get("error_code") or "")
                if error_code == "DISPERSION_GRID_TOO_LARGE":
                    message = result.get(
                        "message",
                        "Dispersion grid is too large for the current preflight limit.",
                    )
                    return ToolResult(
                        success=False,
                        error=message,
                        data={
                            "error_code": error_code,
                            "status": result.get("status"),
                            "message": message,
                            "receptors": result.get("receptors"),
                            "sources": result.get("sources"),
                            "estimated_pairs": result.get("estimated_pairs"),
                            "limit": result.get("limit"),
                        },
                    )
                return ToolResult(
                    success=False,
                    error=result.get("message", "Dispersion calculation failed"),
                    data=error_data,
                )

            data = result["data"]
            data.setdefault("coverage_assessment", coverage.to_dict())
            data["meteorology_used"] = self._build_meteorology_used(meteorology, met_input)
            data["scenario_label"] = scenario_label
            data["roads_wgs84"] = self._serialize_roads_wgs84(roads_gdf)
            if defaults_used:
                data["defaults_used"] = defaults_used
            summary = self._build_summary(data, meteorology, roughness, pollutant)
            return ToolResult(
                success=True,
                error=None,
                data=data,
                summary=summary,
                map_data=self._build_map_data(data, pollutant),
            )
        except Exception as exc:
            logger.error("Dispersion tool execution failed: %s", exc, exc_info=True)
            return ToolResult(
                success=False,
                error=f"Dispersion calculation error: {exc}",
                data=None,
            )

    def _resolve_emission_source(
        self,
        emission_source: str,
        kwargs: Dict[str, Any],
        spatial_layer: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """Resolve emission input from the previous macro-emission result or a file source.

        Phase 7.5B: when a spatial_emission_layer is available with direct geometry,
        emission data can come from _last_result (macro output) while geometry
        is loaded separately from the source file.
        """
        if emission_source == "last_result":
            last_result = kwargs.get("_last_result")
            if not isinstance(last_result, dict):
                return None

            if last_result.get("status") == "success" and isinstance(last_result.get("data"), dict):
                normalized = last_result
            elif last_result.get("success") and isinstance(last_result.get("data"), dict):
                normalized = {"status": "success", "data": last_result["data"]}
            else:
                return None

            results = normalized["data"].get("results")
            if not isinstance(results, list) or not results:
                logger.warning("calculate_dispersion received last_result without data.results")
                return None

            sample = next((item for item in results if isinstance(item, dict)), {})
            if "total_emissions_kg_per_hr" not in sample and "link_length_km" not in sample:
                logger.warning("calculate_dispersion last_result does not look like macro emission output")
                return None

            return normalized

        # Phase 7.5B: file-based emission source with spatial layer
        candidate = str(emission_source).strip()
        if candidate and isinstance(spatial_layer, dict) and spatial_layer.get("layer_available"):
            source_path = spatial_layer.get("source_file_path")
            if source_path:
                return _build_emission_data_from_source_file(source_path, spatial_layer)

        if candidate:
            logger.warning(
                "calculate_dispersion file-based emission_source is not supported yet: %s",
                candidate,
            )
        return None

    def _extract_scenario_label(self, emission_data: Dict[str, Any]) -> Optional[str]:
        data = emission_data.get("data", emission_data)
        if not isinstance(data, dict):
            return None
        label = data.get("scenario_label")
        if isinstance(label, str) and label.strip():
            return label.strip()
        return None

    def _build_met_input(self, meteorology: str, kwargs: Dict[str, Any]) -> Any:
        """Build meteorology input for the calculator from preset, preset+override, custom, or SFC path."""
        if isinstance(meteorology, str) and Path(meteorology).suffix.lower() == ".sfc":
            return meteorology

        user_overrides = self._extract_meteorology_overrides(kwargs)
        if meteorology != "custom":
            if not user_overrides and meteorology in PRESET_METEOROLOGY:
                return meteorology

            if meteorology in PRESET_METEOROLOGY or user_overrides:
                met_dict = self._load_preset(meteorology)
                if user_overrides:
                    met_dict["_source_mode"] = "preset_override"
                    met_dict["_overrides"] = {}
                    for key, value in user_overrides.items():
                        original = met_dict.get(key)
                        met_dict[key] = value
                        met_dict["_overrides"][key] = {"from": original, "to": value}
                    if "stability_class" in user_overrides:
                        self._apply_stability_metadata(met_dict)
                    logger.info(
                        "Meteorology: preset '%s' with overrides: %s",
                        met_dict.get("_preset_name"),
                        sorted(user_overrides),
                    )
                return met_dict

            logger.warning(
                "Unknown meteorology input '%s', falling back to urban_summer_day",
                meteorology,
            )
            return "urban_summer_day"

        if meteorology == "custom":
            met_dict = {
                "wind_speed": float(kwargs.get("wind_speed", 3.0)),
                "wind_direction": float(kwargs.get("wind_direction", 270.0)),
                "stability_class": str(kwargs.get("stability_class", "N1")).upper(),
                "mixing_height": float(kwargs.get("mixing_height", 800.0)),
                "temperature_k": float(kwargs.get("temperature_k", 293.0)),
                "_preset_name": None,
                "_overrides": {},
                "_source_mode": "custom",
            }
            self._apply_stability_metadata(met_dict)
            return met_dict

        logger.warning(
            "Unknown meteorology input '%s', falling back to urban_summer_day",
            meteorology,
        )
        return "urban_summer_day"

    def _extract_meteorology_overrides(self, kwargs: Dict[str, Any]) -> Dict[str, Any]:
        """Return normalized user-provided meteorology overrides, ignoring null values."""
        overrides: Dict[str, Any] = {}
        for key in MET_OVERRIDE_KEYS:
            value = kwargs.get(key)
            if value is None:
                continue
            if key == "stability_class":
                normalized = str(value).upper()
                if normalized not in CUSTOM_STABILITY_TO_L:
                    raise ValueError(f"Unsupported stability_class for meteorology override: {normalized}")
                overrides[key] = normalized
            else:
                overrides[key] = float(value)
        return overrides

    def _apply_stability_metadata(self, met_dict: Dict[str, Any]) -> None:
        """Keep derived stability parameters consistent when stability_class is custom-set or overridden."""
        stability_class = str(met_dict.get("stability_class", "")).upper()
        if stability_class not in CUSTOM_STABILITY_TO_L:
            raise ValueError(f"Unsupported stability_class for meteorology input: {stability_class}")
        met_dict["stability_class"] = stability_class
        met_dict["monin_obukhov_length"] = CUSTOM_STABILITY_TO_L[stability_class]
        met_dict["H"] = CUSTOM_STABILITY_TO_H[stability_class]

    def _load_preset(self, preset_name: str) -> Dict[str, Any]:
        """Load a meteorology preset from YAML and return a calculator-ready dict."""
        presets = _load_meteorology_presets()
        actual_name = preset_name
        preset_data = presets.get(preset_name)
        if preset_data is None:
            logger.warning("Preset '%s' not found, falling back to urban_summer_day", preset_name)
            actual_name = "urban_summer_day"
            preset_data = presets[actual_name]

        met_dict = {
            "wind_speed": float(preset_data["wind_speed_mps"]),
            "wind_direction": float(preset_data["wind_direction_deg"]),
            "stability_class": str(preset_data["stability_class"]).upper(),
            "mixing_height": float(preset_data["mixing_height_m"]),
            "temperature_k": float(preset_data.get("temperature_k", 293.0)),
            "monin_obukhov_length": float(preset_data.get("monin_obukhov_length", -200.0)),
            "_preset_name": actual_name,
            "_overrides": {},
            "_source_mode": "preset",
        }
        if "description" in preset_data:
            met_dict["_preset_description"] = preset_data["description"]
        if actual_name != preset_name:
            met_dict["_requested_preset_name"] = preset_name
        return met_dict

    def _build_meteorology_used(self, meteorology: str, met_input: Any) -> Dict[str, Any]:
        """Build a result-facing meteorology metadata payload for summaries and downstream tools."""
        if isinstance(met_input, dict):
            meteorology_used = dict(met_input)
            if meteorology_used.get("_preset_name"):
                meteorology_used.setdefault(
                    "_source_mode",
                    "preset_override" if meteorology_used.get("_overrides") else "preset",
                )
            else:
                meteorology_used.setdefault("_source_mode", "custom")
            meteorology_used.setdefault("_overrides", {})
            return meteorology_used

        if isinstance(met_input, str) and Path(met_input).suffix.lower() == ".sfc":
            return {
                "_source_mode": "sfc_file",
                "_preset_name": None,
                "_overrides": {},
                "path": met_input,
            }

        if isinstance(met_input, str):
            meteorology_used = self._load_preset(met_input)
            meteorology_used["_source_mode"] = "preset"
            return meteorology_used

        return {
            "_source_mode": "unknown",
            "_preset_name": meteorology,
            "_overrides": {},
        }

    @staticmethod
    def _format_meteorology_value(value: Any) -> str:
        if isinstance(value, float) and value.is_integer():
            return str(int(value))
        if isinstance(value, (int, float)):
            return f"{float(value):g}"
        return str(value)

    def _get_calculator(
        self,
        roughness: float,
        grid_resolution: Optional[float] = None,
        contour_resolution: Optional[float] = None,
    ) -> Any:
        """Get or lazily construct a calculator instance for the requested roughness height."""
        if roughness not in (0.05, 0.5, 1.0):
            raise ValueError("roughness_height must be one of: 0.05, 0.5, 1.0")

        if roughness not in self._calculator_cache:
            config = self._config_class(
                roughness_height=roughness,
                contour_enabled=bool(getattr(self.runtime_config, "enable_contour_output", True)),
                contour_interp_resolution_m=float(
                    getattr(self.runtime_config, "contour_interp_resolution_m", 10.0)
                ),
                contour_n_levels=int(getattr(self.runtime_config, "contour_n_levels", 12)),
                contour_smooth_sigma=float(
                    getattr(self.runtime_config, "contour_smooth_sigma", 1.0)
                ),
            )
            self._calculator_cache[roughness] = self._calculator_class(config=config)
        calculator = self._calculator_cache[roughness]
        if grid_resolution is not None:
            calculator.config.display_grid_resolution_m = float(grid_resolution)
        if contour_resolution is not None:
            calculator.config.contour_interp_resolution_m = float(contour_resolution)
        return calculator

    def preflight_check(self, parameters: Dict[str, Any]) -> PreflightCheckResult:
        """Check that dispersion model files exist for the requested parameters."""
        from calculators.dispersion import get_model_paths, STABILITY_ABBREV

        try:
            meteorology = str(parameters.get("meteorology", "urban_summer_day"))
            # .sfc inputs: stability class is unknown until the file is parsed at runtime
            if Path(meteorology).suffix.lower() == ".sfc":
                return PreflightCheckResult(is_ready=True)

            try:
                roughness_height = float(parameters.get("roughness_height", 0.5))
            except (TypeError, ValueError):
                roughness_height = 0.5

            stability_abbrev = self._resolve_stability_class(meteorology, parameters)
            if stability_abbrev is None:
                # Cannot determine stability ahead of time; let execute() handle it
                return PreflightCheckResult(is_ready=True)

            try:
                x0_path, xneg_path = get_model_paths(stability_abbrev, roughness_height)
            except ValueError:
                # Invalid roughness or stability value; let execute() handle with proper error
                return PreflightCheckResult(is_ready=True)

            missing = [p for p in (x0_path, xneg_path) if not p.exists()]
            if not missing:
                return PreflightCheckResult(is_ready=True)

            # Build availability map across all stability classes for the LLM
            available: list = []
            for abbrev in STABILITY_ABBREV:
                try:
                    p0, pn = get_model_paths(abbrev, roughness_height)
                    if p0.exists() and pn.exists():
                        available.append(abbrev)
                except Exception:
                    pass

            return PreflightCheckResult(
                is_ready=False,
                reason_code="model_asset_missing",
                message=(
                    f"Dispersion model files missing for stability class '{stability_abbrev}': "
                    + ", ".join(p.name for p in missing)
                ),
                missing_requirements=[f"model:{stability_abbrev}"],
                details={
                    "stability_class": stability_abbrev,
                    "roughness_height": roughness_height,
                    "missing_files": [p.name for p in missing],
                    "available_stability_classes": available,
                },
            )

        except Exception:
            logger.warning("Dispersion preflight check error, skipping", exc_info=True)
            return PreflightCheckResult(is_ready=True)

    def _resolve_stability_class(self, meteorology: str, parameters: Dict[str, Any]) -> Optional[str]:
        """Resolve the stability class abbreviation from the meteorology parameter."""
        from calculators.dispersion import STABILITY_ABBREV
        valid = set(STABILITY_ABBREV.keys())

        if meteorology == "custom":
            sc = str(parameters.get("stability_class", "N1")).upper()
            return sc if sc in valid else "N1"

        if meteorology in PRESET_METEOROLOGY:
            try:
                preset = self._load_preset(meteorology)
                sc = str(preset.get("stability_class", "N1")).upper()
                return sc if sc in valid else None
            except Exception:
                return None

        return None

    def _build_summary(
        self,
        data: Dict[str, Any],
        meteorology: str,
        roughness: float,
        pollutant: str,
    ) -> str:
        """Build a concise human-readable summary for synthesis and UI display."""
        summary = data.get("summary", {})
        query_info = data.get("query_info", {})
        receptor_count = summary.get("receptor_count", query_info.get("n_receptors", "N/A"))
        time_steps = summary.get("time_steps", query_info.get("n_time_steps", "N/A"))
        mean_conc = float(summary.get("mean_concentration", 0.0))
        max_conc = float(summary.get("max_concentration", 0.0))
        unit = summary.get("unit", "μg/m³")
        summary_parts = [
            f"{pollutant} dispersion calculation completed.",
            f"Receptors: {receptor_count}, Time steps: {time_steps}",
        ]

        met_info = data.get("meteorology_used", {})
        if isinstance(met_info, dict) and met_info:
            preset_name = met_info.get("_preset_name")
            overrides = met_info.get("_overrides", {})
            source_mode = met_info.get("_source_mode")
            if source_mode == "sfc_file":
                summary_parts.append(f"Meteorology: SFC file '{met_info.get('path', meteorology)}'")
            elif preset_name:
                if overrides:
                    override_desc = ", ".join(
                        f"{key}: {self._format_meteorology_value(change.get('from'))}"
                        f"→{self._format_meteorology_value(change.get('to'))}"
                        for key, change in overrides.items()
                    )
                    summary_parts.append(
                        f"Meteorology: preset '{preset_name}' with overrides ({override_desc})"
                    )
                else:
                    summary_parts.append(f"Meteorology: preset '{preset_name}'")
                summary_parts.append(
                    "Meteorology detail: "
                    f"wind={self._format_meteorology_value(met_info.get('wind_speed'))} m/s, "
                    f"dir={self._format_meteorology_value(met_info.get('wind_direction'))}°, "
                    f"stability={met_info.get('stability_class')}, "
                    f"mixing_height={self._format_meteorology_value(met_info.get('mixing_height'))} m"
                )
            else:
                summary_parts.append(
                    "Meteorology: custom "
                    f"(wind={self._format_meteorology_value(met_info.get('wind_speed'))} m/s, "
                    f"dir={self._format_meteorology_value(met_info.get('wind_direction'))}°, "
                    f"stability={met_info.get('stability_class')}, "
                    f"mixing_height={self._format_meteorology_value(met_info.get('mixing_height'))} m)"
                )
        else:
            met_desc = meteorology or query_info.get("met_source", "unknown")
            summary_parts.append(f"Meteorology: {met_desc}")

        summary_parts.append(f"Surface roughness: {roughness} m")
        summary_parts.append(f"Mean concentration: {mean_conc:.4f} {unit}")
        summary_parts.append(f"Max concentration: {max_conc:.4f} {unit}")

        coverage = data.get("coverage_assessment", {})
        warnings = coverage.get("warnings", []) if isinstance(coverage, dict) else []
        raster = data.get("raster_grid", {})
        if isinstance(raster, dict) and raster:
            summary_parts.append(
                f"Grid resolution: {self._format_meteorology_value(raster.get('resolution_m', 50.0))} m "
                f"({raster.get('rows', 0)}x{raster.get('cols', 0)} cells)"
            )
        for warning in warnings:
            summary_parts.append(f"⚠️ {warning}")

        # Report default parameters used
        defaults_used = data.get("defaults_used", {})
        if defaults_used:
            default_items = []
            if "meteorology" in defaults_used:
                default_items.append(f"气象预设={defaults_used['meteorology']}")
            if "roughness_height" in defaults_used:
                default_items.append(f"地表粗糙度={defaults_used['roughness_height']}m")
            if "pollutant" in defaults_used:
                default_items.append(f"污染物={defaults_used['pollutant']}")
            if "grid_resolution" in defaults_used:
                default_items.append(f"网格分辨率={defaults_used['grid_resolution']}m")
            if "contour_resolution" in defaults_used:
                default_items.append(f"等值带分辨率={defaults_used['contour_resolution']}m")
            summary_parts.append(f"Defaults used: {', '.join(default_items)}")

        return "\n".join(summary_parts)

    def _build_map_data(self, data: Dict[str, Any], pollutant: str) -> Dict[str, Any]:
        """Build map payload with concentration_grid so spatial_renderer can detect it later."""
        contour_bands = data.get("contour_bands")
        has_valid_contour = (
            isinstance(contour_bands, dict)
            and not contour_bands.get("error")
            and isinstance(contour_bands.get("geojson"), dict)
        )
        map_data = {
            "concentration_grid": data.get("concentration_grid", {}),
            "type": "contour" if has_valid_contour else ("raster" if "raster_grid" in data else "concentration"),
            "pollutant": pollutant,
            "summary": data.get("summary", {}),
            "query_info": data.get("query_info", {}),
            "scenario_label": str(data.get("scenario_label") or "baseline"),
        }
        if "raster_grid" in data:
            map_data["raster_grid"] = data["raster_grid"]
        if "contour_bands" in data:
            map_data["contour_bands"] = data["contour_bands"]
        if "coverage_assessment" in data:
            map_data["coverage_assessment"] = data["coverage_assessment"]
        return map_data

    def _serialize_roads_wgs84(self, roads_gdf) -> Dict[str, Any]:
        """Serialize adapted road geometries to GeoJSON for downstream export."""
        if roads_gdf is None or getattr(roads_gdf, "empty", True):
            return {"type": "FeatureCollection", "features": []}

        export_gdf = roads_gdf
        try:
            if getattr(export_gdf, "crs", None) is not None and str(export_gdf.crs) != "EPSG:4326":
                export_gdf = export_gdf.to_crs("EPSG:4326")
        except Exception:
            logger.warning("Failed to normalize roads GeoDataFrame CRS for export", exc_info=True)

        features = []
        for _, row in export_gdf.iterrows():
            geometry = row.get("geometry")
            if geometry is None or getattr(geometry, "is_empty", True):
                continue
            road_id = str(row.get("NAME_1") or row.get("road_id") or "").strip()
            features.append(
                {
                    "type": "Feature",
                    "geometry": mapping(geometry),
                    "properties": {"road_id": road_id},
                }
            )
        return {"type": "FeatureCollection", "features": features}


# ── Phase 7.5B: spatial emission layer geometry helpers ───────────────────


def _load_geometry_from_spatial_layer(
    spatial_layer: Dict[str, Any],
) -> Optional[List[Dict[str, Any]]]:
    """Read geometry-bearing rows from the source file referenced by a spatial emission layer.

    Accepts WKT, GeoJSON, and lonlat_linestring geometry types.  Returns a list of
    dicts with ``link_id`` and ``geometry`` keys suitable for passing as the
    ``geometry_source`` parameter to :meth:`EmissionToDispersionAdapter.adapt`.

    Returns None when the source file cannot be read or the geometry column is absent.
    """
    if not isinstance(spatial_layer, dict):
        return None

    source_path = spatial_layer.get("source_file_path")
    if not source_path:
        return None

    geom_type = str(spatial_layer.get("geometry_type", "")).lower()
    geom_column = spatial_layer.get("geometry_column")
    geometry_columns = spatial_layer.get("geometry_columns") or []
    join_keys = spatial_layer.get("join_key_columns") or {}

    if geom_type not in ("wkt", "geojson", "lonlat_linestring", "spatial_metadata"):
        return None

    # Resolve the geometry column
    resolved_geom_col = geom_column
    if not resolved_geom_col and geometry_columns:
        resolved_geom_col = geometry_columns[0]
    if not resolved_geom_col:
        return None

    # Resolve the join key (prefer link_id)
    link_col = None
    for key_name in ("link_id", "road_id", "segment_id", "edge_id", "link"):
        if key_name in join_keys:
            link_col = join_keys[key_name]
            break
    if not link_col:
        for val in join_keys.values():
            if val:
                link_col = str(val)
                break

    try:
        import pandas as pd
        from pathlib import Path

        path = Path(source_path)
        if not path.exists():
            logger.warning("spatial_emission_layer source file not found: %s", source_path)
            return None

        if path.suffix.lower() == ".csv":
            df = pd.read_csv(source_path)
        elif path.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(source_path)
        else:
            logger.warning("Unsupported source file format for spatial layer: %s", path.suffix)
            return None

        # Normalise column names
        df.columns = df.columns.str.strip()

        if resolved_geom_col not in df.columns:
            logger.warning(
                "Geometry column '%s' not found in source file columns: %s",
                resolved_geom_col,
                list(df.columns),
            )
            return None

        # Determine the id column
        id_col = None
        if link_col and link_col in df.columns:
            id_col = link_col
        else:
            # Fall back to first join key that exists in columns
            for jk_name, jk_col in join_keys.items():
                if jk_col and jk_col in df.columns:
                    id_col = jk_col
                    break

        rows = []
        for _, row in df.iterrows():
            geom_val = row.get(resolved_geom_col)
            if geom_val is None or (isinstance(geom_val, str) and not geom_val.strip()):
                continue
            link_val = str(row[id_col]) if id_col and id_col in df.columns else None
            entry = {"geometry": geom_val}
            if link_val:
                entry["link_id"] = link_val
            rows.append(entry)

        if not rows:
            logger.warning("No geometry rows loaded from spatial layer source: %s", source_path)
            return None

        return rows

    except Exception as exc:
        logger.warning("Failed to load geometry from spatial layer source '%s': %s", source_path, exc)
        return None


def _build_emission_data_from_source_file(
    source_path: str,
    spatial_layer: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Build minimal emission_data payload from a source file when no macro result exists.

    Used by _resolve_emission_source when emission_source is a file path and a
    spatial_emission_layer with direct geometry is available.  Constructs the
    expected {status: success, data: {results: [...]}} structure for the adapter.
    """
    try:
        import pandas as pd
        from pathlib import Path

        path = Path(source_path)
        if not path.exists():
            return None

        if path.suffix.lower() == ".csv":
            df = pd.read_csv(source_path)
        elif path.suffix.lower() in (".xlsx", ".xls"):
            df = pd.read_excel(source_path)
        else:
            return None

        df.columns = df.columns.str.strip()
        join_keys = spatial_layer.get("join_key_columns") or {}
        link_col = join_keys.get("link_id") or join_keys.get("road_id")

        results = []
        for _, row in df.iterrows():
            rec = {}
            # Map link_id
            if link_col and link_col in df.columns:
                rec["link_id"] = row[link_col]
            else:
                # Try to find any id-like column
                for col in df.columns:
                    col_lower = col.lower()
                    if any(t in col_lower for t in ("link_id", "link", "road_id", "segment_id")):
                        rec["link_id"] = row[col]
                        break
                if "link_id" not in rec:
                    continue

            # Map length
            for col in df.columns:
                col_lower = col.lower()
                if any(t in col_lower for t in ("length", "link_length")):
                    rec["link_length_km"] = float(row[col]) if pd.notna(row[col]) else 0.0
                    break

            # Synthetic emission value (placeholder — real values come from macro)
            rec.setdefault("link_length_km", 0.5)
            rec.setdefault("total_emissions_kg_per_hr", {"NOx": 0.0})
            results.append(rec)

        if not results:
            return None

        return {"status": "success", "data": {"results": results}}

    except Exception as exc:
        logger.warning("Failed to build emission data from source file '%s': %s", source_path, exc)
        return None


__all__ = ["DispersionTool"]
