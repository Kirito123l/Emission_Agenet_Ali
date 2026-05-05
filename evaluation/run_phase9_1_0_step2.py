"""Phase 9.1.0 Step 2 — Reproducibility Sampling Runner.

Runs selected Phase 8.2.2.C-2 benchmark tasks in governance_full (GovernedRouter)
or naive (NaiveRouter) mode with full instrumentation:
  - State cleanup before each trial
  - LLM cache telemetry capture (via modified llm_client.py)
  - Path divergence diagnostics (filesystem diff, module state, step type distribution)
  - Nonce prefix to defeat prompt cache

Usage:
  python -m evaluation.run_phase9_1_0_step2 \\
      --task-id e2e_ambiguous_001 \\
      --mode governance_full \\
      --trial-id 1 \\
      --output-dir evaluation/results/_temp_phase9_1_0_step2/
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.governed_router import GovernedRouter
from core.naive_router import NaiveRouter
from tools.registry import get_registry, init_tools

logger = logging.getLogger(__name__)


def _load_benchmark() -> Dict[str, Dict[str, Any]]:
    """Load the 182-task end2end benchmark index."""
    benchmark_path = PROJECT_ROOT / "evaluation" / "benchmarks" / "end2end_tasks.jsonl"
    tasks = {}
    with open(benchmark_path) as f:
        for line in f:
            d = json.loads(line)
            tasks[d["id"]] = d
    return tasks


def _capture_filesystem_state(label: str) -> Dict[str, Any]:
    """Snapshot filesystem state for path divergence diagnosis."""
    state: Dict[str, List[Dict[str, Any]]] = {}
    dirs_to_check = [
        PROJECT_ROOT / "data" / "sessions",
        PROJECT_ROOT / "outputs",
    ]
    for d in dirs_to_check:
        entries = []
        if d.exists():
            for p in d.rglob("*"):
                if p.is_file():
                    st = p.stat()
                    entries.append({
                        "path": str(p.relative_to(PROJECT_ROOT)),
                        "size": st.st_size,
                        "mtime": st.st_mtime,
                    })
        state[str(d.relative_to(PROJECT_ROOT))] = sorted(
            entries, key=lambda e: e["path"]
        )
    return {"label": label, "captured_at_utc": datetime.now(timezone.utc).isoformat(), "state": state}


def _capture_module_state() -> Dict[str, Any]:
    """Snapshot module-level state for path divergence diagnosis."""
    state: Dict[str, Any] = {}

    # Tool registry
    try:
        registry = get_registry()
        tools = registry.list_tools()
        state["tool_registry"] = {
            "initialized": bool(tools),
            "tool_count": len(tools),
            "tool_names": [t.get("function", {}).get("name", "?") for t in tools],
        }
    except Exception as e:
        state["tool_registry"] = {"error": str(e)}

    # Contract registry
    try:
        from tools.contract_loader import get_tool_contract_registry
        cr = get_tool_contract_registry()
        state["contract_registry"] = {
            "naive_available": list(cr.get_naive_available_tools()),
        }
    except Exception as e:
        state["contract_registry"] = {"error": str(e)}

    # Standardization engine
    try:
        from services.standardization_engine import StandardizationEngine
        state["standardization_engine"] = {
            "has_instance": StandardizationEngine._instance is not None if hasattr(StandardizationEngine, "_instance") else "unknown",
        }
    except Exception as e:
        state["standardization_engine"] = {"error": str(e)}

    # LLM client service (class-level)
    try:
        from services.llm_client import LLMClientService
        state["llm_client"] = {
            "class_name": LLMClientService.__name__,
        }
    except Exception as e:
        state["llm_client"] = {"error": str(e)}

    return state


def _cleanup_session_state(session_id: str) -> Dict[str, Any]:
    """Delete persisted state files for this session_id. Returns pre-cleanup status."""
    result: Dict[str, Any] = {"session_id": session_id, "files_deleted": [], "files_not_found": [], "files_present": []}

    paths_to_check = [
        PROJECT_ROOT / "data" / "sessions" / "history" / f"{session_id}.json",
        PROJECT_ROOT / "data" / "sessions" / "router_state" / f"{session_id}.json",
    ]

    for p in paths_to_check:
        if p.exists():
            st = p.stat()
            result["files_present"].append({
                "path": str(p.relative_to(PROJECT_ROOT)),
                "size": st.st_size,
                "mtime": st.st_mtime,
            })
            p.unlink()
            result["files_deleted"].append(str(p.relative_to(PROJECT_ROOT)))
        else:
            result["files_not_found"].append(str(p.relative_to(PROJECT_ROOT)))

    return result


def _collect_llm_telemetry(router: Any) -> List[Dict[str, Any]]:
    """Drain LLM telemetry from the router's LLM client."""
    try:
        llm = None
        # GovernedRouter -> inner_router.llm
        inner = getattr(router, "inner_router", None)
        if inner is not None:
            llm = getattr(inner, "llm", None)
        # NaiveRouter -> self.llm
        if llm is None:
            llm = getattr(router, "llm", None)
        if llm is not None and hasattr(llm, "drain_telemetry_log"):
            return llm.drain_telemetry_log()
    except Exception:
        pass
    return []


def _safe_serialize(obj: Any, max_depth: int = 4, _depth: int = 0) -> Any:
    """Recursively convert trace objects to JSON-safe types."""
    if _depth >= max_depth:
        return str(obj)[:500]
    if obj is None:
        return None
    if isinstance(obj, (str, int, float, bool)):
        return obj
    if isinstance(obj, (list, tuple)):
        return [_safe_serialize(v, max_depth, _depth + 1) for v in obj[:200]]
    if isinstance(obj, dict):
        return {str(k): _safe_serialize(v, max_depth, _depth + 1) for k, v in obj.items()}
    if hasattr(obj, "value"):
        return obj.value
    try:
        return str(obj)[:1000]
    except Exception:
        return f"<unserializable {type(obj).__name__}>"


async def run_step2_trial(
    task: Dict[str, Any],
    mode: str,
    trial_id: int,
    output_dir: Path,
    use_nonce: bool = True,
) -> Dict[str, Any]:
    """Run a single Step 2 trial with full instrumentation."""
    output_dir.mkdir(parents=True, exist_ok=True)
    task_id = task["id"]
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    session_id = f"phase9_1_0_step2_{mode}_{task_id}_trial{trial_id}_{ts}"

    # ── State cleanup ─────────────────────────────────────────────────
    cleanup_result = _cleanup_session_state(session_id)

    # ── Pre-run filesystem state ───────────────────────────────────────
    fs_before = _capture_filesystem_state("pre_run")

    # ── Pre-run module state ───────────────────────────────────────────
    module_before = _capture_module_state()

    # ── Build prompt with optional nonce ───────────────────────────────
    original_message = task["user_message"]
    if use_nonce:
        nonce_ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
        user_message = f"[step2_trial={trial_id}_{nonce_ts}]\n\n{original_message}"
    else:
        user_message = original_message

    # ── Prepare file path ─────────────────────────────────────────────
    file_path = None
    test_file = task.get("test_file")
    if test_file:
        fp = PROJECT_ROOT / test_file
        if fp.exists():
            file_path = str(fp)

    # ── Initialize router ─────────────────────────────────────────────
    started_at = time.time()

    if mode == "governance_full":
        router = GovernedRouter(session_id=session_id)
    elif mode == "naive":
        router = NaiveRouter(session_id=session_id)
    else:
        raise ValueError(f"Unknown mode: {mode}")

    # ── Run single turn ───────────────────────────────────────────────
    turn_start = time.time()
    try:
        response = await router.chat(
            user_message=user_message,
            file_path=file_path,
        )
    except Exception as e:
        logger.error(f"Trial failed: {e}")
        response = None
    turn_elapsed = time.time() - turn_start

    # ── Collect LLM telemetry ─────────────────────────────────────────
    llm_telemetry = _collect_llm_telemetry(router)

    # ── Extract response data ─────────────────────────────────────────
    if response is not None:
        response_text = response.text[:2000] if response.text else ""
        tool_calls = response.executed_tool_calls if hasattr(response, "executed_tool_calls") else []
        if tool_calls is None:
            tool_calls = []
        trace_raw = getattr(response, "trace", None)
        if isinstance(trace_raw, dict):
            trace = _safe_serialize(trace_raw)
        else:
            trace = {}
    else:
        response_text = ""
        tool_calls = []
        trace = {}

    total_elapsed = time.time() - started_at

    # ── Post-run filesystem state ─────────────────────────────────────
    fs_after = _capture_filesystem_state("post_run")

    # ── Post-run module state ─────────────────────────────────────────
    module_after = _capture_module_state()

    # ── Trace step type distribution ───────────────────────────────────
    steps = trace.get("steps", []) if isinstance(trace, dict) else []
    step_type_counts: Dict[str, int] = {}
    step_type_sequence: List[str] = []
    for s in steps:
        if isinstance(s, dict):
            st = s.get("step_type") or s.get("type") or "unknown"
        else:
            st = str(s)
        step_type_counts[st] = step_type_counts.get(st, 0) + 1
        step_type_sequence.append(st)

    # ── Assemble output ───────────────────────────────────────────────
    tool_names = [tc.get("name", "?") for tc in tool_calls]
    tool_successes = [
        tc.get("result", {}).get("success") if isinstance(tc.get("result"), dict) else None
        for tc in tool_calls
    ]

    trial_output = {
        "trial_metadata": {
            "task_id": task_id,
            "mode": mode,
            "trial_id": trial_id,
            "session_id": session_id,
            "run_started_utc": datetime.now(timezone.utc).isoformat(),
            "use_nonce": use_nonce,
            "original_message": original_message,
            "actual_message": user_message,
            "file_path": file_path,
        },
        "state_cleanup": cleanup_result,
        "filesystem_before": fs_before,
        "filesystem_after": fs_after,
        "module_state_before": module_before,
        "module_state_after": module_after,
        "llm_telemetry": llm_telemetry,
        "llm_call_count": len(llm_telemetry),
        "llm_cache_hit_tokens_total": sum(
            (t.get("prompt_cache_hit_tokens") or 0) for t in llm_telemetry
        ),
        "llm_cache_miss_tokens_total": sum(
            (t.get("prompt_cache_miss_tokens") or 0) for t in llm_telemetry
        ),
        "outcome": {
            "tool_chain": tool_names,
            "tool_successes": tool_successes,
            "tool_count": len(tool_names),
            "response_text": response_text,
            "wall_clock_sec": round(total_elapsed, 2),
            "turn_wall_clock_sec": round(turn_elapsed, 2),
        },
        "trace_step_types": {
            "sequence": step_type_sequence,
            "counts": step_type_counts,
            "total_steps": len(step_type_sequence),
        },
        "trace": trace,
    }

    # ── Write output ──────────────────────────────────────────────────
    out_path = output_dir / f"trial_output.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(trial_output, f, ensure_ascii=False, indent=2, default=str)

    # ── Console summary ───────────────────────────────────────────────
    print(json.dumps({
        "task_id": task_id,
        "mode": mode,
        "trial_id": trial_id,
        "session_id": session_id,
        "tool_chain": tool_names,
        "tool_successes": tool_successes,
        "wall_clock_sec": round(total_elapsed, 2),
        "step_count": len(step_type_sequence),
        "step_types_summary": step_type_counts,
        "llm_calls": len(llm_telemetry),
        "cache_hit_tokens": trial_output["llm_cache_hit_tokens_total"],
        "cache_miss_tokens": trial_output["llm_cache_miss_tokens_total"],
        "output_dir": str(output_dir),
    }, ensure_ascii=False, indent=2))

    return trial_output


def main():
    parser = argparse.ArgumentParser(description="Phase 9.1.0 Step 2 — Reproducibility Sampling")
    parser.add_argument("--task-id", type=str, required=True, help="Benchmark task ID")
    parser.add_argument("--mode", type=str, required=True, choices=["governance_full", "naive"])
    parser.add_argument("--trial-id", type=int, required=True, help="Trial number")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="evaluation/results/_temp_phase9_1_0_step2/",
        help="Base output directory",
    )
    parser.add_argument("--no-nonce", action="store_true", help="Disable nonce prefix")
    args = parser.parse_args()

    # Load benchmark
    benchmark = _load_benchmark()
    if args.task_id not in benchmark:
        print(f"ERROR: Task {args.task_id} not found in benchmark", file=sys.stderr)
        sys.exit(1)

    task = benchmark[args.task_id]

    # Build output path: {output_dir}/{task_id}/{mode}/trial_{N}/
    output_dir = (
        Path(args.output_dir) / args.task_id / args.mode / f"trial_{args.trial_id}"
    )

    asyncio.run(run_step2_trial(
        task=task,
        mode=args.mode,
        trial_id=args.trial_id,
        output_dir=output_dir,
        use_nonce=not args.no_nonce,
    ))


if __name__ == "__main__":
    main()
