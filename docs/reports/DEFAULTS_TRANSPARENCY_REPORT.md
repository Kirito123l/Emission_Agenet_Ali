# Defaults Transparency & Pasquill Stability Fix - Report

**Date**: 2026-03-22
**Status**: Complete

---

## 1. Bug Fix: Pasquill A-F Stability Class Mapping

### Problem
LLM sends Pasquill stability class letters (A-F) like `stability_class="C"`, but the standardizer only recognized internal codes (VS/S/N1/N2/U/VU), causing `StandardizationError` abstain errors.

### Solution
Added Pasquill letter aliases to `config/unified_mappings.yaml` stability_classes section. No code changes needed — the standardizer's `_build_lookup_tables()` automatically picks up new aliases from YAML.

### Mapping

| Pasquill Letter | Internal Code | Description |
|----------------|---------------|-------------|
| A | VU | Very Unstable |
| B | U | Unstable |
| C | N2 | Neutral 2 |
| D | N1 | Neutral |
| E | S | Stable |
| F | VS | Very Stable |

Each letter also accepts: lowercase (`a`-`f`), prefix forms (`Pasquill C`, `class D`).

### Files Modified
- `config/unified_mappings.yaml` — Added 24 new aliases (4 per stability class)

### Tests Added
- `tests/test_standardizer_enhanced.py::TestPasquillStabilityMapping` — 16 tests
  - 12 parametrized letter tests (A-F uppercase + lowercase)
  - 2 prefix form tests (`Pasquill C`, `class D`)
  - 2 backward compatibility tests (existing codes + existing aliases)

---

## 2. Feature: Default Parameter Transparency

### Problem
Default parameters (pollutants, model_year, season, fleet_mix, meteorology, roughness, grid_resolution) were used silently. Users had no way to know which parameters used defaults vs explicit values.

### Solution
Added `defaults_used` tracking to both tool execute methods and updated skill files to instruct the LLM to present defaults transparently.

### Implementation

#### `tools/macro_emission.py`
- Tracks defaults for: `pollutants`, `model_year`, `season`, `fleet_mix`
- Adds `defaults_used` dict to `result["data"]` when any defaults are used
- Appends "**使用默认参数:**" line to summary with Chinese-language parameter descriptions

#### `tools/dispersion.py`
- Tracks defaults for: `meteorology`, `roughness_height`, `pollutant`, `grid_resolution`
- Adds `defaults_used` dict to `result["data"]` when any defaults are used
- Appends "Defaults used:" line to `_build_summary()` output

#### Skill Files Updated
| File | Change |
|------|--------|
| `config/skills/emission_skill.yaml` | Added rule 3: defaults transparency instruction |
| `config/skills/post_emission_guide.yaml` | Added rule 2: must report `defaults_used` to user |
| `config/skills/post_dispersion_guide.yaml` | Added rule 3: must report `defaults_used` to user |

### `defaults_used` Schema

```json
// Macro emission example
{
  "defaults_used": {
    "pollutants": ["CO2", "NOx"],
    "model_year": 2020,
    "season": "夏季",
    "fleet_mix": { "Passenger Car": 0.7, ... }
  }
}

// Dispersion example
{
  "defaults_used": {
    "meteorology": "urban_summer_day",
    "roughness_height": 0.5,
    "pollutant": "NOx",
    "grid_resolution": 50
  }
}
```

The field is only present when at least one parameter used a default value. If the user explicitly provides all parameters, `defaults_used` is absent from the result.

---

## 3. Test Results

```
====================== 480 passed, 19 warnings in 44.74s =======================
```

16 new tests added (Pasquill mapping), 0 existing tests broken.

---

## 4. Backward Compatibility

- **Pasquill mapping**: Additive only. All existing stability codes and aliases continue to work identically.
- **`defaults_used`**: Optional field. Downstream code that doesn't check for it is unaffected. The field is absent when no defaults are used.
- **Skill files**: Only add new instructions, don't remove existing ones.
- **No changes to**: `calculators/`, `core/router.py`, `core/assembler.py`, `services/standardizer.py` (code).
