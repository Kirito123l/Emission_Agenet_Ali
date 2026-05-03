"""Run 7: Shanghai e2e workflow — macro emission → dispersion → hotspot map."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.governed_router import GovernedRouter


SHANGHAI_WORKFLOW_PROMPTS = [
    "请用这个路网文件计算上海地区的CO2和NOx排放，车型是乘用车，季节选夏季",
    "请对刚才的排放结果做扩散模拟",
    "请根据扩散结果分析污染热点，并生成空间地图",
]


async def run_shanghai_workflow(
    output_dir: Path,
    demo_file: str = "evaluation/file_tasks/data/macro_direct.csv",
) -> Dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    router = GovernedRouter(session_id="shanghai_e2e_demo")
    trace_steps_all: List[Dict[str, Any]] = []
    tool_calls_all: List[Dict[str, Any]] = []
    turn_results: List[Dict[str, Any]] = []

    started_at = time.time()
    for turn_idx, prompt in enumerate(SHANGHAI_WORKFLOW_PROMPTS):
        turn_start = time.time()
        file_path = str(PROJECT_ROOT / demo_file) if turn_idx == 0 else None
        response = await router.chat(
            user_message=prompt,
            file_path=file_path,
        )
        turn_elapsed = time.time() - turn_start

        turn_record = {
            "turn": turn_idx + 1,
            "prompt": prompt,
            "response_text": response.text[:500] if response.text else "",
            "tool_calls": response.executed_tool_calls or [],
            "trace_steps": response.trace.get("steps", []) if response.trace else [],
            "wall_clock_sec": round(turn_elapsed, 2),
        }
        turn_results.append(turn_record)

        if response.executed_tool_calls:
            tool_calls_all.extend(response.executed_tool_calls)
        if response.trace and response.trace.get("steps"):
            trace_steps_all.extend(response.trace["steps"])

    total_elapsed = time.time() - started_at

    governance_steps = {}
    for step in trace_steps_all:
        step_type = step.get("step_type") if isinstance(step, dict) else step
        governance_steps[step_type] = governance_steps.get(step_type, 0) + 1

    summary = {
        "workflow": "shanghai_e2e",
        "turns": len(SHANGHAI_WORKFLOW_PROMPTS),
        "total_wall_clock_sec": round(total_elapsed, 2),
        "total_tool_calls": len(tool_calls_all),
        "tool_chain": [tc.get("name") for tc in tool_calls_all],
        "governance_step_counts": governance_steps,
        "turn_results": turn_results,
    }

    summary_path = output_dir / "shanghai_e2e_summary.json"
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(summary, f, ensure_ascii=False, indent=2, default=str)

    traces_path = output_dir / "shanghai_e2e_traces.jsonl"
    with open(traces_path, "w", encoding="utf-8") as f:
        for step in trace_steps_all:
            f.write(json.dumps(step, ensure_ascii=False, default=str) + "\n")

    print(json.dumps({
        "workflow": "shanghai_e2e",
        "turns": len(SHANGHAI_WORKFLOW_PROMPTS),
        "total_wall_clock_sec": round(total_elapsed, 2),
        "tool_chain": summary["tool_chain"],
        "governance_steps": governance_steps,
    }, ensure_ascii=False, indent=2))

    return summary


def main():
    output_dir = PROJECT_ROOT / "evaluation" / "results" / "phase8_2_2_c2" / "run7_shanghai_e2e"
    asyncio.run(run_shanghai_workflow(output_dir))


if __name__ == "__main__":
    main()
