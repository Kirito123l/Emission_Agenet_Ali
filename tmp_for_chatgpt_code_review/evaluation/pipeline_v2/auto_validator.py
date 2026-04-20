"""Multi-layer validation for generated benchmark candidates."""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from evaluation.llm_generator import LLMGenerator
from evaluation.pipeline_v2.common import (
    DEFAULT_BENCHMARK_PATH,
    DEFAULT_CONSTRAINTS_PATH,
    DEFAULT_MAPPINGS_PATH,
    GEOMETRY_REQUIRED_TOOLS,
    VALID_CATEGORIES,
    build_mappings_catalog,
    flatten_constraint_rules,
    flatten_expected_params,
    get_tool_chain,
    load_jsonl_records,
    load_yaml,
    match_constraint_rules,
    normalized_edit_distance,
    save_jsonl,
    task_signature,
)


LLM_REVIEW_PROMPT = """你是一个测试质量审查员。请审查以下测试任务的质量。

任务内容：
- 类别: {category}
- 用户消息: {user_message}
- 期望工具链: {expected_tool_chain}
- 期望参数: {expected_params}
- 成功判定: {success_criteria}
- 描述: {description}

系统背景：
- 系统支持 13 种 MOVES 车型、6 种污染物、4 个季节、5 种道路类型
- 系统有参数标准化功能，能把口语别名映射到标准名
- 系统有跨约束验证（摩托车禁止高速、季节-气象一致性等）
- 系统默认值包括 season=夏季、road_type=快速路、model_year=2020；不同工具的 pollutant 默认略有差异

请回答（严格 JSON）：
{{
  "naturalness": 1-5,
  "params_consistency": true,
  "criteria_reasonable": "yes",
  "controversial_reason": "",
  "testing_capability": "这条任务测试的是什么系统能力",
  "suggested_fix": null
}}"""

LLM_REVIEW_SYSTEM_PROMPT = "你只返回严格 JSON 对象，不要附加解释。"


@dataclass
class LayerResult:
    name: str
    status: str
    issues: List[str] = field(default_factory=list)
    details: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "issues": list(self.issues),
            "details": dict(self.details),
        }


class MultiLayerValidator:
    """Five-layer validator for generated benchmark candidates."""

    def __init__(
        self,
        *,
        benchmark_records: Sequence[Dict[str, Any]],
        mappings_payload: Dict[str, Any],
        constraints_payload: Dict[str, Any],
        model: str = "qwen3-max",
        skip_llm_review: bool = False,
        llm_temperature: float = 0.1,
    ) -> None:
        self.benchmark_records = list(benchmark_records)
        self.catalog = build_mappings_catalog(mappings_payload)
        self.flattened_rules = flatten_constraint_rules(constraints_payload)
        self.constraint_names = {rule["constraint_name"] for rule in self.flattened_rules}
        self.signature_counts = Counter(task_signature(record) for record in self.benchmark_records)
        self.existing_messages = [
            str(record.get("user_message") or "").strip()
            for record in self.benchmark_records
            if str(record.get("user_message") or "").strip()
        ]
        self.skip_llm_review = skip_llm_review
        self.llm_temperature = llm_temperature
        self.llm: Optional[LLMGenerator] = None
        self.llm_init_error: Optional[str] = None
        if not skip_llm_review:
            try:
                self.llm = LLMGenerator(model=model, temperature=llm_temperature, call_interval=1.0)
            except Exception as exc:
                self.llm_init_error = str(exc)

    def validate_all(self, tasks: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
        validated: List[Dict[str, Any]] = []
        running_signature_counts = Counter(self.signature_counts)
        for task in tasks:
            record = self.validate(task, signature_counts=running_signature_counts)
            running_signature_counts[task_signature(task)] += 1
            validated.append(record)
        return validated

    def validate(self, task: Dict[str, Any], *, signature_counts: Optional[Counter] = None) -> Dict[str, Any]:
        signature_counts = signature_counts or self.signature_counts
        layers = [
            self.layer1_structure(task),
            self.layer2_params(task),
            self.layer3_constraints(task),
            self.layer4_dedup(task, signature_counts),
            self.layer5_llm_review(task),
        ]
        status = self._aggregate(layers)
        issues = [issue for layer in layers for issue in layer.issues]
        output = dict(task)
        output["validation"] = {
            "status": status,
            "issues": issues,
            "layers": {layer.name: layer.to_dict() for layer in layers},
        }
        return output

    def layer1_structure(self, task: Dict[str, Any]) -> LayerResult:
        issues: List[str] = []
        required = ("id", "category", "user_message", "expected_tool_chain", "expected_params", "success_criteria")
        for key in required:
            if key not in task:
                issues.append(f"Missing required field: {key}")
        if task.get("category") not in VALID_CATEGORIES:
            issues.append(f"Invalid category: {task.get('category')}")
        if not str(task.get("user_message") or "").strip():
            issues.append("user_message is empty")
        if not isinstance(task.get("expected_tool_chain"), list):
            issues.append("expected_tool_chain must be a list")
        if not isinstance(task.get("expected_params"), dict):
            issues.append("expected_params must be a dict")
        if not isinstance(task.get("success_criteria"), dict):
            issues.append("success_criteria must be a dict")
        if task.get("has_file") and not task.get("test_file"):
            issues.append("has_file=true requires test_file")
        follow_up_messages = task.get("follow_up_messages")
        if follow_up_messages is not None:
            if not isinstance(follow_up_messages, list):
                issues.append("follow_up_messages must be a list when provided")
            elif not all(str(message or "").strip() for message in follow_up_messages):
                issues.append("follow_up_messages entries must be non-empty strings")
        return LayerResult("structure", "invalid" if issues else "pass", issues)

    def layer2_params(self, task: Dict[str, Any]) -> LayerResult:
        issues: List[str] = []
        details: Dict[str, Any] = {}
        params = flatten_expected_params(task)

        allowed = {
            "vehicle_type": set(self.catalog["vehicle_types"]),
            "pollutant": set(self.catalog["pollutants"]),
            "season": set(self.catalog["seasons"]),
            "road_type": set(self.catalog["road_types"]),
            "meteorology": set(self.catalog["meteorology_presets"]),
            "stability_class": set(self.catalog["stability_classes"]),
        }

        vehicle_type = params.get("vehicle_type")
        if vehicle_type is not None and str(vehicle_type) not in allowed["vehicle_type"]:
            issues.append(f"vehicle_type must be a MOVES standard name: {vehicle_type}")

        pollutants = []
        if params.get("pollutant"):
            pollutants.append(params["pollutant"])
        pollutants.extend(params.get("pollutants", []) or [])
        for pollutant in pollutants:
            if str(pollutant) not in allowed["pollutant"]:
                issues.append(f"Unsupported pollutant: {pollutant}")

        for name in ("season", "road_type", "meteorology", "stability_class"):
            value = params.get(name)
            if name == "meteorology" and value == "custom":
                continue
            if value is not None and str(value) not in allowed[name]:
                issues.append(f"Unsupported {name}: {value}")

        model_year = params.get("model_year")
        if model_year is not None:
            try:
                year = int(model_year)
                details["model_year"] = year
                if year < 1995 or year > 2025:
                    issues.append(f"model_year out of supported range 1995-2025: {model_year}")
            except (TypeError, ValueError):
                issues.append(f"model_year must be an integer: {model_year}")

        return LayerResult("params", "invalid" if issues else "pass", issues, details)

    def layer3_constraints(self, task: Dict[str, Any]) -> LayerResult:
        issues: List[str] = []
        details: Dict[str, Any] = {}
        category = task.get("category")
        chain = get_tool_chain(task)
        success_criteria = task.get("success_criteria") if isinstance(task.get("success_criteria"), dict) else {}
        metadata = task.get("candidate_metadata") if isinstance(task.get("candidate_metadata"), dict) else {}
        declared_constraints = metadata.get("violated_constraints", []) or []
        if isinstance(declared_constraints, str):
            declared_constraints = [declared_constraints]
        declared_constraints = [str(item) for item in declared_constraints if str(item).strip()]
        unknown_constraints = sorted(name for name in declared_constraints if name not in self.constraint_names)
        if unknown_constraints:
            issues.append(f"violated_constraints not backed by cross_constraints.yaml: {unknown_constraints}")

        matched_rules = match_constraint_rules(task, self.flattened_rules, self.catalog)
        details["matched_rules"] = matched_rules
        details["declared_constraints"] = declared_constraints

        if category == "constraint_violation":
            if not declared_constraints and not matched_rules:
                issues.append("constraint_violation task should match or declare at least one real cross-constraint rule")
            warning_expected = bool(success_criteria.get("constraint_warning"))
            blocked_expected = bool(success_criteria.get("constraint_blocked"))
            needs_user = bool(success_criteria.get("requires_user_response"))
            if warning_expected and not chain:
                issues.append("warning-only constraint tasks must keep a runnable expected_tool_chain")
            if (blocked_expected or needs_user) and chain:
                issues.append("blocked/negotiate constraint tasks should not execute tools before resolution")
            if not (warning_expected or blocked_expected or needs_user):
                issues.append("constraint_violation task must expect warning, block, or user negotiation")
        elif matched_rules:
            issues.append(f"Non-constraint task appears to trigger cross-constraint rules: {matched_rules}")

        status = "needs_review" if issues else "pass"
        return LayerResult("constraints", status, issues, details)

    def layer4_dedup(self, task: Dict[str, Any], signature_counts: Counter) -> LayerResult:
        issues: List[str] = []
        message = str(task.get("user_message") or "").strip()
        details: Dict[str, Any] = {}
        if message and self.existing_messages:
            best_distance = min(normalized_edit_distance(message, existing) for existing in self.existing_messages)
            details["min_message_distance"] = round(best_distance, 4)
            if best_distance < 0.3:
                issues.append(f"Potential near-duplicate user_message; normalized edit distance={best_distance:.3f}")

        signature = task_signature(task)
        existing_count = int(signature_counts.get(signature, 0))
        details["existing_signature_count"] = existing_count
        if existing_count >= 3:
            issues.append(f"Same parameter/tool signature already appears {existing_count} times")

        return LayerResult("dedup", "needs_review" if issues else "pass", issues, details)

    def layer5_llm_review(self, task: Dict[str, Any]) -> LayerResult:
        if self.skip_llm_review:
            return LayerResult("llm_review", "skipped", details={"reason": "skip_llm_review=true"})
        if self.llm is None:
            return LayerResult(
                "llm_review",
                "needs_review",
                [f"LLM review unavailable: {self.llm_init_error or 'unknown initialization error'}"],
            )

        prompt = LLM_REVIEW_PROMPT.format(
            category=task.get("category"),
            user_message=task.get("user_message"),
            expected_tool_chain=json.dumps(task.get("expected_tool_chain", []), ensure_ascii=False),
            expected_params=json.dumps(task.get("expected_params", {}), ensure_ascii=False),
            success_criteria=json.dumps(task.get("success_criteria", {}), ensure_ascii=False),
            description=task.get("description"),
        )
        try:
            review = self.llm.generate_json(LLM_REVIEW_SYSTEM_PROMPT, prompt, temperature=self.llm_temperature)
        except Exception as exc:
            return LayerResult("llm_review", "needs_review", [f"LLM review call failed: {exc}"])
        if not isinstance(review, dict):
            return LayerResult("llm_review", "needs_review", ["LLM review returned no JSON object"])

        issues: List[str] = []
        try:
            naturalness = int(review.get("naturalness", 0))
        except (TypeError, ValueError):
            naturalness = 0
        if naturalness < 3:
            issues.append(f"LLM naturalness score too low: {naturalness}")
        if review.get("params_consistency") is False:
            issues.append("LLM says expected_params are inconsistent with user_message")
        criteria = str(review.get("criteria_reasonable") or "").strip().lower()
        if criteria in {"no", "false"}:
            issues.append("LLM says success_criteria are unreasonable")
        if criteria == "controversial":
            issues.append("LLM marked success_criteria controversial")
        if review.get("suggested_fix"):
            issues.append("LLM suggested a fix")

        return LayerResult("llm_review", "needs_review" if issues else "pass", issues, {"review": review})

    @staticmethod
    def _aggregate(layers: Sequence[LayerResult]) -> str:
        if any(layer.status == "invalid" for layer in layers):
            return "invalid"
        if any(layer.status == "needs_review" for layer in layers):
            return "needs_review"
        return "valid"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate benchmark candidate tasks with five independent layers.")
    parser.add_argument("--candidates", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, default=DEFAULT_BENCHMARK_PATH)
    parser.add_argument("--mappings", type=Path, default=DEFAULT_MAPPINGS_PATH)
    parser.add_argument("--constraints", type=Path, default=DEFAULT_CONSTRAINTS_PATH)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", default="qwen3-max")
    parser.add_argument("--llm-temperature", type=float, default=0.1)
    parser.add_argument("--skip-llm-review", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    candidates = load_jsonl_records(args.candidates)
    benchmark_records = load_jsonl_records(args.benchmark)
    validator = MultiLayerValidator(
        benchmark_records=benchmark_records,
        mappings_payload=load_yaml(args.mappings),
        constraints_payload=load_yaml(args.constraints),
        model=args.model,
        skip_llm_review=args.skip_llm_review,
        llm_temperature=args.llm_temperature,
    )
    validated = validator.validate_all(candidates)
    save_jsonl(args.output, validated)
    status_counts = Counter((record.get("validation") or {}).get("status", "unknown") for record in validated)
    print(json.dumps({"validated": len(validated), "status_counts": status_counts}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
