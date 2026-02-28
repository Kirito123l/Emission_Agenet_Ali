"""
File Analyzer Tool
Analyzes uploaded files to identify type and structure
"""
import pandas as pd
import logging
from pathlib import Path
from typing import Dict, Any
from tools.base import BaseTool, ToolResult
from services.standardizer import get_standardizer

logger = logging.getLogger(__name__)


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

            # Read file
            if path.suffix.lower() == '.csv':
                df = pd.read_csv(file_path)
            elif path.suffix.lower() in ['.xlsx', '.xls']:
                df = pd.read_excel(file_path)
            else:
                return self._error(
                    f"Unsupported file format: {path.suffix}. Supported: .csv, .xlsx, .xls"
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
