from __future__ import annotations

import pytest

from core.data_quality import CleanDataFrameReport, ColumnInfo
from tools.clean_dataframe import CleanDataFrameTool


def _report_payload(extra=None):
    report = CleanDataFrameReport(
        file_path="/tmp/sample.csv",
        row_count=2,
        column_count=2,
        columns=[
            ColumnInfo(
                name="flow",
                dtype="int64",
                non_null_count=2,
                unique_count=2,
                sample_values=[100, 200],
                mean=150.0,
                std=70.710678,
                min=100.0,
                max=200.0,
            ),
            ColumnInfo(
                name="road",
                dtype="object",
                non_null_count=2,
                unique_count=2,
                sample_values=["A", "B"],
            ),
        ],
        missing_summary={"flow": 0, "road": 0},
        encoding_detected="utf-8",
        generated_at="2026-04-24T00:00:00",
        extra=extra or {},
    )
    return report.to_dict()


def test_clean_dataframe_report_round_trip() -> None:
    payload = _report_payload(extra={"profile_version": 1})

    restored = CleanDataFrameReport.from_dict(payload)

    assert restored.to_dict() == payload


def test_clean_dataframe_report_rejects_unknown_fields() -> None:
    payload = _report_payload()
    payload["unexpected"] = True

    with pytest.raises(ValueError, match="unexpected"):
        CleanDataFrameReport.from_dict(payload)


def test_column_info_rejects_unknown_fields() -> None:
    payload = ColumnInfo(
        name="flow",
        dtype="int64",
        non_null_count=1,
        unique_count=1,
        sample_values=[100],
    ).to_dict()
    payload["typo_field"] = "bad"

    with pytest.raises(ValueError, match="typo_field"):
        ColumnInfo.from_dict(payload)


def test_extra_accepts_arbitrary_extension_data() -> None:
    payload = _report_payload(
        extra={
            "fill_suggestions": [{"column": "flow", "strategy": "median"}],
            "nested": {"future": True},
        }
    )

    restored = CleanDataFrameReport.from_dict(payload)

    assert restored.extra["fill_suggestions"][0]["strategy"] == "median"
    assert restored.extra["nested"]["future"] is True


@pytest.mark.anyio
async def test_clean_dataframe_reads_normal_csv_and_describes_columns(tmp_path) -> None:
    csv_path = tmp_path / "roads.csv"
    csv_path.write_text(
        "link_id,flow,road_name\n"
        "A,100,一环\n"
        "B,200,二环\n"
        "C,300,三环\n",
        encoding="utf-8",
    )
    tool = CleanDataFrameTool()

    result = await tool.execute(file_path=str(csv_path))

    assert result.success is True
    report = CleanDataFrameReport.from_dict(result.data["report"])
    assert report.row_count == 3
    assert report.column_count == 3
    assert report.encoding_detected in {"utf-8-sig", "utf-8"}
    columns = {column.name: column for column in report.columns}
    assert columns["flow"].dtype in {"int64", "int32"}
    assert columns["flow"].mean == pytest.approx(200.0)
    assert columns["flow"].std is not None
    assert columns["flow"].min == 100.0
    assert columns["flow"].max == 300.0
    assert columns["road_name"].mean is None
    assert columns["road_name"].sample_values == ["一环", "二环", "三环"]


@pytest.mark.anyio
async def test_clean_dataframe_missing_summary_is_exact(tmp_path) -> None:
    csv_path = tmp_path / "missing.csv"
    csv_path.write_text(
        "link_id,flow,road_name\n"
        "A,100,一环\n"
        "B,,二环\n"
        "C,300,\n",
        encoding="utf-8",
    )
    tool = CleanDataFrameTool()

    result = await tool.execute(file_path=str(csv_path))

    report = CleanDataFrameReport.from_dict(result.data["report"])
    assert report.missing_summary == {
        "link_id": 0,
        "flow": 1,
        "road_name": 1,
    }


@pytest.mark.anyio
async def test_clean_dataframe_sample_values_are_capped(tmp_path) -> None:
    csv_path = tmp_path / "many_rows.csv"
    rows = ["value"] + [str(index) for index in range(10)]
    csv_path.write_text("\n".join(rows), encoding="utf-8")
    tool = CleanDataFrameTool()

    result = await tool.execute(file_path=str(csv_path))

    report = CleanDataFrameReport.from_dict(result.data["report"])
    assert report.columns[0].sample_values == [0, 1, 2]


@pytest.mark.anyio
async def test_clean_dataframe_non_csv_returns_unsupported_format(tmp_path) -> None:
    txt_path = tmp_path / "notes.txt"
    txt_path.write_text("not,csv", encoding="utf-8")
    tool = CleanDataFrameTool()

    result = await tool.execute(file_path=str(txt_path))

    assert result.success is False
    assert result.data["error_type"] == "unsupported_format"


@pytest.mark.anyio
async def test_clean_dataframe_missing_file_returns_read_failed(tmp_path) -> None:
    tool = CleanDataFrameTool()

    result = await tool.execute(file_path=str(tmp_path / "missing.csv"))

    assert result.success is False
    assert result.data["error_type"] == "read_failed"


@pytest.mark.anyio
async def test_clean_dataframe_empty_csv_with_header_is_valid(tmp_path) -> None:
    csv_path = tmp_path / "headers_only.csv"
    csv_path.write_text("link_id,flow\n", encoding="utf-8")
    tool = CleanDataFrameTool()

    result = await tool.execute(file_path=str(csv_path))

    report = CleanDataFrameReport.from_dict(result.data["report"])
    assert report.row_count == 0
    assert report.column_count == 2
    assert report.missing_summary == {"link_id": 0, "flow": 0}
