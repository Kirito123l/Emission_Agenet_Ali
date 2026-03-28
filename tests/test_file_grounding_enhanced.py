"""Tests for enhanced file grounding with multi-signal analysis."""

import pandas as pd


class TestValueFeatureAnalysis:
    """Test _analyze_value_features method."""

    def _get_analyzer(self):
        from tools.file_analyzer import FileAnalyzerTool
        return FileAnalyzerTool()

    def test_vehicle_speed_detection(self):
        """Column with values 0-30 and high variance should hint vehicle speed."""
        df = pd.DataFrame({"speed": [0, 5, 12, 25, 18, 3, 28, 15]})
        features = self._get_analyzer()._analyze_value_features(df)
        assert "possible_vehicle_speed_ms" in features["speed"]["feature_hints"]

    def test_link_speed_detection(self):
        """Column with values 40-120 and low variance should hint link speed."""
        df = pd.DataFrame({"avg_speed": [60, 65, 80, 75, 90, 55, 70, 85]})
        features = self._get_analyzer()._analyze_value_features(df)
        assert "possible_link_speed_kmh" in features["avg_speed"]["feature_hints"]

    def test_acceleration_detection(self):
        """Column with values -3 to 3 centered near 0 should hint acceleration."""
        df = pd.DataFrame({"accel": [-2.1, 0.5, 1.3, -0.8, 0.2, -1.5, 2.0, 0.0]})
        features = self._get_analyzer()._analyze_value_features(df)
        assert "possible_acceleration" in features["accel"]["feature_hints"]

    def test_traffic_flow_detection(self):
        """Positive integers in 100-10000 range should hint traffic flow."""
        df = pd.DataFrame({"vol": [500, 1200, 800, 3500, 2100, 900, 1500, 4000]})
        features = self._get_analyzer()._analyze_value_features(df)
        assert "possible_traffic_flow" in features["vol"]["feature_hints"]

    def test_fraction_detection(self):
        """Values 0-1 should hint fraction."""
        df = pd.DataFrame({"share": [0.7, 0.2, 0.05, 0.03, 0.02]})
        features = self._get_analyzer()._analyze_value_features(df)
        assert "possible_fraction" in features["share"]["feature_hints"]

    def test_negative_column_excluded(self):
        """All-negative column should be flagged."""
        df = pd.DataFrame({"weird": [-5, -10, -3, -8]})
        features = self._get_analyzer()._analyze_value_features(df)
        assert "all_negative_exclude_speed_flow" in features["weird"]["feature_hints"]

    def test_non_numeric_column_skipped(self):
        """Non-numeric columns should get empty or minimal hints."""
        df = pd.DataFrame({"name": ["road_a", "road_b", "road_c"]})
        features = self._get_analyzer()._analyze_value_features(df)
        hints = features.get("name", {}).get("feature_hints", [])
        assert "possible_vehicle_speed_ms" not in hints

    def test_empty_dataframe(self):
        """Empty DataFrame should not crash."""
        df = pd.DataFrame()
        features = self._get_analyzer()._analyze_value_features(df)
        assert features == {}

    def test_all_nan_column(self):
        """All-NaN column should not crash."""
        df = pd.DataFrame({"x": [float("nan"), float("nan"), float("nan")]})
        features = self._get_analyzer()._analyze_value_features(df)
        assert "x" in features


class TestMultiSignalTaskIdentification:
    """Test that _identify_task_type uses all three signals."""

    def _get_analyzer(self):
        from tools.file_analyzer import FileAnalyzerTool
        return FileAnalyzerTool()

    def test_standard_micro_file(self):
        """Standard micro column names should be identified correctly."""
        result = self._get_analyzer()._identify_task_type(
            ["time", "speed", "acceleration", "grade"]
        )
        assert result["task_type"] == "micro_emission"
        assert result["confidence"] > 0.6
        assert len(result["evidence"]) > 0

    def test_standard_macro_file(self):
        """Standard macro column names should be identified correctly."""
        result = self._get_analyzer()._identify_task_type(
            ["link_id", "length", "flow", "speed"]
        )
        assert result["task_type"] == "macro_emission"
        assert result["confidence"] > 0.6
        assert len(result["evidence"]) > 0

    def test_ambiguous_column_names_resolved_by_values(self):
        """When column names are ambiguous, value features should help resolve."""
        value_features = {
            "speed": {"feature_hints": ["possible_link_speed_kmh"], "min": 55.0, "max": 110.0},
            "length": {"feature_hints": ["possible_link_length"], "min": 0.5, "max": 15.0},
            "flow": {"feature_hints": ["possible_traffic_flow"], "min": 200, "max": 5000},
        }
        result = self._get_analyzer()._identify_task_type(
            ["speed", "length", "flow"], value_features
        )
        assert result["task_type"] == "macro_emission"

    def test_unknown_columns_with_value_hints(self):
        """Generic column names but informative values should still identify task."""
        value_features = {
            "col_1": {"feature_hints": ["timestamp"]},
            "col_2": {"feature_hints": ["possible_vehicle_speed_ms"], "min": 0, "max": 35},
            "col_3": {"feature_hints": ["possible_acceleration"], "min": -3.0, "max": 3.0, "mean": 0.1},
        }
        result = self._get_analyzer()._identify_task_type(
            ["col_1", "col_2", "col_3"], value_features
        )
        assert result["task_type"] == "micro_emission"
        assert any("value_range" in e for e in result["evidence"])

    def test_evidence_contains_all_signal_types(self):
        """Evidence should mention different signal types used."""
        value_features = {
            "speed": {"feature_hints": ["possible_vehicle_speed_ms"], "min": 0, "max": 30},
            "time": {"feature_hints": ["timestamp"]},
            "acceleration": {"feature_hints": ["possible_acceleration"], "min": -3, "max": 3, "mean": 0.0},
        }
        result = self._get_analyzer()._identify_task_type(
            ["speed", "time", "acceleration"], value_features
        )
        evidence_text = " ".join(result["evidence"])
        assert "column_name" in evidence_text
        assert "value_range" in evidence_text

    def test_no_signals_returns_unknown(self):
        """Completely unrecognizable columns should return unknown."""
        result = self._get_analyzer()._identify_task_type(["x", "y", "z"])
        assert result["task_type"] == "unknown"
        assert result["confidence"] < 0.4

    def test_evidence_output_is_list_of_strings(self):
        """Evidence must be a list of strings."""
        result = self._get_analyzer()._identify_task_type(["speed", "flow"])
        assert isinstance(result["evidence"], list)
        assert all(isinstance(e, str) for e in result["evidence"])


class TestAnalyzeStructureIntegration:
    """Test that _analyze_structure integrates value features and evidence."""

    def _get_analyzer(self):
        from tools.file_analyzer import FileAnalyzerTool
        return FileAnalyzerTool()

    def test_structure_output_includes_evidence(self):
        """_analyze_structure output should include evidence list."""
        df = pd.DataFrame({
            "speed": [60, 70, 80, 90, 100],
            "length": [1.5, 2.0, 3.5, 1.0, 2.5],
            "flow": [1000, 2000, 1500, 3000, 2500],
        })
        result = self._get_analyzer()._analyze_structure(df, "test.csv")
        assert "evidence" in result
        assert isinstance(result["evidence"], list)
        assert len(result["evidence"]) > 0

    def test_structure_output_backward_compatible(self):
        """All existing fields must still be present."""
        df = pd.DataFrame({
            "speed": [10, 20, 30],
            "time": [1, 2, 3],
            "acceleration": [0.5, -0.3, 0.1],
        })
        result = self._get_analyzer()._analyze_structure(df, "traj.csv")
        required_fields = [
            "filename", "row_count", "columns", "task_type", "confidence",
            "micro_mapping", "macro_mapping", "micro_has_required",
            "macro_has_required", "sample_rows"
        ]
        for field_name in required_fields:
            assert field_name in result, f"Missing field: {field_name}"
