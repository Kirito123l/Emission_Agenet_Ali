"""Run Phase 1.5 OASC benchmark matrix with infrastructure health gates."""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.utils import load_jsonl, write_jsonl


END2END_SCRIPT = PROJECT_ROOT / "evaluation" / "eval_end2end.py"
DEFAULT_SAMPLES = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
RESULTS_ROOT = PROJECT_ROOT / "evaluation" / "results"
REPORT_PATH = PROJECT_ROOT / "PHASE1_5_REPORT.md"
HEALTH_PATH = PROJECT_ROOT / "PHASE1_5_RERUN_HEALTH.md"


GROUPS: Dict[str, Dict[str, str]] = {
    "A": {
        "ENABLE_AO_AWARE_MEMORY": "false",
        "ENABLE_SESSION_STATE_BLOCK": "false",
        "ENABLE_AO_CLASSIFIER_RULE_LAYER": "false",
        "ENABLE_AO_CLASSIFIER_LLM_LAYER": "false",
        "ENABLE_AO_BLOCK_INJECTION": "false",
        "ENABLE_AO_PERSISTENT_FACTS": "false",
    },
    "B": {
        "ENABLE_AO_AWARE_MEMORY": "false",
        "ENABLE_SESSION_STATE_BLOCK": "true",
        "ENABLE_AO_CLASSIFIER_RULE_LAYER": "false",
        "ENABLE_AO_CLASSIFIER_LLM_LAYER": "false",
        "ENABLE_AO_BLOCK_INJECTION": "false",
        "ENABLE_AO_PERSISTENT_FACTS": "false",
    },
    "C": {
        "ENABLE_AO_AWARE_MEMORY": "true",
        "ENABLE_SESSION_STATE_BLOCK": "false",
        "ENABLE_AO_CLASSIFIER_RULE_LAYER": "true",
        "ENABLE_AO_CLASSIFIER_LLM_LAYER": "false",
        "ENABLE_AO_BLOCK_INJECTION": "true",
        "ENABLE_AO_PERSISTENT_FACTS": "true",
    },
    "D": {
        "ENABLE_AO_AWARE_MEMORY": "true",
        "ENABLE_SESSION_STATE_BLOCK": "false",
        "ENABLE_AO_CLASSIFIER_RULE_LAYER": "false",
        "ENABLE_AO_CLASSIFIER_LLM_LAYER": "true",
        "ENABLE_AO_BLOCK_INJECTION": "true",
        "ENABLE_AO_PERSISTENT_FACTS": "true",
    },
    "E": {
        "ENABLE_AO_AWARE_MEMORY": "true",
        "ENABLE_SESSION_STATE_BLOCK": "false",
        "ENABLE_AO_CLASSIFIER_RULE_LAYER": "true",
        "ENABLE_AO_CLASSIFIER_LLM_LAYER": "true",
        "ENABLE_AO_BLOCK_INJECTION": "true",
        "ENABLE_AO_PERSISTENT_FACTS": "true",
    },
    "F": {
        "ENABLE_AO_AWARE_MEMORY": "true",
        "ENABLE_SESSION_STATE_BLOCK": "false",
        "ENABLE_AO_CLASSIFIER_RULE_LAYER": "true",
        "ENABLE_AO_CLASSIFIER_LLM_LAYER": "true",
        "ENABLE_AO_BLOCK_INJECTION": "true",
        "ENABLE_AO_PERSISTENT_FACTS": "false",
    },
}


GROUP_LABELS = {
    "A": "Phase 0 baseline",
    "B": "Phase 1 regression",
    "C": "Rule-only",
    "D": "LLM-only",
    "E": "Hybrid, main",
    "F": "Hybrid w/o persistent facts",
}


def _run_eval(
    samples: Path,
    output_dir: Path,
    env_overrides: Dict[str, str],
    *,
    task_timeout_sec: float,
) -> Dict[str, Any]:
    env = os.environ.copy()
    env.update(env_overrides)
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        sys.executable,
        str(END2END_SCRIPT),
        "--samples",
        str(samples),
        "--output-dir",
        str(output_dir),
        "--mode",
        "router",
        "--task-timeout-sec",
        str(task_timeout_sec),
    ]
    started = time.time()
    proc = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
    (output_dir / "stdout.log").write_text(proc.stdout, encoding="utf-8")
    (output_dir / "stderr.log").write_text(proc.stderr, encoding="utf-8")
    if proc.returncode != 0:
        raise RuntimeError(f"eval_end2end failed rc={proc.returncode}: {proc.stderr[-2000:]}")
    metrics_path = output_dir / "end2end_metrics.json"
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["wall_time_sec"] = round(time.time() - started, 2)
    metrics_path.write_text(json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8")
    return metrics


def _write_health(status: str, entries: List[Dict[str, Any]], message: str = "") -> None:
    lines = [
        "# Phase 1.5 Rerun Health",
        "",
        f"Status: {status}",
        f"Updated: {time.strftime('%Y-%m-%dT%H:%M:%S%z')}",
        "",
    ]
    if message:
        lines.extend(["## Message", message, ""])
    lines.append("## Runs")
    for entry in entries:
        lines.append(
            f"- {entry.get('group')}: status={entry.get('run_status')} "
            f"data_integrity={entry.get('data_integrity')} output={entry.get('output_dir')}"
        )
    HEALTH_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _prepare_preflight_samples(samples: Path, output_dir: Path) -> Path:
    tasks = load_jsonl(samples)
    preflight_path = output_dir / "preflight_samples.jsonl"
    write_jsonl(preflight_path, tasks[:5])
    return preflight_path


def _metric(metrics: Dict[str, Any], key: str) -> float:
    return float(metrics.get(key, 0.0) or 0.0)


def _load_logs(group: str) -> List[Dict[str, Any]]:
    path = RESULTS_ROOT / f"end2end_full_v5_oasc_{group}" / "end2end_logs.jsonl"
    return load_jsonl(path) if path.exists() else []


def _load_metrics(group: str) -> Dict[str, Any]:
    path = RESULTS_ROOT / f"end2end_full_v5_oasc_{group}" / "end2end_metrics.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _pass_fail_delta(logs_a: List[Dict[str, Any]], logs_e: List[Dict[str, Any]]) -> Dict[str, Any]:
    by_a = {str(item.get("task_id")): item for item in logs_a}
    by_e = {str(item.get("task_id")): item for item in logs_e}
    pass_to_fail = []
    fail_to_pass = []
    for task_id in sorted(set(by_a) & set(by_e)):
        a_ok = bool(by_a[task_id].get("success"))
        e_ok = bool(by_e[task_id].get("success"))
        if a_ok and not e_ok:
            pass_to_fail.append(task_id)
        elif not a_ok and e_ok:
            fail_to_pass.append(task_id)
    return {"pass_to_fail": pass_to_fail, "fail_to_pass": fail_to_pass}


def _category_matrix(groups: List[str]) -> Dict[str, Dict[str, float]]:
    categories = sorted(
        {
            category
            for group in groups
            for category in (_load_metrics(group).get("by_category") or {}).keys()
        }
    )
    matrix: Dict[str, Dict[str, float]] = {}
    for category in categories:
        matrix[category] = {}
        for group in groups:
            matrix[category][group] = float(
                ((_load_metrics(group).get("by_category") or {}).get(category) or {}).get("success_rate", 0.0)
            )
    return matrix


def _generate_report(groups: List[str]) -> None:
    metrics = {group: _load_metrics(group) for group in groups}
    logs = {group: _load_logs(group) for group in groups}
    delta = _pass_fail_delta(logs.get("A", []), logs.get("E", []))
    e_metrics = metrics.get("E", {})
    a_metrics = metrics.get("A", {})
    e_vs_a = _metric(e_metrics, "completion_rate") - _metric(a_metrics, "completion_rate")
    category_matrix = _category_matrix(groups)
    parameter_ambiguous = category_matrix.get("parameter_ambiguous", {}).get("E", 0.0)

    hard_floor = {
        "Hybrid completion rate": (_metric(e_metrics, "completion_rate"), 0.72, _metric(e_metrics, "completion_rate") >= 0.72),
        "E vs A": (e_vs_a, 0.06, e_vs_a >= 0.06),
        "pass_to_fail (E vs A)": (len(delta["pass_to_fail"]), 8, len(delta["pass_to_fail"]) < 8),
        "parameter_ambiguous category": (parameter_ambiguous, 0.50, parameter_ambiguous >= 0.50),
        "Feature flag 全关时": (0.0 if metrics.get("A", {}).get("data_integrity") == "clean" else 1.0, 0.01, metrics.get("A", {}).get("data_integrity") == "clean"),
    }
    all_clean = all(metrics[group].get("data_integrity") == "clean" for group in groups)
    hard_floor_met = all(item[2] for item in hard_floor.values()) and all_clean
    recommendation = "READY FOR PHASE 2" if hard_floor_met else "NEEDS REDESIGN"

    lines: List[str] = ["# Phase 1.5 OASC Final Report", ""]
    lines.extend(["## 1. Run Health Status"])
    for group in groups:
        m = metrics[group]
        lines.append(
            f"- {group} 组: data_integrity={m.get('data_integrity')}, "
            f"run_status={m.get('run_status')}, infrastructure_health={m.get('infrastructure_health')}"
        )
    lines.append("- 全部 6 组必须 data_integrity=clean 才视为通过")
    lines.append("")

    lines.extend([
        "## 2. Implementation Summary",
        "Phase 1.5 OASC adds AO-aware memory, classifier-layer ablations, AO block injection, and optional persistent facts behind feature flags. This rerun used isolated output directories and fail-safe health recording in the evaluator.",
        "",
        "## 3. Test Results",
        "- Focused pytest: see latest local test logs",
        "- Manual classifier validation: 15/15 (previous Phase 1.5 validation)",
        "- Full pytest: not rerun by this benchmark script",
        "",
        "## 4. Main Benchmark Results",
        "",
        "| Group | completion_rate | tool_accuracy | parameter_legal | result_data | data_integrity |",
        "|---|---:|---:|---:|---:|:-:|",
    ])
    for group in groups:
        m = metrics[group]
        lines.append(
            f"| {group} ({GROUP_LABELS[group]}) | {_metric(m, 'completion_rate'):.4f} | "
            f"{_metric(m, 'tool_accuracy'):.4f} | {_metric(m, 'parameter_legal_rate'):.4f} | "
            f"{_metric(m, 'result_data_rate'):.4f} | {m.get('data_integrity')} |"
        )
    lines.append("")

    lines.extend(["## 5. Per-Category Breakdown for E vs A", ""])
    lines.append("| Category | A | E | E-A |")
    lines.append("|---|---:|---:|---:|")
    for category, row in category_matrix.items():
        a = row.get("A", 0.0)
        e = row.get("E", 0.0)
        lines.append(f"| {category} | {a:.4f} | {e:.4f} | {e - a:+.4f} |")
    lines.append("")

    lines.extend(["## 6. Hard Floor 验收", ""])
    if not hard_floor_met:
        lines.append("**HARD FLOOR NOT MET**")
        lines.append("")
    lines.append("| 指标 | Hard Floor | E 组实际 | 是否通过 |")
    lines.append("|---|---:|---:|:-:|")
    for name, (actual, floor, passed) in hard_floor.items():
        lines.append(f"| {name} | {floor} | {actual:.4f} | {'YES' if passed else 'NO'} |")
    lines.append("")

    lines.extend(["## 7. Pass/Fail Analysis (E vs A)", ""])
    lines.append(f"- pass_to_fail count: {len(delta['pass_to_fail'])}; task_ids: {delta['pass_to_fail'][:50]}")
    lines.append(f"- fail_to_pass count: {len(delta['fail_to_pass'])}; task_ids: {delta['fail_to_pass'][:50]}")
    buckets: Dict[str, int] = {}
    for task_id in delta["pass_to_fail"]:
        failure = str((next((item for item in logs.get("E", []) if item.get("task_id") == task_id), {}) or {}).get("failure_type") or "unknown")
        buckets[failure] = buckets.get(failure, 0) + 1
    lines.append(f"- pass_to_fail failure buckets: {buckets}")
    lines.append("")

    lines.extend([
        "## 8. Classifier Performance",
        "- Layer 1 命中率: not emitted by current metrics; see OASC telemetry if enabled.",
        "- Layer 2 调用次数和平均延迟: not emitted by current metrics.",
        "- Fallback 触发次数: not emitted by current metrics.",
        "- Manual case 准确率: 15/15 from prior validation.",
        "",
        "## 9. Token Statistics",
        "- Block 平均/中位/最大 tokens: not emitted by current metrics.",
        "- 按场景分桶: not emitted by current metrics.",
        "",
        "## 10. Pass/Fail per Category",
        "",
    ])
    lines.append("| Category | A | B | C | D | E | F |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for category, row in category_matrix.items():
        lines.append(
            f"| {category} | {row.get('A', 0.0):.4f} | {row.get('B', 0.0):.4f} | "
            f"{row.get('C', 0.0):.4f} | {row.get('D', 0.0):.4f} | "
            f"{row.get('E', 0.0):.4f} | {row.get('F', 0.0):.4f} |"
        )
    lines.append("")

    lines.extend(["## 11. Phase 2 Goal Cases", ""])
    e_failures = [item for item in logs.get("E", []) if not item.get("success")]
    by_bucket: Dict[str, List[str]] = {}
    for item in e_failures:
        by_bucket.setdefault(str(item.get("failure_type") or "unknown"), []).append(str(item.get("task_id")))
    for bucket, task_ids in sorted(by_bucket.items()):
        lines.append(f"- {bucket}: {task_ids[:80]}")
    lines.append("")
    lines.append(f"READY FOR PHASE 2: {'YES' if recommendation == 'READY FOR PHASE 2' else 'NO'}")
    lines.append(f"Recommendation: {recommendation}")
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run_matrix(
    samples: Path,
    *,
    clean: bool = True,
    sleep_between_groups_sec: int = 60,
    task_timeout_sec: float = 180.0,
) -> int:
    entries: List[Dict[str, Any]] = []
    preflight_dir = RESULTS_ROOT / "end2end_full_v5_oasc_preflight"
    if clean and preflight_dir.exists():
        shutil.rmtree(preflight_dir)
    preflight_dir.mkdir(parents=True, exist_ok=True)
    preflight_samples = _prepare_preflight_samples(samples, preflight_dir)
    _write_health("preflight_running", entries)
    preflight_metrics = _run_eval(
        preflight_samples,
        preflight_dir / "A",
        GROUPS["A"],
        task_timeout_sec=task_timeout_sec,
    )
    entries.append({
        "group": "preflight_A",
        "run_status": preflight_metrics.get("run_status"),
        "data_integrity": preflight_metrics.get("data_integrity"),
        "output_dir": str(preflight_dir / "A"),
    })
    if preflight_metrics.get("run_status") != "completed" or preflight_metrics.get("data_integrity") != "clean":
        _write_health("preflight_failed", entries, "Preflight did not complete cleanly; formal matrix was not started.")
        return 2

    balance_note = "Provider balance check: not supported by configured evaluator API; preflight success used as account sanity check."
    _write_health("preflight_passed", entries, balance_note)

    for index, group in enumerate(GROUPS):
        output_dir = RESULTS_ROOT / f"end2end_full_v5_oasc_{group}"
        if clean and output_dir.exists():
            shutil.rmtree(output_dir)
        _write_health("running", entries, f"Starting group {group}")
        metrics = _run_eval(samples, output_dir, GROUPS[group], task_timeout_sec=task_timeout_sec)
        if metrics.get("run_status") == "aborted_network":
            _write_health("network_retry_wait", entries, f"Group {group} aborted_network; waiting 5 minutes before one retry.")
            time.sleep(300)
            if output_dir.exists():
                shutil.rmtree(output_dir)
            metrics = _run_eval(samples, output_dir, GROUPS[group], task_timeout_sec=task_timeout_sec)
        entries.append({
            "group": group,
            "run_status": metrics.get("run_status"),
            "data_integrity": metrics.get("data_integrity"),
            "output_dir": str(output_dir),
        })
        _write_health("running", entries, f"Finished group {group}")
        if metrics.get("run_status") == "aborted_billing":
            _write_health("aborted_billing", entries, f"Group {group} aborted due to billing failure; stopping matrix.")
            return 3
        if metrics.get("run_status") == "aborted_network":
            _write_health("aborted_network", entries, f"Group {group} aborted due to network failure after retry; stopping matrix.")
            return 4
        if index < len(GROUPS) - 1:
            time.sleep(sleep_between_groups_sec)

    _generate_report(list(GROUPS.keys()))
    _write_health("completed", entries, "All groups completed; final report generated.")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 1.5 OASC benchmark matrix.")
    parser.add_argument("--samples", type=Path, default=DEFAULT_SAMPLES)
    parser.add_argument("--no-clean", action="store_true")
    parser.add_argument("--sleep-between-groups-sec", type=int, default=60)
    parser.add_argument("--task-timeout-sec", type=float, default=180.0)
    args = parser.parse_args()
    raise SystemExit(
        run_matrix(
            args.samples,
            clean=not args.no_clean,
            sleep_between_groups_sec=args.sleep_between_groups_sec,
            task_timeout_sec=args.task_timeout_sec,
        )
    )


if __name__ == "__main__":
    main()
