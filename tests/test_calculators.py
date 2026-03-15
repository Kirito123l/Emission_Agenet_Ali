"""Tests for the emission calculation engines.

These tests verify core calculation logic WITHOUT any LLM or API dependency.
They use the CSV data files shipped with the repository.
"""
import pandas as pd

from calculators.vsp import VSPCalculator
from calculators.micro_emission import MicroEmissionCalculator
from calculators.emission_factors import EmissionFactorCalculator
from calculators.macro_emission import MacroEmissionCalculator


class TestVSPCalculator:
    """VSP calculation and opMode mapping."""

    def setup_method(self):
        self.calc = VSPCalculator()

    def test_idle_opmode(self):
        """Speed < 1 mph should be idle (opMode 0)."""
        opmode = self.calc.vsp_to_opmode(speed_mph=0.0, vsp=0.0)
        assert opmode == 0

    def test_low_speed_opmode(self):
        """Low speed (< 25 mph) should map to opModes 11-16."""
        opmode = self.calc.vsp_to_opmode(speed_mph=15.0, vsp=5.0)
        assert 11 <= opmode <= 16

    def test_medium_speed_opmode(self):
        """Medium speed (25-50 mph) should map to opModes 21-30."""
        opmode = self.calc.vsp_to_opmode(speed_mph=35.0, vsp=5.0)
        assert 21 <= opmode <= 30

    def test_high_speed_opmode(self):
        """High speed (>= 50 mph) should map to opModes 33-40."""
        opmode = self.calc.vsp_to_opmode(speed_mph=60.0, vsp=10.0)
        assert 33 <= opmode <= 40

    def test_vsp_calculation_passenger_car(self):
        """VSP should produce a finite number for normal inputs."""
        vsp = self.calc.calculate_vsp(
            speed_mps=20.0,    # ~72 km/h
            acc=0.0,
            grade_pct=0.0,
            vehicle_type_id=21  # Passenger Car
        )
        assert isinstance(vsp, float)
        assert -50 < vsp < 200  # Sanity range

    def test_vsp_with_acceleration(self):
        """VSP should increase with positive acceleration."""
        vsp_zero = self.calc.calculate_vsp(20.0, 0.0, 0.0, 21)
        vsp_acc = self.calc.calculate_vsp(20.0, 2.0, 0.0, 21)
        assert vsp_acc > vsp_zero

    def test_vsp_bin_range(self):
        """VSP bin should be between 1 and 14."""
        for vsp_val in [-5.0, 0.0, 5.0, 15.0, 30.0]:
            bin_id = self.calc.vsp_to_bin(vsp_val)
            assert 1 <= bin_id <= 14

    def test_trajectory_vsp_batch(self):
        """Batch trajectory VSP calculation should add vsp/opmode fields."""
        trajectory = [
            {"t": 0, "speed_kph": 0},
            {"t": 1, "speed_kph": 10},
            {"t": 2, "speed_kph": 30},
            {"t": 3, "speed_kph": 50},
        ]
        results = self.calc.calculate_trajectory_vsp(trajectory, vehicle_type_id=21)
        assert len(results) == 4
        for point in results:
            assert "vsp" in point
            assert "opmode" in point

    def test_invalid_vehicle_type_raises(self):
        """Unknown vehicle type ID should raise ValueError."""
        import pytest
        with pytest.raises(ValueError):
            self.calc.calculate_vsp(20.0, 0.0, 0.0, vehicle_type_id=999)


class TestMicroEmissionCalculator:
    """Micro-scale emission calculation end-to-end."""

    def setup_method(self):
        self.calc = MicroEmissionCalculator()

    def test_simple_trajectory_calculation(self):
        """A basic trajectory should produce successful results."""
        trajectory = [
            {"t": 0, "speed_kph": 0},
            {"t": 1, "speed_kph": 10},
            {"t": 2, "speed_kph": 25},
            {"t": 3, "speed_kph": 40},
            {"t": 4, "speed_kph": 60},
        ]
        result = self.calc.calculate(
            trajectory_data=trajectory,
            vehicle_type="Passenger Car",
            pollutants=["CO2", "NOx"],
            model_year=2020,
            season="夏季"
        )
        assert result["status"] == "success"
        assert "data" in result
        assert len(result["data"]["results"]) == 5
        # Each result point should have emissions
        for point in result["data"]["results"]:
            assert "emissions" in point
            assert "CO2" in point["emissions"]

    def test_summary_statistics(self):
        """Summary should contain total emissions and distance."""
        trajectory = [
            {"t": i, "speed_kph": 60} for i in range(10)
        ]
        result = self.calc.calculate(
            trajectory_data=trajectory,
            vehicle_type="Passenger Car",
            pollutants=["CO2"],
            model_year=2020,
            season="夏季"
        )
        assert result["status"] == "success"
        summary = result["data"]["summary"]
        assert "total_emissions_g" in summary
        assert "total_distance_km" in summary
        assert summary["total_distance_km"] > 0

    def test_unknown_vehicle_type_error(self):
        """Unknown vehicle type should return error status."""
        result = self.calc.calculate(
            trajectory_data=[{"t": 0, "speed_kph": 0}],
            vehicle_type="SpaceShip",
            pollutants=["CO2"],
            model_year=2020,
            season="夏季"
        )
        assert result["status"] == "error"

    def test_empty_trajectory_error(self):
        """Empty trajectory should return error."""
        result = self.calc.calculate(
            trajectory_data=[],
            vehicle_type="Passenger Car",
            pollutants=["CO2"],
            model_year=2020,
            season="夏季"
        )
        assert result["status"] == "error"

    def test_year_to_age_group(self):
        """Model year conversion to MOVES age groups."""
        assert self.calc._year_to_age_group(2025) == 1  # 0 years old
        assert self.calc._year_to_age_group(2020) == 2  # 5 years old
        assert self.calc._year_to_age_group(2010) == 5  # 15 years old
        assert self.calc._year_to_age_group(2000) == 9  # 25 years old


class TestMacroEmissionCalculator:
    """Macro-scale emission calculation and matrix lookup behavior."""

    def setup_method(self):
        MacroEmissionCalculator.clear_matrix_cache()
        self.calc = MacroEmissionCalculator()

    def test_load_emission_matrix_reuses_cached_dataframe(self, monkeypatch, tmp_path):
        """Loading the same season twice should reuse the in-process cache."""
        self.calc.data_path = tmp_path
        self.calc.csv_files = {
            "winter": "winter.csv",
            "spring": "spring.csv",
            "summer": "summer.csv",
        }
        (tmp_path / "summer.csv").write_text("unused\n", encoding="utf-8")

        read_calls = []

        def fake_read_csv(path, header=None, names=None):
            read_calls.append(path)
            return pd.DataFrame(
                [
                    {
                        self.calc.COL_OPMODE: self.calc.LOOKUP_OPMODE,
                        self.calc.COL_POLLUTANT: 90,
                        self.calc.COL_SOURCE_TYPE: 21,
                        self.calc.COL_MODEL_YEAR: 2025,
                        self.calc.COL_EMISSION: 1.23,
                        "extra": None,
                    }
                ]
            )

        monkeypatch.setattr(pd, "read_csv", fake_read_csv)

        first = self.calc._load_emission_matrix("夏季")
        second = self.calc._load_emission_matrix("夏季")

        assert first is second
        assert len(read_calls) == 1
        assert first.attrs["macro_emission_rate_lookup"][(90, 21, 2025)] == 1.23

    def test_query_emission_rate_matches_legacy_scan(self):
        """Indexed lookup should return the same rate as the legacy boolean scan."""
        matrix = self.calc._load_emission_matrix("夏季")
        sample_rows = (
            matrix.loc[
                matrix[self.calc.COL_OPMODE] == self.calc.LOOKUP_OPMODE,
                [
                    self.calc.COL_POLLUTANT,
                    self.calc.COL_SOURCE_TYPE,
                    self.calc.COL_MODEL_YEAR,
                    self.calc.COL_EMISSION,
                ],
            ]
            .drop_duplicates()
            .head(5)
        )

        for pollutant_id, source_type, model_year, _ in sample_rows.itertuples(index=False, name=None):
            expected = self.calc._query_emission_rate_scan(
                matrix,
                int(source_type),
                int(pollutant_id),
                int(model_year),
            )
            actual = self.calc._query_emission_rate(
                matrix,
                int(source_type),
                int(pollutant_id),
                int(model_year),
            )
            assert actual == expected

        assert self.calc._query_emission_rate(matrix, 999, 999, 1900) == 0.0

    def test_query_emission_rate_rebuilds_lookup_for_external_matrix(self):
        """Matrices without attrs should lazily rebuild the indexed lookup."""
        matrix = self.calc._load_emission_matrix("夏季").copy()
        matrix.attrs.pop("macro_emission_rate_lookup", None)

        source_type = self.calc.VEHICLE_TO_SOURCE_TYPE["Passenger Car"]
        pollutant_id = self.calc.POLLUTANT_TO_ID["CO2"]
        expected = self.calc._query_emission_rate_scan(matrix, source_type, pollutant_id, 2025)

        actual = self.calc._query_emission_rate(matrix, source_type, pollutant_id, 2025)

        assert actual == expected
        assert "macro_emission_rate_lookup" in matrix.attrs

    def test_calculate_matches_legacy_lookup_path(self, monkeypatch):
        """End-to-end macro calculation output should match the legacy lookup path."""
        links_data = [
            {
                "link_id": "L1",
                "link_length_km": 1.2,
                "traffic_flow_vph": 1200,
                "avg_speed_kph": 45.0,
            },
            {
                "link_id": "L2",
                "link_length_km": 0.8,
                "traffic_flow_vph": 850,
                "avg_speed_kph": 35.0,
                "fleet_mix": {
                    "Passenger Car": 55.0,
                    "Passenger Truck": 25.0,
                    "Transit Bus": 20.0,
                },
            },
        ]
        pollutants = ["CO2", "NOx"]
        default_fleet_mix = {
            "Passenger Car": 60.0,
            "Passenger Truck": 25.0,
            "Transit Bus": 10.0,
            "Combination Long-haul Truck": 5.0,
        }

        optimized = self.calc.calculate(
            links_data=links_data,
            pollutants=pollutants,
            model_year=2025,
            season="夏季",
            default_fleet_mix=default_fleet_mix,
        )

        legacy_calc = MacroEmissionCalculator()
        monkeypatch.setattr(legacy_calc, "_query_emission_rate", legacy_calc._query_emission_rate_scan)
        legacy = legacy_calc.calculate(
            links_data=links_data,
            pollutants=pollutants,
            model_year=2025,
            season="夏季",
            default_fleet_mix=default_fleet_mix,
        )

        assert optimized == legacy


class TestEmissionFactorCalculator:
    """Emission factor query calculator."""

    def setup_method(self):
        self.calc = EmissionFactorCalculator()

    def test_vehicle_type_mapping_complete(self):
        """All 13 MOVES vehicle types should be mapped."""
        assert len(self.calc.VEHICLE_TO_SOURCE_TYPE) == 13
        assert "Passenger Car" in self.calc.VEHICLE_TO_SOURCE_TYPE
        assert "Transit Bus" in self.calc.VEHICLE_TO_SOURCE_TYPE

    def test_pollutant_mapping_complete(self):
        """Key pollutants should be mapped."""
        assert "CO2" in self.calc.POLLUTANT_TO_ID
        assert "NOx" in self.calc.POLLUTANT_TO_ID
        assert "PM2.5" in self.calc.POLLUTANT_TO_ID
