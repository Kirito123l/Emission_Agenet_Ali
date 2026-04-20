from services.artifact_summary import format_artifact_summaries, summarize_frontend_artifacts


def test_artifact_summarizer_handles_map_table_chart_payloads():
    summaries = summarize_frontend_artifacts(
        map_data={
            "type": "contour",
            "title": "NOx Concentration Field",
            "pollutant": "NOx",
            "summary": {
                "mean_concentration": 2.06,
                "max_concentration": 6.73,
                "receptor_count": 1585,
                "unit": "ug/m3",
            },
            "layers": [{"data": {"features": [{"id": 1}, {"id": 2}]}}],
        },
        table_data={
            "type": "topk_summary_table",
            "columns": ["road_id", "NOx"],
            "preview_rows": [{"road_id": "A", "NOx": 1.2}, {"road_id": "B", "NOx": 0.8}],
            "total_rows": 10,
        },
        chart_data={
            "type": "emission_factors",
            "title": "Emission Factors",
            "pollutants": {"NOx": {"curve": [{"speed_kph": 10}, {"speed_kph": 20}]}},
        },
        download_file={"filename": "result.xlsx", "path": "/tmp/result.xlsx"},
    )

    assert [item.kind for item in summaries] == ["map", "table", "chart", "download"]
    assert summaries[0].artifact_type == "contour"
    assert summaries[0].key_stats["pollutant"] == "NOx"
    assert summaries[0].key_stats["avg"] == 2.06
    assert summaries[0].key_stats["max"] == 6.73
    assert summaries[0].key_stats["receptors"] == 1585
    assert summaries[1].key_stats["rows"] == 10
    assert summaries[1].preview[0]["road_id"] == "A"
    assert summaries[2].key_stats["series"] == ["NOx"]

    rendered = format_artifact_summaries(summaries)
    assert "[Artifacts]" in rendered
    assert "NOx Concentration Field" in rendered
    assert "frontend: map + legend + download button" in rendered

