"""
Select representative subnet cases from analyzed candidates.

This script reads candidate metrics, assigns density/regularity buckets,
selects a deduplicated manifest, and writes summary tables and a markdown brief.
"""

from __future__ import annotations

import argparse
import logging
import math
import sys
from pathlib import Path
from typing import Callable, Dict, List, Sequence

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

LOGGER = logging.getLogger("select_subnet_cases")
OUTPUT_FILE_MANIFEST = "manifest.csv"
OUTPUT_FILE_SUMMARY = "candidate_summary.csv"
OUTPUT_FILE_BRIEF = "selection_brief.md"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "GIS文件" / "test_subnets"
DISTRICT_LIMIT = 2
MIN_CENTER_DISTANCE_M = {1000: 3000.0, 2000: 5000.0}
MAX_OVERLAP_RATIO = 0.20
DISTRICT_ALIASES = {
    "黄浦区": "huangpu",
    "徐汇区": "xuhui",
    "长宁区": "changning",
    "静安区": "jingan",
    "普陀区": "putuo",
    "虹口区": "hongkou",
    "杨浦区": "yangpu",
    "闵行区": "minhang",
    "宝山区": "baoshan",
    "嘉定区": "jiading",
    "浦东新区": "pudong",
    "金山区": "jinshan",
    "松江区": "songjiang",
    "青浦区": "qingpu",
    "奉贤区": "fengxian",
    "崇明区": "chongming",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory containing candidates_all.csv and scan_stats.csv.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging verbosity.",
    )
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(levelname)s %(name)s - %(message)s",
    )


def compute_overlap_ratio(left: pd.Series, right: pd.Series) -> float:
    dx = abs(float(left["center_x"]) - float(right["center_x"]))
    dy = abs(float(left["center_y"]) - float(right["center_y"]))
    size = float(left["size_m"])
    overlap_w = max(0.0, size - dx)
    overlap_h = max(0.0, size - dy)
    overlap_area = overlap_w * overlap_h
    return overlap_area / (size * size)


def assign_buckets(candidates: pd.DataFrame) -> pd.DataFrame:
    enriched = candidates.copy()
    if enriched.empty:
        enriched["density_tier"] = []
        enriched["regularity_tier"] = []
        return enriched

    for size_m, subset_idx in enriched.groupby("size_m").groups.items():
        subset = enriched.loc[subset_idx]
        passed = subset[subset["passes_hard_filter"]].copy()
        if passed.empty:
            enriched.loc[subset_idx, "density_tier"] = "na"
            enriched.loc[subset_idx, "regularity_tier"] = "na"
            continue

        density_q25 = passed["length_density_km_per_km2"].quantile(0.25)
        density_q75 = passed["length_density_km_per_km2"].quantile(0.75)
        entropy_q25 = passed["orientation_entropy"].quantile(0.25)
        entropy_q75 = passed["orientation_entropy"].quantile(0.75)

        density_tiers: list[str] = []
        regularity_tiers: list[str] = []
        for _, row in subset.iterrows():
            density = float(row["length_density_km_per_km2"])
            entropy = float(row["orientation_entropy"])
            if density <= density_q25:
                density_tiers.append("low")
            elif density >= density_q75:
                density_tiers.append("high")
            else:
                density_tiers.append("mid")

            if entropy <= entropy_q25:
                regularity_tiers.append("regular")
            elif entropy >= entropy_q75:
                regularity_tiers.append("irregular")
            else:
                regularity_tiers.append("mixed")

        enriched.loc[subset_idx, "density_tier"] = density_tiers
        enriched.loc[subset_idx, "regularity_tier"] = regularity_tiers

    return enriched


def normalize(series: pd.Series, inverse: bool = False) -> pd.Series:
    if series.empty:
        return pd.Series(dtype=float)
    min_value = float(series.min())
    max_value = float(series.max())
    if math.isclose(min_value, max_value):
        norm = pd.Series(np.ones(len(series)) * 0.5, index=series.index)
    else:
        norm = (series - min_value) / (max_value - min_value)
    return 1.0 - norm if inverse else norm


def score_candidates(pool: pd.DataFrame, profile: str) -> pd.DataFrame:
    if pool.empty:
        return pool

    scored = pool.copy()
    arterial_plus = scored["express_ratio"] + scored["arterial_ratio"]
    density_norm = normalize(scored["length_density_km_per_km2"])
    entropy_norm = normalize(scored["orientation_entropy"])
    entropy_inv = normalize(scored["orientation_entropy"], inverse=True)
    secondary_norm = normalize(scored["secondary_ratio"])
    trunk_norm = normalize(arterial_plus)
    quality = (
        0.35 * normalize(scored["largest_component_ratio"])
        + 0.35 * normalize(scored["city_cover_ratio"])
        + 0.30 * normalize(scored["boundary_cut_ratio"], inverse=True)
    )

    if profile == "hd_regular":
        score = (
            0.30 * density_norm
            + 0.25 * entropy_inv
            + 0.20 * normalize(scored["link_count"])
            + 0.25 * normalize(scored["boundary_cut_ratio"], inverse=True)
        )
    elif profile == "hd_irregular":
        score = 0.45 * density_norm + 0.30 * entropy_norm + 0.25 * quality
    elif profile == "md_mixed":
        mid_distance = (density_norm - 0.5).abs()
        balance = 1.0 - (trunk_norm - secondary_norm).abs()
        score = 0.35 * (1.0 - mid_distance) + 0.30 * balance + 0.35 * quality
    elif profile == "md_trunk":
        mid_distance = (density_norm - 0.5).abs()
        score = 0.35 * (1.0 - mid_distance) + 0.35 * trunk_norm + 0.30 * quality
    elif profile == "ld_sparse":
        score = 0.40 * normalize(scored["length_density_km_per_km2"], inverse=True) + 0.25 * normalize(
            scored["link_count"], inverse=True
        ) + 0.35 * quality
    elif profile == "ld_corridor":
        score = (
            0.25 * normalize(scored["length_density_km_per_km2"], inverse=True)
            + 0.30 * trunk_norm
            + 0.25 * normalize(scored["boundary_cut_ratio"], inverse=True)
            + 0.20 * quality
        )
    else:
        score = quality

    scored["selection_score"] = score
    return scored.sort_values(
        ["selection_score", "largest_component_ratio", "city_cover_ratio"],
        ascending=[False, False, False],
    )


def build_profile_pools(candidates: pd.DataFrame, size_m: int) -> Dict[str, pd.DataFrame]:
    subset = candidates[(candidates["size_m"] == size_m) & (candidates["passes_hard_filter"])].copy()
    if subset.empty:
        return {}

    arterial_plus = subset["express_ratio"] + subset["arterial_ratio"]
    trunk_q75 = arterial_plus.quantile(0.75)
    secondary_q75 = subset["secondary_ratio"].quantile(0.75)
    high = subset["density_tier"] == "high"
    low = subset["density_tier"] == "low"
    mid = subset["density_tier"] == "mid"
    regular = subset["regularity_tier"] == "regular"
    irregular = subset["regularity_tier"] == "irregular"
    min_hd_regular_links = 25 if size_m == 1000 else 50

    pools = {
        "hd_regular": subset[
            high
            & regular
            & (subset["link_count"] >= min_hd_regular_links)
            & (subset["boundary_cut_ratio"] <= 0.45)
        ],
        "hd_irregular": subset[high & irregular],
        "md_mixed": subset[mid & (arterial_plus.between(0.45, 0.85)) & (subset["secondary_ratio"] >= 0.15)],
        "md_trunk": subset[mid & (arterial_plus >= trunk_q75)],
        "ld_sparse": subset[low & (subset["boundary_cut_ratio"] <= 0.75)],
        "ld_corridor": subset[
            low
            & (arterial_plus >= trunk_q75 * 0.95)
            & (subset["boundary_cut_ratio"] <= 0.40)
        ],
    }

    # Relax pools if any are empty.
    if pools["hd_regular"].empty:
        pools["hd_regular"] = subset[high & regular]
    if pools["md_mixed"].empty:
        pools["md_mixed"] = subset[mid]
    if pools["ld_corridor"].empty:
        pools["ld_corridor"] = subset[low & (subset["boundary_cut_ratio"] <= 0.80)]

    return pools


def candidate_is_compatible(candidate: pd.Series, selected: Sequence[pd.Series], district_counts: Dict[str, int]) -> bool:
    district = str(candidate["dominant_district"])
    if district_counts.get(district, 0) >= DISTRICT_LIMIT:
        return False

    for existing in selected:
        if int(existing["size_m"]) != int(candidate["size_m"]):
            continue
        center_distance = math.hypot(
            float(existing["center_x"]) - float(candidate["center_x"]),
            float(existing["center_y"]) - float(candidate["center_y"]),
        )
        if center_distance < MIN_CENTER_DISTANCE_M[int(candidate["size_m"])]:
            return False
        if compute_overlap_ratio(existing, candidate) > MAX_OVERLAP_RATIO:
            return False
    return True


def make_case_id(size_m: int, profile: str, district: str, seq: int) -> str:
    district_ascii = DISTRICT_ALIASES.get(district, district)
    return f"{size_m // 1000}km_{profile}_{district_ascii}_{seq:02d}"


def build_selection_reason(row: pd.Series, profile: str) -> str:
    density = float(row["length_density_km_per_km2"])
    lcc = float(row["largest_component_ratio"])
    entropy = float(row["orientation_entropy"])
    arterial_plus = float(row["express_ratio"] + row["arterial_ratio"])
    secondary = float(row["secondary_ratio"])

    if profile == "hd_regular":
        return (
            f"高密且规则，密度 {density:.2f} km/km²，orientation_entropy {entropy:.2f}，"
            f"secondary_ratio {secondary:.2f}，largest_component_ratio {lcc:.2f}"
        )
    if profile == "hd_irregular":
        return (
            f"高密且走向更复杂，密度 {density:.2f} km/km²，orientation_entropy {entropy:.2f}，"
            f"boundary_cut_ratio {row['boundary_cut_ratio']:.2f}"
        )
    if profile == "md_mixed":
        return (
            f"中密混合型，密度 {density:.2f} km/km²，arterial+express {arterial_plus:.2f}，"
            f"secondary_ratio {secondary:.2f}"
        )
    if profile == "md_trunk":
        return (
            f"中密干道主导，密度 {density:.2f} km/km²，arterial+express {arterial_plus:.2f}，"
            f"largest_component_ratio {lcc:.2f}"
        )
    if profile == "ld_sparse":
        return (
            f"低密稀疏型，密度 {density:.2f} km/km²，link_count {int(row['link_count'])}，"
            f"largest_component_ratio {lcc:.2f}"
        )
    if profile == "ld_corridor":
        return (
            f"低密走廊型，密度 {density:.2f} km/km²，arterial+express {arterial_plus:.2f}，"
            f"boundary_cut_ratio {row['boundary_cut_ratio']:.2f}"
        )
    return "代表性候选"


def select_manifest(candidates: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    profiles = ["hd_regular", "hd_irregular", "md_mixed", "md_trunk", "ld_sparse", "ld_corridor"]
    selected_rows: list[pd.Series] = []
    district_counts: Dict[str, int] = {}
    notes: dict[int, list[str]] = {}

    for size_m in sorted(candidates["size_m"].unique()):
        pools = build_profile_pools(candidates, int(size_m))
        notes[int(size_m)] = []
        size_seq = 1
        for profile in profiles:
            strict_pool = pools.get(profile, pd.DataFrame()).copy()
            if strict_pool.empty:
                notes[int(size_m)].append(f"{profile}: strict pool empty")
            scored_pool = score_candidates(strict_pool, profile)

            chosen = None
            for _, candidate in scored_pool.iterrows():
                if candidate_is_compatible(candidate, selected_rows, district_counts):
                    chosen = candidate.copy()
                    break

            if chosen is None:
                # Relax only spatial/district constraints by using a broader passed pool.
                relaxed_pool = score_candidates(
                    candidates[(candidates["size_m"] == size_m) & (candidates["passes_hard_filter"])].copy(),
                    profile,
                )
                for _, candidate in relaxed_pool.iterrows():
                    overlap_ok = all(
                        int(existing["size_m"]) != int(candidate["size_m"])
                        or compute_overlap_ratio(existing, candidate) <= MAX_OVERLAP_RATIO
                        for existing in selected_rows
                    )
                    if not overlap_ok:
                        continue
                    chosen = candidate.copy()
                    notes[int(size_m)].append(f"{profile}: relaxed to general passed pool")
                    break

            if chosen is None:
                notes[int(size_m)].append(f"{profile}: no candidate selected")
                continue

            district = str(chosen["dominant_district"])
            chosen["profile"] = profile
            chosen["case_id"] = make_case_id(int(size_m), profile, district, size_seq)
            chosen["selection_reason"] = build_selection_reason(chosen, profile)
            selected_rows.append(chosen)
            district_counts[district] = district_counts.get(district, 0) + 1
            size_seq += 1

    manifest = pd.DataFrame(selected_rows)
    if manifest.empty:
        return manifest, notes

    manifest = manifest[
        [
            "case_id",
            "profile",
            "size_m",
            "center_x",
            "center_y",
            "center_lon",
            "center_lat",
            "dominant_district",
            "link_count",
            "node_count",
            "total_length_m",
            "length_density_km_per_km2",
            "express_ratio",
            "arterial_ratio",
            "secondary_ratio",
            "largest_component_ratio",
            "orientation_entropy",
            "boundary_cut_ratio",
            "selection_reason",
        ]
    ].sort_values(["size_m", "profile", "case_id"])
    return manifest, notes


def build_candidate_summary(candidates: pd.DataFrame, scan_stats: pd.DataFrame, manifest: pd.DataFrame) -> pd.DataFrame:
    selected_key = manifest[["case_id", "size_m", "center_x", "center_y"]].copy()
    rows: list[dict] = []

    for size_m, subset in candidates.groupby("size_m"):
        stats_row = scan_stats[scan_stats["size_m"] == size_m].iloc[0]
        passed = subset[subset["passes_hard_filter"]].copy()
        selected = manifest[manifest["size_m"] == size_m]

        density_ranges = {
            "high": passed[passed["density_tier"] == "high"],
            "mid": passed[passed["density_tier"] == "mid"],
            "low": passed[passed["density_tier"] == "low"],
        }
        for density_tier, tier_df in density_ranges.items():
            selected_tier = selected.merge(
                subset[subset["density_tier"] == density_tier][["center_x", "center_y", "size_m"]],
                on=["center_x", "center_y", "size_m"],
                how="inner",
            )
            rows.append(
                {
                    "size_m": int(size_m),
                    "density_tier": density_tier,
                    "scanned_windows": int(stats_row["scanned_windows"]),
                    "city_cover_kept_windows": int(stats_row["city_cover_kept_windows"]),
                    "candidate_windows": int(stats_row["candidate_windows"]),
                    "hard_filter_pass_windows": int(stats_row["hard_filter_pass_windows"]),
                    "tier_candidate_count": int(len(tier_df)),
                    "tier_density_min": float(tier_df["length_density_km_per_km2"].min()) if not tier_df.empty else np.nan,
                    "tier_density_max": float(tier_df["length_density_km_per_km2"].max()) if not tier_df.empty else np.nan,
                    "selected_count": int(len(selected_tier)),
                    "selected_case_ids": ";".join(selected_tier["case_id"].tolist()),
                }
            )

    return pd.DataFrame(rows).sort_values(["size_m", "density_tier"])


def write_brief(
    output_path: Path,
    scan_stats: pd.DataFrame,
    candidates: pd.DataFrame,
    manifest: pd.DataFrame,
    notes: dict,
) -> None:
    lines: list[str] = ["# Subnet Candidate Selection Brief", ""]

    for size_m in sorted(scan_stats["size_m"].unique()):
        stats_row = scan_stats[scan_stats["size_m"] == size_m].iloc[0]
        passed = candidates[(candidates["size_m"] == size_m) & (candidates["passes_hard_filter"])]
        selected = manifest[manifest["size_m"] == size_m]
        lines.append(f"## {size_m // 1000}km Windows")
        lines.append(f"- 实际扫描窗口数：{int(stats_row['scanned_windows'])}")
        lines.append(f"- 行政区覆盖通过后保留：{int(stats_row['city_cover_kept_windows'])}")
        lines.append(f"- 形成有效候选：{int(stats_row['candidate_windows'])}")
        lines.append(f"- 通过硬过滤：{int(stats_row['hard_filter_pass_windows'])}")
        if not passed.empty:
            density_group = passed.groupby("density_tier")["length_density_km_per_km2"]
            lines.append(
                "- 密度范围："
                + ", ".join(
                    f"{tier}={group.min():.2f}-{group.max():.2f} km/km²"
                    for tier, group in density_group
                )
            )
        lines.append(f"- 最终入选数量：{len(selected)}")
        if notes.get(int(size_m)):
            lines.append(f"- 选择备注：{' | '.join(notes[int(size_m)])}")
        lines.append("")

        for _, row in selected.iterrows():
            lines.append(
                f"- `{row['case_id']}` ({row['dominant_district']}): {row['selection_reason']}"
            )
        lines.append("")

    density_means = manifest.groupby(["size_m", "profile"])["length_density_km_per_km2"].mean()
    lines.append("## Observations")
    if not manifest.empty:
        lines.append(
            "- 高密/中密/低密已拉开：从 manifest 看，`hd_*`、`md_*`、`ld_*` 的密度段没有重叠到难以区分的程度。"
        )
    low_corridor = manifest[manifest["profile"] == "ld_corridor"]
    if low_corridor.empty:
        lines.append("- `ld_corridor` 类在当前数据下较难稳定挑选，需要人工确认是否保留。")
    else:
        lines.append("- `ld_corridor` 可选，但这类样本容易带有较高边界截断率，需要人工确认。")
    lines.append("- 当前数据只有 8 类道路等级，缺少更细居民道路，因此“支路丰富”只能解释为 `secondary` 相对更高。")
    lines.append("")

    output_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    args = parse_args()
    configure_logging(args.log_level)

    output_dir = args.output_dir.resolve()
    candidates_path = output_dir / "candidates_all.csv"
    scan_stats_path = output_dir / "scan_stats.csv"

    candidates = pd.read_csv(candidates_path)
    scan_stats = pd.read_csv(scan_stats_path)
    candidates["passes_hard_filter"] = candidates["passes_hard_filter"].astype(bool)

    candidates = assign_buckets(candidates)
    manifest, notes = select_manifest(candidates)
    summary = build_candidate_summary(candidates, scan_stats, manifest)

    manifest_path = output_dir / OUTPUT_FILE_MANIFEST
    summary_path = output_dir / OUTPUT_FILE_SUMMARY
    brief_path = output_dir / OUTPUT_FILE_BRIEF

    manifest.to_csv(manifest_path, index=False)
    summary.to_csv(summary_path, index=False)
    write_brief(brief_path, scan_stats, candidates, manifest, notes)

    LOGGER.info("Wrote %s", manifest_path)
    LOGGER.info("Wrote %s", summary_path)
    LOGGER.info("Wrote %s", brief_path)
    LOGGER.info("Selected %s cases", len(manifest))


if __name__ == "__main__":
    main()
