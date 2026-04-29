"""Consistency tests for runtime_defaults vs emission_domain_schema.

Phase 5.2 Round 2: validates that _RUNTIME_DEFAULTS stays in sync with
the emission domain schema, and that changing the schema propagates to
runtime defaults (no hardcoded values left behind).
"""

from __future__ import annotations

import pytest

from core.contracts.emission_schema import get_default as _schema_get_default


def test_runtime_defaults_model_year_matches_schema():
    """model_year default in runtime_defaults reads from schema, no drift."""
    from core.contracts import runtime_defaults as rt
    # force re-evaluation by clearing cache
    import core.contracts.emission_schema as es
    es._CACHE = None
    rt._loaded = False

    default = rt.get_runtime_default("query_emission_factors", "model_year")
    expected = _schema_get_default("model_year")
    assert default == expected, (
        f"runtime_defaults.model_year={default} != schema.model_year={expected}"
    )


def test_runtime_defaults_follows_schema_change(monkeypatch):
    """When schema reports a different model_year default, runtime_defaults reflects it."""
    import copy

    import core.contracts.emission_schema as es

    original_cache = es._CACHE
    patched_schema = copy.deepcopy(original_cache or es._load_schema())
    patched_schema["dimensions"]["model_year"]["default"] = 2025

    monkeypatch.setattr(
        "core.contracts.emission_schema._load_schema",
        lambda: patched_schema,
    )
    es._CACHE = None

    from core.contracts import runtime_defaults as rt
    rt._loaded = False
    rt._RUNTIME_DEFAULTS.clear()

    default = rt.get_runtime_default("query_emission_factors", "model_year")
    assert default == 2025, f"Expected 2025 from mocked _load_schema, got {default}"

    # Cleanup
    monkeypatch.undo()
    es._CACHE = original_cache
    rt._loaded = False
    rt._RUNTIME_DEFAULTS.clear()
