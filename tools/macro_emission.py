"""
Macro Emission Calculation Tool

Simplified tool for calculating road link-level emissions using MOVES-Matrix method.
Standardization is handled by the executor layer.
"""
import os
import tempfile
import zipfile
from typing import Dict, Optional, List
from pathlib import Path
import logging
from .base import BaseTool, ToolResult
from .formatter import format_emission_multi_unit, calculate_stats, build_emission_table_summary
from calculators.macro_emission import MacroEmissionCalculator
from skills.macro_emission.excel_handler import ExcelHandler

logger = logging.getLogger(__name__)

# Try importing geopandas for Shapefile support
try:
    import geopandas as gpd
    GEOPANDAS_AVAILABLE = True
except ImportError:
    GEOPANDAS_AVAILABLE = False
    logger.warning("[MacroEmission] geopandas not available, Shapefile support disabled")


class MacroEmissionTool(BaseTool):
    """Calculate macro-scale emissions for road links"""

    def __init__(self):
        self._calculator = MacroEmissionCalculator()
        # Excel handler for file I/O
        try:
            from llm.client import get_llm
            llm_client = get_llm("agent")
            self._excel_handler = ExcelHandler(llm_client=llm_client)
            logger.info("[MacroEmission] Intelligent column mapping enabled")
        except Exception as e:
            logger.warning(f"[MacroEmission] Using hardcoded mapping: {e}")
            self._excel_handler = ExcelHandler(llm_client=None)

    @property
    def name(self) -> str:
        return "calculate_macro_emission"

    @property
    def description(self) -> str:
        return "Calculate road link-level emissions using MOVES-Matrix method"

    def _fix_common_errors(self, links_data: List[Dict]) -> List[Dict]:
        """Auto-fix common parameter errors"""
        fixed_links = []

        for idx, link in enumerate(links_data):
            fixed_link = {}

            # Field name mapping: correct_name -> possible_wrong_names
            field_mapping = {
                "link_length_km": ["length", "link_length", "length_km", "road_length"],
                "traffic_flow_vph": ["traffic_volume_veh_h", "traffic_flow", "flow", "volume", "traffic_volume"],
                "avg_speed_kph": ["avg_speed_kmh", "speed", "avg_speed", "average_speed"],
                "fleet_mix": ["vehicle_composition", "vehicle_mix", "composition", "fleet_composition"],
                "link_id": ["id", "road_id", "segment_id"]
            }

            for correct_name, possible_names in field_mapping.items():
                # Check correct name first
                if correct_name in link:
                    fixed_link[correct_name] = link[correct_name]
                else:
                    # Check possible wrong names
                    for wrong_name in possible_names:
                        if wrong_name in link:
                            fixed_link[correct_name] = link[wrong_name]
                            logger.info(f"Auto-fixed field name: {wrong_name} -> {correct_name}")
                            break

            # Fix fleet_mix format (convert array to object if needed)
            if "fleet_mix" in fixed_link:
                fleet_mix = fixed_link["fleet_mix"]
                if isinstance(fleet_mix, list):
                    # Convert array to object
                    fixed_fleet_mix = {}
                    for item in fleet_mix:
                        if isinstance(item, dict):
                            if "vehicle_type" in item and "percentage" in item:
                                fixed_fleet_mix[item["vehicle_type"]] = item["percentage"]
                            elif "type" in item and "percentage" in item:
                                fixed_fleet_mix[item["type"]] = item["percentage"]
                    if fixed_fleet_mix:
                        fixed_link["fleet_mix"] = fixed_fleet_mix
                        logger.info("Auto-fixed fleet_mix format: array -> object")

            # Generate link_id if missing or empty (FIX for "unknown" LINK_ID issue)
            if not fixed_link.get("link_id"):
                # Check if original link had any ID-like field
                original_id = (
                    link.get("id") or
                    link.get("road_id") or
                    link.get("segment_id") or
                    link.get("link_id") or
                    None
                )

                if original_id and str(original_id).strip():
                    # Use the original ID if it exists and is not empty
                    fixed_link["link_id"] = str(original_id).strip()
                    logger.info(f"Using existing ID from field: {fixed_link['link_id']}")
                else:
                    # Generate a meaningful ID: Link_1, Link_2, Link_3...
                    fixed_link["link_id"] = f"Link_{idx + 1}"
                    logger.info(f"Generated link_id: {fixed_link['link_id']} for link at index {idx}")
            else:
                # If link_id exists but is empty string, also generate a new one
                link_id = fixed_link.get("link_id", "")
                if isinstance(link_id, str) and not link_id.strip():
                    fixed_link["link_id"] = f"Link_{idx + 1}"
                    logger.info(f"Replaced empty link_id with: {fixed_link['link_id']}")
                elif link_id == "unknown":
                    fixed_link["link_id"] = f"Link_{idx + 1}"
                    logger.info(f"Replaced 'unknown' link_id with: {fixed_link['link_id']}")

            # Preserve geometry field for map visualization
            for key in link.keys():
                key_lower = key.lower()
                if key_lower in ["geometry", "geom", "wkt", "shape", "几何", "路段几何", "坐标"]:
                    fixed_link[key] = link[key]
                    break

            fixed_links.append(fixed_link)

        return fixed_links

    def _standardize_fleet_mix(self, fleet_mix: Optional[Dict]) -> Optional[Dict]:
        """Standardize fleet mix using centralized standardizer."""
        if not fleet_mix or not isinstance(fleet_mix, dict):
            return None

        from services.standardizer import get_standardizer
        standardizer = get_standardizer()
        supported = set(self._calculator.VEHICLE_TO_SOURCE_TYPE.keys())

        result = {}
        for raw_name, raw_pct in fleet_mix.items():
            try:
                pct = float(raw_pct)
            except Exception:
                continue
            if pct <= 0:
                continue
            std_name = standardizer.standardize_vehicle(str(raw_name))
            if std_name and std_name in supported:
                result[std_name] = result.get(std_name, 0) + pct
            else:
                logger.warning(f"Unsupported vehicle in fleet_mix: {raw_name}")

        return result if result else None

    def _apply_global_fleet_mix(self, links_data: List[Dict], global_fleet_mix: Optional[Dict]) -> List[Dict]:
        """
        Apply top-level fleet mix to each link when link-level fleet_mix is missing.
        This fixes cases where LLM passes `fleet_mix` at top-level instead of per-link.
        """
        standardized_global = self._standardize_fleet_mix(global_fleet_mix)

        updated_links = []
        applied_count = 0
        standardized_count = 0
        for link in links_data:
            new_link = dict(link)
            link_mix = self._standardize_fleet_mix(new_link.get("fleet_mix"))
            if link_mix:
                # Always normalize link-level fleet mix when present.
                new_link["fleet_mix"] = link_mix
                standardized_count += 1
            elif standardized_global:
                # Fallback to global fleet mix for links without valid link-level mix.
                new_link["fleet_mix"] = dict(standardized_global)
                applied_count += 1
            updated_links.append(new_link)

        if applied_count > 0:
            logger.info(f"[MacroEmission] Applied global fleet_mix to {applied_count} links")
        if standardized_count > 0:
            logger.info(f"[MacroEmission] Standardized link-level fleet_mix for {standardized_count} links")

        return updated_links

    def _fill_missing_link_fleet_mix(
        self,
        links_data: List[Dict],
        fallback_fleet_mix: Dict,
    ) -> Dict:
        """
        Fill links that still miss fleet_mix after all standardization.
        Returns updated links and fill metadata for transparency/output export.
        """
        if not fallback_fleet_mix:
            return {"links_data": links_data, "filled_count": 0, "filled_link_ids": [], "filled_row_indices": []}

        updated_links: List[Dict] = []
        filled_link_ids: List[str] = []
        filled_row_indices: List[int] = []

        for idx, link in enumerate(links_data):
            new_link = dict(link)
            link_mix = new_link.get("fleet_mix")
            has_valid_mix = False
            if isinstance(link_mix, dict):
                for raw_value in link_mix.values():
                    try:
                        if float(raw_value) > 0:
                            has_valid_mix = True
                            break
                    except Exception:
                        continue
            if not has_valid_mix:
                new_link["fleet_mix"] = dict(fallback_fleet_mix)
                filled_row_indices.append(idx)
                filled_link_ids.append(str(new_link.get("link_id", f"Link_{idx + 1}")))
            updated_links.append(new_link)

        return {
            "links_data": updated_links,
            "filled_count": len(filled_row_indices),
            "filled_link_ids": filled_link_ids,
            "filled_row_indices": filled_row_indices,
        }

    def _build_map_data(
        self,
        original_links: List[Dict],
        calculated_results: List[Dict],
        pollutants: List[str],
        summary: str
    ) -> Optional[Dict]:
        """
        Build map data for visualization if geometry is available

        Note: If geometry only contains 2 coordinate points, links will render as
        straight lines. This is a data limitation, not a bug. To show curved roads
        following actual paths, the input geometry must contain multiple intermediate
        coordinates (e.g., LINESTRING with more than 2 points).

        Args:
            original_links: Original input links (may contain geometry)
            calculated_results: Calculated emission results
            pollutants: List of pollutant names
            summary: Current summary text (will be modified for coord warning)

        Returns:
            Map data dict or None if no geometry found
        """
        import json
        try:
            from shapely.geometry import shape
            from shapely import wkt
            SHAPELY_AVAILABLE = True
        except ImportError:
            SHAPELY_AVAILABLE = False
            logger.warning("[MacroEmission] shapely not available, geometry parsing limited")

        # Check if any link has geometry
        has_geometry = False
        coord_warning = False

        # Prepare links with geometry
        map_links = []

        for orig_link, calc_result in zip(original_links, calculated_results):
            geom_raw = None

            # Check for geometry field with various aliases
            for key in orig_link.keys():
                key_lower = key.lower()
                if key_lower in ["geometry", "geom", "wkt", "shape", "几何", "路段几何", "坐标"]:
                    geom_raw = orig_link.get(key)
                    break

            if not geom_raw:
                continue

            # Parse geometry based on format
            coordinates = None
            try:
                geom_str = str(geom_raw).strip()

                # Case 1: WKT format (LINESTRING(...))
                if geom_str.upper().startswith("LINESTRING"):
                    if SHAPELY_AVAILABLE:
                        geom = wkt.loads(geom_str)
                        coordinates = list(geom.coords)
                    else:
                        # Simple WKT parser for LINESTRING
                        import re
                        match = re.search(r"LINESTRING\s*\(([^)]+)\)", geom_str, re.IGNORECASE)
                        if match:
                            coords_str = match.group(1)
                            points = [p.strip().split() for p in coords_str.split(",")]
                            coordinates = [[float(p[0]), float(p[1])] for p in points]

                # Case 2: GeoJSON string
                elif geom_str.startswith("{"):
                    geojson = json.loads(geom_str)
                    if geojson.get("type") == "LineString":
                        coordinates = geojson.get("coordinates", [])
                    elif SHAPELY_AVAILABLE:
                        geom = shape(geojson)
                        if hasattr(geom, "coords"):
                            coordinates = list(geom.coords)

                # Case 3: List of coordinates (already a list or list-like string)
                elif "[" in geom_str:
                    # First check if geom_raw is already a list (from Shapefile processing)
                    if isinstance(geom_raw, list):
                        # Validate list format
                        if all(isinstance(c, (list, tuple)) and len(c) >= 2 for c in geom_raw):
                            # Convert any tuples to lists and ensure float values
                            coordinates = [[float(c[0]), float(c[1])] for c in geom_raw]
                    else:
                        # Try to parse as JSON string
                        try:
                            coordinates = json.loads(geom_str)
                        except:
                            pass

                # Case 4: Comma-separated pairs "121.4,31.2;121.5,31.3"
                elif ";" in geom_str or "," in geom_str:
                    parts = geom_str.replace(";", ",").split(",")
                    if len(parts) >= 4 and len(parts) % 2 == 0:
                        coords = []
                        for i in range(0, len(parts), 2):
                            try:
                                lon = float(parts[i].strip())
                                lat = float(parts[i + 1].strip())
                                coords.append([lon, lat])
                            except:
                                break
                        if len(coords) >= 2:
                            coordinates = coords

                if coordinates and len(coordinates) >= 2:
                    # Validate coordinate range (WGS84: lon -180~180, lat -90~90)
                    first_coord = coordinates[0]
                    if abs(first_coord[0]) > 180 or abs(first_coord[1]) > 90:
                        coord_warning = True
                        # Still try to use the coordinates, might be projected coords
                        logger.warning(f"[MacroEmission] Link {calc_result.get('link_id')} has coordinates outside WGS84 range")

                    # Calculate emission intensity (kg/(h·km)) by dividing total emission by link length
                    link_length_km = calc_result.get("link_length_km", 0)
                    if link_length_km <= 0:
                        link_length_km = 0.1  # Prevent division by zero

                    total_emissions = calc_result.get("total_emissions_kg_per_hr", {})
                    emission_intensity = {
                        pollutant: round(emission_kg_h / link_length_km, 4)
                        for pollutant, emission_kg_h in total_emissions.items()
                    }

                    map_links.append({
                        "link_id": calc_result.get("link_id"),
                        "geometry": coordinates,
                        "emissions": emission_intensity,  # Changed to emission intensity
                        "emission_rate": calc_result.get("emission_rates_g_per_veh_km", {}),
                        "link_length_km": link_length_km,
                        "avg_speed_kph": calc_result.get("avg_speed_kph", 0),
                        "traffic_flow_vph": calc_result.get("traffic_flow_vph", 0)
                    })
                    has_geometry = True

            except Exception as e:
                logger.warning(f"[MacroEmission] Failed to parse geometry for link {orig_link.get('link_id')}: {e}")
                continue

        if not has_geometry or not map_links:
            return None

        # Build map data structure
        main_pollutant = pollutants[0] if pollutants else "CO2"

        # Calculate emission range for color scaling
        emissions = [
            link["emissions"].get(main_pollutant, 0)
            for link in map_links
        ]
        min_emission = min(emissions) if emissions else 0
        max_emission = max(emissions) if emissions else 100

        # Calculate map center from all coordinates
        all_coords = []
        for link in map_links:
            all_coords.extend(link["geometry"])

        if all_coords:
            center = [
                sum(c[0] for c in all_coords) / len(all_coords),
                sum(c[1] for c in all_coords) / len(all_coords)
            ]
        else:
            center = [116.4074, 39.9042]  # Default to Beijing

        map_data = {
            "type": "macro_emission_map",
            "center": center,
            "zoom": 12,
            "pollutant": main_pollutant,
            "unit": "kg/(h·km)",  # Changed from "kg/h" to emission intensity unit
            "color_scale": {
                "min": float(min_emission),
                "max": float(max_emission),
                "colors": ["#fee5d9", "#fcae91", "#fb6a4a", "#de2d26", "#a50f15"]
            },
            "links": map_links,
            "summary": {
                "total_links": len(map_links),
                "total_emissions_kg_per_hr": {
                    p: sum(link["emissions"].get(p, 0) for link in map_links)
                    for p in pollutants
                }
            }
        }

        return map_data

    def _read_from_zip(self, zip_path: str) -> tuple:
        """
        Read links data from ZIP file (Shapefile or Excel)

        Args:
            zip_path: Path to ZIP file

        Returns:
            (success, links_data, error_message)
        """
        import zipfile
        import tempfile
        import os

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                file_list = zip_ref.namelist()

                # Check for Shapefile first
                shp_files = [f for f in file_list if f.endswith('.shp')]
                if shp_files and GEOPANDAS_AVAILABLE:
                    return self._read_shapefile_from_zip(zip_ref, shp_files[0])

                # Check for Excel/CSV files
                excel_files = [f for f in file_list if f.endswith(('.xlsx', '.xls', '.csv'))]
                if excel_files:
                    return self._read_excel_from_zip(zip_ref, excel_files[0])

                return False, None, "ZIP must contain .shp or .xlsx/.xls/.csv file"

        except Exception as e:
            logger.exception(f"[MacroEmission] Failed to read ZIP file: {zip_path}")
            return False, None, f"Failed to read ZIP file: {str(e)}"

    def _read_shapefile_from_zip(self, zip_ref, shp_filename: str) -> tuple:
        """Read Shapefile from ZIP and convert to links_data format"""
        import tempfile
        import glob

        with tempfile.TemporaryDirectory() as tmp_dir:
            # Extract ALL files from ZIP to preserve directory structure
            # This handles cases where .shp file is in a subdirectory
            zip_ref.extractall(tmp_dir)

            # Recursively search for .shp files in the extracted directory
            shp_files_found = glob.glob(os.path.join(tmp_dir, '**', '*.shp'), recursive=True)

            if not shp_files_found:
                return False, None, "ZIP file contains no .shp files after extraction"

            # Use the first .shp file found
            shp_path = shp_files_found[0]
            logger.info(f"[MacroEmission] Found Shapefile: {shp_path}")

            gdf = gpd.read_file(shp_path)

            # Convert GeoDataFrame to links_data format
            links_data = []

            for idx, row in gdf.iterrows():
                link_data = {}

                # Convert all columns to dict (except geometry)
                for col in gdf.columns:
                    if col != 'geometry':
                        link_data[col] = row[col]

                # Convert geometry to coordinate list (list of lists, not list of tuples)
                # This format is compatible with _build_map_data's JSON parsing
                if hasattr(row['geometry'], 'coords'):
                    # LineString: list of coordinates
                    # Convert list of tuples to list of lists for JSON compatibility
                    coords_tuples = list(row['geometry'].coords)
                    link_data['geometry'] = [[float(x), float(y)] for x, y in coords_tuples]
                elif hasattr(row['geometry'], 'geoms'):
                    # MultiLineString: concatenate all line segments
                    coords = []
                    for geom in row['geometry'].geoms:
                        if hasattr(geom, 'coords'):
                            coords_tuples = list(geom.coords)
                            coords.extend([[float(x), float(y)] for x, y in coords_tuples])
                    link_data['geometry'] = coords
                elif hasattr(row['geometry'], 'exterior'):
                    # Polygon: use exterior ring
                    coords_tuples = list(row['geometry'].exterior.coords)
                    link_data['geometry'] = [[float(x), float(y)] for x, y in coords_tuples]
                else:
                    # Other geometry types, try to get coords
                    try:
                        coords_tuples = list(row['geometry'].coords)
                        link_data['geometry'] = [[float(x), float(y)] for x, y in coords_tuples]
                    except:
                        pass  # No usable geometry

                # Generate link_id if missing
                if 'link_id' not in link_data or not link_data['link_id']:
                    link_data['link_id'] = f"Link_{idx + 1}"

                links_data.append(link_data)

            logger.info(f"[MacroEmission] Read {len(links_data)} links from Shapefile")
            return True, links_data, None

    def _read_excel_from_zip(self, zip_ref, filename: str) -> tuple:
        """Read Excel/CSV file from ZIP"""
        import tempfile
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmp_dir:
            extracted_path = os.path.join(tmp_dir, filename)

            with zip_ref.open(filename) as source:
                with open(extracted_path, 'wb') as target:
                    target.write(source.read())

            # Use ExcelHandler to read
            return self._excel_handler.read_links_from_excel(extracted_path)

    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute macro emission calculation

        Parameters (already standardized by executor):
            links_data: List[Dict] - Road link data
            pollutants: List[str] - List of pollutants (default: ["CO2", "NOx"])
            model_year: int - Vehicle model year (default: 2020)
            season: str - Season (default: "夏季")
            default_fleet_mix: Dict (optional) - Default fleet composition
            input_file: str (optional) - Path to Excel input file
            output_file: str (optional) - Path to Excel output file
        """
        try:
            # 参数名兼容：file_path → input_file
            if "file_path" in kwargs and "input_file" not in kwargs:
                kwargs["input_file"] = kwargs["file_path"]
                logger.info(f"[MacroEmission] Mapped file_path to input_file: {kwargs['file_path']}")

            # 1. Extract parameters
            links_data = kwargs.get("links_data")
            pollutants = kwargs.get("pollutants", ["CO2", "NOx"])
            model_year = kwargs.get("model_year", 2020)
            season = kwargs.get("season", "夏季")
            default_fleet_mix = kwargs.get("default_fleet_mix")
            global_fleet_mix = kwargs.get("fleet_mix")
            input_file = kwargs.get("input_file")
            output_file = kwargs.get("output_file")

            # 2. Get links data (from parameter or file)
            if input_file:
                # Check if it's a ZIP file
                input_path = Path(input_file)
                if input_path.suffix.lower() == '.zip':
                    # Handle ZIP file (may contain Shapefile or Excel)
                    success, links_data, read_error = self._read_from_zip(input_file)
                else:
                    # Read from Excel file
                    success, links_data, read_error = self._excel_handler.read_links_from_excel(input_file)

                if not success:
                    return ToolResult(
                        success=False,
                        error=f"Failed to read input file: {read_error}",
                        data={"input_file": input_file}
                    )
            elif not links_data:
                return ToolResult(
                    success=False,
                    error="Missing required parameter: links_data or input_file",
                    data=None
                )

            # 3. Validate links data
            if not isinstance(links_data, list) or len(links_data) == 0:
                return ToolResult(
                    success=False,
                    error="links_data must be a non-empty list",
                    data=None
                )

            # 4. Auto-fix common errors
            links_data = self._fix_common_errors(links_data)

            # 4.1 Apply top-level fleet_mix and standardize fleet names
            links_data = self._apply_global_fleet_mix(links_data, global_fleet_mix)

            # 4.2 Standardize default_fleet_mix names if provided
            if default_fleet_mix:
                default_fleet_mix = self._standardize_fleet_mix(default_fleet_mix) or default_fleet_mix

            # 4.3 Fill per-link missing fleet_mix explicitly for deterministic behavior
            effective_default_fleet_mix = default_fleet_mix or dict(self._calculator.DEFAULT_FLEET_MIX)
            fill_info = self._fill_missing_link_fleet_mix(links_data, effective_default_fleet_mix)
            links_data = fill_info["links_data"]

            # 5. Execute calculation
            result = self._calculator.calculate(
                links_data=links_data,
                pollutants=pollutants,
                model_year=model_year,
                season=season,
                default_fleet_mix=effective_default_fleet_mix
            )

            # 6. Handle calculation errors
            if result.get("status") == "error":
                return ToolResult(
                    success=False,
                    error=result.get("message", result.get("error")),
                    data={
                        "error_code": result.get("error_code"),
                        "query_params": {
                            "pollutants": pollutants,
                            "model_year": model_year,
                            "season": season,
                            "links_count": len(links_data),
                            "filled_fleet_mix_links": fill_info["filled_count"],
                        }
                    }
                )

            # Add fill metadata for frontend and synthesis transparency
            result["data"]["fleet_mix_fill"] = {
                "strategy": "default_fleet_mix",
                "filled_count": fill_info["filled_count"],
                "filled_link_ids": fill_info["filled_link_ids"],
                "filled_row_indices": fill_info["filled_row_indices"],
                "default_fleet_mix_used": effective_default_fleet_mix,
            }

            # 7. Write output file (if specified)
            if output_file:
                results_data = result["data"].get("links", [])

                write_success, write_error = self._excel_handler.write_results_to_excel(
                    output_file,
                    results_data,
                    pollutants
                )

                if not write_success:
                    result["data"]["output_file_warning"] = f"Failed to write output file: {write_error}"
                else:
                    result["data"]["output_file"] = output_file

            # 8. Generate download file (if input_file provided)
            if input_file:
                try:
                    from config import get_config
                    config = get_config()
                    outputs_dir = str(config.outputs_dir)

                    results_data = result["data"].get("results", [])  # 修复：使用 "results" 而不是 "links"

                    success, output_path, filename, error = self._excel_handler.generate_result_excel(
                        input_file,  # 添加原始文件路径作为第一个参数
                        results_data,
                        pollutants,
                        outputs_dir,
                        fleet_fill_info=result["data"].get("fleet_mix_fill"),
                    )

                    if success:
                        result["data"]["download_file"] = {
                            "path": output_path,
                            "filename": filename
                        }
                except Exception as e:
                    logger.warning(f"Failed to generate download file: {e}")

            # 9. Return success result
            # Create enhanced summary with multi-unit formatting
            links_results = result["data"].get("results", [])
            summary_data = result["data"].get("summary", {})

            num_links = len(links_results)
            pollutant_names = ", ".join(pollutants)
            total_emissions = summary_data.get("total_emissions_kg_per_hr", {})

            # Build enhanced summary with multi-unit display
            summary_parts = [
                f"已完成宏观排放计算，共 {num_links} 个路段",
                f"车型年份: {model_year}，季节: {season}，污染物: {pollutant_names}"
            ]

            # Total emissions with multi-unit display
            if total_emissions:
                summary_parts.append("**总排放量:**")
                for pollutant, value_kg in total_emissions.items():
                    # Convert kg to g for formatter
                    value_g = value_kg * 1000
                    formatted = format_emission_multi_unit(value_g, "hour")
                    summary_parts.append(f"  - {pollutant}: {formatted}")
                if all(float(v) == 0.0 for v in total_emissions.values()):
                    summary_parts.append("⚠️ 所有污染物结果为 0。请检查车型映射、污染物选择或输入参数是否有效。")

            fill_count = result["data"].get("fleet_mix_fill", {}).get("filled_count", 0)
            if fill_count > 0:
                summary_parts.append(f"**缺失车型分布处理:** 已对 {fill_count} 个路段使用默认车队组成填补空白行")

            # Unit emission rates (average across all links)
            emission_rates = {}
            for link in links_results:
                for pol, rate in link.get("emission_rates_g_per_veh_km", {}).items():
                    if pol not in emission_rates:
                        emission_rates[pol] = []
                    emission_rates[pol].append(rate)

            if emission_rates:
                summary_parts.append("**单位排放率 (平均):**")
                for pollutant, rates in emission_rates.items():
                    avg_rate = sum(rates) / len(rates)
                    summary_parts.append(f"  - {pollutant}: {avg_rate:.2f} g/(veh·km)")

            # Link statistics
            main_pollutant = pollutants[0] if pollutants else "CO2"
            link_emissions = [
                link.get("total_emissions_kg_per_hr", {}).get(main_pollutant, 0)
                for link in links_results
            ]
            stats = calculate_stats(link_emissions)
            if stats and stats.get("count", 0) > 0:
                summary_parts.append(f"**路段统计 ({main_pollutant}):**")
                summary_parts.append(f"  - 单路段平均: {stats['avg']:.2f} kg/h")
                summary_parts.append(f"  - 单路段最高: {stats['max']:.2f} kg/h")
                summary_parts.append(f"  - 单路段最低: {stats['min']:.2f} kg/h")

            summary = "\n".join(summary_parts)

            # Build map_data if geometry is available
            map_data = None
            try:
                map_data = self._build_map_data(
                    links_data, links_results, pollutants, summary
                )
                if map_data:
                    logger.info(f"[MacroEmission] Built map_data with {len(map_data.get('links', []))} links")
            except Exception as e:
                logger.warning(f"[MacroEmission] Failed to build map_data: {e}")
                # Don't fail the whole calculation if map building fails
                map_data = None

            return ToolResult(
                success=True,
                error=None,
                data=result["data"],
                summary=summary,
                map_data=map_data
            )

        except Exception as e:
            return ToolResult(
                success=False,
                error=f"Macro emission calculation failed: {str(e)}",
                data=None
            )

