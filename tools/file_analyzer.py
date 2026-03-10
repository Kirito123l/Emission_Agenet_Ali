"""
File Analyzer Tool
Analyzes uploaded files to identify type and structure
"""
import pandas as pd
import logging
import os
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Any
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

            # Read file
            if path.suffix.lower() == '.csv':
                df = pd.read_csv(file_path)
            elif path.suffix.lower() in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path)
            else:
                return self._error(
                    f"Unsupported file format: {path.suffix}. Supported: .csv, .xlsx, .xls, .zip"
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

        # Try to identify task type
        task_type, confidence = self._identify_task_type(columns)

        # Map columns
        micro_mapping = self.standardizer.map_columns(columns, "micro_emission")
        macro_mapping = self.standardizer.map_columns(columns, "macro_emission")

        # Check required columns
        micro_required = self.standardizer.get_required_columns("micro_emission")
        macro_required = self.standardizer.get_required_columns("macro_emission")

        micro_has_required = all(
            any(col in micro_mapping.values() for col in [req])
            for req in micro_required
        )
        macro_has_required = all(
            any(col in macro_mapping.values() for col in [req])
            for req in macro_required
        )

        # Sample data
        sample_rows = df.head(2).to_dict('records')

        return {
            "filename": filename,
            "row_count": row_count,
            "columns": columns,
            "task_type": task_type,
            "confidence": confidence,
            "micro_mapping": micro_mapping,
            "macro_mapping": macro_mapping,
            "micro_has_required": micro_has_required,
            "macro_has_required": macro_has_required,
            "sample_rows": sample_rows
        }

    def _identify_task_type(self, columns: list) -> tuple:
        """
        Identify likely task type from columns

        Returns:
            (task_type, confidence)
        """
        columns_lower = [c.lower() for c in columns]

        # Micro emission indicators
        micro_indicators = ['speed', 'velocity', '速度', 'time', 'acceleration', '加速']
        micro_score = sum(1 for ind in micro_indicators if any(ind in col for col in columns_lower))

        # Macro emission indicators
        macro_indicators = ['length', 'flow', 'volume', 'traffic', '长度', '流量', 'link']
        macro_score = sum(1 for ind in macro_indicators if any(ind in col for col in columns_lower))

        if micro_score > macro_score:
            confidence = min(0.5 + micro_score * 0.15, 0.95)
            return "micro_emission", confidence
        elif macro_score > micro_score:
            confidence = min(0.5 + macro_score * 0.15, 0.95)
            return "macro_emission", confidence
        else:
            return "unknown", 0.3

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

        return "\n".join(lines)

    async def _analyze_zip_file(self, zip_path: Path) -> ToolResult:
        """
        Analyze ZIP file contents

        Args:
            zip_path: Path to ZIP file

        Returns:
            ToolResult with ZIP file analysis
        """
        import zipfile
        import tempfile
        import os

        try:
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                # List contents
                file_list = zip_ref.namelist()

                # Check for Shapefile
                shp_files = [f for f in file_list if f.endswith('.shp')]
                csv_files = [f for f in file_list if f.endswith(('.csv', '.xlsx', '.xls'))]

                if shp_files:
                    return await self._analyze_shapefile_zip(zip_path, zip_ref, shp_files[0])
                elif csv_files:
                    return await self._analyze_tabular_zip(zip_path, zip_ref, csv_files[0])
                else:
                    return self._error(
                        f"ZIP file must contain either a .shp file (Shapefile) or .csv/.xlsx/.xls file. "
                        f"Found: {file_list}"
                    )

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
        # Get geometry type
        geom_types = gdf.geometry.geom_type.unique() if len(gdf) > 0 else []

        # Get bounds
        if len(gdf) > 0 and gdf.crs:
            bounds = gdf.total_bounds
            bounds_info = {
                "min_lon": float(bounds[0]),
                "min_lat": float(bounds[1]),
                "max_lon": float(bounds[2]),
                "max_lat": float(bounds[3]),
                "crs": str(gdf.crs)
            }
        else:
            bounds_info = None

        # Get columns (excluding geometry)
        columns = [col for col in gdf.columns if col != 'geometry']

        # Sample data
        sample_data = None
        if len(gdf) > 0:
            # Convert first row to dict (without geometry)
            sample_row = gdf.iloc[0].to_dict()
            sample_data = {k: v for k, v in sample_row.items() if k != 'geometry'}

        return {
            "filename": filename,
            "format": "shapefile",
            "row_count": len(gdf),
            "geometry_types": list(geom_types),
            "columns": columns,
            "bounds": bounds_info,
            "sample_data": sample_data,
            "task_type": "macro_emission"  # Shapefiles are typically for macro emission
        }

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
