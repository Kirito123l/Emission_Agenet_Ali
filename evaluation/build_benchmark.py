"""Build a six-dimension parameter-standardization benchmark from YAML mappings."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml


PROJECT_ROOT = Path(__file__).resolve().parents[1]
MAPPINGS_PATH = PROJECT_ROOT / "config" / "unified_mappings.yaml"
OUTPUT_PATH = PROJECT_ROOT / "evaluation" / "benchmarks" / "standardization_benchmark.jsonl"
MIN_CASES_PER_DIMENSION = 50


def load_mappings() -> Dict[str, Any]:
    with MAPPINGS_PATH.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _contains_cjk(text: str) -> bool:
    return any("\u4e00" <= char <= "\u9fff" for char in text)


def _language_tag(text: str) -> str:
    if _contains_cjk(text):
        if any(char.isascii() and char.isalpha() for char in text):
            return "mixed"
        return "zh"
    return "en"


def _coerce_text(value: Any) -> str:
    return str(value or "").strip()


def _medium_variants(base: str) -> List[Tuple[str, str]]:
    cleaned = _coerce_text(base)
    if not cleaned:
        return []

    variants: List[Tuple[str, str]] = [
        (f" {cleaned} ", "trimmed whitespace variant"),
    ]
    if cleaned.lower() != cleaned:
        variants.append((cleaned.lower(), "lowercase variant"))
    if cleaned.upper() != cleaned:
        variants.append((cleaned.upper(), "uppercase variant"))
    titled = cleaned.title()
    if titled != cleaned:
        variants.append((titled, "title-case variant"))
    if " " in cleaned:
        variants.append((cleaned.replace(" ", "  "), "expanded spacing variant"))
        variants.append((cleaned.replace(" ", ""), "collapsed spacing variant"))
        variants.append((cleaned.replace(" ", "_"), "underscore separator variant"))
    if "_" in cleaned:
        variants.append((cleaned.replace("_", " "), "underscore to space variant"))
    if "-" in cleaned:
        variants.append((cleaned.replace("-", " "), "hyphen to space variant"))
        variants.append((cleaned.replace("-", ""), "collapsed hyphen variant"))
    return variants


def _hard_variants(base: str) -> List[Tuple[str, str]]:
    cleaned = _coerce_text(base)
    if len(cleaned) < 4 or _contains_cjk(cleaned):
        return []

    alpha_positions = [idx for idx, char in enumerate(cleaned) if char.isalpha()]
    if len(alpha_positions) < 4:
        return []

    variants: List[Tuple[str, str]] = []
    mid = alpha_positions[len(alpha_positions) // 2]
    variants.append((cleaned[:mid] + cleaned[mid + 1 :], "single-character deletion typo"))

    swap_index = alpha_positions[min(len(alpha_positions) // 2, len(alpha_positions) - 2)]
    if swap_index + 1 < len(cleaned):
        swapped = list(cleaned)
        swapped[swap_index], swapped[swap_index + 1] = swapped[swap_index + 1], swapped[swap_index]
        variants.append(("".join(swapped), "adjacent-character swap typo"))

    duplicate_index = alpha_positions[1]
    variants.append(
        (
            cleaned[: duplicate_index + 1] + cleaned[duplicate_index] + cleaned[duplicate_index + 1 :],
            "duplicated-character typo",
        )
    )
    return variants


def _make_case(
    dimension: str,
    difficulty: str,
    raw_input: str,
    expected_output: Optional[str],
    notes: str = "",
) -> Dict[str, Any]:
    return {
        "dimension": dimension,
        "difficulty": difficulty,
        "raw_input": raw_input,
        "expected_output": expected_output,
        "language": _language_tag(raw_input),
        "notes": notes,
    }


def _dedupe_cases(cases: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    deduped: List[Dict[str, Any]] = []
    for case in cases:
        key = (case["dimension"], case["raw_input"].strip().lower())
        if key in seen:
            continue
        seen.add(key)
        deduped.append(case)
    return deduped


def _top_up_cases(
    dimension: str,
    expected_output: str,
    base_terms: Sequence[str],
    existing_cases: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    cases = list(existing_cases)
    if len(cases) >= MIN_CASES_PER_DIMENSION:
        return cases

    seen = {(case["dimension"], case["raw_input"].strip().lower()) for case in cases}
    for term in base_terms:
        for variant, note in _medium_variants(term) + _hard_variants(term):
            key = (dimension, variant.strip().lower())
            if key in seen:
                continue
            difficulty = "medium" if "variant" in note else "hard"
            cases.append(_make_case(dimension, difficulty, variant, expected_output, note))
            seen.add(key)
            if len(cases) >= MIN_CASES_PER_DIMENSION:
                return cases
    return cases


def _build_cases_for_entries(
    *,
    dimension: str,
    entries: Sequence[Tuple[str, Sequence[str], Optional[str]]],
    hard_cases: Sequence[Tuple[str, Optional[str], str]],
) -> List[Dict[str, Any]]:
    cases: List[Dict[str, Any]] = []
    canonical_terms: List[Tuple[str, str]] = []

    for standard_name, aliases, display_name in entries:
        positive_terms = [_coerce_text(standard_name)]
        if display_name:
            positive_terms.append(_coerce_text(display_name))
        positive_terms.extend(_coerce_text(alias) for alias in aliases if _coerce_text(alias))

        canonical_terms.extend((standard_name, term) for term in positive_terms if term)

        for term in positive_terms:
            cases.append(_make_case(dimension, "easy", term, standard_name, "direct known mapping"))

        for term in positive_terms:
            for variant, note in _medium_variants(term):
                cases.append(_make_case(dimension, "medium", variant, standard_name, note))

        for term in positive_terms:
            for variant, note in _hard_variants(term):
                cases.append(_make_case(dimension, "hard", variant, standard_name, note))

        if display_name and not _contains_cjk(standard_name):
            mixed_variant = f"{display_name} {standard_name}"
            cases.append(_make_case(dimension, "hard", mixed_variant, standard_name, "mixed-language variant"))

    for raw_input, expected_output, notes in hard_cases:
        cases.append(_make_case(dimension, "hard", raw_input, expected_output, notes))

    cases = _dedupe_cases(cases)
    if len(cases) < MIN_CASES_PER_DIMENSION and canonical_terms:
        top_up_terms = [term for _, term in canonical_terms]
        dominant_output = canonical_terms[0][0]
        cases = _top_up_cases(dimension, dominant_output, top_up_terms, cases)
    return cases


def generate_vehicle_cases(mappings: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries = [
        (
            item["standard_name"],
            item.get("aliases", []),
            item.get("display_name_zh"),
        )
        for item in mappings.get("vehicle_types", [])
        if item.get("standard_name")
    ]
    hard_cases = [
        ("小轿车", "Passenger Car", "colloquial variant"),
        ("家用车", "Passenger Car", "colloquial private vehicle"),
        ("公共汽车", "Transit Bus", "common synonym"),
        ("pasenger car", "Passenger Car", "misspelled english input"),
        ("motor cycle", "Motorcycle", "split english compound"),
        ("渣土车", "Refuse Truck", "industry-specific Chinese term"),
        ("卡车", None, "ambiguous truck family"),
        ("半挂", None, "ambiguous articulated truck family"),
        ("电瓶车", None, "outside MOVES vehicle taxonomy"),
        ("公务车", "Passenger Car", "organizational vehicle colloquialism"),
    ]
    return _build_cases_for_entries(dimension="vehicle_type", entries=entries, hard_cases=hard_cases)


def generate_pollutant_cases(mappings: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries = [
        (
            item["standard_name"],
            item.get("aliases", []),
            item.get("display_name_zh"),
        )
        for item in mappings.get("pollutants", [])
        if item.get("standard_name")
    ]
    hard_cases = [
        ("尾气", None, "generic emission term rather than a pollutant"),
        ("碳", "CO2", "extreme shorthand"),
        ("nitrogen oxide", "NOx", "singular english full name"),
        ("pm", None, "ambiguous particulate size class"),
        ("颗粒", None, "ambiguous particulate shorthand"),
        ("一氧化碳气体", "CO", "extended Chinese phrasing"),
        ("二氧化碳排放", "CO2", "task-oriented phrasing"),
        ("noxes", "NOx", "pluralized english typo"),
        ("pm 2 5", "PM2.5", "spaced english shorthand"),
        ("总碳氢", "THC", "truncated Chinese alias"),
    ]
    return _build_cases_for_entries(dimension="pollutant", entries=entries, hard_cases=hard_cases)


def generate_season_cases(mappings: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries = [
        (
            item["standard_name"],
            item.get("aliases", []),
            None,
        )
        for item in mappings.get("seasons", [])
        if item.get("standard_name")
    ]
    hard_cases = [
        ("Jan", "冬季", "english month abbreviation"),
        ("1月", "冬季", "numeric month inference"),
        ("January", "冬季", "english month inference"),
        ("Feb", "冬季", "english month abbreviation"),
        ("2月", "冬季", "numeric month inference"),
        ("Mar", "春季", "english month abbreviation"),
        ("March", "春季", "english month inference"),
        ("4月", "春季", "numeric month inference"),
        ("Apr", "春季", "english month abbreviation"),
        ("May", "春季", "english month inference"),
        ("Jun", "夏季", "english month abbreviation"),
        ("6月", "夏季", "numeric month inference"),
        ("July", "夏季", "english month inference"),
        ("Aug", "夏季", "english month abbreviation"),
        ("8月", "夏季", "numeric month inference"),
        ("Sep", "秋季", "english month abbreviation"),
        ("September", "秋季", "english month inference"),
        ("10月", "秋季", "numeric month inference"),
        ("Oct", "秋季", "english month abbreviation"),
        ("November", "秋季", "english month inference"),
        ("Dec", "冬季", "english month abbreviation"),
        ("12月", "冬季", "numeric month inference"),
        ("暑假", "夏季", "school-calendar colloquial reference"),
        ("开学季", "秋季", "school-calendar colloquial reference"),
        ("寒冬", "冬季", "descriptive seasonal wording"),
        ("梅雨季", None, "unsupported rainy-season concept"),
        ("monsoon", None, "not one of the supported seasons"),
    ]
    return _build_cases_for_entries(dimension="season", entries=entries, hard_cases=hard_cases)


def generate_road_type_cases(mappings: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries: List[Tuple[str, Sequence[str], Optional[str]]] = []
    for standard_name, info in (mappings.get("road_types") or {}).items():
        aliases = info.get("aliases", []) if isinstance(info, dict) else []
        entries.append((standard_name, aliases, None))

    hard_cases = [
        ("高架", "快速路", "colloquial urban expressway reference"),
        ("国道", None, "unsupported national-road category"),
        ("省道", None, "unsupported provincial-road category"),
        ("high way", "高速公路", "split english alias"),
        ("小路", "支路", "colloquial local-road wording"),
        ("主路", "主干道", "common colloquial wording"),
        ("辅路", "次干道", "colloquial secondary-road wording"),
        ("街道", "支路", "generic urban local street wording"),
        ("motor way", "高速公路", "split english motorway spelling"),
        ("urban expwy", "快速路", "compressed english abbreviation"),
    ]
    return _build_cases_for_entries(dimension="road_type", entries=entries, hard_cases=hard_cases)


def generate_meteorology_cases(mappings: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries: List[Tuple[str, Sequence[str], Optional[str]]] = []
    presets = ((mappings.get("meteorology") or {}).get("presets") or {})
    for standard_name, info in presets.items():
        aliases = info.get("aliases", []) if isinstance(info, dict) else []
        entries.append((standard_name, aliases, None))

    hard_cases = [
        ("summer daytime", "urban_summer_day", "expanded english phrasing"),
        ("winter night city", "urban_winter_night", "reordered english phrasing"),
        ("城市夏夜", "urban_summer_night", "compressed Chinese shorthand"),
        ("城市冬夜", "urban_winter_night", "compressed Chinese shorthand"),
        ("微风稳定", "calm_stable", "descriptive Chinese variant"),
        ("大风天", "windy_neutral", "colloquial Chinese weather phrase"),
        ("urban summer day preset", "urban_summer_day", "suffix wording"),
        ("no-wind stable", "calm_stable", "hyphenated english wording"),
        ("stormy", None, "unsupported meteorology preset"),
        ("rainy day", None, "unsupported weather condition"),
    ]
    return _build_cases_for_entries(dimension="meteorology", entries=entries, hard_cases=hard_cases)


def generate_stability_cases(mappings: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries: List[Tuple[str, Sequence[str], Optional[str]]] = []
    for standard_name, info in (mappings.get("stability_classes") or {}).items():
        aliases = info.get("aliases", []) if isinstance(info, dict) else []
        entries.append((standard_name, aliases, None))

    hard_cases = [
        ("Pasquill A class", "VU", "expanded Pasquill wording"),
        ("Pasquill F class", "VS", "expanded Pasquill wording"),
        ("class neutral", "N1", "reordered english wording"),
        ("neutral class c", "N2", "mixed english wording"),
        ("very-unstable", "VU", "hyphenated english wording"),
        ("极不稳定", "VU", "intensified Chinese wording"),
        ("较稳定", "S", "comparative Chinese wording"),
        ("pg class b", "U", "abbreviated Pasquill-Gifford wording"),
        ("class g", None, "unsupported stability class"),
        ("中性偏稳", None, "unsupported nuanced stability wording"),
    ]
    return _build_cases_for_entries(
        dimension="stability_class",
        entries=entries,
        hard_cases=hard_cases,
    )


def build_benchmark() -> List[Dict[str, Any]]:
    mappings = load_mappings()
    all_cases: List[Dict[str, Any]] = []
    all_cases.extend(generate_vehicle_cases(mappings))
    all_cases.extend(generate_pollutant_cases(mappings))
    all_cases.extend(generate_season_cases(mappings))
    all_cases.extend(generate_road_type_cases(mappings))
    all_cases.extend(generate_meteorology_cases(mappings))
    all_cases.extend(generate_stability_cases(mappings))

    deduped = _dedupe_cases(all_cases)
    for index, case in enumerate(deduped, start=1):
        case["id"] = f"{case['dimension']}_{case['difficulty']}_{index:04d}"
    return deduped


def write_benchmark(cases: Sequence[Dict[str, Any]], output_path: Path = OUTPUT_PATH) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")


def summarize_cases(cases: Sequence[Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    by_dimension = Counter(case["dimension"] for case in cases)
    by_difficulty = Counter(case["difficulty"] for case in cases)
    by_dimension_difficulty = Counter(f"{case['dimension']}::{case['difficulty']}" for case in cases)
    return {
        "by_dimension": dict(sorted(by_dimension.items())),
        "by_difficulty": dict(sorted(by_difficulty.items())),
        "by_dimension_difficulty": dict(sorted(by_dimension_difficulty.items())),
    }


def main() -> None:
    cases = build_benchmark()
    write_benchmark(cases)
    summary = summarize_cases(cases)
    print(f"总计生成 {len(cases)} 条标准化 benchmark 用例")
    print(f"输出文件: {OUTPUT_PATH}")
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    dimension_counts = summary["by_dimension"]
    insufficient = [dimension for dimension, count in dimension_counts.items() if count < MIN_CASES_PER_DIMENSION]
    if insufficient:
        raise SystemExit(f"以下维度样本不足 {MIN_CASES_PER_DIMENSION} 条: {', '.join(insufficient)}")


if __name__ == "__main__":
    main()
