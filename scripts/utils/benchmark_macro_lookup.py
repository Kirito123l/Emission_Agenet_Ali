"""Benchmark macro-emission lookup and calculate() performance on real matrix data."""

from __future__ import annotations

import argparse
import sys
from time import perf_counter
from pathlib import Path
from typing import Callable, Dict, List, Tuple

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from calculators.macro_emission import MacroEmissionCalculator


Query = Tuple[int, int, int]


def build_queries(calc: MacroEmissionCalculator, limit: int, repeats: int) -> List[Query]:
    """Use real matrix keys so the benchmark reflects actual lookup traffic."""
    matrix = calc._load_emission_matrix("夏季")
    rows = (
        matrix.loc[
            matrix[calc.COL_OPMODE] == calc.LOOKUP_OPMODE,
            [calc.COL_SOURCE_TYPE, calc.COL_POLLUTANT, calc.COL_MODEL_YEAR],
        ]
        .drop_duplicates()
        .head(limit)
    )
    base_queries = [
        (int(source_type), int(pollutant_id), int(model_year))
        for source_type, pollutant_id, model_year in rows.itertuples(index=False, name=None)
    ]
    return base_queries * repeats


def build_links(calc: MacroEmissionCalculator, count: int) -> List[Dict]:
    """Build deterministic representative links for end-to-end macro benchmarking."""
    vehicle_names = list(calc.VEHICLE_TO_SOURCE_TYPE.keys())
    links: List[Dict] = []
    for idx in range(count):
        link = {
            "link_id": f"benchmark_link_{idx + 1}",
            "link_length_km": round(0.4 + ((idx % 9) * 0.18), 3),
            "traffic_flow_vph": 500 + (idx % 7) * 175,
            "avg_speed_kph": 25 + (idx % 8) * 6,
        }

        if idx % 3 == 0:
            base = idx % len(vehicle_names)
            link["fleet_mix"] = {
                vehicle_names[base]: 55.0,
                vehicle_names[(base + 1) % len(vehicle_names)]: 30.0,
                vehicle_names[(base + 2) % len(vehicle_names)]: 15.0,
            }

        links.append(link)

    return links


def measure(
    calc: MacroEmissionCalculator,
    queries: List[Query],
    fn: Callable[[object, int, int, int], float],
) -> Tuple[float, float]:
    """Return elapsed seconds and a checksum to prevent the loop being optimized away."""
    matrix = calc._load_emission_matrix("夏季")
    start = perf_counter()
    checksum = 0.0
    for source_type, pollutant_id, model_year in queries:
        checksum += fn(matrix, source_type, pollutant_id, model_year)
    return perf_counter() - start, checksum


def measure_calculate(
    calc: MacroEmissionCalculator,
    links_data: List[Dict],
    pollutants: List[str],
    *,
    legacy_scan: bool = False,
    cold_cache: bool = False,
) -> Tuple[float, Dict]:
    """Measure the real calculate() path, optionally forcing legacy lookup behavior."""
    if cold_cache:
        calc.clear_matrix_cache()

    original_query = None
    if legacy_scan:
        original_query = calc._query_emission_rate
        calc._query_emission_rate = calc._query_emission_rate_scan

    try:
        start = perf_counter()
        result = calc.calculate(
            links_data=links_data,
            pollutants=pollutants,
            model_year=2025,
            season="夏季",
        )
        elapsed = perf_counter() - start
    finally:
        if original_query is not None:
            calc._query_emission_rate = original_query

    return elapsed, result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=3, help="Unique query keys to sample before repeating")
    parser.add_argument("--repeats", type=int, default=3, help="How many times to repeat the sampled keys")
    parser.add_argument("--links", type=int, default=8, help="Representative links to use in the calculate() benchmark")
    args = parser.parse_args()

    calc = MacroEmissionCalculator()
    calc.clear_matrix_cache()
    matrix = calc._load_emission_matrix("夏季")

    matrix.attrs.pop("macro_emission_rate_lookup", None)
    lookup_build_start = perf_counter()
    calc._get_rate_lookup(matrix)
    lookup_build_seconds = perf_counter() - lookup_build_start

    queries = build_queries(calc, limit=args.limit, repeats=args.repeats)
    legacy_seconds, legacy_checksum = measure(calc, queries, calc._query_emission_rate_scan)
    indexed_seconds, indexed_checksum = measure(calc, queries, calc._query_emission_rate)

    links_data = build_links(calc, args.links)
    pollutants = ["CO2", "NOx"]
    optimized_cold_seconds, optimized_cold_result = measure_calculate(
        MacroEmissionCalculator(), links_data, pollutants, cold_cache=True
    )
    optimized_warm_seconds, optimized_warm_result = measure_calculate(
        MacroEmissionCalculator(), links_data, pollutants
    )
    legacy_warm_seconds, legacy_warm_result = measure_calculate(
        MacroEmissionCalculator(), links_data, pollutants, legacy_scan=True
    )

    print(f"lookup_build_seconds={lookup_build_seconds:.6f}")
    print(f"queries={len(queries)}")
    print(f"legacy_scan_seconds={legacy_seconds:.6f}")
    print(f"indexed_lookup_seconds={indexed_seconds:.6f}")
    print(f"speedup={legacy_seconds / indexed_seconds:.2f}x")
    print(f"checksums_match={abs(legacy_checksum - indexed_checksum) < 1e-9}")
    print(f"links={len(links_data)}")
    print(f"calculate_optimized_cold_seconds={optimized_cold_seconds:.6f}")
    print(f"calculate_optimized_warm_seconds={optimized_warm_seconds:.6f}")
    print(f"calculate_legacy_warm_seconds={legacy_warm_seconds:.6f}")
    print(f"calculate_speedup={legacy_warm_seconds / optimized_warm_seconds:.2f}x")
    print(f"calculate_results_match={optimized_warm_result == legacy_warm_result == optimized_cold_result}")


if __name__ == "__main__":
    main()
