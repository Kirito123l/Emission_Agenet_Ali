"""CSV data-quality inspection tool."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

from core.data_quality import CleanDataFrameReport, ColumnInfo
from tools.base import BaseTool, ToolResult

logger = logging.getLogger(__name__)


CSV_ENCODINGS: Tuple[str, ...] = ("utf-8-sig", "utf-8", "gbk", "latin1")


class CleanDataFrameTool(BaseTool):
    """Inspect an uploaded CSV and return a structured data-quality report."""

    def __init__(self):
        super().__init__()
        self.name = "clean_dataframe"

    async def execute(self, file_path: str, **kwargs: Any) -> ToolResult:
        path = Path(str(file_path or "").strip())
        if path.suffix.lower() != ".csv":
            return self._typed_error(
                "unsupported_format",
                "clean_dataframe only supports CSV files.",
            )

        if not path.exists() or not path.is_file():
            return self._typed_error(
                "read_failed",
                f"CSV file not found or unreadable: {file_path}",
            )

        try:
            df, encoding = self._read_csv(path)
        except Exception as exc:
            logger.exception("clean_dataframe failed to read CSV: %s", path)
            return self._typed_error(
                "read_failed",
                f"Failed to read CSV file: {exc}",
            )

        report = self._build_report(path, df, encoding)
        missing_total = sum(report.missing_summary.values())
        summary = (
            "Data quality report generated: "
            f"{report.row_count} rows, {report.column_count} columns, "
            f"{missing_total} missing values"
        )
        return self._success(
            data={
                "report": report.to_dict(),
                "result_type": "data_quality_report",
            },
            summary=summary,
        )

    def _read_csv(self, path: Path) -> Tuple[pd.DataFrame, str]:
        last_error: Exception | None = None
        for encoding in CSV_ENCODINGS:
            try:
                return pd.read_csv(path, encoding=encoding), encoding
            except UnicodeDecodeError as exc:
                last_error = exc
                continue
            except pd.errors.EmptyDataError as exc:
                raise exc
            except Exception as exc:
                last_error = exc
                continue
        if last_error is not None:
            raise last_error
        raise ValueError("No CSV encoding candidates were available")

    def _build_report(
        self,
        path: Path,
        df: pd.DataFrame,
        encoding: str,
    ) -> CleanDataFrameReport:
        columns: List[ColumnInfo] = [
            self._build_column_info(str(column), df[column])
            for column in df.columns
        ]
        missing_summary = {
            str(column): int(df[column].isna().sum())
            for column in df.columns
        }
        return CleanDataFrameReport(
            file_path=str(path),
            row_count=int(len(df)),
            column_count=int(len(df.columns)),
            columns=columns,
            missing_summary=missing_summary,
            encoding_detected=encoding,
            generated_at=datetime.now().isoformat(),
            extra={},
        )

    def _build_column_info(self, name: str, series: pd.Series) -> ColumnInfo:
        non_null = series.dropna()
        sample_values = [self._sample_value(value) for value in non_null.head(3).tolist()]
        column_info = ColumnInfo(
            name=name,
            dtype=str(series.dtype),
            non_null_count=int(series.notna().sum()),
            unique_count=int(series.nunique(dropna=True)),
            sample_values=sample_values,
        )

        if pd.api.types.is_numeric_dtype(series):
            column_info.mean = self._safe_float(series.mean())
            column_info.std = self._safe_float(series.std())
            column_info.min = self._safe_float(series.min())
            column_info.max = self._safe_float(series.max())
        return column_info

    @staticmethod
    def _sample_value(value: Any) -> Any:
        if hasattr(value, "item"):
            try:
                value = value.item()
            except Exception:
                pass
        return value

    @staticmethod
    def _safe_float(value: Any) -> float | None:
        try:
            if pd.isna(value):
                return None
            return float(value)
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _typed_error(error_type: str, message: str) -> ToolResult:
        return ToolResult(
            success=False,
            data={
                "error_type": error_type,
                "message": message,
            },
            error=message,
            summary=message,
        )
