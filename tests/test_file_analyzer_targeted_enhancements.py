import zipfile
from pathlib import Path

import pandas as pd
import pytest

from tools.file_analyzer import FileAnalyzerTool


class _FakeGeomType:
    def __init__(self, values):
        self._series = pd.Series(values)

    def unique(self):
        return self._series.unique()

    def value_counts(self):
        return self._series.value_counts()


class _FakeHasZ:
    def __init__(self, values):
        self._series = pd.Series(values)

    def any(self):
        return bool(self._series.any())


class _FakeGeometry:
    def __init__(self, geom_types, has_z=None):
        self.name = "geometry"
        self.geom_type = _FakeGeomType(geom_types)
        self.has_z = _FakeHasZ(has_z or [False] * len(geom_types))


class _FakeCRS:
    def __init__(self, value="EPSG:4326", epsg=4326, is_projected=False, is_geographic=True):
        self._value = value
        self._epsg = epsg
        self.is_projected = is_projected
        self.is_geographic = is_geographic

    def __str__(self):
        return self._value

    def to_epsg(self):
        return self._epsg


class _FakeGeoDataFrame:
    def __init__(self, data: pd.DataFrame, geom_types, bounds, crs=None):
        self._df = data
        self.geometry = _FakeGeometry(geom_types)
        self.total_bounds = bounds
        self.crs = crs or _FakeCRS()
        self.columns = list(data.columns) + ["geometry"]

    def __len__(self):
        return len(self._df)

    def __getitem__(self, key):
        return self._df.__getitem__(key)


def _make_analyzer():
    return FileAnalyzerTool()


def test_missing_field_diagnostics_include_derivable_opportunities():
    analyzer = _make_analyzer()
    df = pd.DataFrame(
        {
            "time_stamp": ["2025-01-01 00:00:00", "2025-01-01 00:00:01", "2025-01-01 00:00:02"],
            "spd_ms": [8.0, 10.0, 12.0],
            "acc": [0.5, -0.1, 0.2],
        }
    )

    analysis = analyzer._analyze_structure(df, "traj_nonstandard.csv")
    diagnostics = analysis["missing_field_diagnostics"]

    assert diagnostics["task_type"] == "micro_emission"
    assert diagnostics["status"] == "partial"
    statuses = {item["field"]: item["status"] for item in diagnostics["required_field_statuses"]}
    assert statuses["speed_kph"] == "derivable"
    assert "speed_kph" in diagnostics["required_fields"]
    assert diagnostics["derivable_opportunities"]


def test_shapefile_analysis_exposes_structured_spatial_metadata():
    analyzer = _make_analyzer()
    fake_gdf = _FakeGeoDataFrame(
        pd.DataFrame(
            {
                "link_id": ["L1", "L2"],
                "flow": [1200, 1500],
                "speed": [45, 52],
                "length": [1.2, 0.8],
            }
        ),
        geom_types=["LineString", "LineString"],
        bounds=[116.1, 39.8, 116.5, 40.1],
    )

    analysis = analyzer._analyze_shapefile_structure(fake_gdf, "roads.shp")

    assert analysis["spatial_metadata"]["geometry_column"] == "geometry"
    assert analysis["spatial_metadata"]["geometry_types"] == ["LineString"]
    assert analysis["spatial_metadata"]["geometry_type_counts"]["LineString"] == 2
    assert analysis["spatial_metadata"]["epsg"] == 4326
    assert analysis["spatial_metadata"]["bounds"]["min_x"] == pytest.approx(116.1)
    assert analysis["task_type"] == "macro_emission"


@pytest.mark.anyio
async def test_zip_multi_dataset_analysis_outputs_dataset_roles(tmp_path: Path):
    analyzer = _make_analyzer()
    zip_path = tmp_path / "bundle.zip"

    roads = pd.DataFrame(
        {
            "link_id": ["L1", "L2"],
            "flow": [1200, 900],
            "speed": [45, 50],
            "length": [1.2, 0.9],
        }
    )
    traj = pd.DataFrame(
        {
            "time": [1, 2, 3],
            "speed": [8, 9, 10],
            "acceleration": [0.1, -0.1, 0.2],
        }
    )
    roads_path = tmp_path / "roads.csv"
    traj_path = tmp_path / "trajectories.csv"
    readme_path = tmp_path / "README.txt"
    roads.to_csv(roads_path, index=False)
    traj.to_csv(traj_path, index=False)
    readme_path.write_text("bundle metadata", encoding="utf-8")

    with zipfile.ZipFile(zip_path, "w") as zip_ref:
        zip_ref.write(roads_path, arcname="roads.csv")
        zip_ref.write(traj_path, arcname="trajectories.csv")
        zip_ref.write(readme_path, arcname="README.txt")

    result = await analyzer.execute(str(zip_path))

    assert result.success is True
    data = result.data
    assert data["selected_primary_table"] == "roads.csv"
    role_map = {item["dataset_name"]: item["role"] for item in data["dataset_roles"]}
    assert role_map["roads.csv"] == "primary_analysis"
    assert role_map["trajectories.csv"] in {"secondary_analysis", "trajectory_candidate"}
    assert role_map["README.txt"] == "metadata"
    assert data["dataset_role_summary"]["strategy"] == "rule"
