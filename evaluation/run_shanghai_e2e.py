"""Run 7: Shanghai e2e workflow — macro emission → dispersion → hotspot map.

Phase 9.1.0: Full trace export (not just steps). Output dir configurable via --output-dir.
Phase 9.1.0 Step 1: Multi-trial support (--trial-id) for LLM variance characterization.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.governed_router import GovernedRouter

logger = logging.getLogger(__name__)

SHANGHAI_WORKFLOW_PROMPTS = [
    "请用这个路网文件计算上海地区的CO2和NOx排放，车型是乘用车，季节选夏季",
    "请对刚才的排放结果做扩散模拟",
    "请根据扩散结果分析污染热点，并生成空间地图",
]

# ── Phase 9.1.0: known trace dict top-level keys (from code audit) ──────────
EXPECTED_TRACE_KEYS = [
    "session_id", "start_time", "end_time", "total_duration_ms",
    "final_stage", "step_count", "steps",
    "oasc", "classifier_telemetry", "ao_lifecycle_events", "block_telemetry",
    "reconciled_decision", "b_validator_filter", "projected_chain",
]


def _safe_serialize(obj: Any, max_depth: int = 4, _depth: int = 0) -> Any:
    """Recursively convert trace objects to JSON-safe types with depth limit."""
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


def _extract_full_trace(response) -> Dict[str, Any]:
    """Extract the complete trace dict from a RouterResponse, coercing to JSON-safe types."""
    raw = getattr(response, "trace", None)
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return _safe_serialize(raw)
    return {"_raw": str(raw)[:2000]}


def _dump_llm_config() -> Dict[str, Any]:
    """Capture current LLM configuration for reproducibility audit. No secrets."""
    from config import get_config
    c = get_config()
    return {
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "agent_llm": {
            "provider": c.agent_llm.provider,
            "model": c.agent_llm.model,
            "temperature": c.agent_llm.temperature,
            "max_tokens": c.agent_llm.max_tokens,
        },
        "deepseek": {
            "enable_thinking": c.deepseek_enable_thinking,
            "reasoning_effort": c.deepseek_reasoning_effort,
            "thinking_models": list(c.deepseek_thinking_models),
            "base_url_set": bool(os.environ.get("DEEPSEEK_BASE_URL")),
        },
        "flags_relevant_to_variance": {
            "enable_state_orchestration": c.enable_state_orchestration,
            "enable_llm_decision_field": c.enable_llm_decision_field,
            "enable_conversation_fast_path": c.enable_conversation_fast_path,
            "enable_clarification_contract": getattr(c, "enable_clarification_contract", True),
            "enable_ao_classifier_rule_layer": c.enable_ao_classifier_rule_layer,
            "enable_ao_classifier_llm_layer": c.enable_ao_classifier_llm_layer,
            "enable_execution_idempotency": getattr(c, "enable_execution_idempotency", False),
            "enable_reply_pipeline": getattr(c, "enable_reply_pipeline", True),
            "enable_llm_reply_parser": getattr(c, "enable_llm_reply_parser", True),
        },
        "llm_provider": c.llm_provider,
        "llm_reasoning_model": c.llm_reasoning_model,
    }


def _git_head() -> Optional[str]:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, cwd=str(PROJECT_ROOT), timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return None


async def run_shanghai_workflow(
    output_dir: Path,
    trial_id: Optional[int] = None,
    demo_file: str = "evaluation/file_tasks/data/macro_direct.csv",
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Phase 9.1.0 Step 1: unique session per trial ────────────────────
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    trial_slug = f"trial_{trial_id}" if trial_id else "single"
    session_id = f"shanghai_e2e_{trial_slug}_{ts}"

    # ── Write LLM config metadata BEFORE trial starts ───────────────────
    run_meta = {
        "purpose": "Phase 9.1.0 Step 1 — Run 7 LLM variance characterization",
        "trial_id": trial_id,
        "session_id": session_id,
        "run_started_utc": datetime.now(timezone.utc).isoformat(),
        "git_head": _git_head(),
        "llm_config": _dump_llm_config(),
        "prompts": SHANGHAI_WORKFLOW_PROMPTS,
        "demo_file": demo_file,
    }
    meta_path = output_dir / "run_metadata.json"
    with open(meta_path, "w", encoding="utf-8") as f:
        json.dump(run_meta, f, ensure_ascii=False, indent=2, default=str)

    router = GovernedRouter(session_id=session_id)
    turn_results: List[Dict[str, Any]] = []
    all_tool_calls: List[Dict[str, Any]] = []
    all_trace_steps: List[Dict[str, Any]] = []

    started_at = time.time()
    for turn_idx, prompt in enumerate(SHANGHAI_WORKFLOW_PROMPTS):
        turn_start = time.time()
        file_path = str(PROJECT_ROOT / demo_file) if turn_idx == 0 else None
        response = await router.chat(
            user_message=prompt,
            file_path=file_path,
        )
        turn_elapsed = time.time() - turn_start

        full_trace = _extract_full_trace(response)
        trace_steps = full_trace.get("steps", []) if isinstance(full_trace, dict) else []

        turn_record = {
            "turn": turn_idx + 1,
            "prompt": prompt,
            "response_text": response.text[:500] if response.text else "",
            "tool_calls": response.executed_tool_calls or [],
            "trace": full_trace,
            "wall_clock_sec": round(turn_elapsed, 2),
        }
        turn_results.append(turn_record)

        if response.executed_tool_calls:
            all_tool_calls.extend(response.executed_tool_calls)
        if trace_steps:
            all_trace_steps.extend(trace_steps)

    total_elapsed = time.time() - started_at

    governance_steps: Dict[str, int] = {}
    for step in all_trace_steps:
        if isinstance(step, dict):
            step_type = step.get("step_type") or step.get("type") or "unknown"
        else:
            step_type = str(step)
        governance_steps[step_type] = governance_steps.get(step_type, 0) + 1

    trace_key_presence: Dict[str, List[bool]] = {k: [] for k in EXPECTED_TRACE_KEYS}
    for tr in turn_results:
        t = tr.get("trace")
        for k in EXPECTED_TRACE_KEYS:
            trace_key_presence[k].append(k in t if isinstance(t, dict) else False)

    summary = {
        "workflow": "shanghai_e2e",
        "trial_id": trial_id,
        "session_id": session_id,
        "turns": len(SHANGHAI_WORKFLOW_PROMPTS),
        "total_wall_clock_sec": round(total_elapsed, 2),
        "total_tool_calls": len(all_tool_calls),
        "tool_chain": [tc.get("name") for tc in all_tool_calls],
        "governance_step_counts": governance_steps,
        "trace_key_presence_per_turn": {
            k: v for k, v in trace_key_presence.items() if any(v)
        },
        "trace_key_absent_all_turns": [k for k, v in trace_key_presence.items() if not any(v)],
        "turn_results": turn_results,
    }

    summary_path = output_dir / "shanghai_e2e_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    traces_path = output_dir / "shanghai_e2e_traces.jsonl"
    with open(traces_path, "w", encoding="utf-8") as f:
        for tr in turn_results:
            line = {
                "turn": tr["turn"],
                "prompt": tr["prompt"],
                "tool_calls": tr["tool_calls"],
                "trace": tr["trace"],
                "wall_clock_sec": tr["wall_clock_sec"],
            }
            f.write(json.dumps(line, ensure_ascii=False, default=str) + "\n")

    print(json.dumps({
        "trial_id": trial_id,
        "session_id": session_id,
        "workflow": "shanghai_e2e",
        "turns": len(SHANGHAI_WORKFLOW_PROMPTS),
        "total_wall_clock_sec": round(total_elapsed, 2),
        "tool_chain": summary["tool_chain"],
        "governance_steps": governance_steps,
        "trace_keys_found": sorted(summary["trace_key_presence_per_turn"].keys()),
        "trace_keys_absent": summary["trace_key_absent_all_turns"],
        "output_dir": str(output_dir),
    }, ensure_ascii=False, indent=2))

    return summary


def main():
    parser = argparse.ArgumentParser(description="Run 7: Shanghai e2e workflow")
    parser.add_argument(
        "--output-dir",
        type=str,
        default=None,
        help="Base output directory (default: evaluation/results/_temp_phase9_1_0_run7_recheck/)",
    )
    parser.add_argument(
        "--trial-id",
        type=int,
        default=None,
        help="Trial number (1-5) for variance characterization. Creates trial_{N}/ subdirectory.",
    )
    parser.add_argument(
        "--demo-file",
        type=str,
        default="evaluation/file_tasks/data/macro_direct.csv",
        help="Demo CSV file path relative to project root",
    )
    args = parser.parse_args()

    trial_id = args.trial_id

    if args.output_dir:
        base_dir = Path(args.output_dir)
    elif trial_id is not None:
        base_dir = PROJECT_ROOT / "evaluation" / "results" / "_temp_phase9_1_0_variance"
    else:
        base_dir = PROJECT_ROOT / "evaluation" / "results" / "_temp_phase9_1_0_run7_recheck"

    if trial_id is not None:
        output_dir = base_dir / f"trial_{trial_id}"
    else:
        output_dir = base_dir

    asyncio.run(run_shanghai_workflow(
        output_dir,
        trial_id=trial_id,
        demo_file=args.demo_file,
    ))


if __name__ == "__main__":
    main()
