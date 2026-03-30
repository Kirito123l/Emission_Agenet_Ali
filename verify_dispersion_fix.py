#!/usr/bin/env python
"""
Verification script for dispersion fix.
Demonstrates that:
1. Models are loaded on-demand (not all at once)
2. Missing models for unused stability classes don't cause failure
3. Stab_Class is not overwritten by _normalize_met_df
"""

import sys
from pathlib import Path
from calculators.dispersion import (
    get_model_paths,
    load_models_for_stability,
    DispersionCalculator,
    DispersionConfig,
)
import pandas as pd

def test_on_demand_loading():
    """Test that models are loaded only for needed stability classes."""
    print("\n=== Test 1: On-Demand Model Loading ===")

    config = DispersionConfig(roughness_height=0.5)
    calc = DispersionCalculator(config)

    # Initialize models dict (empty)
    calc._ensure_models_loaded()
    print(f"Initial models dict: {calc._models}")
    assert calc._models == {}, "Models should start empty"

    # Load only VU model
    vu_models = calc._get_or_load_model("VU")
    print(f"After loading VU: {list(calc._models.keys())}")
    assert "VU" in calc._models, "VU should be loaded"
    assert len(calc._models) == 1, "Only VU should be loaded"

    # Load U model
    u_models = calc._get_or_load_model("U")
    print(f"After loading U: {list(calc._models.keys())}")
    assert "U" in calc._models, "U should be loaded"
    assert len(calc._models) == 2, "Only VU and U should be loaded"

    print("✓ On-demand loading works correctly")

def test_stab_class_preservation():
    """Test that preset stability_class is not overwritten."""
    print("\n=== Test 2: Stab_Class Preservation ===")

    config = DispersionConfig()
    calc = DispersionCalculator(config)

    # Create met_df with explicit Stab_Class from preset
    met_df = pd.DataFrame({
        "Date": [202401010],
        "WSPD": [2.5],
        "WDIR": [225],
        "MixHGT_C": [1500],
        "L": [-50],
        "H": [0],
        "Stab_Class": ["VU"],  # Explicit from preset
    })

    normalized = calc._normalize_met_df(met_df)
    print(f"Input Stab_Class: VU")
    print(f"Output Stab_Class: {normalized['Stab_Class'].iloc[0]}")
    assert normalized["Stab_Class"].iloc[0] == "VU", "Stab_Class should not be overwritten"

    print("✓ Stab_Class preservation works correctly")

def test_partial_nan_handling():
    """Test that only NaN rows are recalculated."""
    print("\n=== Test 3: Partial NaN Handling ===")

    config = DispersionConfig()
    calc = DispersionCalculator(config)

    # Create met_df with mixed NaN and valid values
    met_df = pd.DataFrame({
        "Date": [202401010, 202401011],
        "WSPD": [2.5, 3.0],
        "WDIR": [225, 270],
        "MixHGT_C": [1500, 800],
        "L": [-50, -300],
        "H": [0, 0],
        "Stab_Class": ["VU", None],  # Second row is NaN
    })

    normalized = calc._normalize_met_df(met_df)
    print(f"Input Stab_Class: {met_df['Stab_Class'].tolist()}")
    print(f"Output Stab_Class: {normalized['Stab_Class'].tolist()}")

    # First row should keep VU
    assert normalized["Stab_Class"].iloc[0] == "VU", "First row should keep VU"
    # Second row should be calculated as U (because -300 is in -1000 < L <= -200)
    assert normalized["Stab_Class"].iloc[1] == "U", "Second row should be calculated as U"

    print("✓ Partial NaN handling works correctly")

def test_model_paths():
    """Test that model paths are correctly constructed."""
    print("\n=== Test 4: Model Path Construction ===")

    x0_path, xneg_path = get_model_paths("VU", 0.5)
    print(f"VU x0 path: {x0_path.name}")
    print(f"VU x-1 path: {xneg_path.name}")

    assert "veryunstable" in x0_path.name, "Should contain 'veryunstable'"
    assert "x0" in x0_path.name, "Should contain 'x0'"
    assert "x-1" in xneg_path.name, "Should contain 'x-1'"

    print("✓ Model path construction works correctly")

if __name__ == "__main__":
    try:
        test_on_demand_loading()
        test_stab_class_preservation()
        test_partial_nan_handling()
        test_model_paths()
        print("\n" + "="*50)
        print("✓ All verification tests passed!")
        print("="*50)
        sys.exit(0)
    except Exception as e:
        print(f"\n✗ Verification failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
