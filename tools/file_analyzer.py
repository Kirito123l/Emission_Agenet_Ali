"""
File Analyzer Tool
Analyzes uploaded files to identify type and structure
"""
import json
import logging
import os
import pandas as pd
import tempfile
import zipfile
import warnings
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from tools.base import BaseTool, ToolResult
from services.standardizer import get_standardizer

logger = logging.getLogger(__name__)

# Try importing geopandas for Shapefile support
try:
    import geopandas as gpd
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[FileAnalyzer] geopandas not available, Shapefile support disabled")


class FileAnalyzerTool(BaseTool):
    """
    Analyzes file structure and suggests processing method

    Ported from: skills/common/file_analyzer.py
    """

    def __init__(self):
        super().__init__()
        self.standardizer = get_standardizer()

    async def execute(self, file_path: str, **kwargs) -> ToolResult:
        """
        Analyze file structure

        Args:
            file_path: Path to file

        Returns:
            ToolResult with file analysis
        """
        try:
            # Validate file exists
            path = Path(file_path)
            if not path.exists():
                return self._error(f"File not found: {file_path}")

            # Handle ZIP files
            if path.suffix.lower() == '.zip':
                return await self._analyze_zip_file(path)

            if path.suffix.lower() == '.shp':
                if not GEOPANDAS_AVAILABLE:
                    return self._error("Shapefile support requires geopandas, which is not available in this runtime.")
                gdf = gpd.read_file(file_path)
                analysis = self._analyze_shapefile_structure(gdf, path.name)
                summary = self._format_shapefile_summary(analysis)
                return self._success(
                    data=analysis,
                    summary=summary
                )

            if path.suffix.lower() in ['.geojson', '.json']:
                return await self._analyze_geojson_file(path)

            # Read file
            if path.suffix.lower() == '.csv':
                df = pd.read_csv(file_path)
            elif path.suffix.lower() in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path)
            else:
                return self._error(
                    f"Unsupported file format: {path.suffix}. Supported: .csv, .xlsx, .xls, .zip, .geojson, .json, .shp"
                )

            if df.empty:
                return self._error("File is empty")

            # Clean column names
            df.columns = df.columns.str.strip()

            # Analyze structure
            analysis = self._analyze_structure(df, path.name)

            # Create summary
            summary = self._format_summary(analysis)

            return self._success(
                data=analysis,
                summary=summary
            )

        except Exception as e:
            logger.exception("File analysis failed")
            return self._error(f"Failed to analyze file: {str(e)}")

    def _analyze_structure(self, df: pd.DataFrame, filename: str) -> Dict[str, Any]:
        """Analyze DataFrame structure"""
        columns = list(df.columns)
        row_count = len(df)

        value_features = self._analyze_value_features(df)
        task_identification = self._identify_task_type(columns, value_features)

        # Map columns
        micro_mapping = self.standardizer.map_columns(columns, "micro_emission")
        macro_mapping = self.standardizer.map_columns(columns, "macro_emission")

        # Check required columns
        micro_required = self.standardizer.get_required_columns("micro_emission")
        macro_required = self.standardizer.get_required_columns("macro_emission")

        micro_has_required = self._has_required_columns(
            micro_mapping,
            micro_required,
            "micro_emission",
        )
        macro_has_required = self._has_required_columns(
            macro_mapping,
            macro_required,
            "macro_emission",
        )

        # Sample data
        sample_rows = df.head(2).to_dict('records')
        column_mapping = self._select_primary_mapping(
            task_identification["task_type"],
            micro_mapping,
            macro_mapping,
        )
        primary_mapping = micro_mapping if task_identification["task_type"] == "micro_emission" else macro_mapping
        missing_field_diagnostics = self._build_missing_field_diagnostics(
            task_identification["task_type"],
            columns,
            primary_mapping if task_identification["task_type"] in {"micro_emission", "macro_emission"} else {},
            value_features,
        )
        unresolved_columns = self._compute_unresolved_columns(
            columns,
            task_identification["task_type"],
            micro_mapping,
            macro_mapping,
        )
        data_quality_warnings = self._build_data_quality_warnings(
            df,
            task_identification["task_type"],
            macro_mapping,
            value_features,
        )

        return {
            "filename": filename,
            "format": "tabular",
            "row_count": row_count,
            "columns": columns,
            "task_type": task_identification["task_type"],
            "confidence": task_identification["confidence"],
            "micro_mapping": micro_mapping,
            "macro_mapping": macro_mapping,
            "column_mapping": column_mapping,
            "micro_has_required": micro_has_required,
            "macro_has_required": macro_has_required,
            "sample_rows": sample_rows,
            "unresolved_columns": unresolved_columns,
            "evidence": task_identification["evidence"],
            "analysis_strategy": "rule",
            "fallback_used": False,
            "selected_primary_table": filename,
            "dataset_roles": [
                {
                    "dataset_name": filename,
                    "role": "primary_analysis",
                    "format": "tabular",
                    "task_type": task_identification["task_type"],
                    "confidence": task_identification["confidence"],
                    "selection_score": task_identification["confidence"],
                    "reason": "Single tabular dataset; rule analyzer treated it as the primary analysis table.",
                    "selected": True,
                    "row_count": row_count,
                    "column_count": len(columns),
                }
            ],
            "dataset_role_summary": {
                "strategy": "rule",
                "ambiguous": False,
                "selected_primary_table": filename,
                "selection_score_gap": None,
                "role_fallback_eligible": False,
            },
            "missing_field_diagnostics": missing_field_diagnostics,
            "data_quality_warnings": data_quality_warnings,
            "value_features_summary": {
                col: feat.get("feature_hints", [])
                for col, feat in value_features.items()
                if feat.get("feature_hints")
            },
        }

    def _is_mapping_reliable(self, source_column: str, standard_name: str, task_type: str) -> bool:
        """Filter out low-signal substring matches such as single-letter columns."""
        source_lower = source_column.lower().strip()
        patterns = self.standardizer.column_patterns.get(task_type, {})

        for field_config in patterns.values():
            if field_config.get("standard") != standard_name:
                continue
            pattern_list = [pattern.lower() for pattern in field_config.get("patterns", [])]
            if source_lower in pattern_list:
                return True
            break

        return len(source_lower) >= 3

    def _has_required_columns(
        self,
        mapping: Dict[str, str],
        required_columns: List[str],
        task_type: str,
    ) -> bool:
        """Check required-field completeness while ignoring suspicious mappings."""
        reliable_mapped_fields = {
            standard_name
            for source_column, standard_name in mapping.items()
            if self._is_mapping_reliable(source_column, standard_name, task_type)
        }
        return all(req in reliable_mapped_fields for req in required_columns)

    def _select_primary_mapping(
        self,
        task_type: str,
        micro_mapping: Dict[str, str],
        macro_mapping: Dict[str, str],
    ) -> Dict[str, str]:
        if task_type == "micro_emission":
            return dict(micro_mapping or {})
        if task_type == "macro_emission":
            return dict(macro_mapping or {})
        return {}

    def _compute_unresolved_columns(
        self,
        columns: List[str],
        task_type: str,
        micro_mapping: Dict[str, str],
        macro_mapping: Dict[str, str],
    ) -> List[str]:
        if task_type == "micro_emission":
            mapped = set((micro_mapping or {}).keys())
        elif task_type == "macro_emission":
            mapped = set((macro_mapping or {}).keys())
        else:
            mapped = set((micro_mapping or {}).keys()) | set((macro_mapping or {}).keys())
        return [str(column) for column in columns if column not in mapped]

    def _build_data_quality_warnings(
        self,
        df: pd.DataFrame,
        task_type: str,
        macro_mapping: Dict[str, str],
        value_features: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if task_type != "macro_emission" or df.empty:
            return []

        speed_column = next(
            (source for source, standard in (macro_mapping or {}).items() if standard == "avg_speed_kph"),
            None,
        )
        if not speed_column:
            candidates = self._identify_derivable_candidates(
                "avg_speed_kph",
                list(df.columns),
                value_features,
            )
            for candidate in candidates:
                if candidate.get("derivation") in {"direct_speed_signal", "speed_unit_conversion"}:
                    speed_column = candidate["source_column"]
                    break

        road_type_column = self._find_road_type_column(list(df.columns))
        if not speed_column or not road_type_column:
            return []

        speed_series = pd.to_numeric(df[speed_column], errors="coerce")
        road_type_series = self._normalize_road_type_series(df[road_type_column])
        quality_frame = pd.DataFrame(
            {
                "road_type": road_type_series,
                "avg_speed_kph": speed_series,
            }
        ).dropna()
        if quality_frame.empty:
            return []

        warnings: List[Dict[str, Any]] = []
        grouped = quality_frame.groupby("road_type")["avg_speed_kph"].agg(["mean", "count"])

        if "高速公路" in grouped.index:
            mean_speed = float(grouped.loc["高速公路", "mean"])
            if mean_speed < 30.0:
                warnings.append(
                    {
                        "warning_type": "speed_road_type_consistency",
                        "severity": "warning",
                        "road_type": "高速公路",
                        "observed_mean_speed_kph": round(mean_speed, 2),
                        "expected_range_note": "高速公路均速通常不应长期低于 30 km/h",
                        "sample_size": int(grouped.loc["高速公路", "count"]),
                        "source_columns": {
                            "road_type": road_type_column,
                            "avg_speed_kph": speed_column,
                        },
                        "message": (
                            f"Road rows standardized as 高速公路 have mean speed {mean_speed:.1f} km/h, "
                            "which is unusually low and may indicate road-type labeling or speed-quality issues."
                        ),
                    }
                )

        if "支路" in grouped.index:
            mean_speed = float(grouped.loc["支路", "mean"])
            if mean_speed > 100.0:
                warnings.append(
                    {
                        "warning_type": "speed_road_type_consistency",
                        "severity": "warning",
                        "road_type": "支路",
                        "observed_mean_speed_kph": round(mean_speed, 2),
                        "expected_range_note": "支路均速通常不应长期高于 100 km/h",
                        "sample_size": int(grouped.loc["支路", "count"]),
                        "source_columns": {
                            "road_type": road_type_column,
                            "avg_speed_kph": speed_column,
                        },
                        "message": (
                            f"Road rows standardized as 支路 have mean speed {mean_speed:.1f} km/h, "
                            "which is unusually high and may indicate road-type labeling or speed-quality issues."
                        ),
                    }
                )

        return warnings

    def _find_road_type_column(self, columns: List[str]) -> Optional[str]:
        preferred_exact = {
            "road_type",
            "road_class",
            "road_category",
            "functional_class",
            "道路类型",
            "道路等级",
            "道路功能",
            "highway",
        }
        preferred_tokens = (
            "road_type",
            "roadclass",
            "road_class",
            "roadcategory",
            "road_category",
            "functionalclass",
            "functional_class",
            "道路类型",
            "道路等级",
            "道路功能",
            "highway",
        )

        for column in columns:
            normalized = str(column).lower().strip().replace("-", "_").replace(" ", "_")
            if normalized in preferred_exact:
                return str(column)

        for column in columns:
            normalized = str(column).lower().strip().replace("-", "_").replace(" ", "_")
            if any(token in normalized for token in preferred_tokens):
                return str(column)

        return None

    def _normalize_road_type_series(self, series: pd.Series) -> pd.Series:
        cache: Dict[str, Optional[str]] = {}
        normalized_values: List[Optional[str]] = []

        for value in series:
            text = str(value).strip() if value is not None else ""
            if not text or text.lower() == "nan":
                normalized_values.append(None)
                continue

            if text not in cache:
                result = self.standardizer.standardize_road_type(text)
                cache[text] = result.normalized if result.strategy != "default" else None
            normalized_values.append(cache[text])

        return pd.Series(normalized_values, index=series.index, dtype="object")

    def _build_missing_field_diagnostics(
        self,
        task_type: str,
        columns: List[str],
        mapping: Dict[str, str],
        value_features: Dict[str, Dict[str, Any]],
    ) -> Dict[str, Any]:
        if task_type not in {"macro_emission", "micro_emission"}:
            return {
                "task_type": task_type or "unknown",
                "status": "unknown_task",
                "required_fields": [],
                "mapped_fields": [],
                "required_field_statuses": [],
                "missing_fields": [],
                "derivable_opportunities": [],
            }

        required_fields = [str(item) for item in self.standardizer.get_required_columns(task_type)]
        mapped_fields = set((mapping or {}).values())
        source_by_field = {
            str(standard_name): str(source_column)
            for source_column, standard_name in (mapping or {}).items()
        }

        field_statuses: List[Dict[str, Any]] = []
        derivable_opportunities: List[Dict[str, Any]] = []

        for field_name in required_fields:
            if field_name in mapped_fields:
                field_statuses.append(
                    {
                        "field": field_name,
                        "status": "present",
                        "mapped_from": source_by_field.get(field_name),
                        "candidate_columns": [],
                        "reason": "A reliable rule-based mapping is already available.",
                    }
                )
                continue

            candidates = self._identify_derivable_candidates(field_name, columns, value_features)
            if len(candidates) == 1:
                status = "derivable"
                reason = candidates[0]["reason"]
            elif len(candidates) > 1:
                status = "ambiguous"
                reason = "Multiple plausible source columns remain; a deterministic rule choice is unsafe."
            else:
                status = "missing"
                reason = "No reliable mapping or bounded derivation opportunity was detected."

            candidate_columns = [candidate["source_column"] for candidate in candidates]
            entry = {
                "field": field_name,
                "status": status,
                "mapped_from": None,
                "candidate_columns": candidate_columns,
                "reason": reason,
            }
            if candidates:
                entry["derivation_candidates"] = candidates
            field_statuses.append(entry)
            if status in {"derivable", "ambiguous"}:
                derivable_opportunities.append(entry)

        missing_fields = [entry for entry in field_statuses if entry["status"] != "present"]
        if all(entry["status"] == "present" for entry in field_statuses):
            overall_status = "complete"
        elif any(entry["status"] in {"present", "derivable"} for entry in field_statuses):
            overall_status = "partial"
        else:
            overall_status = "insufficient"

        return {
            "task_type": task_type,
            "status": overall_status,
            "required_fields": required_fields,
            "mapped_fields": sorted(mapped_fields),
            "required_field_statuses": field_statuses,
            "missing_fields": missing_fields,
            "derivable_opportunities": derivable_opportunities,
        }

    def _identify_derivable_candidates(
        self,
        field_name: str,
        columns: List[str],
        value_features: Dict[str, Dict[str, Any]],
    ) -> List[Dict[str, str]]:
        candidates: List[Dict[str, str]] = []

        for column in columns:
            column_name = str(column)
            normalized = column_name.lower().strip().replace("-", "_")
            hints = value_features.get(column_name, {}).get("feature_hints", [])

            if field_name == "link_id" and any(token in normalized for token in ("link", "edge", "road", "seg", "id")):
                candidates.append(
                    {
                        "source_column": column_name,
                        "derivation": "identifier_name_match",
                        "reason": f"Column '{column_name}' looks like a link identifier by filename/token heuristics.",
                    }
                )
            elif field_name in {"traffic_flow_vph"} and (
                "possible_traffic_flow" in hints or any(token in normalized for token in ("flow", "vol", "aadt", "traffic"))
            ):
                candidates.append(
                    {
                        "source_column": column_name,
                        "derivation": "traffic_flow_signal",
                        "reason": f"Column '{column_name}' looks like traffic flow from value hints or common abbreviations.",
                    }
                )
            elif field_name in {"avg_speed_kph", "speed_kph"}:
                if "possible_link_speed_kmh" in hints:
                    candidates.append(
                        {
                            "source_column": column_name,
                            "derivation": "direct_speed_signal",
                            "reason": f"Column '{column_name}' already looks like speed in km/h.",
                        }
                    )
                elif "possible_vehicle_speed_ms" in hints or any(token in normalized for token in ("spd", "speed", "vel")):
                    candidates.append(
                        {
                            "source_column": column_name,
                            "derivation": "speed_unit_conversion",
                            "reason": f"Column '{column_name}' looks like speed and may need a bounded unit conversion to km/h.",
                        }
                    )
            elif field_name == "link_length_km":
                if "possible_link_length" in hints or any(token in normalized for token in ("len", "length", "dist", "km")):
                    derivation = "direct_length_signal"
                    reason = f"Column '{column_name}' looks like link length."
                    if "meter" in normalized or normalized.endswith("_m"):
                        derivation = "length_unit_conversion"
                        reason = f"Column '{column_name}' likely stores link length in meters and may be convertible to km."
                    candidates.append(
                        {
                            "source_column": column_name,
                            "derivation": derivation,
                            "reason": reason,
                        }
                    )
            elif field_name == "time" and (
                "timestamp" in hints or any(token in normalized for token in ("time", "timestamp", "datetime", "date"))
            ):
                candidates.append(
                    {
                        "source_column": column_name,
                        "derivation": "timestamp_signal",
                        "reason": f"Column '{column_name}' looks like a time axis for sequential records.",
                    }
                )
            elif field_name == "acceleration_mps2" and (
                "possible_acceleration" in hints or any(token in normalized for token in ("acc", "accel"))
            ):
                candidates.append(
                    {
                        "source_column": column_name,
                        "derivation": "acceleration_signal",
                        "reason": f"Column '{column_name}' looks like acceleration.",
                    }
                )
            elif field_name == "grade_pct" and (
                "possible_percentage" in hints
                or "possible_fraction" in hints
                or any(token in normalized for token in ("grade", "slope", "pct", "percent"))
            ):
                derivation = "grade_percentage_signal"
                reason = f"Column '{column_name}' looks like grade percentage."
                if "possible_fraction" in hints:
                    derivation = "grade_fraction_conversion"
                    reason = f"Column '{column_name}' looks like a 0-1 fraction and may be convertible to percent grade."
                candidates.append(
                    {
                        "source_column": column_name,
                        "derivation": derivation,
                        "reason": reason,
                    }
                )

        deduped: List[Dict[str, str]] = []
        seen: set[Tuple[str, str]] = set()
        for candidate in candidates:
            key = (candidate["source_column"], candidate["derivation"])
            if key in seen:
                continue
            seen.add(key)
            deduped.append(candidate)
        return deduped

    def _extract_spatial_metadata(self, gdf) -> Dict[str, Any]:
        geometry_name = getattr(getattr(gdf, "geometry", None), "name", None) or "geometry"
        geometry_types = []
        geometry_type_counts: Dict[str, int] = {}
        has_z: Optional[bool] = None
        try:
            geom_type_series = getattr(gdf.geometry, "geom_type", None)
            if geom_type_series is not None:
                geometry_types = [str(item) for item in geom_type_series.unique().tolist()]
                geometry_type_counts = {
                    str(key): int(value)
                    for key, value in geom_type_series.value_counts().to_dict().items()
                }
            has_z_series = getattr(gdf.geometry, "has_z", None)
            if has_z_series is not None:
                has_z = bool(has_z_series.any())
        except Exception:
            geometry_types = []
            geometry_type_counts = {}

        crs_obj = getattr(gdf, "crs", None)
        crs_value = str(crs_obj) if crs_obj else None
        epsg_value = None
        is_projected = None
        is_geographic = None
        if crs_obj is not None:
            try:
                epsg_value = crs_obj.to_epsg()
            except Exception:
                epsg_value = None
            is_projected = getattr(crs_obj, "is_projected", None)
            is_geographic = getattr(crs_obj, "is_geographic", None)

        bounds_info = None
        try:
            bounds = getattr(gdf, "total_bounds", None)
            if bounds is not None and len(bounds) == 4:
                bounds_info = {
                    "min_x": float(bounds[0]),
                    "min_y": float(bounds[1]),
                    "max_x": float(bounds[2]),
                    "max_y": float(bounds[3]),
                }
        except Exception:
            bounds_info = None

        return {
            "geometry_column": geometry_name,
            "feature_count": int(len(gdf)),
            "geometry_types": geometry_types,
            "geometry_type_counts": geometry_type_counts,
            "crs": crs_value,
            "epsg": int(epsg_value) if isinstance(epsg_value, int) else epsg_value,
            "is_projected": is_projected,
            "is_geographic": is_geographic,
            "has_z": has_z,
            "bounds": bounds_info,
        }

    def _score_dataset_candidate(self, analysis: Dict[str, Any], dataset_name: str) -> float:
        confidence = float(analysis.get("confidence") or 0.0)
        task_type = str(analysis.get("task_type") or "unknown").strip()
        score = confidence

        if task_type == "macro_emission" and analysis.get("macro_has_required"):
            score += 0.25
        if task_type == "micro_emission" and analysis.get("micro_has_required"):
            score += 0.25

        normalized_name = dataset_name.lower()
        if any(token in normalized_name for token in ("road", "link", "network", "edge")):
            score += 0.08
        if any(token in normalized_name for token in ("traj", "track", "gps", "probe")):
            score -= 0.04 if task_type == "macro_emission" else 0.08
            if task_type == "micro_emission":
                score += 0.08
        if analysis.get("format") == "shapefile":
            score += 0.05

        return round(score, 3)

    def _role_from_analysis(self, analysis: Dict[str, Any], selected_primary_table: Optional[str]) -> Tuple[str, str]:
        dataset_name = str(analysis.get("filename") or "")
        normalized_name = dataset_name.lower()
        if selected_primary_table and dataset_name == selected_primary_table:
            return "primary_analysis", "Highest bounded score among ZIP candidate datasets."
        if any(token in normalized_name for token in ("traj", "track", "gps", "probe")):
            return "trajectory_candidate", "Filename suggests trajectory-like data rather than the primary aggregate analysis table."
        if analysis.get("format") == "shapefile":
            return "spatial_context", "Geospatial layer retained as a supporting spatial dataset."
        return "secondary_analysis", "Candidate dataset was analyzable but not selected as the primary analysis table."

    def _build_dataset_roles(
        self,
        candidate_analyses: List[Dict[str, Any]],
        file_list: List[str],
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Optional[str]]:
        if not candidate_analyses:
            return [], {"strategy": "rule", "ambiguous": False, "role_fallback_eligible": False}, None

        scored = sorted(
            (
                {
                    **analysis,
                    "selection_score": self._score_dataset_candidate(analysis, str(analysis.get("filename") or "")),
                }
                for analysis in candidate_analyses
            ),
            key=lambda item: item["selection_score"],
            reverse=True,
        )
        selected_primary = str(scored[0].get("filename") or "") if scored else None
        score_gap = 0.0
        if len(scored) > 1:
            score_gap = round(scored[0]["selection_score"] - scored[1]["selection_score"], 3)
        ambiguous = len(scored) > 1 and score_gap < 0.12

        roles: List[Dict[str, Any]] = []
        candidate_names = {str(item.get("filename") or "") for item in scored}
        for analysis in scored:
            role, reason = self._role_from_analysis(analysis, selected_primary)
            if ambiguous and role == "primary_analysis":
                reason = "Rule scoring found multiple close candidates; primary selection remained bounded but ambiguous."
            roles.append(
                {
                    "dataset_name": analysis.get("filename"),
                    "role": role,
                    "format": analysis.get("format"),
                    "task_type": analysis.get("task_type"),
                    "confidence": analysis.get("confidence"),
                    "selection_score": analysis.get("selection_score"),
                    "reason": reason,
                    "selected": analysis.get("filename") == selected_primary,
                    "row_count": analysis.get("row_count"),
                    "column_count": len(analysis.get("columns") or []),
                }
            )

        supporting_files = [item for item in file_list if item not in candidate_names]
        for supporting_file in supporting_files:
            normalized_name = supporting_file.lower()
            role = "supporting_asset"
            reason = "Non-tabular supporting asset inside the ZIP package."
            if normalized_name.endswith((".dbf", ".shx", ".prj", ".cpg", ".qix")):
                role = "supporting_component"
                reason = "Geospatial sidecar component that supports a shapefile dataset."
            elif normalized_name.endswith((".txt", ".md", ".xml")):
                role = "metadata"
                reason = "Metadata or documentation file inside the ZIP package."
            roles.append(
                {
                    "dataset_name": supporting_file,
                    "role": role,
                    "format": Path(supporting_file).suffix.lower().lstrip(".") or "unknown",
                    "task_type": None,
                    "confidence": None,
                    "selection_score": None,
                    "reason": reason,
                    "selected": False,
                }
            )

        role_summary = {
            "strategy": "rule",
            "ambiguous": ambiguous,
            "selected_primary_table": selected_primary,
            "selection_score_gap": score_gap,
            "role_fallback_eligible": ambiguous,
        }
        return roles, role_summary, selected_primary

    def _analyze_value_features(self, df: pd.DataFrame) -> Dict[str, Dict[str, Any]]:
        """Analyze numerical characteristics of each column to assist task type inference.

        Examines value ranges, distributions, and patterns to generate feature hints
        that complement column-name-based identification.

        Args:
            df: The uploaded DataFrame

        Returns:
            Dict mapping column names to their feature analysis:
            {column_name: {dtype, min, max, mean, std, is_positive, is_integer, feature_hints: [...]}}
        """
        if df.empty:
            return {}

        features: Dict[str, Dict[str, Any]] = {}
        for col in df.columns:
            feature_info: Dict[str, Any] = {
                "dtype": str(df[col].dtype),
                "min": None,
                "max": None,
                "mean": None,
                "std": None,
                "is_positive": None,
                "is_integer": None,
                "feature_hints": [],
            }
            features[col] = feature_info

            try:
                series = df[col]

                if not pd.api.types.is_numeric_dtype(series):
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore", UserWarning)
                            converted = pd.to_datetime(series, errors="coerce")
                        valid_ratio = float(converted.notna().mean()) if len(series) > 0 else 0.0
                        if valid_ratio > 0.5:
                            feature_info["feature_hints"].append("timestamp")
                    except Exception:
                        feature_info["feature_hints"] = []
                    continue

                numeric_series = pd.to_numeric(series, errors="coerce").dropna()
                if numeric_series.empty:
                    continue

                min_val = float(numeric_series.min())
                max_val = float(numeric_series.max())
                mean_val = float(numeric_series.mean())
                std_val = float(numeric_series.std(ddof=0))
                is_positive = bool((numeric_series >= 0).all())
                is_integer = bool(((numeric_series - numeric_series.astype(int)).abs() < 1e-9).all())

                feature_info.update({
                    "min": min_val,
                    "max": max_val,
                    "mean": mean_val,
                    "std": std_val,
                    "is_positive": is_positive,
                    "is_integer": is_integer,
                })

                if 0 <= min_val and max_val <= 50 and std_val > 2.0:
                    feature_info["feature_hints"].append("possible_vehicle_speed_ms")
                if 20 <= min_val and max_val <= 160 and std_val < 35:
                    feature_info["feature_hints"].append("possible_link_speed_kmh")
                if -10 <= min_val and max_val <= 10 and abs(mean_val) < 2.0:
                    feature_info["feature_hints"].append("possible_acceleration")
                if 0 <= min_val and max_val <= 1.05:
                    feature_info["feature_hints"].append("possible_fraction")
                if 0 <= min_val and max_val <= 100.5 and is_positive:
                    feature_info["feature_hints"].append("possible_percentage")
                if is_positive and is_integer and 50 <= max_val <= 100000:
                    feature_info["feature_hints"].append("possible_traffic_flow")
                if is_positive and (numeric_series > 0).all() and max_val <= 500:
                    feature_info["feature_hints"].append("possible_link_length")
                if max_val < 0:
                    feature_info["feature_hints"].append("all_negative_exclude_speed_flow")
            except Exception:
                feature_info["feature_hints"] = []

        return features

    def _identify_task_type(
        self,
        columns: List[str],
        value_features: Dict[str, Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Identify task type using multi-signal analysis.

        Signal 1: Column name keyword matching (existing logic, enhanced with evidence)
        Signal 2: Value range and distribution features (new)
        Signal 3: Required field completeness check (existing logic, enhanced)

        Args:
            columns: List of column names from the file
            value_features: Output of _analyze_value_features(), or None if unavailable

        Returns:
            {
                "task_type": "micro_emission" | "macro_emission" | "unknown",
                "confidence": float,
                "evidence": List[str],
            }
        """
        micro_indicators = {
            "speed": "speed",
            "velocity": "velocity",
            "速度": "速度",
            "time": "time",
            "acceleration": "acceleration",
            "加速": "加速",
        }
        macro_indicators = {
            "length": "length",
            "flow": "flow",
            "volume": "volume",
            "traffic": "traffic",
            "长度": "长度",
            "流量": "流量",
            "link": "link",
        }

        micro_score = 0.0
        macro_score = 0.0
        evidence: List[str] = []

        for col in columns:
            col_lower = col.lower().strip()
            for keyword, label in micro_indicators.items():
                if keyword in col_lower:
                    micro_score += 1
                    evidence.append(
                        f"Column '{col}' matches micro keyword '{label}' (signal: column_name)"
                    )
                    break
            for keyword, label in macro_indicators.items():
                if keyword in col_lower:
                    macro_score += 1
                    evidence.append(
                        f"Column '{col}' matches macro keyword '{label}' (signal: column_name)"
                    )
                    break

        if value_features:
            for col, feat in value_features.items():
                hints = feat.get("feature_hints", [])
                if "possible_vehicle_speed_ms" in hints:
                    micro_score += 1.0
                    evidence.append(
                        f"Column '{col}': values {feat.get('min', 0):.1f}-{feat.get('max', 0):.1f}, "
                        f"consistent with vehicle speed in m/s (signal: value_range)"
                    )
                if "possible_acceleration" in hints:
                    micro_score += 1.0
                    evidence.append(
                        f"Column '{col}': values {feat.get('min', 0):.1f}-{feat.get('max', 0):.1f}, "
                        f"consistent with acceleration (signal: value_range)"
                    )
                if "timestamp" in hints:
                    micro_score += 0.5
                    evidence.append(
                        f"Column '{col}': detected as timestamp (signal: value_range)"
                    )
                if "possible_link_speed_kmh" in hints:
                    macro_score += 0.8
                    evidence.append(
                        f"Column '{col}': values {feat.get('min', 0):.1f}-{feat.get('max', 0):.1f}, "
                        f"consistent with link-level speed in km/h (signal: value_range)"
                    )
                if "possible_traffic_flow" in hints:
                    macro_score += 1.0
                    evidence.append(
                        f"Column '{col}': positive integers up to {feat.get('max', 0):.0f}, "
                        f"consistent with traffic flow (signal: value_range)"
                    )
                if "possible_link_length" in hints:
                    macro_score += 0.8
                    evidence.append(
                        f"Column '{col}': positive values up to {feat.get('max', 0):.1f}, "
                        f"consistent with road link length (signal: value_range)"
                    )
                if "possible_fraction" in hints or "possible_percentage" in hints:
                    macro_score += 0.5
                    evidence.append(
                        f"Column '{col}': values suggest proportion/percentage, "
                        f"consistent with fleet composition (signal: value_range)"
                    )
                if "all_negative_exclude_speed_flow" in hints:
                    evidence.append(
                        f"Column '{col}': all negative values, excluded from speed/flow mapping (signal: value_range)"
                    )

        std = get_standardizer()
        micro_mapping = std.map_columns(columns, "micro_emission")
        macro_mapping = std.map_columns(columns, "macro_emission")
        micro_required = std.get_required_columns("micro_emission")
        macro_required = std.get_required_columns("macro_emission")

        micro_has_required = self._has_required_columns(
            micro_mapping,
            micro_required,
            "micro_emission",
        )
        macro_has_required = self._has_required_columns(
            macro_mapping,
            macro_required,
            "macro_emission",
        )

        if micro_has_required:
            micro_score += 1.5
            evidence.append(
                f"All required micro fields present: {micro_required} (signal: completeness)"
            )
        if macro_has_required:
            macro_score += 1.5
            evidence.append(
                f"All required macro fields present: {macro_required} (signal: completeness)"
            )

        if micro_score > macro_score and micro_score > 0:
            task_type = "micro_emission"
            confidence = min(0.4 + micro_score * 0.10, 0.95)
        elif macro_score > micro_score and macro_score > 0:
            task_type = "macro_emission"
            confidence = min(0.4 + macro_score * 0.10, 0.95)
        elif micro_score == macro_score and micro_score > 0:
            task_type = "unknown"
            confidence = 0.3
            evidence.append("Micro and macro signals are tied; task type is ambiguous")
        else:
            task_type = "unknown"
            confidence = 0.2
            evidence.append("No clear task type indicators found")

        return {
            "task_type": task_type,
            "confidence": round(confidence, 3),
            "evidence": evidence,
        }

    def _format_summary(self, analysis: Dict) -> str:
        """Format analysis summary for LLM — purely descriptive, no judgment"""
        import json
        lines = [
            f"File: {analysis['filename']}",
            f"Rows: {analysis['row_count']}",
            f"Columns: {', '.join(analysis['columns'])}",
            f"Detected type: {analysis['task_type']} (confidence: {analysis['confidence']:.0%})"
        ]

        if analysis.get('sample_rows'):
            lines.append(f"Sample: {json.dumps(analysis['sample_rows'][:2], ensure_ascii=False)}")

        summary = "\n".join(lines)
        if analysis.get("evidence"):
            summary += "\n\nGrounding evidence:\n"
            for e in analysis["evidence"][:8]:
                summary += f"  - {e}\n"
        if analysis.get("data_quality_warnings"):
            summary += "\nData quality warnings:\n"
            for warning in analysis["data_quality_warnings"][:3]:
                summary += f"  - {warning.get('message')}\n"

        return summary

    async def _analyze_tabular_path(self, extracted_path: Path, display_name: str) -> Dict[str, Any]:
        if extracted_path.suffix.lower() == ".csv":
            df = pd.read_csv(extracted_path)
        else:
            df = pd.read_excel(extracted_path)

        if df.empty:
            raise ValueError(f"Dataset '{display_name}' is empty")

        df.columns = df.columns.str.strip()
        analysis = self._analyze_structure(df, display_name)
        analysis["source_path"] = str(extracted_path)
        return analysis

    async def _analyze_shapefile_path(self, shp_path: Path, display_name: str) -> Dict[str, Any]:
        if not GEOPANDAS_AVAILABLE:
            raise ValueError("geopandas is required to read Shapefile")

        gdf = gpd.read_file(shp_path)
        analysis = self._analyze_shapefile_structure(gdf, display_name)
        analysis["source_path"] = str(shp_path)
        return analysis

    async def _collect_zip_candidate_analyses(
        self,
        tmp_dir: str,
        file_list: List[str],
    ) -> List[Dict[str, Any]]:
        root = Path(tmp_dir)
        candidate_analyses: List[Dict[str, Any]] = []

        for relative_name in file_list:
            suffix = Path(relative_name).suffix.lower()
            if suffix not in {".csv", ".xlsx", ".xls", ".shp"}:
                continue

            extracted_path = root / Path(relative_name)
            if not extracted_path.exists():
                continue

            try:
                if suffix == ".shp":
                    analysis = await self._analyze_shapefile_path(extracted_path, relative_name)
                    analysis["format"] = "shapefile"
                else:
                    analysis = await self._analyze_tabular_path(extracted_path, relative_name)
                    analysis["format"] = suffix.lstrip(".")
                candidate_analyses.append(analysis)
            except Exception as exc:
                logger.warning("[FileAnalyzer] Skipping ZIP candidate %s: %s", relative_name, exc)

        return candidate_analyses

    async def _analyze_zip_file(self, zip_path: Path) -> ToolResult:
        """
        Analyze ZIP file contents

        Args:
            zip_path: Path to ZIP file

        Returns:
            ToolResult with ZIP file analysis
        """
        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()
                candidate_tables = [
                    item for item in file_list if Path(item).suffix.lower() in {".shp", ".csv", ".xlsx", ".xls"}
                ]
                if not candidate_tables:
                    return self._error(
                        f"ZIP file must contain either a .shp file (Shapefile) or .csv/.xlsx/.xls file. "
                        f"Found: {file_list}"
                    )

                with tempfile.TemporaryDirectory() as tmp_dir:
                    zip_ref.extractall(tmp_dir)
                    candidate_analyses = await self._collect_zip_candidate_analyses(tmp_dir, file_list)

                if not candidate_analyses:
                    return self._error("ZIP file contained candidate datasets, but none could be analyzed safely.")

                dataset_roles, dataset_role_summary, selected_primary = self._build_dataset_roles(
                    candidate_analyses,
                    file_list,
                )
                selected_primary = selected_primary or str(candidate_analyses[0].get("filename") or candidate_tables[0])

                primary_analysis = next(
                    (
                        dict(item)
                        for item in candidate_analyses
                        if str(item.get("filename") or "") == selected_primary
                    ),
                    dict(candidate_analyses[0]),
                )
                primary_format = str(primary_analysis.get("format") or "").lower()
                if primary_format == "shapefile":
                    primary_analysis["format"] = "zip_shapefile"
                elif len(candidate_analyses) > 1:
                    primary_analysis["format"] = "zip_multi_dataset"
                else:
                    primary_analysis["format"] = "zip_tabular"

                primary_analysis["zip_contents"] = file_list
                primary_analysis["candidate_tables"] = candidate_tables
                primary_analysis["selected_primary_table"] = selected_primary
                primary_analysis["dataset_roles"] = dataset_roles
                primary_analysis["dataset_role_summary"] = dataset_role_summary

                summary = self._format_summary(primary_analysis)
                return self._success(data=primary_analysis, summary=summary)

        except zipfile.BadZipFile:
            return self._error("Invalid ZIP file")
        except Exception as e:
            logger.exception("ZIP file analysis failed")
            return self._error(f"Failed to analyze ZIP file: {str(e)}")

    async def _analyze_shapefile_zip(self, zip_path: Path, zip_ref, shp_filename: str) -> ToolResult:
        """Analyze Shapefile inside ZIP"""
        if not GEOPANDAS_AVAILABLE:
            return self._error(
                "geopandas is required to read Shapefile. Please install it: pip install geopandas"
            )

        import tempfile
        import glob

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Extract ALL files from ZIP to preserve directory structure
            zip_ref.extractall(tmp_dir)

            # Recursively search for .shp files in the extracted directory
            shp_files_found = glob.glob(os.path.join(tmp_dir, '**', '*.shp'), recursive=True)

            if not shp_files_found:
                return self._error(
                    f"ZIP file contains no .shp files after extraction. Extracted to: {tmp_dir}"
                )

            # Use the first .shp file found
            shp_path = shp_files_found[0]
            logger.info(f"[FileAnalyzer] Found Shapefile: {shp_path}")

            gdf = gpd.read_file(shp_path)

            # Analyze structure
            analysis = self._analyze_shapefile_structure(gdf, zip_path.name)

            # Create summary
            summary = self._format_shapefile_summary(analysis)

            return self._success(
                data=analysis,
                summary=summary
            )

    def _analyze_shapefile_structure(self, gdf, filename: str) -> Dict[str, Any]:
        """Analyze GeoDataFrame structure"""
        spatial_metadata = self._extract_spatial_metadata(gdf)
        geom_types = spatial_metadata.get("geometry_types") or []
        bounds_info = None
        if spatial_metadata.get("bounds"):
            bounds_info = {
                "min_lon": spatial_metadata["bounds"]["min_x"],
                "min_lat": spatial_metadata["bounds"]["min_y"],
                "max_lon": spatial_metadata["bounds"]["max_x"],
                "max_lat": spatial_metadata["bounds"]["max_y"],
                "crs": spatial_metadata.get("crs"),
            }

        # Get columns (excluding geometry)
        columns = [col for col in gdf.columns if col != 'geometry']
        attr_df = gdf[columns].copy() if columns else pd.DataFrame()
        value_features = self._analyze_value_features(attr_df) if not attr_df.empty else {}
        task_identification = self._identify_task_type(columns, value_features)

        micro_mapping = self.standardizer.map_columns(columns, "micro_emission")
        macro_mapping = self.standardizer.map_columns(columns, "macro_emission")
        micro_required = self.standardizer.get_required_columns("micro_emission")
        macro_required = self.standardizer.get_required_columns("macro_emission")

        micro_has_required = self._has_required_columns(
            micro_mapping,
            micro_required,
            "micro_emission",
        )
        macro_has_required = self._has_required_columns(
            macro_mapping,
            macro_required,
            "macro_emission",
        )

        if task_identification["task_type"] == "unknown" and len(geom_types) > 0:
            task_identification["task_type"] = "macro_emission"
            task_identification["confidence"] = max(task_identification["confidence"], 0.55)
            task_identification["evidence"].append(
                f"Geometry types {list(geom_types)} suggest a geospatial link-level dataset (signal: geometry)."
            )

        sample_rows = attr_df.head(2).to_dict("records") if not attr_df.empty else []
        column_mapping = self._select_primary_mapping(
            task_identification["task_type"],
            micro_mapping,
            macro_mapping,
        )
        primary_mapping = micro_mapping if task_identification["task_type"] == "micro_emission" else macro_mapping
        missing_field_diagnostics = self._build_missing_field_diagnostics(
            task_identification["task_type"],
            columns,
            primary_mapping if task_identification["task_type"] in {"micro_emission", "macro_emission"} else {},
            value_features,
        )
        unresolved_columns = self._compute_unresolved_columns(
            columns,
            task_identification["task_type"],
            micro_mapping,
            macro_mapping,
        )
        data_quality_warnings = self._build_data_quality_warnings(
            attr_df,
            task_identification["task_type"],
            macro_mapping,
            value_features,
        )

        return {
            "filename": filename,
            "format": "shapefile",
            "row_count": len(gdf),
            "geometry_types": list(geom_types),
            "columns": columns,
            "bounds": bounds_info,
            "sample_rows": sample_rows,
            "task_type": task_identification["task_type"],
            "confidence": task_identification["confidence"],
            "micro_mapping": micro_mapping,
            "macro_mapping": macro_mapping,
            "column_mapping": column_mapping,
            "micro_has_required": micro_has_required,
            "macro_has_required": macro_has_required,
            "unresolved_columns": unresolved_columns,
            "analysis_strategy": "rule",
            "fallback_used": False,
            "selected_primary_table": filename,
            "dataset_roles": [
                {
                    "dataset_name": filename,
                    "role": "primary_analysis",
                    "format": "shapefile",
                    "task_type": task_identification["task_type"],
                    "confidence": task_identification["confidence"],
                    "selection_score": task_identification["confidence"],
                    "reason": "Single shapefile dataset; rule analyzer treated it as the primary geospatial analysis table.",
                    "selected": True,
                    "row_count": len(gdf),
                    "column_count": len(columns),
                }
            ],
            "dataset_role_summary": {
                "strategy": "rule",
                "ambiguous": False,
                "selected_primary_table": filename,
                "selection_score_gap": None,
                "role_fallback_eligible": False,
            },
            "missing_field_diagnostics": missing_field_diagnostics,
            "data_quality_warnings": data_quality_warnings,
            "spatial_metadata": spatial_metadata,
            "evidence": task_identification["evidence"],
            "value_features_summary": {
                col: feat.get("feature_hints", [])
                for col, feat in value_features.items()
                if feat.get("feature_hints")
            },
        }

    def _extract_geojson_spatial_metadata(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        features = payload.get("features", [])
        geometry_types: List[str] = []
        geometry_type_counts: Dict[str, int] = {}
        all_coords: List[List[float]] = []

        for feature in features:
            geometry = feature.get("geometry") or {}
            geom_type = str(geometry.get("type") or "").strip()
            if geom_type:
                geometry_type_counts[geom_type] = geometry_type_counts.get(geom_type, 0) + 1
                if geom_type not in geometry_types:
                    geometry_types.append(geom_type)
            self._extract_coords_recursive(geometry.get("coordinates"), all_coords)

        bounds_info = None
        if all_coords:
            xs = [coord[0] for coord in all_coords]
            ys = [coord[1] for coord in all_coords]
            bounds_info = {
                "min_x": float(min(xs)),
                "min_y": float(min(ys)),
                "max_x": float(max(xs)),
                "max_y": float(max(ys)),
            }

        crs_payload = payload.get("crs")
        crs_value = None
        if isinstance(crs_payload, dict):
            properties = crs_payload.get("properties") or {}
            crs_value = (
                properties.get("name")
                or crs_payload.get("name")
                or crs_payload.get("type")
            )

        return {
            "geometry_column": "geometry",
            "feature_count": len(features),
            "geometry_types": geometry_types,
            "geometry_type_counts": geometry_type_counts,
            "crs": crs_value,
            "epsg": None,
            "is_projected": None,
            "is_geographic": None,
            "has_z": None,
            "bounds": bounds_info,
        }

    def _extract_geojson_columns(self, features: List[Dict[str, Any]]) -> List[str]:
        columns: List[str] = []
        seen = set()
        for feature in features[:25]:
            properties = feature.get("properties") or {}
            if not isinstance(properties, dict):
                continue
            for key in properties.keys():
                text = str(key).strip()
                if text and text not in seen:
                    seen.add(text)
                    columns.append(text)
        return columns

    def _extract_geojson_sample_rows(self, features: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sample_rows: List[Dict[str, Any]] = []
        for feature in features[:2]:
            properties = feature.get("properties") or {}
            sample_rows.append(dict(properties) if isinstance(properties, dict) else {})
        return sample_rows

    def _extract_coords_recursive(self, coords: Any, result: List[List[float]]) -> None:
        if not coords:
            return
        if isinstance(coords, (list, tuple)) and coords and isinstance(coords[0], (int, float)):
            if len(coords) >= 2:
                result.append([float(coords[0]), float(coords[1])])
            return
        if isinstance(coords, (list, tuple)):
            for item in coords:
                self._extract_coords_recursive(item, result)

    async def _analyze_geojson_file(self, path: Path) -> ToolResult:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)

        if isinstance(payload, dict) and payload.get("type") == "Feature":
            payload = {"type": "FeatureCollection", "features": [payload]}

        if not isinstance(payload, dict) or payload.get("type") != "FeatureCollection":
            return self._error("GeoJSON analysis only supports FeatureCollection or Feature payloads.")

        analysis = self._analyze_geojson_structure(payload, path.name)
        summary = self._format_geojson_summary(analysis)
        return self._success(
            data=analysis,
            summary=summary
        )

    def _analyze_geojson_structure(self, payload: Dict[str, Any], filename: str) -> Dict[str, Any]:
        features = payload.get("features") or []
        if not isinstance(features, list) or not features:
            return {
                "filename": filename,
                "format": "geojson",
                "row_count": 0,
                "columns": [],
                "task_type": "unknown",
                "confidence": 0.0,
                "sample_rows": [],
                "micro_mapping": {},
                "macro_mapping": {},
                "column_mapping": {},
                "micro_has_required": False,
                "macro_has_required": False,
                "selected_primary_table": filename,
                "dataset_roles": [],
                "dataset_role_summary": {
                    "strategy": "rule",
                    "ambiguous": False,
                    "selected_primary_table": filename,
                    "selection_score_gap": None,
                    "role_fallback_eligible": False,
                },
                "missing_field_diagnostics": {
                    "task_type": "unknown",
                    "status": "unknown_task",
                    "required_fields": [],
                    "mapped_fields": [],
                    "required_field_statuses": [],
                    "missing_fields": [],
                    "derivable_opportunities": [],
                },
                "data_quality_warnings": [],
                "spatial_metadata": self._extract_geojson_spatial_metadata(payload),
                "analysis_strategy": "rule",
                "fallback_used": False,
                "evidence": ["GeoJSON payload contained no features."],
            }

        columns = self._extract_geojson_columns(features)
        sample_rows = self._extract_geojson_sample_rows(features)
        attr_df = pd.DataFrame(sample_rows)
        value_features = self._analyze_value_features(attr_df) if not attr_df.empty else {}
        task_identification = self._identify_task_type(columns, value_features)
        spatial_metadata = self._extract_geojson_spatial_metadata(payload)

        micro_mapping = self.standardizer.map_columns(columns, "micro_emission")
        macro_mapping = self.standardizer.map_columns(columns, "macro_emission")
        micro_required = self.standardizer.get_required_columns("micro_emission")
        macro_required = self.standardizer.get_required_columns("macro_emission")
        micro_has_required = self._has_required_columns(
            micro_mapping,
            micro_required,
            "micro_emission",
        )
        macro_has_required = self._has_required_columns(
            macro_mapping,
            macro_required,
            "macro_emission",
        )

        if task_identification["task_type"] == "unknown" and spatial_metadata.get("geometry_types"):
            task_identification["task_type"] = "macro_emission"
            task_identification["confidence"] = max(task_identification["confidence"], 0.55)
            task_identification["evidence"].append(
                "GeoJSON geometry types suggest a bounded geospatial link-level dataset."
            )

        column_mapping = self._select_primary_mapping(
            task_identification["task_type"],
            micro_mapping,
            macro_mapping,
        )
        primary_mapping = micro_mapping if task_identification["task_type"] == "micro_emission" else macro_mapping
        missing_field_diagnostics = self._build_missing_field_diagnostics(
            task_identification["task_type"],
            columns,
            primary_mapping if task_identification["task_type"] in {"micro_emission", "macro_emission"} else {},
            value_features,
        )
        unresolved_columns = self._compute_unresolved_columns(
            columns,
            task_identification["task_type"],
            micro_mapping,
            macro_mapping,
        )

        return {
            "filename": filename,
            "format": "geojson",
            "row_count": len(features),
            "columns": columns,
            "sample_rows": sample_rows,
            "task_type": task_identification["task_type"],
            "confidence": task_identification["confidence"],
            "micro_mapping": micro_mapping,
            "macro_mapping": macro_mapping,
            "column_mapping": column_mapping,
            "micro_has_required": micro_has_required,
            "macro_has_required": macro_has_required,
            "unresolved_columns": unresolved_columns,
            "analysis_strategy": "rule",
            "fallback_used": False,
            "selected_primary_table": filename,
            "dataset_roles": [
                {
                    "dataset_name": filename,
                    "role": "primary_analysis",
                    "format": "geojson",
                    "task_type": task_identification["task_type"],
                    "confidence": task_identification["confidence"],
                    "selection_score": task_identification["confidence"],
                    "reason": "Single GeoJSON dataset; rule analyzer treated it as the primary geospatial analysis table.",
                    "selected": True,
                    "row_count": len(features),
                    "column_count": len(columns),
                }
            ],
            "dataset_role_summary": {
                "strategy": "rule",
                "ambiguous": False,
                "selected_primary_table": filename,
                "selection_score_gap": None,
                "role_fallback_eligible": False,
            },
            "missing_field_diagnostics": missing_field_diagnostics,
            "data_quality_warnings": [],
            "spatial_metadata": spatial_metadata,
            "evidence": task_identification["evidence"],
            "value_features_summary": {
                col: feat.get("feature_hints", [])
                for col, feat in value_features.items()
                if feat.get("feature_hints")
            },
        }

    def _format_geojson_summary(self, analysis: Dict[str, Any]) -> str:
        lines = [
            f"File: {analysis['filename']}",
            f"Format: GeoJSON ({analysis['row_count']} features)",
        ]
        geometry_types = (analysis.get("spatial_metadata") or {}).get("geometry_types") or []
        if geometry_types:
            lines.append(f"Geometry types: {', '.join(geometry_types)}")
        bounds = (analysis.get("spatial_metadata") or {}).get("bounds") or {}
        if bounds:
            lines.append(
                "Bounds: "
                f"[{bounds['min_x']:.4f}, {bounds['min_y']:.4f}] -> "
                f"[{bounds['max_x']:.4f}, {bounds['max_y']:.4f}]"
            )
        columns = analysis.get("columns") or []
        if columns:
            lines.append(f"Columns: {', '.join(columns)}")
        for warning in analysis.get("data_quality_warnings", [])[:3]:
            lines.append(f"Data quality warning: {warning.get('message')}")
        return "\n".join(lines)

    def _format_shapefile_summary(self, analysis: Dict) -> str:
        """Format Shapefile analysis summary"""
        lines = [
            f"File: {analysis['filename']}",
            f"Format: Shapefile ({analysis['row_count']} features)",
            f"Geometry types: {', '.join(analysis['geometry_types'])}",
        ]

        if analysis.get('bounds'):
            b = analysis['bounds']
            lines.append(f"Bounds: Lon [{b['min_lon']:.4f}, {b['max_lon']:.4f}], Lat [{b['min_lat']:.4f}, {b['max_lat']:.4f}]")
            lines.append(f"Coordinate system: {b['crs']}")

        lines.append(f"Columns: {', '.join(analysis['columns'])}")
        for warning in analysis.get("data_quality_warnings", [])[:3]:
            lines.append(f"Data quality warning: {warning.get('message')}")

        return "\n".join(lines)

    async def _analyze_tabular_zip(self, zip_path: Path, zip_ref, filename: str) -> ToolResult:
        """Analyze tabular file (CSV/Excel) inside ZIP"""
        import tempfile
        import os

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Extract file
            extracted_path = os.path.join(tmp_dir, filename)
            with zip_ref.open(filename) as source:
                with open(extracted_path, 'wb') as target:
                    target.write(source.read())

            # Read as DataFrame
            if filename.endswith('.csv'):
                df = pd.read_csv(extracted_path)
            else:
                df = pd.read_excel(extracted_path)

            if df.empty:
                return self._error("Extracted file is empty")

            # Clean column names
            df.columns = df.columns.str.strip()

            # Analyze structure
            analysis = self._analyze_structure(df, filename)

            # Create summary
            summary = self._format_summary(analysis)

            return self._success(
                data=analysis,
                summary=summary
            )
