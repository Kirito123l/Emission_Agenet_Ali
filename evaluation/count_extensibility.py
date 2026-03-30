"""Count current declarative tool-contract footprint and per-tool YAML spans."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List


PROJECT_ROOT = Path(__file__).resolve().parents[1]
TOOL_CONTRACTS_PATH = PROJECT_ROOT / "config" / "tool_contracts.yaml"
DEFINITIONS_PATH = PROJECT_ROOT / "tools" / "definitions.py"
DEPENDENCIES_PATH = PROJECT_ROOT / "core" / "tool_dependencies.py"


def _line_count(path: Path) -> int:
    return len(path.read_text(encoding="utf-8").splitlines())


def _tool_line_spans(path: Path) -> Dict[str, int]:
    lines = path.read_text(encoding="utf-8").splitlines()
    tool_starts: List[tuple[str, int]] = []
    in_tools_block = False

    for index, line in enumerate(lines, start=1):
        if line.startswith("tools:"):
            in_tools_block = True
            continue
        if not in_tools_block:
            continue
        if line and not line.startswith("  "):
            break
        if line.startswith("  ") and not line.startswith("    ") and line.strip().endswith(":"):
            tool_name = line.strip()[:-1]
            tool_starts.append((tool_name, index))

    spans: Dict[str, int] = {}
    for position, (tool_name, start_line) in enumerate(tool_starts):
        end_line = tool_starts[position + 1][1] - 1 if position + 1 < len(tool_starts) else len(lines)
        spans[tool_name] = end_line - start_line + 1
    return spans


def main() -> None:
    payload = {
        "tool_contracts_yaml_lines": _line_count(TOOL_CONTRACTS_PATH),
        "tool_contract_line_spans": _tool_line_spans(TOOL_CONTRACTS_PATH),
        "definitions_py_lines": _line_count(DEFINITIONS_PATH),
        "tool_dependencies_py_lines": _line_count(DEPENDENCIES_PATH),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
