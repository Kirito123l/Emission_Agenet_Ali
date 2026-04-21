from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict, List, Optional

import yaml

from core.contracts.clarification_contract import ClarificationContract


class SplitContractSupport(ClarificationContract):
    """Shared Wave 2 helpers while the legacy ClarificationContract remains intact."""

    @staticmethod
    def _stage2_system_prompt() -> str:
        return (
            "你是交通排放分析的紧凑意图与参数补全器。输出 JSON，不要解释。\n"
            "规则: 只基于用户明确表达、文件上下文或强常识映射填 slots；不要编造 model_year，未知用 null/source=missing。"
            "口语车型/道路/季节/污染物可标准化，raw_text 保留原词。缺必需槽位时 needs_clarification=true 并给一句问题。"
            "如果用户表达多步链路，输出 chain，使用 canonical tool names，按执行顺序列出。"
            "输出格式: {slots:{slot:{value,source,confidence,raw_text}},intent:{tool,conf},stance:{value,conf},chain:[],"
            "missing_required:[],needs_clarification:false,clarification_question:\"\",ambiguous_slots:[]}。"
            "intent.conf 取 high/low/none；stance.value 取 directive/deliberative/exploratory；stance.conf 取 high/medium/low。"
            "不要输出 intent.reasoning 或 stance.reasoning。value 禁止使用 missing/unknown/none/n/a/null 字符串。"
        )

    async def _run_stage2_llm_with_telemetry(
        self,
        *,
        user_message: str,
        state: Any,
        current_ao: Any,
        tool_name: Optional[str],
        snapshot: Dict[str, Dict[str, Any]],
        tool_spec: Dict[str, Any],
        classification: Any,
    ) -> tuple[Dict[str, Any], Dict[str, Any]]:
        prompt_payload = {
            "user_message": user_message,
            "tool_name": tool_name,
            "available_tools": self._available_tool_intent_descriptions(),
            "file_context": {
                "has_file": bool(getattr(state.file_context, "has_file", False)),
                "task_type": getattr(state.file_context, "task_type", None),
                "file_path": getattr(state.file_context, "file_path", None),
            },
            "current_ao_id": getattr(current_ao, "ao_id", None) if current_ao is not None else None,
            "classification": classification.classification.name if classification is not None else None,
            "existing_parameter_snapshot": snapshot,
            "tool_slots": {
                "required_slots": list(tool_spec.get("required_slots") or []),
                "optional_slots": list(tool_spec.get("optional_slots") or []),
                "defaults": dict(tool_spec.get("defaults") or {}),
                "clarification_followup_slots": list(tool_spec.get("clarification_followup_slots") or []),
            },
            "legal_values": self._build_legal_values(tool_spec),
        }
        user_content = yaml.safe_dump(prompt_payload, allow_unicode=True, sort_keys=False)
        system_prompt = self._stage2_system_prompt()
        started = time.perf_counter()
        client_call = getattr(self.llm_client, "chat_json_with_metadata", None)
        if client_call is not None:
            result = await asyncio.wait_for(
                client_call(
                    messages=[{"role": "user", "content": user_content}],
                    system=system_prompt,
                    temperature=0.0,
                ),
                timeout=float(getattr(self.runtime_config, "clarification_llm_timeout_sec", 5.0)),
            )
            payload = dict(result.get("payload") or {})
            raw_response = str(result.get("raw_response") or "")
            usage = dict(result.get("usage") or {})
        else:
            payload = await asyncio.wait_for(
                self.llm_client.chat_json(
                    messages=[{"role": "user", "content": user_content}],
                    system=system_prompt,
                    temperature=0.0,
                ),
                timeout=float(getattr(self.runtime_config, "clarification_llm_timeout_sec", 5.0)),
            )
            raw_response = json.dumps(payload, ensure_ascii=False)
            usage = {}
        intent_raw = payload.get("intent") if isinstance(payload.get("intent"), dict) else None
        stance_raw = payload.get("stance") if isinstance(payload.get("stance"), dict) else None
        return payload, {
            "stage2_called": True,
            "stage2_latency_ms": round((time.perf_counter() - started) * 1000, 2),
            "stage2_response_chars": len(raw_response),
            "stage2_intent_chars": len(json.dumps(intent_raw, ensure_ascii=False)) if intent_raw else 0,
            "stage2_stance_chars": len(json.dumps(stance_raw, ensure_ascii=False)) if stance_raw else 0,
            "stage2_prompt_tokens": usage.get("prompt_tokens"),
            "stage2_completion_tokens": usage.get("completion_tokens"),
            "stage2_raw_response_truncated": raw_response[:1500] if raw_response else None,
            "stage2_missing_required": list(payload.get("missing_required") or []),
            "stage2_clarification_question": str(payload.get("clarification_question") or "").strip() or None,
        }

    def _standardize_slot(
        self,
        slot_name: str,
        *,
        value: Any,
        raw_text: Any,
    ) -> tuple[Any, bool, str, List[str]]:
        canonical, canonical_ok = self._accept_already_canonical(slot_name, value)
        if canonical_ok:
            return canonical, True, "already_canonical", []
        if slot_name in {"pollutants", "pollutant"}:
            normalized, success = self._standardize_pollutant_value(value if raw_text in (None, "", []) else raw_text)
            if success:
                if slot_name == "pollutant" and isinstance(normalized, list):
                    normalized = normalized[0] if normalized else None
                return normalized, True, "pollutant_list_fallback", []
        return super()._standardize_slot(slot_name, value=value, raw_text=raw_text)

    def _accept_already_canonical(self, slot_name: str, value: Any) -> tuple[Any, bool]:
        if slot_name not in {"vehicle_type", "pollutants", "pollutant", "road_type", "season"}:
            return value, False
        legal_values = self._build_legal_values({"required_slots": [slot_name], "optional_slots": []}).get(slot_name)
        if not legal_values:
            return value, False
        legal_set = {str(item) for item in legal_values}
        if slot_name == "pollutants":
            values = value if isinstance(value, list) else [value]
            if values and all(str(item) in legal_set for item in values):
                return list(values), True
            return value, False
        if slot_name == "pollutant":
            if isinstance(value, list):
                if len(value) == 1 and str(value[0]) in legal_set:
                    return value[0], True
                return value, False
            return value, str(value) in legal_set
        return value, str(value) in legal_set

    @staticmethod
    def _standardize_pollutant_value(value: Any) -> tuple[Any, bool]:
        alias = {
            "co2": "CO2",
            "co₂": "CO2",
            "二氧化碳": "CO2",
            "nox": "NOx",
            "no x": "NOx",
            "氮氧": "NOx",
            "氮氧化物": "NOx",
            "pm25": "PM2.5",
            "pm2.5": "PM2.5",
            "pm2_5": "PM2.5",
            "pm 2.5": "PM2.5",
            "pm10": "PM10",
            "pm 10": "PM10",
            "co": "CO",
            "一氧化碳": "CO",
            "thc": "THC",
            "hc": "THC",
            "总烃": "THC",
        }
        suffix_tokens = ("emissions", "emission", "factor", "排放", "因子")
        values = value if isinstance(value, list) else [value]
        normalized: List[Any] = []
        ok = True
        for item in values:
            if not isinstance(item, str):
                normalized.append(item)
                continue
            cleaned = item.strip()
            lowered = cleaned.lower()
            for suffix in suffix_tokens:
                suffix_lower = suffix.lower()
                if lowered.endswith(suffix_lower):
                    cleaned = cleaned[: -len(suffix)].strip()
                    lowered = cleaned.lower()
                    break
            key = cleaned.lower().replace(" ", "")
            key = key.replace("p.m.", "pm")
            mapped = alias.get(key)
            if mapped is None:
                ok = False
                normalized.append(item)
            else:
                normalized.append(mapped)
        return normalized, ok
