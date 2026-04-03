"""Session-scoped structured result storage with scenario versioning."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.tool_dependencies import normalize_result_token

logger = logging.getLogger(__name__)

MAX_SUMMARY_CHARS = 500
MAX_CONTEXT_SUMMARY_CHARS = 500


@dataclass
class StoredResult:
    """One successful tool result stored with semantic type and scenario label."""

    result_type: str
    tool_name: str
    label: str
    timestamp: str
    summary: str
    data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def compact(self) -> Dict[str, Any]:
        """Return an LLM-safe compact representation without raw payloads."""
        return {
            "type": self.result_type,
            "tool": self.tool_name,
            "label": self.label,
            "summary": self.summary,
            "metadata": self.metadata,
        }

    def to_persisted_dict(self) -> Dict[str, Any]:
        """Return a disk-safe representation including the full payload."""
        return {
            "result_type": self.result_type,
            "tool_name": self.tool_name,
            "label": self.label,
            "timestamp": self.timestamp,
            "summary": self.summary,
            "data": self.data,
            "metadata": self.metadata,
        }

    @classmethod
    def from_persisted_dict(cls, payload: Dict[str, Any]) -> "StoredResult":
        return cls(
            result_type=str(payload.get("result_type") or "unknown"),
            tool_name=str(payload.get("tool_name") or "unknown"),
            label=str(payload.get("label") or SessionContextStore.BASELINE_LABEL),
            timestamp=str(payload.get("timestamp") or datetime.now().isoformat()),
            summary=str(payload.get("summary") or ""),
            data=payload.get("data") if isinstance(payload.get("data"), dict) else {},
            metadata=payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {},
        )


class SessionContextStore:
    """
    Keep semantic tool results for the active router/session instance.

    Results are keyed by semantic type + scenario label so downstream tools can
    resolve the correct upstream data without depending on "the last result".
    """

    BASELINE_LABEL = "baseline"
    MAX_SCENARIOS = 5

    TOOL_TO_RESULT_TYPE = {
        "calculate_macro_emission": "emission",
        "calculate_micro_emission": "emission",
        "calculate_dispersion": "dispersion",
        "analyze_hotspots": "hotspot",
        "render_spatial_map": "visualization",
        "compare_scenarios": "scenario_comparison",
        "analyze_file": "file_analysis",
        "query_emission_factors": "emission_factors",
        "query_knowledge": "knowledge",
    }

    TOOL_DEPENDENCIES: Dict[str, Any] = {
        "calculate_dispersion": ["emission"],
        "analyze_hotspots": ["dispersion"],
        "render_spatial_map": {
            "emission": ["emission"],
            "dispersion": ["dispersion"],
            "raster": ["dispersion"],
            "concentration": ["dispersion"],
            "contour": ["dispersion"],
            "hotspot": ["hotspot"],
            "_default": ["hotspot", "dispersion", "emission"],
        },
    }

    def __init__(self) -> None:
        self._store: Dict[str, StoredResult] = {}
        self._history: List[StoredResult] = []
        self._current_turn_results: List[Dict[str, Any]] = []

    def store_result(self, tool_name: str, result: Dict[str, Any]) -> Optional[StoredResult]:
        """Store one successful tool result under semantic type + scenario label."""
        if not isinstance(result, dict) or not result.get("success"):
            return None

        result_type = self.TOOL_TO_RESULT_TYPE.get(tool_name, "unknown")
        label = self._extract_label(result)
        stored = StoredResult(
            result_type=result_type,
            tool_name=tool_name,
            label=label,
            timestamp=datetime.now().isoformat(),
            summary=self._build_summary(tool_name, result),
            data=result,
            metadata=self._build_metadata(tool_name, result, label),
        )

        key = self._make_key(result_type, label)
        self._store[key] = stored
        self._history.append(stored)
        self._enforce_scenario_limit(result_type)

        if result_type == "emission":
            self._invalidate_dependents(label, ["dispersion", "hotspot"])
        elif result_type == "dispersion":
            self._invalidate_dependents(label, ["hotspot"])

        logger.info(
            "Context store: saved %s from %s with metadata=%s",
            key,
            tool_name,
            stored.metadata,
        )
        return stored

    def get_result_for_tool(
        self,
        requesting_tool: str,
        *,
        label: Optional[str] = None,
        **kwargs: Any,
    ) -> Optional[Dict[str, Any]]:
        """Return the best full tool result payload for a downstream tool."""
        deps = self.TOOL_DEPENDENCIES.get(requesting_tool)
        if deps is None:
            return None

        if isinstance(deps, dict):
            layer_type = normalize_result_token(kwargs.get("layer_type")) or str(
                kwargs.get("layer_type") or ""
            ).strip().lower()
            needed_types = deps.get(layer_type, deps.get("_default", []))
        else:
            needed_types = deps

        requested_label = str(label).strip() if label else None
        for result_type in needed_types:
            current_turn = self._find_current_turn_result(result_type, label=requested_label)
            if current_turn is not None:
                logger.info(
                    "Context store: providing current-turn %s%s data to %s",
                    result_type,
                    f":{requested_label}" if requested_label else "",
                    requesting_tool,
                )
                return current_turn

            stored = self.get_by_type(result_type, label=requested_label)
            if stored is not None and stored.data:
                logger.info(
                    "Context store: providing stored %s:%s data to %s",
                    result_type,
                    stored.label,
                    requesting_tool,
                )
                return stored.data

            if requested_label and requested_label != self.BASELINE_LABEL:
                baseline = self.get_by_type(result_type, label=self.BASELINE_LABEL)
                if baseline is not None and baseline.data:
                    logger.info(
                        "Context store: falling back to %s:%s for %s",
                        result_type,
                        self.BASELINE_LABEL,
                        requesting_tool,
                    )
                    return baseline.data

        logger.warning(
            "Context store: no data found for %s (needed=%s, label=%s, available=%s)",
            requesting_tool,
            needed_types,
            requested_label or self.BASELINE_LABEL,
            sorted(self._store.keys()),
        )
        return None

    def get_latest(self) -> Optional[StoredResult]:
        return self._history[-1] if self._history else None

    def get_by_type(self, result_type: str, label: Optional[str] = None) -> Optional[StoredResult]:
        """Return one stored result, defaulting to baseline when available."""
        result_type = normalize_result_token(result_type) or result_type
        requested_label = str(label).strip() if label else None
        if requested_label:
            return self._store.get(self._make_key(result_type, requested_label))

        baseline = self._store.get(self._make_key(result_type, self.BASELINE_LABEL))
        if baseline is not None:
            return baseline

        candidates = [item for item in self._store.values() if item.result_type == result_type]
        if not candidates:
            return None
        return max(candidates, key=lambda item: item.timestamp)

    def has_result(self, result_type: str, label: Optional[str] = None) -> bool:
        return self.get_by_type(result_type, label=label) is not None

    def get_scenario_pair(
        self,
        result_type: str,
        baseline: str,
        scenario: str,
    ) -> tuple[Optional[Dict[str, Any]], Optional[Dict[str, Any]]]:
        result_type = normalize_result_token(result_type) or result_type
        baseline_stored = self.get_by_type(result_type, label=baseline)
        scenario_stored = self.get_by_type(result_type, label=scenario)
        return (
            baseline_stored.data if baseline_stored is not None else None,
            scenario_stored.data if scenario_stored is not None else None,
        )

    def list_scenarios(self, result_type: Optional[str] = None) -> Dict[str, List[str]]:
        grouped: Dict[str, List[str]] = {}
        for stored in self._store.values():
            if result_type and stored.result_type != result_type:
                continue
            grouped.setdefault(stored.result_type, [])
            if stored.label not in grouped[stored.result_type]:
                grouped[stored.result_type].append(stored.label)

        for labels in grouped.values():
            labels.sort(key=lambda item: (item != self.BASELINE_LABEL, item))
        return grouped

    def get_context_summary(self) -> str:
        """Build a compact session summary safe for LLM context."""
        if not self._store:
            return ""

        lines = ["[Available session analysis results]"]
        grouped: Dict[str, List[StoredResult]] = {}
        for stored in self._store.values():
            grouped.setdefault(stored.result_type, []).append(stored)

        for result_type in sorted(grouped.keys()):
            stored_items = sorted(
                grouped[result_type],
                key=lambda item: (item.label != self.BASELINE_LABEL, item.label),
            )
            if len(stored_items) == 1:
                item = stored_items[0]
                stale = " [stale]" if item.metadata.get("stale") else ""
                lines.append(f"- {result_type}[{item.label}]{stale}: {item.summary}")
                continue

            labels_desc = []
            for item in stored_items:
                label_text = item.label + ("*" if item.metadata.get("stale") else "")
                labels_desc.append(f"{label_text}={item.summary}")
            lines.append(f"- {result_type}: " + " | ".join(labels_desc))

        summary = "\n".join(lines)
        if len(summary) <= MAX_CONTEXT_SUMMARY_CHARS:
            return summary
        return summary[: MAX_CONTEXT_SUMMARY_CHARS - 3].rstrip() + "..."

    def get_available_types(self, include_stale: bool = False) -> set[str]:
        available = set()
        for item in self._current_turn_results:
            result_type = normalize_result_token(item.get("result_type")) or item.get("result_type")
            if not result_type:
                continue
            label = str(item.get("label") or self.BASELINE_LABEL)
            stored = self._store.get(self._make_key(result_type, label))
            if stored is not None and stored.metadata.get("stale") and not include_stale:
                continue
            available.add(result_type)
        for stored in self._store.values():
            if stored.metadata.get("stale") and not include_stale:
                continue
            available.add(stored.result_type)
        return available

    def get_result_availability(
        self,
        result_type: str,
        *,
        label: Optional[str] = None,
        include_stale: bool = False,
    ) -> Dict[str, Any]:
        """Describe whether one semantic result token is currently usable."""
        result_type = normalize_result_token(result_type) or result_type
        requested_label = str(label).strip() if label else None

        def _availability_payload(
            *,
            available: bool,
            stale: bool,
            source: str,
            resolved_label: Optional[str],
        ) -> Dict[str, Any]:
            return {
                "token": result_type,
                "available": available,
                "stale": stale,
                "source": source,
                "label": resolved_label,
            }

        if requested_label:
            current_turn_entry = self._find_current_turn_entry(result_type, label=requested_label)
            if current_turn_entry is not None:
                entry_label = str(current_turn_entry.get("label") or requested_label or self.BASELINE_LABEL)
                stored_current = self._store.get(self._make_key(result_type, entry_label))
                is_stale = bool(stored_current.metadata.get("stale")) if stored_current is not None else False
                return _availability_payload(
                    available=include_stale or not is_stale,
                    stale=is_stale,
                    source="current_turn",
                    resolved_label=entry_label,
                )

            stored_exact = self._store.get(self._make_key(result_type, requested_label))
            if stored_exact is not None:
                is_stale = bool(stored_exact.metadata.get("stale"))
                return _availability_payload(
                    available=include_stale or not is_stale,
                    stale=is_stale,
                    source="stored_exact",
                    resolved_label=stored_exact.label,
                )

            if requested_label != self.BASELINE_LABEL:
                current_turn_entry = self._find_current_turn_entry(result_type, label=self.BASELINE_LABEL)
                if current_turn_entry is not None:
                    stored_current = self._store.get(self._make_key(result_type, self.BASELINE_LABEL))
                    is_stale = bool(stored_current.metadata.get("stale")) if stored_current is not None else False
                    return _availability_payload(
                        available=include_stale or not is_stale,
                        stale=is_stale,
                        source="current_turn_baseline_fallback",
                        resolved_label=self.BASELINE_LABEL,
                    )

                stored_baseline = self._store.get(self._make_key(result_type, self.BASELINE_LABEL))
                if stored_baseline is not None:
                    is_stale = bool(stored_baseline.metadata.get("stale"))
                    return _availability_payload(
                        available=include_stale or not is_stale,
                        stale=is_stale,
                        source="stored_baseline_fallback",
                        resolved_label=stored_baseline.label,
                    )

            return _availability_payload(
                available=False,
                stale=False,
                source="unavailable",
                resolved_label=requested_label,
            )

        current_turn_entry = self._find_current_turn_entry(result_type)
        if current_turn_entry is not None:
            entry_label = str(current_turn_entry.get("label") or self.BASELINE_LABEL)
            stored_current = self._store.get(self._make_key(result_type, entry_label))
            is_stale = bool(stored_current.metadata.get("stale")) if stored_current is not None else False
            return _availability_payload(
                available=include_stale or not is_stale,
                stale=is_stale,
                source="current_turn",
                resolved_label=entry_label,
            )

        stored_default = self.get_by_type(result_type)
        if stored_default is None:
            return _availability_payload(
                available=False,
                stale=False,
                source="unavailable",
                resolved_label=None,
            )

        is_stale = bool(stored_default.metadata.get("stale"))
        return _availability_payload(
            available=include_stale or not is_stale,
            stale=is_stale,
            source="stored",
            resolved_label=stored_default.label,
        )

    def add_current_turn_result(self, tool_name: str, result: Dict[str, Any]) -> None:
        entry = {
            "name": tool_name,
            "result": result,
            "result_type": self.TOOL_TO_RESULT_TYPE.get(tool_name, "unknown"),
            "label": self._extract_label(result),
        }
        self._current_turn_results.append(entry)
        if isinstance(result, dict) and result.get("success"):
            self.store_result(tool_name, result)

    def get_current_turn_results(self) -> List[Dict[str, Any]]:
        return list(self._current_turn_results)

    def clear_current_turn(self) -> None:
        self._current_turn_results = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "results": {key: value.compact() for key, value in self._store.items()},
            "history_count": len(self._history),
        }

    def to_persisted_dict(self) -> Dict[str, Any]:
        return {
            "store": {key: value.to_persisted_dict() for key, value in self._store.items()},
            "history": [value.to_persisted_dict() for value in self._history],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SessionContextStore":
        """Restore compact metadata only; full payloads are kept in memory only."""
        store = cls()
        results = data.get("results", {})
        if not isinstance(results, dict):
            return store

        for key, compact in results.items():
            if not isinstance(compact, dict):
                continue
            label = str(compact.get("label") or cls.BASELINE_LABEL)
            result_type = str(compact.get("type") or key.split(":", 1)[0])
            store._store[key] = StoredResult(
                result_type=result_type,
                tool_name=str(compact.get("tool") or "unknown"),
                label=label,
                timestamp=datetime.now().isoformat(),
                summary=str(compact.get("summary") or ""),
                data={},
                metadata=compact.get("metadata", {}) if isinstance(compact.get("metadata"), dict) else {},
            )
        return store

    @classmethod
    def from_persisted_dict(cls, data: Dict[str, Any]) -> "SessionContextStore":
        """Restore full persisted payloads for session reuse across process restarts."""
        store = cls()
        payload_store = data.get("store", {})
        payload_history = data.get("history", [])

        if isinstance(payload_store, dict):
            for key, payload in payload_store.items():
                if not isinstance(payload, dict):
                    continue
                store._store[str(key)] = StoredResult.from_persisted_dict(payload)

        if isinstance(payload_history, list):
            for payload in payload_history:
                if not isinstance(payload, dict):
                    continue
                store._history.append(StoredResult.from_persisted_dict(payload))

        if not store._history and store._store:
            store._history = list(store._store.values())
        return store

    def _extract_label(self, result: Dict[str, Any]) -> str:
        data = result.get("data", {})
        if isinstance(data, dict):
            label = data.get("scenario_label")
            if isinstance(label, str) and label.strip():
                return label.strip()
        return self.BASELINE_LABEL

    def _make_key(self, result_type: str, label: str) -> str:
        return f"{result_type}:{label}"

    def _find_current_turn_result(
        self,
        result_type: str,
        *,
        label: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        entry = self._find_current_turn_entry(result_type, label=label)
        if entry is None:
            return None
        result = entry.get("result")
        if isinstance(result, dict) and result.get("success"):
            return result
        return None

    def _find_current_turn_entry(
        self,
        result_type: str,
        *,
        label: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        for item in reversed(self._current_turn_results):
            if item.get("result_type") != result_type:
                continue
            if label and item.get("label") != label:
                continue
            result = item.get("result")
            if isinstance(result, dict) and result.get("success"):
                return item
        return None

    def _invalidate_dependents(self, label: str, dependent_types: List[str]) -> None:
        for dependent_type in dependent_types:
            key = self._make_key(dependent_type, label)
            stored = self._store.get(key)
            if stored is None:
                continue
            stored.metadata["stale"] = True
            logger.info("Context store: marked %s as stale", key)

    def _enforce_scenario_limit(self, result_type: str) -> None:
        candidates = [
            item
            for key, item in self._store.items()
            if item.result_type == result_type and item.label != self.BASELINE_LABEL
        ]
        if len(candidates) <= self.MAX_SCENARIOS:
            return

        removable = sorted(candidates, key=lambda item: item.timestamp)[: len(candidates) - self.MAX_SCENARIOS]
        for item in removable:
            key = self._make_key(item.result_type, item.label)
            self._store.pop(key, None)
            logger.info("Context store: removed %s due to scenario limit", key)

    def _build_summary(self, tool_name: str, result: Dict[str, Any]) -> str:
        summary = str(result.get("summary") or "").strip()
        if summary:
            compact = " ".join(summary.split())
            return compact[:MAX_SUMMARY_CHARS]

        data = result.get("data", {})
        if isinstance(data, dict):
            summary_block = data.get("summary", {})
            if isinstance(summary_block, dict):
                if "total_links" in summary_block:
                    return f"Emission calculation for {summary_block['total_links']} links"
                if "receptor_count" in summary_block:
                    return f"Dispersion analysis for {summary_block['receptor_count']} receptors"
                if "hotspot_count" in summary_block:
                    return f"Hotspot analysis with {summary_block['hotspot_count']} hotspots"
        return f"{tool_name} completed"

    def _build_metadata(
        self,
        tool_name: str,
        result: Dict[str, Any],
        label: str,
    ) -> Dict[str, Any]:
        data = result.get("data", {})
        metadata: Dict[str, Any] = {
            "tool_name": tool_name,
            "scenario_label": label,
        }
        if not isinstance(data, dict):
            return metadata

        results_list = data.get("results")
        if isinstance(results_list, list):
            metadata["count"] = len(results_list)
            if results_list and isinstance(results_list[0], dict):
                metadata["has_geometry"] = any(
                    isinstance(item, dict) and bool(item.get("geometry"))
                    for item in results_list[:5]
                )

        query_info = data.get("query_info", {})
        if isinstance(query_info, dict):
            if query_info.get("pollutants"):
                metadata["pollutants"] = query_info.get("pollutants")
            if query_info.get("pollutant"):
                metadata["pollutant"] = query_info.get("pollutant")
            if query_info.get("model_year") is not None:
                metadata["model_year"] = query_info.get("model_year")

        summary = data.get("summary", {})
        if isinstance(summary, dict):
            for key in (
                "total_links",
                "receptor_count",
                "hotspot_count",
                "mean_concentration",
                "max_concentration",
            ):
                if key in summary:
                    metadata[key] = summary[key]

        overrides = data.get("overrides_applied")
        if isinstance(overrides, list) and overrides:
            metadata["override_count"] = len(overrides)

        return metadata
