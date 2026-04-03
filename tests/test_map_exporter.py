"""Tests for server-side static map export."""

from __future__ import annotations

import asyncio
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace

from PIL import Image
import pytest
import matplotlib.pyplot as plt
from starlette.requests import Request

import api.map_export as map_export_module
from api.models import ExportMapRequest
from config import reset_config
from services.map_exporter import MapExporter


def _make_roads_geojson() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[121.401, 31.201], [121.406, 31.201]],
                },
                "properties": {"road_id": "R1"},
            },
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[121.402, 31.203], [121.407, 31.204]],
                },
                "properties": {"road_id": "R2"},
            },
        ],
    }


def _make_contour_bands() -> dict:
    return {
        "type": "contour_bands",
        "interp_resolution_m": 10.0,
        "n_levels": 3,
        "levels": [0.05, 0.2, 0.8],
        "bbox_wgs84": [121.4, 31.2, 121.408, 31.206],
        "n_receptors_used": 24,
        "geojson": {
            "type": "FeatureCollection",
            "features": [
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [
                            [[
                                [121.401, 31.201],
                                [121.406, 31.201],
                                [121.406, 31.205],
                                [121.401, 31.205],
                                [121.401, 31.201],
                            ]]
                        ],
                    },
                    "properties": {
                        "level_min": 0.01,
                        "level_max": 0.05,
                        "level_index": 0,
                        "label": "0.01 - 0.05 μg/m³",
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [
                            [[
                                [121.402, 31.202],
                                [121.4065, 31.202],
                                [121.4065, 31.2048],
                                [121.402, 31.2048],
                                [121.402, 31.202],
                            ]]
                        ],
                    },
                    "properties": {
                        "level_min": 0.05,
                        "level_max": 0.2,
                        "level_index": 1,
                        "label": "0.05 - 0.20 μg/m³",
                    },
                },
                {
                    "type": "Feature",
                    "geometry": {
                        "type": "MultiPolygon",
                        "coordinates": [
                            [[
                                [121.403, 31.2025],
                                [121.4058, 31.2025],
                                [121.4058, 31.2042],
                                [121.403, 31.2042],
                                [121.403, 31.2025],
                            ]]
                        ],
                    },
                    "properties": {
                        "level_min": 0.2,
                        "level_max": 0.8,
                        "level_index": 2,
                        "label": "0.20 - 0.80 μg/m³",
                    },
                },
            ],
        },
        "stats": {
            "min_concentration": 0.01,
            "max_concentration": 0.8,
            "mean_concentration": 0.23,
            "total_area_m2": 125000.0,
        },
    }


def _make_raster_grid() -> dict:
    return {
        "matrix_mean": [[0.1, 0.2], [0.5, 0.8]],
        "matrix_max": [[0.2, 0.3], [0.7, 1.0]],
        "bbox_local": [0.0, 0.0, 100.0, 100.0],
        "bbox_wgs84": [121.4, 31.2, 121.406, 31.204],
        "resolution_m": 50.0,
        "rows": 2,
        "cols": 2,
        "nodata": 0.0,
        "cell_receptor_map": {"0_0": [0], "0_1": [1], "1_0": [2], "1_1": [3]},
        "cell_centers_wgs84": [
            {"row": 0, "col": 0, "lon": 121.401, "lat": 31.201, "mean_conc": 0.1, "max_conc": 0.2},
            {"row": 0, "col": 1, "lon": 121.404, "lat": 31.201, "mean_conc": 0.2, "max_conc": 0.3},
            {"row": 1, "col": 0, "lon": 121.401, "lat": 31.203, "mean_conc": 0.5, "max_conc": 0.7},
            {"row": 1, "col": 1, "lon": 121.404, "lat": 31.203, "mean_conc": 0.8, "max_conc": 1.0},
        ],
        "stats": {"total_cells": 4, "nonzero_cells": 4, "coverage_pct": 100.0},
    }


def _make_dispersion_payload(*, with_contour: bool = True) -> dict:
    payload = {
        "query_info": {"pollutant": "NOx"},
        "summary": {"mean_concentration": 0.23, "max_concentration": 0.8, "unit": "μg/m³"},
        "roads_wgs84": _make_roads_geojson(),
        "raster_grid": _make_raster_grid(),
        "scenario_label": "baseline",
    }
    if with_contour:
        payload["contour_bands"] = _make_contour_bands()
    return payload


def _make_hotspot_payload() -> dict:
    payload = _make_dispersion_payload(with_contour=True)
    payload.update(
        {
            "hotspots": [
                {
                    "hotspot_id": 1,
                    "rank": 1,
                    "center": {"lon": 121.404, "lat": 31.2035},
                    "bbox": [121.4032, 31.2028, 121.4052, 31.2040],
                    "area_m2": 2400.0,
                    "max_conc": 0.8,
                    "mean_conc": 0.55,
                }
            ],
            "summary": {
                "hotspot_count": 1,
                "total_hotspot_area_m2": 2400.0,
                "area_fraction_pct": 12.5,
                "max_concentration": 0.8,
            },
        }
    )
    return payload


def _assert_valid_png(path: Path) -> None:
    assert path.exists()
    assert path.stat().st_size > 0
    image = Image.open(path)
    image.verify()


class TestMapExporter:
    def test_resolve_language_falls_back_to_english_without_cjk_font(self, monkeypatch):
        exporter = MapExporter()
        monkeypatch.setattr("services.map_exporter._CJK_FONT", None)

        assert exporter._resolve_language("zh") == "en"
        assert exporter._resolve_language(None) == "en"
        assert exporter._resolve_language("en") == "en"

    def test_can_reach_tile_server_returns_false_on_timeout(self, monkeypatch):
        exporter = MapExporter()

        def fake_create_connection(*args, **kwargs):
            raise TimeoutError("timed out")

        monkeypatch.setattr("socket.create_connection", fake_create_connection)

        assert exporter._can_reach_tile_server(timeout=0.01) is False

    def test_try_add_basemap_skips_when_disabled(self, monkeypatch):
        exporter = MapExporter(
            runtime_config=SimpleNamespace(
                map_export_basemap_enabled=False,
                map_export_basemap_timeout=2,
            )
        )
        calls: list[str] = []

        class DummyContextily:
            providers = SimpleNamespace(CartoDB=SimpleNamespace(PositronNoLabels="dummy"))

            @staticmethod
            def add_basemap(*args, **kwargs):
                calls.append("called")

        monkeypatch.setattr("services.map_exporter.HAS_CONTEXTILY", True)
        monkeypatch.setattr("services.map_exporter.ctx", DummyContextily)
        monkeypatch.setattr(exporter, "_can_reach_tile_server", lambda timeout=2: True)

        fig, ax = plt.subplots()
        try:
            exporter._try_add_basemap(ax)
        finally:
            plt.close(fig)

        assert calls == []

    def test_export_dispersion_map_with_contour(self, tmp_path: Path):
        exporter = MapExporter()
        output_path = tmp_path / "dispersion.png"

        file_path = exporter.export_dispersion_map(
            {"success": True, "data": _make_dispersion_payload(with_contour=True)},
            output_path=output_path,
            add_basemap=False,
        )

        _assert_valid_png(Path(file_path))

    def test_export_dispersion_map_falls_back_to_raster(self, tmp_path: Path):
        exporter = MapExporter()
        output_path = tmp_path / "dispersion_raster.png"

        file_path = exporter.export_dispersion_map(
            {"success": True, "data": _make_dispersion_payload(with_contour=False)},
            output_path=output_path,
            add_basemap=False,
        )

        _assert_valid_png(Path(file_path))

    def test_export_hotspot_map(self, tmp_path: Path):
        exporter = MapExporter()
        output_path = tmp_path / "hotspot.png"

        file_path = exporter.export_hotspot_map(
            {"success": True, "data": _make_hotspot_payload()},
            output_path=output_path,
            add_basemap=False,
        )

        _assert_valid_png(Path(file_path))

    def test_build_metadata_footer_text_includes_analysis_context(self):
        exporter = MapExporter()
        footer = exporter._build_metadata_footer_text(
            {
                "query_info": {"pollutant": "NOx", "met_source": "preset"},
                "scenario_label": "scenario_a",
            }
        )

        assert "Pollutant: NOx" in footer
        assert "Met: preset" in footer
        assert "Scenario: scenario_a" in footer
        assert "Emission Agent" in footer


class _DummyStored:
    def __init__(self, data: dict):
        self.data = data


class _DummyContextStore:
    def __init__(self, payload: dict):
        self.payload = payload

    def get_by_type(self, result_type: str, label: str | None = None):
        return _DummyStored(self.payload)


class _DummyRouter:
    def __init__(self, payload: dict):
        self.context_store = _DummyContextStore(payload)


class _DummySession:
    def __init__(self, payload: dict):
        self.router = _DummyRouter(payload)


class _DummySessionManager:
    def __init__(self, payload: dict):
        self._payload = payload

    def get_session(self, session_id: str):
        return _DummySession(self._payload)


class TestMapExportApi:
    @pytest.mark.anyio
    async def test_export_map_endpoint_returns_png(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("MAP_EXPORT_DIR", str(tmp_path / "exports"))
        reset_config()

        payload = {"success": True, "data": _make_dispersion_payload(with_contour=True)}

        class DummyRegistry:
            @staticmethod
            def get(user_id: str):
                return _DummySessionManager(payload)

        class InlineLoop:
            async def run_in_executor(self, executor, func):
                return func()

        monkeypatch.setattr(map_export_module, "SessionRegistry", DummyRegistry)
        monkeypatch.setattr(map_export_module.asyncio, "get_running_loop", lambda: InlineLoop())

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/export_map",
                "headers": [(b"x-user-id", b"test-user")],
            }
        )
        response = await map_export_module.export_map(
            ExportMapRequest(
                session_id="session-1",
                result_type="dispersion",
                scenario_label="baseline",
                format="png",
                dpi=150,
                add_basemap=False,
                add_roads=True,
                language="zh",
            ),
            request,
        )

        assert response.media_type == "image/png"
        export_path = Path(response.path)
        assert export_path.exists()
        assert export_path.name.startswith("dispersion_baseline_")
        image = Image.open(BytesIO(export_path.read_bytes()))
        image.verify()

    @pytest.mark.anyio
    async def test_export_map_endpoint_uses_run_in_executor(self, monkeypatch, tmp_path: Path):
        monkeypatch.setenv("MAP_EXPORT_DIR", str(tmp_path / "exports"))
        reset_config()

        payload = {"success": True, "data": _make_dispersion_payload(with_contour=True)}

        class DummyRegistry:
            @staticmethod
            def get(user_id: str):
                return _DummySessionManager(payload)

        class FakeLoop:
            def __init__(self):
                self.called = False
                self.executor = None

            async def run_in_executor(self, executor, func):
                self.called = True
                self.executor = executor
                return func()

        fake_loop = FakeLoop()

        monkeypatch.setattr(map_export_module, "SessionRegistry", DummyRegistry)
        monkeypatch.setattr(map_export_module.asyncio, "get_running_loop", lambda: fake_loop)

        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/api/export_map",
                "headers": [(b"x-user-id", b"test-user")],
            }
        )
        response = await map_export_module.export_map(
            ExportMapRequest(
                session_id="session-1",
                result_type="dispersion",
                scenario_label="baseline",
                format="png",
                dpi=150,
                add_basemap=False,
                add_roads=True,
                language="zh",
            ),
            request,
        )

        assert fake_loop.called is True
        assert fake_loop.executor is map_export_module._export_executor
        assert Path(response.path).exists()


@pytest.fixture(autouse=True)
def _reset_runtime_config():
    reset_config()
    yield
    reset_config()
