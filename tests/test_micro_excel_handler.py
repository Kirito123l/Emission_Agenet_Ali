"""Regression coverage for the micro-emission Excel reader."""
from skills.micro_emission.excel_handler import ExcelHandler


def test_read_trajectory_from_excel_strips_columns_without_stdout_noise(tmp_path, capsys):
    csv_path = tmp_path / "trajectory.csv"
    csv_path.write_text(" speed_kph , time_sec \n10,0\n20,1\n", encoding="utf-8")

    handler = ExcelHandler()

    success, trajectory, error = handler.read_trajectory_from_excel(str(csv_path))
    captured = capsys.readouterr()

    assert success is True
    assert error is None
    assert captured.out == ""
    assert trajectory == [
        {
            "t": 0.0,
            "speed_kph": 10.0,
            "acceleration_mps2": 2.7777777777777777,
            "grade_pct": 0.0,
        },
        {
            "t": 1.0,
            "speed_kph": 20.0,
            "acceleration_mps2": 2.7777777777777777,
            "grade_pct": 0.0,
        },
    ]
