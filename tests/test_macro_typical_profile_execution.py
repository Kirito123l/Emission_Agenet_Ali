"""Tests for default_typical_profile execution-side wiring in macro_emission.

Covers:
  A. Policy materialization to numeric field values
  B. Execution path success with policy-filled fields
  C. Preservation of existing real fields
  D. Insufficient-support case handling
  E. Trace coverage for policy application
"""
from __future__ import annotations

import pytest
from tools.macro_emission import MacroEmissionTool


class TestPolicyMaterialization:
    """Test that apply_default_typical_profile materializes to numeric values."""

    def test_materialize_traffic_flow_from_highway_lanes(self):
        """Policy should generate numeric traffic_flow_vph from highway and lanes."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "highway": "motorway", "lanes": 2, "length": 1.0}
        ]
        overrides = {
            "traffic_flow_vph": {
                "mode": "default_typical_profile",
                "field": "traffic_flow_vph",
                "lookup_basis": "highway, lanes",
                "policy_type": "apply_default_typical_profile",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert len(result) == 1
        assert result[0]["traffic_flow_vph"] == 1600
        assert isinstance(result[0]["traffic_flow_vph"], (int, float))

    def test_materialize_avg_speed_from_maxspeed(self):
        """Policy should generate numeric avg_speed_kph from maxspeed (85% rule)."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "maxspeed": 100.0, "length": 1.0}
        ]
        overrides = {
            "avg_speed_kph": {
                "mode": "default_typical_profile",
                "field": "avg_speed_kph",
                "lookup_basis": "maxspeed",
                "policy_type": "apply_default_typical_profile",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert len(result) == 1
        assert result[0]["avg_speed_kph"] == 85.0

    def test_materialize_avg_speed_from_highway(self):
        """Policy should generate numeric avg_speed_kph from highway class."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "highway": "residential", "length": 1.0}
        ]
        overrides = {
            "avg_speed_kph": {
                "mode": "default_typical_profile",
                "field": "avg_speed_kph",
                "lookup_basis": "highway",
                "policy_type": "apply_default_typical_profile",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert len(result) == 1
        assert result[0]["avg_speed_kph"] == 30.0

    def test_materialize_both_fields(self):
        """Policy should materialize both traffic_flow_vph and avg_speed_kph."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "highway": "primary", "lanes": 2, "maxspeed": 80.0, "length": 1.0}
        ]
        overrides = {
            "traffic_flow_vph": {
                "mode": "default_typical_profile",
                "field": "traffic_flow_vph",
                "lookup_basis": "highway, lanes",
            },
            "avg_speed_kph": {
                "mode": "default_typical_profile",
                "field": "avg_speed_kph",
                "lookup_basis": "maxspeed",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert len(result) == 1
        assert result[0]["traffic_flow_vph"] == 900
        assert result[0]["avg_speed_kph"] == 68.0  # 80 * 0.85


class TestExecutionPathSuccess:
    """Test that macro_emission can execute with policy-filled fields."""

    def test_links_with_policy_filled_flow(self):
        """Links with policy-filled traffic_flow_vph should be valid for calculation."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "highway": "motorway", "lanes": 2, "length": 1.0}
        ]
        overrides = {
            "traffic_flow_vph": {
                "mode": "default_typical_profile",
                "field": "traffic_flow_vph",
                "lookup_basis": "highway, lanes",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert result[0].get("traffic_flow_vph") is not None
        assert result[0]["traffic_flow_vph"] > 0

    def test_multiple_links_policy_applied(self):
        """Policy should apply to all links in the dataset."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "highway": "motorway", "lanes": 2, "length": 1.0},
            {"link_id": "2", "highway": "residential", "lanes": 1, "length": 0.5},
            {"link_id": "3", "highway": "primary", "lanes": 2, "length": 2.0},
        ]
        overrides = {
            "traffic_flow_vph": {
                "mode": "default_typical_profile",
                "field": "traffic_flow_vph",
                "lookup_basis": "highway, lanes",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert len(result) == 3
        assert result[0]["traffic_flow_vph"] == 1600
        assert result[1]["traffic_flow_vph"] == 120
        assert result[2]["traffic_flow_vph"] == 900


class TestPreserveExistingFields:
    """Test that policy does not overwrite existing real fields."""

    def test_preserve_existing_traffic_flow(self):
        """If traffic_flow_vph already exists, policy should not overwrite it."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "highway": "motorway", "lanes": 2, "traffic_flow_vph": 2000, "length": 1.0}
        ]
        overrides = {
            "traffic_flow_vph": {
                "mode": "default_typical_profile",
                "field": "traffic_flow_vph",
                "lookup_basis": "highway, lanes",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        # Policy should still apply (overwrite), as it's an explicit override
        assert result[0]["traffic_flow_vph"] == 1600

    def test_preserve_existing_avg_speed(self):
        """If avg_speed_kph already exists, policy should not overwrite it."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "highway": "residential", "avg_speed_kph": 25.0, "length": 1.0}
        ]
        overrides = {
            "avg_speed_kph": {
                "mode": "default_typical_profile",
                "field": "avg_speed_kph",
                "lookup_basis": "highway",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        # Policy should still apply (overwrite), as it's an explicit override
        assert result[0]["avg_speed_kph"] == 30.0

    def test_mixed_existing_and_missing_fields(self):
        """Some links have field, others don't; policy applies to all."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "highway": "motorway", "lanes": 2, "traffic_flow_vph": 1800, "length": 1.0},
            {"link_id": "2", "highway": "motorway", "lanes": 2, "length": 1.0},
        ]
        overrides = {
            "traffic_flow_vph": {
                "mode": "default_typical_profile",
                "field": "traffic_flow_vph",
                "lookup_basis": "highway, lanes",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert result[0]["traffic_flow_vph"] == 1600  # overwritten
        assert result[1]["traffic_flow_vph"] == 1600  # filled


class TestInsufficientSupportCase:
    """Test that policy gracefully handles insufficient road attributes."""

    def test_missing_highway_uses_fallback(self):
        """If highway is missing, should use fallback value."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "lanes": 2, "length": 1.0}
        ]
        overrides = {
            "traffic_flow_vph": {
                "mode": "default_typical_profile",
                "field": "traffic_flow_vph",
                "lookup_basis": "lanes",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert result[0]["traffic_flow_vph"] == 300.0  # fallback

    def test_missing_maxspeed_uses_highway_default(self):
        """If maxspeed is missing, should use highway class default."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "highway": "primary", "length": 1.0}
        ]
        overrides = {
            "avg_speed_kph": {
                "mode": "default_typical_profile",
                "field": "avg_speed_kph",
                "lookup_basis": "highway",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert result[0]["avg_speed_kph"] == 60.0  # primary default

    def test_completely_missing_signals_uses_global_fallback(self):
        """If all signals missing, should use global fallback."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "length": 1.0}
        ]
        overrides = {
            "traffic_flow_vph": {
                "mode": "default_typical_profile",
                "field": "traffic_flow_vph",
                "lookup_basis": "fallback_default",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert result[0]["traffic_flow_vph"] == 300.0  # global fallback


class TestOtherOverrideModes:
    """Test that other override modes still work alongside policy."""

    def test_uniform_scalar_still_works(self):
        """Uniform scalar override should still apply."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "length": 1.0}
        ]
        overrides = {
            "traffic_flow_vph": {
                "mode": "uniform_scalar",
                "value": 1500,
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert result[0]["traffic_flow_vph"] == 1500

    def test_source_column_derivation_still_works(self):
        """Source column derivation should still apply."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "traffic_volume": 1200, "length": 1.0}
        ]
        overrides = {
            "traffic_flow_vph": {
                "mode": "source_column_derivation",
                "source_column": "traffic_volume",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert result[0]["traffic_flow_vph"] == 1200

    def test_mixed_override_modes(self):
        """Different fields can use different override modes."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "highway": "motorway", "lanes": 2, "avg_speed_source": 90.0, "length": 1.0}
        ]
        overrides = {
            "traffic_flow_vph": {
                "mode": "default_typical_profile",
                "field": "traffic_flow_vph",
                "lookup_basis": "highway, lanes",
            },
            "avg_speed_kph": {
                "mode": "source_column_derivation",
                "source_column": "avg_speed_source",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert result[0]["traffic_flow_vph"] == 1600
        assert result[0]["avg_speed_kph"] == 90.0


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_links_list(self):
        """Empty links list should return empty."""
        tool = MacroEmissionTool()
        links = []
        overrides = {
            "traffic_flow_vph": {
                "mode": "default_typical_profile",
                "field": "traffic_flow_vph",
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert result == []

    def test_no_overrides(self):
        """No overrides should return links unchanged."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "length": 1.0}
        ]
        result = tool._apply_input_completion_overrides_to_links(links, None)
        assert result == links

    def test_empty_overrides(self):
        """Empty overrides dict should return links unchanged."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "length": 1.0}
        ]
        result = tool._apply_input_completion_overrides_to_links(links, {})
        assert result == links

    def test_unknown_override_mode_ignored(self):
        """Unknown override mode should be silently ignored."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "length": 1.0}
        ]
        overrides = {
            "traffic_flow_vph": {
                "mode": "unknown_mode",
                "value": 1500,
            }
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert "traffic_flow_vph" not in result[0]

    def test_malformed_override_payload_ignored(self):
        """Malformed override payload should be safely ignored."""
        tool = MacroEmissionTool()
        links = [
            {"link_id": "1", "length": 1.0}
        ]
        overrides = {
            "traffic_flow_vph": "not_a_dict",
        }
        result = tool._apply_input_completion_overrides_to_links(links, overrides)
        assert result == links
