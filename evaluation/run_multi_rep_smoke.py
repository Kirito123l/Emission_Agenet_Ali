#!/usr/bin/env python3
"""Multi-repetition smoke runner for statistical validation.

Usage:
  python evaluation/run_multi_rep_smoke.py on 30task 5
  python evaluation/run_multi_rep_smoke.py off 11task 7

Output dirs: evaluation/results/multi_rep/<flag>_<benchmark>/rep_<n>/
Summary printed to stdout as markdown.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

BENCHMARK_FILES = {
    "30task": PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl",
    "11task": PROJECT_ROOT / "evaluation" / "results" / "a_smoke" / "smoke_10.jsonl",
}

EVAL_SCRIPT = PROJECT_ROOT / "evaluation" / "eval_end2end.py"


def run_single(flag: str, benchmark: str, output_dir: Path, rep: int) -> dict:
    """Run a single smoke rep. Returns the metrics dict."""
    rep_dir = output_dir / f"rep_{rep}"
    rep_dir.mkdir(parents=True, exist_ok=True)

    env = os.environ.copy()
    env[args.flag_var] = "true" if flag == "on" else "false"
    env["PYTHONUNBUFFERED"] = "1"

    samples = BENCHMARK_FILES[benchmark]
    cmd = [
        sys.executable,
        str(EVAL_SCRIPT),
        "--samples", str(samples),
        "--output-dir", str(rep_dir),
        "--mode", "router",
        "--parallel", "4",
        "--smoke",
        "--cache",
    ]

    t0 = time.perf_counter()
    result = subprocess.run(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=900,  # 15 min per rep
    )
    elapsed = time.perf_counter() - t0

    metrics_path = rep_dir / "end2end_metrics.json"
    if metrics_path.exists():
        metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
        metrics["_rep"] = rep
        metrics["_elapsed_sec"] = round(elapsed, 1)
        metrics["_returncode"] = result.returncode
        return metrics

    # Fallback: try to parse stdout
    try:
        metrics = json.loads(result.stdout.strip().split("\n")[-1])
        metrics["_rep"] = rep
        metrics["_elapsed_sec"] = round(elapsed, 1)
        metrics["_returncode"] = result.returncode
        return metrics
    except (json.JSONDecodeError, IndexError):
        return {
            "_rep": rep,
            "_elapsed_sec": round(elapsed, 1),
            "_returncode": result.returncode,
            "_error": "no_metrics_file",
            "_stderr_tail": (result.stderr or "")[-500:],
            "completion_rate": 0.0,
            "tasks": 0,
        }


def load_task_results(rep_dir: Path) -> list[dict]:
    """Load individual task results from a rep's logs."""
    logs_path = rep_dir / "end2end_logs.jsonl"
    if not logs_path.exists():
        return []
    tasks = []
    with open(logs_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            tasks.append(json.loads(line))
    return tasks


def aggregate(flag: str, benchmark: str, output_dir: Path, n_reps: int) -> str:
    """Aggregate across all reps and produce markdown summary."""
    metrics_list = []
    all_tasks: dict[str, list[bool]] = {}  # task_id -> [pass/fail per rep]

    for rep in range(1, n_reps + 1):
        rep_dir = output_dir / f"rep_{rep}"
        metrics_path = rep_dir / "end2end_metrics.json"
        if metrics_path.exists():
            m = json.loads(metrics_path.read_text(encoding="utf-8"))
            m["_rep"] = rep
            metrics_list.append(m)

        tasks = load_task_results(rep_dir)
        for t in tasks:
            tid = t.get("task_id", "?")
            if tid not in all_tasks:
                all_tasks[tid] = []
            all_tasks[tid].append(t.get("success", False))

    completions = [m["completion_rate"] for m in metrics_list if m.get("completion_rate") is not None]
    n_completed = len(completions)

    if n_completed == 0:
        return "## Multi-rep Smoke: NO DATA (all reps failed to produce metrics)"

    mean_cr = statistics.mean(completions) if completions else 0
    stdev_cr = statistics.stdev(completions) if len(completions) >= 2 else 0
    min_cr = min(completions)
    max_cr = max(completions)

    lines = []
    lines.append("## Multi-rep Smoke Summary")
    lines.append(f"**Config**: flag=`{flag}`, benchmark=`{benchmark}`, n={n_completed}")
    lines.append("")
    lines.append(f"**Aggregate**: mean={mean_cr:.1%} (±{stdev_cr:.1%}pp), spread=[{min_cr:.1%}, {max_cr:.1%}]")
    lines.append(f"**Wall clock**: {sum(m.get('_elapsed_sec', 0) for m in metrics_list):.0f}s total across {n_completed} reps")
    lines.append("")

    # Per-rep breakdown
    lines.append("| Rep | Completion | Tasks | Elapsed |")
    lines.append("|-----|-----------|-------|---------|")
    for m in metrics_list:
        lines.append(f"| {m.get('_rep', '?')} | {m.get('completion_rate', 0):.1%} | {m.get('tasks', '?')} | {m.get('_elapsed_sec', 0):.0f}s |")
    lines.append("")

    # Flaky task analysis
    if all_tasks:
        stable_pass = []
        stable_fail = []
        flaky = []

        for tid, results in sorted(all_tasks.items()):
            n = len(results)
            passes = sum(results)
            if passes == n:
                stable_pass.append(tid)
            elif passes == 0:
                stable_fail.append(tid)
            else:
                flaky.append((tid, passes, n))

        lines.append(f"**Stable PASS ({len(stable_pass)})**: {', '.join(stable_pass) if stable_pass else '(none)'}")
        lines.append(f"**Stable FAIL ({len(stable_fail)})**: {', '.join(stable_fail) if stable_fail else '(none)'}")
        lines.append("")

        if flaky:
            lines.append(f"**Flaky ({len(flaky)})**:")
            lines.append("| Task | Pass Rate | Pattern |")
            lines.append("|------|-----------|---------|")
            for tid, passes, n in sorted(flaky, key=lambda x: x[1], reverse=True):
                pct = passes / n * 100
                bar = "█" * int(pct / 10) + "░" * (10 - int(pct / 10))
                lines.append(f"| {tid} | {passes}/{n} ({pct:.0f}%) | {bar} |")
            lines.append("")

        lines.append(f"**Task count**: {len(all_tasks)} total ({len(stable_pass)} stable pass, {len(stable_fail)} stable fail, {len(flaky)} flaky)")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Multi-rep smoke runner for statistical validation")
    parser.add_argument("flag", choices=["on", "off"], help="Feature flag value: on|off")
    parser.add_argument(
        "--flag-var",
        default="ENABLE_LLM_USER_REPLY_PARSER",
        help="Env var name controlled by flag (default: ENABLE_LLM_USER_REPLY_PARSER)",
    )
    parser.add_argument("benchmark", choices=["30task", "11task"], help="Benchmark: 30task or 11task")
    parser.add_argument("n_reps", type=int, default=5, nargs="?", help="Number of repetitions (default: 5)")
    parser.add_argument("--dry-run", action="store_true", help="Print mock summary without running")
    args = parser.parse_args()

    output_dir = PROJECT_ROOT / "evaluation" / "results" / "multi_rep" / f"{args.flag}_{args.benchmark}"

    if args.dry_run:
        print("## Multi-rep Smoke Summary (DRY RUN — mock data)")
        print(f"**Config**: flag=`{args.flag}`, benchmark=`{args.benchmark}`, n={args.n_reps}")
        print("")
        print(f"**Aggregate**: mean=82.0% (±4.2pp), spread=[76.7%, 86.7%]")
        print("")
        print("| Rep | Completion | Tasks | Elapsed |")
        print("|-----|-----------|-------|---------|")
        for r in range(1, args.n_reps + 1):
            fake_cr = 0.80 + (r % 3) * 0.033
            print(f"| {r} | {fake_cr:.1%} | 30 | 250s |")
        print("")
        print("**Stable PASS (22)**: e2e_ambiguous_001, e2e_ambiguous_010, e2e_ambiguous_034, ...")
        print("**Stable FAIL (4)**: e2e_clarification_105, e2e_clarification_110, e2e_clarification_119, e2e_clarification_120")
        print("")
        print("**Flaky (4)**：")
        print("| Task | Pass Rate | Pattern |")
        print("|------|-----------|---------|")
        print("| e2e_codeswitch_161 | 4/5 (80%) | ████████░░ |")
        print("| e2e_colloquial_143 | 3/5 (60%) | ██████░░░░ |")
        print("| e2e_codeswitch_165 | 2/5 (40%) | ████░░░░░░ |")
        print("| e2e_simple_023 | 1/5 (20%) | ██░░░░░░░░ |")
        print("")
        print(f"**Task count**: 30 total (22 stable pass, 4 stable fail, 4 flaky)")
        return

    if not BENCHMARK_FILES[args.benchmark].exists():
        print(f"ERROR: benchmark file not found: {BENCHMARK_FILES[args.benchmark]}", file=sys.stderr)
        sys.exit(1)

    print(f"Running {args.n_reps} reps of {args.benchmark} smoke (flag={args.flag})...")
    print(f"Output: {output_dir}")
    print()

    for rep in range(1, args.n_reps + 1):
        print(f"--- Rep {rep}/{args.n_reps} ---")
        metrics = run_single(args.flag, args.benchmark, output_dir, rep)
        cr = metrics.get("completion_rate", 0)
        elapsed = metrics.get("_elapsed_sec", 0)
        print(f"  completion={cr:.1%}, tasks={metrics.get('tasks', '?')}, elapsed={elapsed:.0f}s")

    print()
    summary = aggregate(args.flag, args.benchmark, output_dir, args.n_reps)
    print(summary)


if __name__ == "__main__":
    main()
