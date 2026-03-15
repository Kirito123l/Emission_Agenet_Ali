# GIS Phase 1 Matrix Lookup Optimization Report

## 1. Executive Summary
- Targeted bottleneck: repeated full-DataFrame boolean filtering in `calculators/macro_emission.py` during macro emission matrix lookups.
- Implemented optimization: in-process season matrix caching plus a pre-indexed tuple-key lookup for the fixed `opMode=300` query path.
- Intentionally left untouched: frontend map rendering, session/history payload size, and broader GIS pipeline changes.

## 2. Current Bottleneck Confirmation
- Previous behavior:
  - `_load_emission_matrix()` read the CSV on every calculation call.
  - `_query_emission_rate()` filtered the full pandas DataFrame every time using:
    - `opModeID == 300`
    - `pollutantID == pollutant_id`
    - `sourceTypeID == source_type`
    - `modelYearID == model_year`
- Why it was expensive:
  - The summer matrix has `184,574` rows.
  - Large macro runs call `_query_emission_rate()` at high frequency inside the `links × vehicle types × pollutants` loop.
  - Each lookup used a fresh boolean scan over the full matrix.
- Actual lookup dimensions used today:
  - Fixed `opModeID=300`
  - `pollutantID`
  - `sourceTypeID`
  - `modelYearID`

## 3. Optimization Implemented
- Files changed:
  - `calculators/macro_emission.py`
  - `tests/test_calculators.py`
  - `scripts/utils/benchmark_macro_lookup.py`
- Caching added:
  - `MacroEmissionCalculator` now keeps an in-process season matrix cache keyed by `winter/spring/summer`.
  - Repeated loads of the same season now reuse the same DataFrame instead of rereading the CSV.
- Indexed lookup introduced:
  - A tuple-key dictionary is built for the fixed query path:
    - key: `(pollutant_id, source_type_id, model_year)`
    - value: `em`
  - The lookup is built only from `opModeID == 300`, which matches current query behavior.
  - The lookup is attached to the DataFrame via `matrix.attrs` so synthetic/test matrices can also build it lazily.
- Compatibility preservation:
  - Duplicate keys preserve legacy behavior by keeping the first row encountered, matching `result.iloc[0]`.
  - `_query_emission_rate()` still falls back to the legacy boolean scan if a key is missing from the indexed lookup.
  - Calculator outputs remain unchanged on representative samples.

## 4. Verification
- Tests added/updated:
  - `tests/test_calculators.py::TestMacroEmissionCalculator::test_load_emission_matrix_reuses_cached_dataframe`
  - `tests/test_calculators.py::TestMacroEmissionCalculator::test_query_emission_rate_matches_legacy_scan`
  - `tests/test_calculators.py::TestMacroEmissionCalculator::test_calculate_matches_legacy_lookup_path`
- Commands run:
  - `pytest tests/test_calculators.py`
  - `python scripts/utils/benchmark_macro_lookup.py`
  - `python main.py health`
  - `pytest`
- What passed:
  - `pytest tests/test_calculators.py`: `19 passed`
  - `python main.py health`: all 5 tools healthy
  - `pytest`: `77 passed`

## 5. Performance Check
- Lightweight measurement helper:
  - `scripts/utils/benchmark_macro_lookup.py`
- Command run:
  - `python scripts/utils/benchmark_macro_lookup.py`
- Observed output on the current baseline:
  - `lookup_build_seconds=0.003250`
  - `queries=25`
  - `legacy_scan_seconds=4.101911`
  - `indexed_lookup_seconds=0.000013`
  - `speedup=317289.37x`
  - `checksums_match=True`
- Measurement limitations:
  - This isolates lookup cost, not full-road-network end-to-end latency.
  - The benchmark uses a small representative query set on the real summer matrix, not the full Shanghai road network workflow.
  - Full-run improvements will still depend on other later-phase GIS bottlenecks such as large map payloads and frontend rendering.

## 6. What Was Intentionally Deferred
- Frontend GIS rendering optimization
- Session/history payload size reduction
- Map-data transport/persistence optimization
- Broader macro-emission calculator architecture redesign
- Any API/frontend behavior changes

## 7. Recommended Next Step
- Add a second GIS optimization pass focused on reducing oversized `map_data` transport/persistence costs, since the backend lookup hot path is now substantially cheaper.

## Suggested Next Safe Actions
- Benchmark a representative medium-size macro-emission tool run before and after this change to quantify end-to-end impact beyond isolated lookup timing.
- Profile map payload size and session history growth for large-road-network runs to identify the next highest-ROI GIS bottleneck.
- Keep any future macro-emission optimizations compatibility-first: preserve current result shapes and reuse focused calculator-level tests.
