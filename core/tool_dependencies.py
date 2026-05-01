"""
EmissionAgent - Canonical Tool Dependency Graph

Defines lightweight prerequisite relationships between tools.
This layer is intentionally validation-focused; execution still relies on
router argument preparation plus the session context store.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Sequence, Set

from core.plan import PlanStatus, PlanStep, PlanStepStatus
from tools.contract_loader import get_tool_contract_registry

if TYPE_CHECKING:
    from core.context_store import SessionContextStore


CANONICAL_RESULT_ALIASES: Dict[str, str] = {
    "emission_result": "emission",
    "dispersion_result": "dispersion",
    "hotspot_analysis": "hotspot",
    "concentration": "dispersion",
    "raster": "dispersion",
    "contour": "dispersion",
    "spatial_emission": "spatial_emission",
    "spatial_emission_result": "spatial_emission",
    "spatial_emission_layer": "spatial_emission",
}


# Each tool declares what results it requires and what it provides.
# Canonical result tokens are used throughout this graph.
TOOL_GRAPH: Dict[str, Dict[str, List[str]]] = (
    get_tool_contract_registry().get_tool_graph()
)


def normalize_result_token(token: Optional[str]) -> Optional[str]:
    """Map legacy result tokens and render-layer aliases to canonical tokens."""
    if token is None:
        return None
    text = str(token).strip().lower()
    if not text:
        return None
    return CANONICAL_RESULT_ALIASES.get(text, text)


def normalize_tokens(tokens: Optional[Iterable[str]]) -> List[str]:
    """Normalize tokens with stable ordering and de-duplication."""
    seen: Set[str] = set()
    normalized: List[str] = []
    for token in tokens or []:
        mapped = normalize_result_token(token)
        if not mapped or mapped in seen:
            continue
        seen.add(mapped)
        normalized.append(mapped)
    return normalized


def _extract_result_data(payload: Any) -> Optional[Dict[str, Any]]:
    if not isinstance(payload, dict):
        return None
    if "data" in payload and isinstance(payload.get("data"), dict):
        if payload.get("success") is False:
            return None
        return payload["data"]
    return payload if isinstance(payload, dict) else None


def _infer_result_tokens_from_payload(payload: Any) -> List[str]:
    data = _extract_result_data(payload)
    if not isinstance(data, dict):
        return []

    inferred: List[str] = []
    results = data.get("results")
    if isinstance(results, list):
        sample = [item for item in results[:3] if isinstance(item, dict)]
        if any("total_emissions_kg_per_hr" in item for item in sample):
            inferred.append("emission")

    if "raster_grid" in data or "concentration_grid" in data:
        inferred.append("dispersion")

    if "hotspots" in data or data.get("hotspot_count") is not None:
        inferred.append("hotspot")

    summary = data.get("summary")
    if isinstance(summary, dict):
        if "mean_concentration" in summary or "receptor_count" in summary:
            inferred.append("dispersion")
        if "hotspot_count" in summary or "total_hotspot_area_m2" in summary:
            inferred.append("hotspot")

    return normalize_tokens(inferred)


def _infer_inline_available_tokens(
    tool_name: str,
    arguments: Optional[Dict[str, Any]],
) -> List[str]:
    if not isinstance(arguments, dict):
        return []

    inferred = _infer_result_tokens_from_payload(arguments.get("_last_result"))
    if not inferred:
        return []

    required_tokens = set(get_required_result_tokens(tool_name, arguments))
    if not required_tokens:
        return inferred
    return [token for token in inferred if token in required_tokens]


def get_required_result_tokens(
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Return canonical prerequisite result tokens for a tool call."""
    if tool_name == "render_spatial_map":
        layer_type = normalize_result_token((arguments or {}).get("layer_type"))
        if layer_type in {"emission", "dispersion", "hotspot"}:
            return [layer_type]
        return []
    return normalize_tokens(TOOL_GRAPH.get(tool_name, {}).get("requires", []))


def get_missing_prerequisites(
    tool_name: str,
    available_results: Set[str],
    arguments: Optional[Dict[str, Any]] = None,
) -> List[str]:
    """Check whether a tool's prerequisites are met using canonical tokens."""
    available = set(normalize_tokens(available_results))
    requires = get_required_result_tokens(tool_name, arguments)
    return [req for req in requires if req not in available]


@dataclass
class DependencyValidationIssue:
    token: str
    issue_type: str
    message: str
    source: Optional[str] = None
    label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "token": self.token,
            "issue_type": self.issue_type,
            "message": self.message,
            "source": self.source,
            "label": self.label,
        }


@dataclass
class DependencyValidationResult:
    tool_name: str
    required_tokens: List[str]
    available_tokens: List[str]
    missing_tokens: List[str] = field(default_factory=list)
    stale_tokens: List[str] = field(default_factory=list)
    is_valid: bool = True
    message: str = ""
    issues: List[DependencyValidationIssue] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "required_tokens": list(self.required_tokens),
            "available_tokens": list(self.available_tokens),
            "missing_tokens": list(self.missing_tokens),
            "stale_tokens": list(self.stale_tokens),
            "is_valid": self.is_valid,
            "message": self.message,
            "issues": [issue.to_dict() for issue in self.issues],
        }


def validate_tool_prerequisites(
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
    available_tokens: Optional[Iterable[str]] = None,
    context_store: Optional["SessionContextStore"] = None,
    include_stale: bool = False,
) -> DependencyValidationResult:
    """Deterministically validate runtime prerequisites for one tool call."""
    required_tokens = get_required_result_tokens(tool_name, arguments)
    normalized_available = set(normalize_tokens(available_tokens))
    resolved_available = set(normalized_available)
    resolved_available.update(_infer_inline_available_tokens(tool_name, arguments))
    missing_tokens: List[str] = []
    stale_tokens: List[str] = []
    issues: List[DependencyValidationIssue] = []
    label = None
    if isinstance(arguments, dict) and arguments.get("scenario_label"):
        label = str(arguments["scenario_label"]).strip() or None

    for token in required_tokens:
        if token in resolved_available:
            continue

        availability = None
        if context_store is not None and hasattr(context_store, "get_result_availability"):
            availability = context_store.get_result_availability(
                token,
                label=label,
                include_stale=include_stale,
            )

        if isinstance(availability, dict):
            if availability.get("available"):
                resolved_available.add(token)
                continue
            if availability.get("stale"):
                stale_tokens.append(token)
                issues.append(
                    DependencyValidationIssue(
                        token=token,
                        issue_type="stale",
                        message=(
                            f"Prerequisite '{token}' is only available as stale context and "
                            "include_stale=False."
                        ),
                        source=availability.get("source"),
                        label=availability.get("label"),
                    )
                )
                continue

        missing_tokens.append(token)
        issues.append(
            DependencyValidationIssue(
                token=token,
                issue_type="missing",
                message=f"Missing prerequisite result '{token}'.",
                source=availability.get("source") if isinstance(availability, dict) else None,
                label=availability.get("label") if isinstance(availability, dict) else label,
            )
        )

    is_valid = not missing_tokens and not stale_tokens
    if required_tokens and is_valid:
        message = f"All prerequisite result tokens available for {tool_name}: {required_tokens}."
    elif not required_tokens:
        message = f"No canonical prerequisite result tokens required for {tool_name}."
    else:
        message_parts: List[str] = []
        if missing_tokens:
            message_parts.append(f"missing={missing_tokens}")
        if stale_tokens:
            message_parts.append(f"stale={stale_tokens}")
        message = f"Cannot execute {tool_name}; prerequisite validation failed ({', '.join(message_parts)})."

    return DependencyValidationResult(
        tool_name=tool_name,
        required_tokens=required_tokens,
        available_tokens=sorted(resolved_available),
        missing_tokens=missing_tokens,
        stale_tokens=stale_tokens,
        is_valid=is_valid,
        message=message,
        issues=issues,
    )


def suggest_prerequisite_tool(missing_result: str) -> Optional[str]:
    """Suggest which tool can produce a missing canonical result token."""
    normalized = normalize_result_token(missing_result)
    if not normalized:
        return None
    for tool_name, info in TOOL_GRAPH.items():
        if normalized in normalize_tokens(info.get("provides", [])):
            return tool_name
    return None


def get_tool_provides(tool_name: str) -> List[str]:
    """Get the canonical result types a tool provides."""
    return normalize_tokens(TOOL_GRAPH.get(tool_name, {}).get("provides", []))


# ── Geometry dependency helpers (Phase 7.3) ──────────────────────────────

_ACCEPTABLE_ROAD_GEOMETRY_TYPES: Set[str] = {
    "wkt", "geojson", "lonlat_linestring", "spatial_metadata",
}

_REJECTED_ROAD_GEOMETRY_TYPES: Set[str] = {
    "lonlat_point", "join_key_only", "none",
}


def get_geometry_requirements(tool_name: str) -> Dict[str, Any]:
    """Return geometry_requirements metadata for a tool from its contract.

    Returns an empty dict when the tool has no geometry_requirements block.
    """
    registry = get_tool_contract_registry()
    contract = dict(registry._contracts.get(tool_name, {}))
    geo_req = contract.get("geometry_requirements")
    if isinstance(geo_req, dict):
        return dict(geo_req)
    return {}


def requires_road_geometry(tool_name: str) -> bool:
    """Check whether *tool_name* declares a road-geometry requirement."""
    geo_req = get_geometry_requirements(tool_name)
    return bool(geo_req.get("requires_road_geometry", False))


def is_acceptable_road_geometry_type(geometry_type: str, tool_name: str = "calculate_dispersion") -> bool:
    """Check whether *geometry_type* satisfies the road-geometry requirement for *tool_name*."""
    geo_req = get_geometry_requirements(tool_name)
    acceptable = set(geo_req.get("acceptable_geometry_types", _ACCEPTABLE_ROAD_GEOMETRY_TYPES))
    if not acceptable:
        acceptable = _ACCEPTABLE_ROAD_GEOMETRY_TYPES
    return str(geometry_type).strip().lower() in acceptable


def is_rejected_road_geometry_type(geometry_type: str, tool_name: str = "calculate_dispersion") -> bool:
    """Check whether *geometry_type* is explicitly rejected for road-geometry requirements."""
    geo_req = get_geometry_requirements(tool_name)
    rejected = set(geo_req.get("rejected_geometry_types", _REJECTED_ROAD_GEOMETRY_TYPES))
    if not rejected:
        rejected = _REJECTED_ROAD_GEOMETRY_TYPES
    return str(geometry_type).strip().lower() in rejected


def check_road_geometry_from_metadata(
    geometry_metadata: Optional[Dict[str, Any]],
    tool_name: str = "calculate_dispersion",
) -> Dict[str, Any]:
    """Deterministic road-geometry availability check against geometry_metadata.

    Returns a diagnostic dict with:
      - satisfied: bool
      - reason_code: str
      - geometry_type: str
      - road_geometry_available: bool
      - message: str
    """
    geo_meta = dict(geometry_metadata or {})
    geometry_type = str(geo_meta.get("geometry_type", "none")).strip().lower()
    road_available = bool(geo_meta.get("road_geometry_available", False))
    line_constructible = bool(geo_meta.get("line_geometry_constructible", False))
    point_available = bool(geo_meta.get("point_geometry_available", False))
    geo_available = bool(geo_meta.get("geometry_available", False))
    join_keys = dict(geo_meta.get("join_key_columns") or {})

    if not requires_road_geometry(tool_name):
        return {
            "satisfied": True,
            "reason_code": "no_road_geometry_requirement",
            "geometry_type": geometry_type,
            "road_geometry_available": road_available,
            "message": f"Tool '{tool_name}' does not require road geometry.",
        }

    # Acceptable road geometry types
    if geometry_type in _ACCEPTABLE_ROAD_GEOMETRY_TYPES and road_available:
        return {
            "satisfied": True,
            "reason_code": "road_geometry_available",
            "geometry_type": geometry_type,
            "road_geometry_available": True,
            "message": f"Road geometry available (type={geometry_type}).",
        }

    # lonlat point only
    if geometry_type == "lonlat_point" and point_available:
        return {
            "satisfied": False,
            "reason_code": "missing_road_geometry_point_only",
            "geometry_type": geometry_type,
            "road_geometry_available": False,
            "point_geometry_available": True,
            "message": (
                "Only point coordinates (lon/lat) found in file. "
                "Dispersion requires road-segment line geometry (WKT, GeoJSON, "
                "start-end coordinates, or shapefile)."
            ),
        }

    # join key only
    if geometry_type == "join_key_only" and join_keys:
        jk_list = sorted(join_keys.keys())
        return {
            "satisfied": False,
            "reason_code": "missing_road_geometry_join_key_only",
            "geometry_type": geometry_type,
            "road_geometry_available": False,
            "join_key_columns": jk_list,
            "message": (
                f"Join key columns found ({', '.join(jk_list)}) but no road geometry. "
                "Please provide a geometry file (shapefile/GeoJSON) or columns with WKT/"
                "start-end coordinates for road-segment dispersion."
            ),
        }

    # no geometry at all
    if geometry_type == "none" or not geo_available:
        return {
            "satisfied": False,
            "reason_code": "missing_road_geometry",
            "geometry_type": geometry_type or "none",
            "road_geometry_available": False,
            "message": (
                "No road geometry detected in the uploaded file. "
                "Dispersion requires road-segment line geometry. "
                "Please upload a file with WKT, GeoJSON, start-end coordinates, "
                "or a shapefile."
            ),
        }

    # unexpected / unknown geometry type — not road
    return {
        "satisfied": False,
        "reason_code": "missing_road_geometry",
        "geometry_type": geometry_type,
        "road_geometry_available": False,
        "message": (
            f"Geometry type '{geometry_type}' is not usable for road-segment dispersion. "
            "Required: WKT, GeoJSON, start-end coordinates, or shapefile geometry."
        ),
    }


def _build_tool_graph_for_prompt() -> dict:
    """Build a simplified tool-graph snippet safe for LLM prompt injection."""
    graph: dict = {}
    for tool_name, info in TOOL_GRAPH.items():
        requires = normalize_tokens(info.get("requires", []))
        provides = normalize_tokens(info.get("provides", []))
        upstream = set()
        for req in requires:
            for other_tool, other_info in TOOL_GRAPH.items():
                if other_tool == tool_name:
                    continue
                if req in normalize_tokens(other_info.get("provides", [])):
                    upstream.add(other_tool)
        graph[tool_name] = {
            "requires": requires,
            "provides": provides,
            "upstream_tools": sorted(upstream),
        }
    return graph


def _extract_step_field(step: Any, field_name: str, default: Any) -> Any:
    if isinstance(step, dict):
        return step.get(field_name, default)
    return getattr(step, field_name, default)


def validate_plan_steps(
    plan_steps: Sequence[PlanStep | Dict[str, Any]],
    available_tokens: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """Deterministically validate plan-step dependencies in order."""
    if not plan_steps:
        return {
            "status": PlanStatus.INVALID,
            "initial_available_tokens": sorted(normalize_tokens(available_tokens)),
            "final_available_tokens": sorted(normalize_tokens(available_tokens)),
            "validation_notes": ["Plan has no executable analysis steps."],
            "step_results": [],
        }

    available = set(normalize_tokens(available_tokens))
    step_results: List[Dict[str, Any]] = []
    validation_notes: List[str] = []
    invalid_count = 0
    blocked_count = 0

    for index, step in enumerate(plan_steps):
        tool_name = str(_extract_step_field(step, "tool_name", "") or "").strip()
        step_id = str(_extract_step_field(step, "step_id", "") or f"s{index + 1}").strip()
        argument_hints = _extract_step_field(step, "argument_hints", {}) or {}
        declared_depends = normalize_tokens(_extract_step_field(step, "depends_on", []))
        declared_produces = normalize_tokens(_extract_step_field(step, "produces", []))
        inferred_requires = get_required_result_tokens(tool_name, argument_hints)
        canonical_provides = get_tool_provides(tool_name)

        status = PlanStepStatus.READY
        notes: List[str] = []

        if tool_name not in TOOL_GRAPH:
            status = PlanStepStatus.FAILED
            invalid_count += 1
            notes.append(f"Unknown tool '{tool_name}' in plan.")
        else:
            if declared_depends and declared_depends != inferred_requires:
                notes.append(
                    "Declared depends_on normalized to %s, tool semantics imply %s."
                    % (declared_depends, inferred_requires)
                )
            elif not declared_depends and inferred_requires:
                notes.append(f"depends_on inferred from tool semantics: {inferred_requires}.")

            if declared_produces and canonical_provides and declared_produces != canonical_provides:
                notes.append(
                    "Declared produces normalized to %s, canonical tool output is %s."
                    % (declared_produces, canonical_provides)
                )

            validation = validate_tool_prerequisites(
                tool_name,
                arguments=argument_hints,
                available_tokens=available,
                include_stale=False,
            )
            effective_requires = validation.required_tokens or declared_depends
            effective_produces = canonical_provides or declared_produces
            if validation.missing_tokens or validation.stale_tokens:
                status = PlanStepStatus.BLOCKED
                blocked_count += 1
                notes.append(validation.message)
            else:
                available.update(effective_produces)
        step_results.append(
            {
                "step_id": step_id,
                "tool_name": tool_name,
                "required_tokens": inferred_requires or declared_depends,
                "produced_tokens": canonical_provides or declared_produces,
                "status": status,
                "validation_notes": notes,
                "missing_tokens": validation.missing_tokens if tool_name in TOOL_GRAPH else [],
                "stale_tokens": validation.stale_tokens if tool_name in TOOL_GRAPH else [],
            }
        )

    if invalid_count:
        overall_status = PlanStatus.INVALID
        validation_notes.append("Plan contains unknown or invalid tools.")
    elif blocked_count:
        overall_status = PlanStatus.PARTIAL
        validation_notes.append("Plan is only partially executable with current available results.")
    else:
        overall_status = PlanStatus.VALID
        validation_notes.append("Plan dependency chain is executable in order.")

    return {
        "status": overall_status,
        "initial_available_tokens": sorted(normalize_tokens(available_tokens)),
        "final_available_tokens": sorted(available),
        "validation_notes": validation_notes,
        "step_results": step_results,
    }
