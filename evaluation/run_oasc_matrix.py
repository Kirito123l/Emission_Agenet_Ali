from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
DEFAULT_SAMPLES = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
DEFAULT_RESULTS = PROJECT_ROOT / "evaluation" / "results"

GROUP_CONFIGS: List[Dict[str, Any]] = [
    {
        "name": "A",
        "desc": "Phase 0 baseline",
        "env": {
            "ENABLE_AO_AWARE_MEMORY": "false",
            "ENABLE_SESSION_STATE_BLOCK": "false",
            "ENABLE_AO_CLASSIFIER_RULE_LAYER": "false",
            "ENABLE_AO_CLASSIFIER_LLM_LAYER": "false",
            "ENABLE_AO_BLOCK_INJECTION": "false",
            "ENABLE_AO_PERSISTENT_FACTS": "false",
            "ENABLE_GOVERNED_ROUTER": "false",
            "ENABLE_CLARIFICATION_CONTRACT": "false",
        },
    },
    {
        "name": "B",
        "desc": "Phase 1 regression",
        "env": {
            "ENABLE_AO_AWARE_MEMORY": "false",
            "ENABLE_SESSION_STATE_BLOCK": "true",
            "ENABLE_AO_CLASSIFIER_RULE_LAYER": "false",
            "ENABLE_AO_CLASSIFIER_LLM_LAYER": "false",
            "ENABLE_AO_BLOCK_INJECTION": "false",
            "ENABLE_AO_PERSISTENT_FACTS": "false",
            "ENABLE_GOVERNED_ROUTER": "false",
            "ENABLE_CLARIFICATION_CONTRACT": "false",
        },
    },
    {
        "name": "C",
        "desc": "Rule-only",
        "env": {
            "ENABLE_AO_AWARE_MEMORY": "true",
            "ENABLE_SESSION_STATE_BLOCK": "false",
            "ENABLE_AO_CLASSIFIER_RULE_LAYER": "true",
            "ENABLE_AO_CLASSIFIER_LLM_LAYER": "false",
            "ENABLE_AO_BLOCK_INJECTION": "true",
            "ENABLE_AO_PERSISTENT_FACTS": "true",
            "ENABLE_GOVERNED_ROUTER": "true",
            "ENABLE_CLARIFICATION_CONTRACT": "true",
            "ENABLE_CONTRACT_SPLIT": "true",
        },
    },
    {
        "name": "D",
        "desc": "LLM-only",
        "env": {
            "ENABLE_AO_AWARE_MEMORY": "true",
            "ENABLE_SESSION_STATE_BLOCK": "false",
            "ENABLE_AO_CLASSIFIER_RULE_LAYER": "false",
            "ENABLE_AO_CLASSIFIER_LLM_LAYER": "true",
            "ENABLE_AO_BLOCK_INJECTION": "true",
            "ENABLE_AO_PERSISTENT_FACTS": "true",
            "ENABLE_GOVERNED_ROUTER": "true",
            "ENABLE_CLARIFICATION_CONTRACT": "true",
            "ENABLE_CONTRACT_SPLIT": "true",
        },
    },
    {
        "name": "E",
        "desc": "Hybrid",
        "env": {
            "ENABLE_AO_AWARE_MEMORY": "true",
            "ENABLE_SESSION_STATE_BLOCK": "false",
            "ENABLE_AO_CLASSIFIER_RULE_LAYER": "true",
            "ENABLE_AO_CLASSIFIER_LLM_LAYER": "true",
            "ENABLE_AO_BLOCK_INJECTION": "true",
            "ENABLE_AO_PERSISTENT_FACTS": "true",
            "ENABLE_GOVERNED_ROUTER": "true",
            "ENABLE_CLARIFICATION_CONTRACT": "true",
            "ENABLE_CONTRACT_SPLIT": "true",
        },
    },
    {
        "name": "F",
        "desc": "Hybrid without persistent facts",
        "env": {
            "ENABLE_AO_AWARE_MEMORY": "true",
            "ENABLE_SESSION_STATE_BLOCK": "false",
            "ENABLE_AO_CLASSIFIER_RULE_LAYER": "true",
            "ENABLE_AO_CLASSIFIER_LLM_LAYER": "true",
            "ENABLE_AO_BLOCK_INJECTION": "true",
            "ENABLE_AO_PERSISTENT_FACTS": "false",
            "ENABLE_GOVERNED_ROUTER": "true",
            "ENABLE_CLARIFICATION_CONTRACT": "true",
            "ENABLE_CONTRACT_SPLIT": "true",
        },
    },
    {
        "name": "G",
        "desc": "Hybrid without clarification contract",
        "env": {
            "ENABLE_AO_AWARE_MEMORY": "true",
            "ENABLE_SESSION_STATE_BLOCK": "false",
            "ENABLE_AO_CLASSIFIER_RULE_LAYER": "true",
            "ENABLE_AO_CLASSIFIER_LLM_LAYER": "true",
            "ENABLE_AO_BLOCK_INJECTION": "true",
            "ENABLE_AO_PERSISTENT_FACTS": "true",
            "ENABLE_GOVERNED_ROUTER": "true",
            "ENABLE_CLARIFICATION_CONTRACT": "false",
        },
    },
]


def _resolve_groups(group_names: str) -> List[Dict[str, Any]]:
    requested = [item.strip().upper() for item in str(group_names or "").split(",") if item.strip()]
    if not requested:
        requested = [item["name"] for item in GROUP_CONFIGS]
    lookup = {item["name"]: item for item in GROUP_CONFIGS}
    missing = [name for name in requested if name not in lookup]
    if missing:
        raise ValueError(f"Unknown groups: {', '.join(missing)}")
    return [lookup[name] for name in requested]


def _write_rerun_health(output_path: Path, content: str) -> None:
    output_path.write_text(content, encoding="utf-8")


def _clear_eval_session_history() -> None:
    history_dir = PROJECT_ROOT / "data" / "sessions" / "history"
    if not history_dir.exists():
        return
    for path in history_dir.glob("eval_*.json"):
        path.unlink(missing_ok=True)
    for path in history_dir.glob("eval_naive_*.json"):
        path.unlink(missing_ok=True)


def _run_group(
    group: Dict[str, Any],
    samples_path: Path,
    output_dir: Path,
    *,
    parallel: int,
    qps_limit: float,
    smoke: bool,
    cache_enabled: bool,
    filter_categories: Optional[str] = None,
) -> Dict[str, Any]:
    env = os.environ.copy()
    env.update(group["env"])
    env["PYTHONUNBUFFERED"] = "1"
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "evaluation" / "eval_end2end.py"),
        "--samples",
        str(samples_path),
        "--output-dir",
        str(output_dir),
        "--mode",
        "router",
        "--parallel",
        str(parallel),
        "--qps-limit",
        str(qps_limit),
    ]
    if smoke:
        cmd.append("--smoke")
    if filter_categories:
        cmd.extend(["--filter-categories", str(filter_categories)])
    cmd.append("--cache" if cache_enabled else "--no-cache")
    subprocess.run(cmd, cwd=str(PROJECT_ROOT), env=env, check=True)
    metrics_path = output_dir / "end2end_metrics.json"
    return json.loads(metrics_path.read_text(encoding="utf-8"))


def run_matrix(
    *,
    samples_path: Path,
    results_root: Path,
    preflight_count: int = 5,
    groups: str = "A,B,C,D,E,F",
    parallel: int = 8,
    qps_limit: float = 15.0,
    smoke: bool = False,
    cache_enabled: bool = True,
    output_prefix: str = "end2end_full_v5_oasc",
    filter_categories: Optional[str] = None,
) -> Dict[str, Any]:
    from evaluation.run_health import run_preflight

    rerun_health_path = PROJECT_ROOT / "PHASE1_5_RERUN_HEALTH.md"
    preflight_dir = results_root / "end2end_preflight_v5_oasc"
    preflight = run_preflight(samples_path=samples_path, output_dir=preflight_dir, count=preflight_count)
    if not preflight["all_infrastructure_ok"] or preflight["run_status"] != "completed":
        _write_rerun_health(
            rerun_health_path,
            "# Phase 1.5 Rerun Health\n\n"
            "Preflight failed.\n\n"
            f"- run_status: `{preflight['run_status']}`\n"
            f"- data_integrity: `{preflight['data_integrity']}`\n"
            f"- infrastructure_health: `{json.dumps(preflight['infrastructure_health'], ensure_ascii=False)}`\n",
        )
        raise RuntimeError("Preflight failed; benchmark matrix aborted.")
    _clear_eval_session_history()

    selected_groups = _resolve_groups(groups)
    results: Dict[str, Any] = {"preflight": preflight, "groups": {}, "selected_groups": [g["name"] for g in selected_groups]}
    for index, group in enumerate(selected_groups):
        group_name = group["name"]
        output_dir = results_root / f"{output_prefix}_{group_name}"
        _clear_eval_session_history()
        attempts = 0
        while True:
            attempts += 1
            metrics = _run_group(
                group,
                samples_path,
                output_dir,
                parallel=parallel,
                qps_limit=qps_limit,
                smoke=smoke,
                cache_enabled=cache_enabled,
                filter_categories=filter_categories,
            )
            results["groups"][group_name] = metrics
            run_status = str(metrics.get("run_status") or "completed")
            if run_status == "aborted_billing":
                _write_rerun_health(
                    rerun_health_path,
                    "# Phase 1.5 Rerun Health\n\n"
                    f"Benchmark aborted in group `{group_name}` due to billing failure.\n\n"
                    f"- output_dir: `{output_dir}`\n"
                    f"- run_status: `{run_status}`\n"
                    f"- data_integrity: `{metrics.get('data_integrity')}`\n",
                )
                raise RuntimeError(f"Benchmark aborted in group {group_name} due to billing failure.")
            if run_status == "aborted_network":
                if attempts >= 2:
                    _write_rerun_health(
                        rerun_health_path,
                        "# Phase 1.5 Rerun Health\n\n"
                        f"Benchmark aborted in group `{group_name}` due to repeated network failure.\n\n"
                        f"- output_dir: `{output_dir}`\n"
                        f"- run_status: `{run_status}`\n",
                    )
                    raise RuntimeError(f"Benchmark aborted in group {group_name} due to repeated network failure.")
                time.sleep(300)
                continue
            break

        if index < len(selected_groups) - 1:
            time.sleep(60)

    if rerun_health_path.exists():
        rerun_health_path.unlink()
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Run OASC benchmark matrix serially.")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS)
    parser.add_argument("--preflight-count", type=int, default=5)
    parser.add_argument("--groups", default="A,B,C,D,E,F,G")
    parser.add_argument("--parallel", type=int, default=8)
    parser.add_argument("--qps-limit", type=float, default=15.0)
    parser.add_argument("--smoke", action="store_true")
    parser.add_argument("--cache", dest="cache_enabled", action="store_true", default=True)
    parser.add_argument("--no-cache", dest="cache_enabled", action="store_false")
    parser.add_argument("--output-prefix", default="end2end_full_v5_oasc")
    parser.add_argument("--filter-categories", default="")
    args = parser.parse_args()

    summary = run_matrix(
        samples_path=args.samples,
        results_root=args.results_root,
        preflight_count=args.preflight_count,
        groups=args.groups,
        parallel=args.parallel,
        qps_limit=args.qps_limit,
        smoke=args.smoke,
        cache_enabled=args.cache_enabled,
        output_prefix=args.output_prefix,
        filter_categories=args.filter_categories or None,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
