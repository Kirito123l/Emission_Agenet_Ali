#!/usr/bin/env python3
"""Run Phase 5.3 fixed 3-way benchmark ablations."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from dotenv import dotenv_values
except ImportError:  # pragma: no cover - config.py requires python-dotenv in normal runs
    dotenv_values = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
EVAL_SCRIPT = PROJECT_ROOT / "evaluation" / "eval_end2end.py"
CONFIG_PATH = PROJECT_ROOT / "config.py"
DOTENV_PATH = PROJECT_ROOT / ".env"

BENCHMARKS: Dict[str, Dict[str, Any]] = {
    "30task": {
        "path": PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl",
        "smoke": True,
    },
    "180task": {
        "path": PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl",
        "smoke": False,
    },
    "75task_heldout": {
        "path": PROJECT_ROOT / "evaluation" / "benchmarks" / "held_out_tasks.jsonl",
        "smoke": False,
    },
}

NAIVE_BASELINE_ENV = {
    "ENABLE_AO_AWARE_MEMORY": "false",
    "ENABLE_AO_CLASSIFIER_RULE_LAYER": "false",
    "ENABLE_AO_CLASSIFIER_LLM_LAYER": "false",
    "ENABLE_AO_BLOCK_INJECTION": "false",
    "ENABLE_AO_PERSISTENT_FACTS": "false",
    "ENABLE_AO_FIRST_CLASS_STATE": "false",
    "ENABLE_GOVERNED_ROUTER": "false",
    "ENABLE_CLARIFICATION_CONTRACT": "false",
    "ENABLE_CONTRACT_SPLIT": "false",
    "ENABLE_SPLIT_INTENT_CONTRACT": "false",
    "ENABLE_SPLIT_STANCE_CONTRACT": "false",
    "ENABLE_SPLIT_READINESS_CONTRACT": "false",
    "ENABLE_SPLIT_CONTINUATION_STATE": "false",
    "ENABLE_RUNTIME_DEFAULT_AWARE_READINESS": "false",
    "ENABLE_LLM_DECISION_FIELD": "false",
    "ENABLE_CROSS_CONSTRAINT_VALIDATION": "false",
    "ENABLE_READINESS_GATING": "false",
    "ENABLE_LLM_USER_REPLY_PARSER": "false",
}

AO_ON_ENV = {
    "ENABLE_AO_AWARE_MEMORY": "true",
    "ENABLE_AO_CLASSIFIER_RULE_LAYER": "true",
    "ENABLE_AO_CLASSIFIER_LLM_LAYER": "true",
    "ENABLE_AO_BLOCK_INJECTION": "true",
    "ENABLE_AO_PERSISTENT_FACTS": "true",
    "ENABLE_AO_FIRST_CLASS_STATE": "true",
    "ENABLE_SESSION_STATE_BLOCK": "false",
    "ENABLE_GOVERNED_ROUTER": "true",
}

GOVERNANCE_OFF_ENV = {
    "ENABLE_CLARIFICATION_CONTRACT": "false",
    "ENABLE_CONTRACT_SPLIT": "false",
    "ENABLE_SPLIT_INTENT_CONTRACT": "false",
    "ENABLE_SPLIT_STANCE_CONTRACT": "false",
    "ENABLE_SPLIT_READINESS_CONTRACT": "false",
    "ENABLE_SPLIT_CONTINUATION_STATE": "false",
    "ENABLE_RUNTIME_DEFAULT_AWARE_READINESS": "false",
    "ENABLE_LLM_DECISION_FIELD": "false",
    "ENABLE_CROSS_CONSTRAINT_VALIDATION": "false",
    "ENABLE_READINESS_GATING": "false",
    "ENABLE_LLM_USER_REPLY_PARSER": "false",
}

GOVERNANCE_ON_ENV = {
    "ENABLE_CLARIFICATION_CONTRACT": "true",
    "ENABLE_CONTRACT_SPLIT": "true",
    "ENABLE_SPLIT_INTENT_CONTRACT": "true",
    "ENABLE_SPLIT_STANCE_CONTRACT": "true",
    "ENABLE_SPLIT_READINESS_CONTRACT": "true",
    "ENABLE_SPLIT_CONTINUATION_STATE": "true",
    "ENABLE_RUNTIME_DEFAULT_AWARE_READINESS": "true",
    "ENABLE_LLM_DECISION_FIELD": "true",
    "ENABLE_CROSS_CONSTRAINT_VALIDATION": "true",
    "ENABLE_READINESS_GATING": "true",
    "ENABLE_LLM_USER_REPLY_PARSER": "false",
}

ABLATION_MODES: Dict[str, Dict[str, Any]] = {
    "naive": {
        "router_mode": "naive",
        "env": dict(NAIVE_BASELINE_ENV),
    },
    "ao_only": {
        "router_mode": "router",
        "env": {**AO_ON_ENV, **GOVERNANCE_OFF_ENV},
    },
    "governance_full": {
        "router_mode": "router",
        "env": {**AO_ON_ENV, **GOVERNANCE_ON_ENV},
    },
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_rev_parse(*args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(PROJECT_ROOT),
            check=True,
            capture_output=True,
            text=True,
        )
        return result.stdout.strip()
    except Exception:
        return "unknown"


def _config_env_defaults() -> Dict[str, Optional[str]]:
    defaults: Dict[str, Optional[str]] = {}
    tree = ast.parse(CONFIG_PATH.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "getenv"
            and isinstance(node.func.value, ast.Name)
            and node.func.value.id == "os"
        ):
            continue
        if not node.args or not isinstance(node.args[0], ast.Constant):
            continue
        key = node.args[0].value
        if not isinstance(key, str):
            continue
        if not (key.startswith("ENABLE_") or key.startswith("LLM_")):
            continue
        default: Optional[str] = None
        if len(node.args) >= 2:
            arg = node.args[1]
            if isinstance(arg, ast.Constant):
                default = None if arg.value is None else str(arg.value)
            else:
                default = ast.unparse(arg)
        defaults[key] = default
    return dict(sorted(defaults.items()))


def _dotenv_values() -> Dict[str, str]:
    if dotenv_values is None or not DOTENV_PATH.exists():
        return {}
    return {
        str(key): str(value)
        for key, value in dotenv_values(DOTENV_PATH).items()
        if key is not None and value is not None
    }


def _effective_env_snapshot(mode_env: Dict[str, str]) -> Dict[str, Dict[str, Optional[str]]]:
    defaults = _config_env_defaults()
    dotenv = _dotenv_values()
    snapshot: Dict[str, Dict[str, Optional[str]]] = {}
    for key, default in defaults.items():
        if key in dotenv:
            value = dotenv[key]
            source = ".env"
        elif key in mode_env:
            value = mode_env[key]
            source = "child_env"
        elif key in os.environ:
            value = os.environ[key]
            source = "parent_env"
        else:
            value = default
            source = "config_default"
        snapshot[key] = {
            "value": value,
            "source": source,
            "config_default": default,
            "mode_override": mode_env.get(key),
        }
    return snapshot


def _write_config_snapshot(
    *,
    path: Path,
    mode_name: str,
    router_mode: str,
    benchmark_name: str,
    benchmark_path: Path,
    mode_env: Dict[str, str],
    command: List[str],
    returncode: Optional[int],
) -> None:
    payload = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "git": {
            "commit": _git_rev_parse("rev-parse", "HEAD"),
            "branch": _git_rev_parse("rev-parse", "--abbrev-ref", "HEAD"),
        },
        "python": {
            "executable": sys.executable,
            "version": sys.version,
            "platform": platform.platform(),
        },
        "benchmark": {
            "name": benchmark_name,
            "path": str(benchmark_path),
            "sha256": _sha256(benchmark_path),
        },
        "ablation": {
            "mode": mode_name,
            "router_mode": router_mode,
            "mode_env": dict(sorted(mode_env.items())),
        },
        "env": _effective_env_snapshot(mode_env),
        "command": command,
        "returncode": returncode,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _clear_cache(env: Dict[str, str]) -> None:
    subprocess.run(
        [sys.executable, str(EVAL_SCRIPT), "--clear-cache"],
        cwd=str(PROJECT_ROOT),
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )


def _run_one(
    *,
    mode_name: str,
    mode_config: Dict[str, Any],
    benchmark_name: str,
    benchmark_config: Dict[str, Any],
    output_dir: Path,
    rep: int,
    parallel: int,
    qps_limit: float,
    cache_enabled: bool,
    task_timeout_sec: Optional[float],
) -> Dict[str, Any]:
    router_mode = str(mode_config["router_mode"])
    mode_env = {str(k): str(v) for k, v in dict(mode_config["env"]).items()}
    env = os.environ.copy()
    env.update(mode_env)
    env["PYTHONUNBUFFERED"] = "1"

    rep_dir = output_dir / mode_name / f"rep_{rep}"
    rep_dir.mkdir(parents=True, exist_ok=True)

    if cache_enabled:
        _clear_cache(env)

    command = [
        sys.executable,
        str(EVAL_SCRIPT),
        "--samples",
        str(benchmark_config["path"]),
        "--output-dir",
        str(rep_dir),
        "--mode",
        router_mode,
        "--parallel",
        str(parallel),
        "--qps-limit",
        str(qps_limit),
    ]
    if benchmark_config.get("smoke"):
        command.append("--smoke")
    command.append("--cache" if cache_enabled else "--no-cache")
    if task_timeout_sec is not None:
        command.extend(["--task-timeout-sec", str(task_timeout_sec)])

    proc = subprocess.run(
        command,
        cwd=str(PROJECT_ROOT),
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    (rep_dir / "stdout.log").write_text(proc.stdout or "", encoding="utf-8")
    (rep_dir / "stderr.log").write_text(proc.stderr or "", encoding="utf-8")
    _write_config_snapshot(
        path=rep_dir / "config_snapshot.json",
        mode_name=mode_name,
        router_mode=router_mode,
        benchmark_name=benchmark_name,
        benchmark_path=benchmark_config["path"],
        mode_env=mode_env,
        command=command,
        returncode=proc.returncode,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"{mode_name} rep {rep} failed rc={proc.returncode}: {(proc.stderr or '')[-2000:]}"
        )
    metrics_path = rep_dir / "end2end_metrics.json"
    if not metrics_path.exists():
        raise RuntimeError(f"{mode_name} rep {rep} did not produce {metrics_path}")
    metrics = json.loads(metrics_path.read_text(encoding="utf-8"))
    metrics["_mode"] = mode_name
    metrics["_rep"] = rep
    return metrics


def run_ablation(
    *,
    mode: str,
    benchmark: str,
    reps: int,
    output_dir: Path,
    parallel: int,
    qps_limit: float,
    cache_enabled: bool,
    task_timeout_sec: Optional[float],
) -> Dict[str, Any]:
    if benchmark not in BENCHMARKS:
        raise ValueError(f"Unknown benchmark: {benchmark}")
    benchmark_config = BENCHMARKS[benchmark]
    if not benchmark_config["path"].exists():
        raise FileNotFoundError(f"Benchmark file not found: {benchmark_config['path']}")

    modes = list(ABLATION_MODES) if mode == "all" else [mode]
    missing = [name for name in modes if name not in ABLATION_MODES]
    if missing:
        raise ValueError(f"Unknown mode(s): {', '.join(missing)}")

    summary: Dict[str, Any] = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "benchmark": benchmark,
        "reps": reps,
        "output_dir": str(output_dir),
        "runs": {},
    }
    for mode_name in modes:
        summary["runs"][mode_name] = []
        for rep in range(1, reps + 1):
            print(f"=== {mode_name} rep {rep}/{reps} ({benchmark}) ===", flush=True)
            metrics = _run_one(
                mode_name=mode_name,
                mode_config=ABLATION_MODES[mode_name],
                benchmark_name=benchmark,
                benchmark_config=benchmark_config,
                output_dir=output_dir,
                rep=rep,
                parallel=parallel,
                qps_limit=qps_limit,
                cache_enabled=cache_enabled,
                task_timeout_sec=task_timeout_sec,
            )
            passed = round(float(metrics.get("completion_rate", 0.0)) * int(metrics.get("tasks", 0)))
            print(
                f"{mode_name} rep {rep}: {passed}/{metrics.get('tasks', 0)} "
                f"({float(metrics.get('completion_rate', 0.0)):.1%})",
                flush=True,
            )
            summary["runs"][mode_name].append(metrics)

    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "phase5_3_ablation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Phase 5.3 fixed 3-way ablation benchmark.")
    parser.add_argument("--mode", choices=["naive", "ao_only", "governance_full", "all"], required=True)
    parser.add_argument("--benchmark", choices=sorted(BENCHMARKS), required=True)
    parser.add_argument("--reps", type=int, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--parallel", type=int, default=4)
    parser.add_argument("--qps-limit", type=float, default=15.0)
    parser.add_argument("--cache", dest="cache_enabled", action="store_true", default=True)
    parser.add_argument("--no-cache", dest="cache_enabled", action="store_false")
    parser.add_argument("--task-timeout-sec", type=float, default=None)
    args = parser.parse_args()

    summary = run_ablation(
        mode=args.mode,
        benchmark=args.benchmark,
        reps=max(1, int(args.reps)),
        output_dir=args.output_dir,
        parallel=max(1, int(args.parallel)),
        qps_limit=float(args.qps_limit),
        cache_enabled=bool(args.cache_enabled),
        task_timeout_sec=args.task_timeout_sec,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
