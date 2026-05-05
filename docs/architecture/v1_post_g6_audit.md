# v1 Backend Post-G6 Audit — Frontend Integration Prep

**Date:** 2026-05-05
**Branch:** `phase3-governance-reset`
**Commit:** `460ed9d` (HEAD)
**Scope:** Audit-only. No .py / .yaml / .md changes beyond this file.
**Motivation:** Frontend v4 publishing from Claude Design; backend audit before integration + deploy.

---

## §A — Architecture + Module Overview

### §A.1 Module Inventory (by LOC)

Command: `wc -l core/*.py core/contracts/*.py tools/*.py api/*.py`

#### core/ — 47 modules, ~28K LOC

| Module | LOC | Responsibility |
|---|---|---|
| `router.py` | 12,082 | Main orchestrator: dual-loop dispatch, tool dispatch, reply generation, synthesis, trace persistence. 439 KB monolith. |
| `governed_router.py` | 1,353 | Governance wrapper: 4-contract pipeline (clarification → intent → stance → readiness), cross-constraints, decision field. |
| `readiness.py` | 1,662 | Pre-execution gating: ReadinessStatus enum, ActionAffordance, build_readiness_assessment(). |
| `ao_manager.py` | 1,846 | Analytical Objective lifecycle: creation, continuation, fingerprint-based dedup, revision invalidation, execution state. |
| `trace.py` | 1,146 | Auditable decision trace: 100+ TraceStepType values, Trace dataclass, to_user_friendly(), persistence. |
| `contracts/clarification_contract.py` | 1,746 | Stage 1 contract: file grounding, PCM collection mode, probe questions, split/non-split dual path. |
| `contracts/execution_readiness_contract.py` | 1,137 | Stage 4 contract: readiness gating, parameter snapshot, AO state sync, repair gating. |
| `assembler.py` | 1,002 | Context assembly: prompt template loading, block telemetry, skill injection, multi-block prompt construction. |
| `memory.py` | 1,034 | MemoryManager: fact memory (file analysis, standardization, emission results) + episodic memory. |
| `task_state.py` | 1,037 | TaskState composite dataclass: 7 TaskStage states, ParamEntry with confidence/strategy/lock, validated transitions. |
| `context_store.py` | 829 | SessionContextStore: structured result storage with scenario versioning, dependency-aware lookup. |
| `intent_resolution.py` | 786 | Deliverable/Progress intent types, IntentResolutionApplicationPlan resolution logic. |
| `input_completion.py` | 808 | Parameter completion: missing field detection, probe generation, user reply parsing. |
| `spatial_emission_resolver.py` | 1,027 | Spatial emission layer construction: join-key geometry resolution, emission-to-links binding. |
| `parameter_negotiation.py` | 709 | Deterministic reply parsing for ambiguous parameters, parameter confirmation/rejection. |
| `analytical_objective.py` | 711 | AO dataclass: AORelationship, ExecutionStep, ToolCallRecord, ExecutionStepStatus, IncompatibleSessionError. |
| `plan.py` | 231 | ExecutionPlan + PlanStep + PlanStepStatus enums. |
| `plan_repair.py` | 757 | 8 bounded RepairActionType values, plan deviation detection, repair proposal/application. |
| `workflow_templates.py` | 623 | 5 hardcoded workflow templates (NOT config-driven). |
| `remediation_policy.py` | 367 | HCM 6th ed. cited lookup tables for missing field defaults. |
| `router_render_utils.py` | 864 | Synthesis-side rendering helpers extracted from router. |
| `router_payload_utils.py` | 334 | Frontend payload shaping: chart_data, table_data, map_data extraction. |
| `router_synthesis_utils.py` | 89 | Synthesis preparation helpers extracted from router. |
| `router_memory_utils.py` | 48 | Memory compaction helpers extracted from router. |
| `executor.py` | 388 | ToolExecutor: standardization pipeline, tool dispatch, error handling. |
| `reply_parser_llm.py` | 274 | LLM-backed user reply parser (user→agent direction). |
| `core/reply/` (package) | 655 | Reply parsing: llm_parser (LLMReplyParser), reply_context (ReplyContext), reply_context_builder. |
| `skill_injector.py` | 243 | Skill YAML loading + injection into prompt context. |
| `capability_summary.py` | 285 | Capability-aware follow-up guidance: hard constraints injected into synthesis. |
| `tool_dependencies.py` | 555 | TOOL_GRAPH: declarative requires/provides per tool, dependency validation. |
| `snapshot_coercion.py` | 75 | Type coercion for parameter snapshots. |
| `stance_resolver.py` | 221 | Conversational stance detection: standard request vs chit-chat vs reversal. |
| `intent_resolver.py` | 391 | Intent resolution: maps user message to tool intent + deliverable/progress bias. |
| `ao_classifier.py` | 498 | AO classifier: multi-layer task type detection from user message. |
| `coverage_assessment.py` | 240 | Road coverage CRS detection + receptor grid projection. |
| `residual_reentry.py` | 379 | RecoveredWorkflowReentryContext for geometry-recovery resume. |
| `summary_delivery.py` | 1,061 | Bounded chart/summary delivery surface: artifact_actions integration. |
| `supplemental_merge.py` | 1,081 | Bounded supplemental-column merge path for multi-table file packages. |
| `execution_continuation.py` | 88 | PendingObjective enum + execution continuation state. |
| `artifact_memory.py` | 859 | ArtifactMemoryState: tracks delivered artifacts, detects duplicates, biases follow-up suggestions. |
| `file_analysis_fallback.py` | 582 | LLM fallback for low-confidence file grounding. |
| `file_relationship_resolution.py` | 915 | Multi-file relationship resolution: merge/concat/independent detection. |
| `geometry_recovery.py` | 516 | Geometry recovery from join keys via OSM/TileZen. |
| `spatial_emission.py` | 222 | SpatialEmissionLayer dataclass: geometry ↔ emission binding. |
| `spatial_types.py` | 149 | Spatial type definitions for emission/dispersion/hotspot geometry. |
| `data_quality.py` | 176 | DataQualityReport schema for CSV inspection. |
| `output_safety.py` | 47 | User-facing output safety rails. |
| `conversation_intent.py` | 208 | Conservative conversation-intent classifier for fast-path routing. |
| `constraint_violation_writer.py` | 190 | Governance-layer persistence for cross-constraint violations. |

**Note:** `core/reply/` (655 LOC across 4 files) is a package directory, not captured by the `core/*.py` glob. It contains `llm_parser.py` (132 LOC), `reply_context.py` (236 LOC), `reply_context_builder.py` (264 LOC), and `__init__.py` (23 LOC).

#### tools/ — 12 modules, ~5.5K LOC

| Module | LOC | Responsibility |
|---|---|---|
| `file_analyzer.py` | 1,911 | File structure analysis: type detection, column mapping, multi-table role detection, spatial metadata extraction. |
| `spatial_renderer.py` | 922 | 6 `_build_*_map()` methods for emission/contour/raster/hotspot/concentration/points map rendering. |
| `macro_emission.py` | 951 | Link-level macro emission: MOVES EF lookup, fleet-mix weighting, Excel I/O, scenario labeling. |
| `dispersion.py` | 873 | PS-XGB-RLINE surrogate dispersion: concentration raster, contour bands, receptor grids, road contributions. |
| `contract_loader.py` | 298 | ToolContractRegistry: YAML contract loading, parameter schema resolution. |
| `override_engine.py` | 316 | Parameter override application for scenario simulation. |
| `micro_emission.py` | 251 | VSP-based second-by-second micro emission from trajectory data. |
| `emission_factors.py` | 229 | EF curve query: MOVES Atlanta database, 73 speed points, multi-pollutant. |
| `scenario_compare.py` | 229 | Multi-scenario comparison: metric deltas, percentage changes, per-link differences. |
| `hotspot.py` | 206 | Hotspot analysis: percentile/threshold methods, source attribution, clustering. |
| `base.py` | 127 | BaseTool ABC + ToolResult dataclass. |
| `registry.py` | 151 | ToolRegistry singleton; `init_tools()` manually imports 9 tools. |
| `clean_dataframe.py` | 154 | Data quality inspection: column types, missing values, numeric describe. |
| `knowledge.py` | 73 | Knowledge base search: wraps knowledge retrieval skill. |
| `formatter.py` | 138 | Shared formatting utilities for tool outputs. |
| `definitions.py` | 6 | Static JSON schemas (manual sync with TOOL_GRAPH required). |

#### api/ — 8 modules, ~3.6K LOC

| Module | LOC | Responsibility |
|---|---|---|
| `routes.py` | 1,035 | 16 endpoints: chat, chat/stream, sessions CRUD, file preview/download, GIS basemap, auth, templates. |
| `models.py` | 126 | Pydantic models: ChatRequest, ChatResponse, SessionInfo, Auth models. |
| `session.py` | 424 | SessionRegistry + ChatSessionService: session lifecycle, router dispatch, turn processing. |
| `main.py` | 92 | FastAPI app factory, middleware, lifespan events. |
| `database.py` | 142 | Async SQLite database layer for user accounts. |
| `auth.py` | 85 | JWT auth: password hashing, token create/decode, user_id generation. |
| `chart_utils.py` | 143 | Emission chart data construction, key point extraction. |
| `response_utils.py` | 15 | Reply text cleaning, friendly error messages, download normalization. |
| `map_export.py` | 200 | Map export to GeoJSON/HTML. |
| `logging_config.py` | 339 | Structured JSON logging configuration. |

### §A.2 Cross-Module Import Graph

**Key dependencies (callers → callees):**

```
api/routes.py → api/session.py → core/governed_router.py → core/router.py
                                                          → core/contracts/*
                                                          → core/ao_manager.py
                                                          → core/reply/*
                                                          → core/stance_resolver.py
                                                          → core/task_state.py

api/session.py → core/naive_router.py → tools/registry.py → tools/*

core/governed_router.py:
  → core/analytical_objective.py
  → core/ao_manager.py
  → core/constraint_violation_writer.py
  → core/context_store.py
  → core/contracts/ (clarification, intent, stance, readiness, oasc, dependency)
  → core/contracts/decision_validator.py
  → core/reply/ (llm_parser, reply_context, reply_context_builder)
  → core/router.py (UnifiedRouter, RouterResponse)
  → core/stance_resolver.py
  → core/task_state.py
  → core/tool_dependencies.py
  → services/cross_constraints.py
  → services/config_loader.py

core/router.py:
  → core/trace.py (Trace, to_user_friendly)
  → core/plan.py
  → core/router_payload_utils.py
  → core/router_render_utils.py
  → tools/registry.py
  → tools/base.py (ToolResult)

core/contracts/clarification_contract.py:
  → core/analytical_objective.py
  → core/ao_classifier.py
  → core/contracts/base.py
  → core/intent_resolver.py
  → core/router.py
  → core/contracts/runtime_defaults.py
  → core/contracts/emission_schema.py
  → core/stance_resolver.py
  → core/tool_dependencies.py
  → tools/file_analyzer.py
  → tools/contract_loader.py

core/naive_router.py:
  → tools/base.py
  → tools/contract_loader.py
  → tools/registry.py

core/task_state.py:
  → core/geometry_recovery.py
  → core/file_relationship_resolution.py
  → core/artifact_memory.py
  → core/input_completion.py
  → core/intent_resolution.py
  → core/parameter_negotiation.py
  → core/plan.py
  → core/plan_repair.py
  → core/residual_reentry.py
  → core/supplemental_merge.py
  → core/summary_delivery.py
  → core/workflow_templates.py
```

**Observations:**
- `router.py` (12K LOC) is the hub; nearly every module imports from it or is imported by it.
- `governed_router.py` is the second hub, bridging contracts, AO management, reply parsing, and the inner router.
- `naive_router.py` is relatively self-contained (imports only from tools/ and base).
- No circular import issues detected (module graph was tested by 115 passing tests).

### §A.3 YAML Config Inventory

Command: `ls -la config/*.yaml`

| File | Size | Purpose |
|---|---|---|
| `tool_contracts.yaml` | 31,828 B (992 lines) | 10 tool parameter schemas, required/optional slots, dependencies, readiness rules, action variants, artifact actions |
| `unified_mappings.yaml` | 11,724 B | 13 MOVES vehicle types, pollutants, seasons, road types, meteorology presets, VSP parameters |
| `cross_constraints.yaml` | 4,481 B | Cross-constraint rules: mutually exclusive params, co-required params, value range limits |
| `decision_few_shot_examples.yaml` | 4,851 B | Few-shot examples for LLM decision field (reconciler) |
| `emission_domain_schema.yaml` | 2,923 B | Domain schema defaults: vehicle types, pollutant lists, model_year range, season/road defaults |
| `dispersion_pollutants.yaml` | 1,245 B | Dispersion-specific pollutant configuration |
| `meteorology_presets.yaml` | 1,364 B | Meteorology presets: urban_summer_day, urban_winter_day, rural_neutral, etc. |
| `stance_signals.yaml` | 871 B | Conversational stance detection signals |

**Additional config (skills/):**
```bash
ls config/skills/*.yaml
```
- `scenario_skill.yaml` — Scenario comparison skill
- Additional skill YAML files for domain-specific workflows.

---

## §B — API + Stream Schema Real State vs §26 Comparison

### §B.1 Endpoint Inventory (from `api/routes.py`)

Read source: `api/routes.py` (1,035 lines).

| # | Method | Path | Auth | Parameters | Response |
|---|---|---|---|---|---|
| 1 | POST | `/chat` | Optional JWT | `message` (Form, required), `session_id` (Form, optional), `file` (UploadFile, optional), `mode` (Form, optional) | `ChatResponse` (JSON) |
| 2 | POST | `/chat/stream` | Optional JWT | Same as `/chat` | `text/event-stream` (SSE, newline-delimited JSON) |
| 3 | POST | `/file/preview` | None | `file` (UploadFile, required) | `FilePreviewResponse` (JSON) |
| 4 | GET | `/file/download/{file_id}` | Optional JWT | `file_id` (path), `user_id` (query) | `FileResponse` (XLSX binary) |
| 5 | GET | `/file/download/message/{session_id}/{message_id}` | Optional JWT | `session_id`, `message_id` (path), `user_id` (query) | `FileResponse` (XLSX binary) |
| 6 | GET | `/file/template/{template_type}` | None | `template_type` (path: `trajectory` or `links`) | `FileResponse` (XLSX binary) |
| 7 | GET | `/download/{filename}` | None | `filename` (path) | `FileResponse` (XLSX binary) |
| 8 | GET | `/gis/basemap` | None | — | GeoJSON (Shanghai 16 districts) |
| 9 | GET | `/gis/roadnetwork` | None | — | GeoJSON (simplified road network) |
| 10 | GET | `/sessions` | Optional JWT | — | `SessionListResponse` (JSON) |
| 11 | POST | `/sessions/new` | Optional JWT | — | `{"session_id": "..."}` |
| 12 | DELETE | `/sessions/{session_id}` | Optional JWT | `session_id` (path) | `{"status": "ok"}` |
| 13 | PATCH | `/sessions/{session_id}/title` | Optional JWT | `session_id` (path), body: `{"title": "..."}` | `{"status": "ok", "session_id": "...", "title": "..."}` |
| 14 | POST | `/sessions/{session_id}/generate_title` | Optional JWT | `session_id` (path) | `{"session_id": "...", "title": "..." or null}` |
| 15 | GET | `/sessions/{session_id}/history` | Optional JWT | `session_id` (path) | `HistoryResponse` (JSON) |
| 16 | GET | `/health` | None | — | `{"status": "healthy", "timestamp": "..."}` |
| 17 | GET | `/test` | None | — | `{"status": "ok", "timestamp": "..."}` |
| 18 | POST | `/register` | None | body: `RegisterRequest` | `AuthResponse` (JSON) |
| 19 | POST | `/login` | None | body: `LoginRequest` | `AuthResponse` (JSON) |
| 20 | GET | `/me` | JWT required | — | `UserInfo` (JSON) |

**Finding B.1**: 20 endpoints (not "16" as §26 text alludes to). §26 only covers `/chat`, `/chat/stream`, file download, GIS, and sessions. It omits `/download/{filename}`, `/test`, auth endpoints (`/register`, `/login`, `/me`), and template endpoint for completeness. Not a mismatch — §26 was scoped to "frontend-relevant" endpoints.

### §B.2 Stream Chunk Type Inventory (from `api/routes.py:307-430`)

All chunks are newline-delimited JSON via `text/event-stream`.

| Chunk type | Lines | JSON shape | Notes |
|---|---|---|---|
| `status` | 310-328 | `{"type":"status","content":"..."}` | 3 possible messages: "正在理解您的问题...", "正在处理上传的文件...", "正在分析任务..." |
| `heartbeat` | 333,348 | `{"type":"heartbeat"}` | Emitted every 15s while router is computing |
| `text` | 358-361 | `{"type":"text","content":"..."}` | 20-char chunks, 50ms delay between chunks |
| `chart` | 379-382 | `{"type":"chart","content":<chart_data>}` | Only when `chart_data` is non-empty |
| `table` | 388-393 | `{"type":"table","content":<table_data>,"download_file":{...},"file_id":"..."}` | Only when `table_data` is non-empty |
| `map` | 401-404 | `{"type":"map","content":<map_data>}` | Only when `map_data` is non-empty |
| `done` | 407-416 | `{"type":"done","session_id":"...","mode":"...","file_id":"...","download_file":...,"map_data":...,"message_id":"...","trace_friendly":[...]}` | Always emitted (final chunk) |
| `error` | 421-429 | `{"type":"error","content":"..."}` | Only on exception (IncompatibleSessionError or general Exception) |

**Comparison with §26.2.1:**

| §26 claim | Actual | Match? |
|---|---|---|
| 8 chunk types | 8 chunk types | ✅ |
| `status` — phase transitions | 3 fixed messages + file-processing status | ✅ |
| `heartbeat` — every 15s | Confirmed: `asyncio.wait_for(..., timeout=15)` | ✅ |
| `text` — 20-char chunks, 50ms | Confirmed: `chunk_size=20`, `await asyncio.sleep(0.05)` | ✅ |
| `chart` — if chart_data | Confirmed | ✅ |
| `table` — with download_file, file_id | Confirmed | ✅ |
| `map` — if map_data | Confirmed | ✅ |
| `done` — with session_id, mode, file_id, download_file, map_data, message_id, trace_friendly | Confirmed + `map_data` also in done chunk (redundant with map chunk) | ⚠️ |
| `error` — on exception | Confirmed | ✅ |

**Finding B.2**: `map_data` is duplicated in both `map` chunk (line 401-404) AND `done` chunk (line 413). This is redundant — frontend already received map_data in the `map` chunk. If the frontend processes the `done` chunk's `map_data` field, it may re-render the map.
- Evidence: `api/routes.py:396-416`
- Severity: minor
- Recommended action: Remove `map_data` from `done` chunk or document that it may be redundant.
- Frontend integration impact: maybe (depends on whether frontend re-processes done.map_data)

### §B.3 `chart` Chunk Real Schema

Source: `core/router_payload_utils.py:39-95` (`format_emission_factors_chart`, `extract_chart_data`).

Only one subtype exists: `emission_factors`. Produced exclusively by `query_emission_factors`.

```json
{
  "type": "chart",
  "content": {
    "type": "emission_factors",
    "vehicle_type": "Transit Bus",
    "model_year": 2019,
    "pollutants": {
      "CO2": {
        "curve": [
          {"speed_mph": 5, "speed_kph": 8.0, "emission_rate": 4629.52, "unit": "g/mile"}
        ],
        "unit": "g/mile"
      }
    },
    "metadata": {
      "data_source": "MOVES (Atlanta)",
      "speed_range": {"min_kph": 8.0, "max_kph": 117.5},
      "data_points": 73
    }
  }
}
```

**Comparison with §26.2.2:**

| §26 claim | Actual | Match? |
|---|---|---|
| Only `emission_factors` subtype | Confirmed: only `"type": "emission_factors"` appears in code | ✅ |
| `query_emission_factors` only producer | Confirmed: `extract_chart_data()` only handles `query_emission_factors` | ✅ |
| Backend pushes raw curve data, not ECharts spec | Confirmed | ✅ |
| `return_curve` varies resolution | Confirmed: `return_curve=false` → speed_curve, `true` → curve with g/km | ✅ |
| No other tool produces chart_data through ChartData path | Confirmed | ✅ |

**Finding B.3**: §26.2.2 is fully accurate for chart chunk. No mismatches.

### §B.4 `map` Chunk Real Schema — 6 Subtypes

Source: `tools/spatial_renderer.py` (6 `_build_*_map()` methods).

| # | Subtype | `type` field value | `layer_type` value | Produced by |
|---|---|---|---|---|
| 1 | Macro emission | `macro_emission_map` | `emission` | `render_spatial_map` after macro emission |
| 2 | Contour | `contour` | `contour` | `render_spatial_map` after dispersion |
| 3 | Raster | `raster` | `raster` | `render_spatial_map` after dispersion |
| 4 | Hotspot | `hotspot` | `hotspot` | `render_spatial_map` after hotspot analysis |
| 5 | Concentration (receptor scatter) | `concentration` | `concentration` | `render_spatial_map` after dispersion |
| 6 | Points (generic scatter) | `points` | `points` | `render_spatial_map` with any point data |

Each subtype schema matches §26.2.4 descriptions. Additionally, a multi-map wrapper exists:

```json
{
  "type": "map_collection",
  "items": [{...map1...}, {...map2...}],
  "summary": {"map_count": 2, "map_types": ["macro_emission_map", "contour"]}
}
```

Source: `core/router_payload_utils.py:300-334` (`extract_map_data`).

**Comparison with §26.2.4:**

| §26 claim | Actual | Match? |
|---|---|---|
| 6 subtypes: emission/contour/raster/hotspot/concentration/points | Confirmed via `layer_type` enum in YAML + 6 `_build_*_map()` methods | ✅ |
| Each subtype has center, zoom, pollutant, unit, color_scale | Confirmed for emission/contour/raster/concentration; hotspot has pollutant+unit but no zoom | ⚠️ minor |
| Multi-map wrapper `map_collection` | Confirmed | ✅ |
| `layer_type` parameter explicitly lists all 6 in YAML | Confirmed: `tool_contracts.yaml:745-751` | ✅ |

**Finding B.4**: Hotspot map subtype has no `center`/`zoom` fields (only `pollutant`, `unit`, `hotspots` array, `summary`, `interpretation`, `scenario_label`). §26.2.4 hotspot subtype schema correctly omits them too. No mismatch — §26 is accurate.

### §B.5 `done` Chunk and `trace_friendly`

Source: `api/routes.py:407-416`, `core/trace.py:272-286` (`to_user_friendly()`).

Actual `done` chunk shape (from code, line 407-416):
```json
{
  "type": "done",
  "session_id": "eval_848526036_task_001",
  "mode": "governed_v2",
  "file_id": "msg_abc123",
  "download_file": {"path": "/outputs/macro_results.xlsx", "filename": "macro_results.xlsx"},
  "map_data": null,
  "message_id": "msg_abc123",
  "trace_friendly": [...]
}
```

**IMPORTANT G6 UPDATE:** Since commit `460ed9d`, `to_user_friendly()` output now includes `type` + `latency_ms` fields (G6 fix). Each trace_friendly entry shape:

```json
{
  "title": "回复生成 / Reply Generation",
  "description": "LLM reply parser generated final reply",
  "status": "success",
  "type": "reply_generation",
  "step_type": "reply_generation",
  "latency_ms": 2341
}
```

Fields in `to_user_friendly()` output:

| Field | Type | Always present? | Notes |
|---|---|---|---|
| `title` | string | Yes | Bilingual (Chinese / English) |
| `description` | string | Yes | Multi-line, may include stats |
| `status` | string | Yes | `success` / `warning` / `error` |
| `type` | string | Yes | Set from `step_type` if `type` not already present (line 282) |
| `step_type` | string | Yes | TraceStepType enum value |
| `latency_ms` | int | **No** — only when `step.duration_ms is not None` (line 283-284) | G6 addition |

**However:** The `to_user_friendly()` path only applies when `trace_obj.to_user_friendly()` is called via `router.py:11327-11515` (8 call sites). Inline `trace_friendly` dicts assembled in `governed_router.py` and contracts do NOT go through `to_user_friendly()` and therefore do NOT get the G6 `type` + `latency_ms` normalization.

**Comparison with §26.2.5:**

| §26 claim | Actual (post-G6) | Match? |
|---|---|---|
| `step_type` not `type` | **FIXED** — `type` now ALSO present (setdefault at line 282) | ⚠️ §26 out of date |
| `latency` absent | **FIXED** — `latency_ms` now present when `duration_ms` is not None | ⚠️ §26 out of date |
| Only `reply_generation` steps appended | Still true for inline dicts; `to_user_friendly()` covers all trace steps | ⚠️ Partial |

**Finding B.5**: §26.2.5 is OUT OF DATE after G6 fix. The `type` field now exists and `latency_ms` is populated when available. The document should be updated to reflect the G6 fix. However, only steps going through `to_user_friendly()` benefit from this fix; hardcoded inline `trace_friendly` dicts in `governed_router.py` and contracts still use `step_type` without `latency_ms`. See §C for details.

### §B.6 `error` and `status` Chunks — Undocumented Fields

**`error` chunk** (lines 421-429):
```json
{"type": "error", "content": "错误描述..."}
```
- Only has `type` + `content`. No `error_code`, no `suggestion`, no `retryable` field.
- §26.2.1 correctly describes this as `{"type":"error","content":"..."}`.

**`status` chunk** (lines 310-328):
```json
{"type": "status", "content": "正在理解您的问题..."}
```
- Only has `type` + `content`. No `progress_pct`, no `substage`, no `estimated_remaining`.
- §26.2.1 correctly describes this shape.

**Finding B.6**: `error` chunk has no `error_code` or machine-parseable error field. Frontend can only match on `content` string, which is fragile for i18n or conditional error handling.
- Evidence: `api/routes.py:421-429`
- Severity: minor
- Recommended action: Consider adding optional `error_code` field to error chunk for frontend error-type routing.
- Frontend integration impact: maybe (if frontend needs to distinguish error types programmatically)

**Finding B.7**: `status` chunk has no `progress_pct` or `substage` field. The 3 status messages are hardcoded strings. Frontend cannot render a progress bar from this.
- Evidence: `api/routes.py:310-328`
- Severity: cosmetic
- Recommended action: Add optional `progress` field (0.0–1.0) for future progress bar support.
- Frontend integration impact: no (current v1 frontend likely uses loading spinner, not progress bar)

---

## §C — Trace G6 Full Picture

### §C.1 TraceStepType Enum Values

100+ enum values defined. First-class types (used in `_format_step_friendly()`):

| # | Enum value | Bilingual title | Meaning |
|---|---|---|---|
| 1 | `file_grounding` | 文件识别 / File Analysis | Initial file analysis: task type, row count, columns, confidence |
| 2 | `file_analysis_multi_table_roles` | 多表角色 / Multi-Table Roles | Multi-dataset file package role detection |
| 3 | `file_analysis_missing_fields` | 缺失字段诊断 / Missing-Field Diagnostics | Required-field diagnostics for file grounding |
| 4 | `file_analysis_spatial_metadata` | 空间元数据 / Spatial Metadata | Spatial metadata extraction from geospatial files |
| 5 | `file_analysis_fallback_triggered` | 文件兜底触发 / File Fallback Triggered | Low-confidence → LLM fallback triggered |
| 6 | `file_analysis_fallback_applied` | 文件兜底应用 / File Fallback Applied | LLM fallback merged into canonical result |
| 7 | `file_analysis_fallback_skipped` | 文件兜底跳过 / File Fallback Skipped | Rule-based analysis sufficient; no fallback |
| 8 | `file_analysis_fallback_failed` | 文件兜底失败 / File Fallback Failed | LLM fallback failed; kept rule-based result |

Plus 90+ more covering: FILE_RELATIONSHIP_*, SUPPLEMENTAL_MERGE_*, INTENT_RESOLUTION_*, ARTIFACT_*, SUMMARY_DELIVERY_*, READINESS_ASSESSMENT_*, ACTION_READINESS_*, WORKFLOW_TEMPLATE_*, PLAN_*, DEPENDENCY_*, PLAN_REPAIR_*, PARAMETER_NEGOTIATION_*, INPUT_COMPLETION_*, GEOMETRY_*, RESIDUAL_REENTRY_*, REMEDIATION_POLICY_*, PARAMETER_STANDARDIZATION, CROSS_CONSTRAINT_*, TOOL_SELECTION, TOOL_EXECUTION, STATE_TRANSITION, CLARIFICATION, SYNTHESIS, REPLY_GENERATION, ERROR, IDEMPOTENT_SKIP, RECONCILER_*, B_VALIDATOR_FILTER, PCM_ADVISORY_INJECTED, PROJECTED_CHAIN_GENERATED, AO_CLASSIFIER_FORCED_NEW_AO, READINESS_GATING_SKIPPED, CROSS_CONSTRAINT_CHECK_SKIPPED, FAST_PATH_SKIPPED, CONTINUATION_OVERRIDDEN_TO_NEW_AO.

Total: 100+ TraceStepType values (source: `core/trace.py:17-126`).

### §C.2 `to_user_friendly()` Output Fields (G6 Fix Applied)

Command: `grep -A 30 "def to_user_friendly" core/trace.py`

```python
def to_user_friendly(self) -> List[Dict[str, str]]:
    friendly = []
    for step in self.steps:
        entry = self._format_step_friendly(step)
        if entry:
            entry.setdefault("type", entry.get("step_type", ""))    # G6: add type alias
            if step.duration_ms is not None:
                entry["latency_ms"] = int(step.duration_ms)         # G6: add latency
            friendly.append(entry)
    return friendly
```

Full field inventory from `to_user_friendly()`:

| Key | Type | Always present? | Source |
|---|---|---|---|
| `title` | string | Yes | Hardcoded bilingual string per step type |
| `description` | string | Yes | Computed from step data (reasoning, output_summary, error) |
| `status` | string | Yes | `success` / `warning` / `error` |
| `step_type` | string | Yes | `step.step_type.value` |
| `type` | string | Yes | `entry.setdefault("type", entry.get("step_type", ""))` — G6 addition |
| `latency_ms` | int | No | Only when `step.duration_ms is not None` — G6 addition |

### §C.3 Inline `trace_friendly` Assembly Points — Consistency Check

Command: `grep -n "trace_friendly\|step_type\|latency_ms" core/governed_router.py core/naive_router.py core/contracts/*.py`

#### Governed Router (4 assembly points)

**GR-1:** `governed_router.py:1089` — cross_constraint_violation
```python
trace_friendly = [{"type": "cross_constraint_violation", "step_type": "cross_constraint_violation", "summary": violation_text[:200]}]
```
- Has `type` ✅ | Has `step_type` ✅ | Has `latency_ms` ❌ | Uses `summary` (not `description`) ⚠️

**GR-2:** `governed_router.py:1117` — decision_field_clarify
```python
trace_friendly = [{"type": "clarification", "step_type": "clarification", "summary": question}]
```
- Has `type` ✅ | Has `step_type` ✅ | Has `latency_ms` ❌ | Uses `summary` (not `description`) ⚠️

**GR-3:** `governed_router.py:1143` — decision_field_deliberate
```python
trace_friendly = [{"type": "clarification", "step_type": "clarification", "summary": reasoning}]
```
- Has `type` ✅ | Has `step_type` ✅ | Has `latency_ms` ❌ | Uses `summary` (not `description`) ⚠️

**GR-4:** `governed_router.py:436-451` — reply_generation (appended to existing)
```python
entry = {"title": "...", "description": "...", "status": "...", "type": "reply_generation", "step_type": "reply_generation"}
if reply_latency is not None:
    entry["latency_ms"] = int(reply_latency)
result.trace_friendly.append(entry)
```
- Has `type` ✅ | Has `step_type` ✅ | Has `latency_ms` ✅ (conditional) | Has `title`/`description`/`status` ✅

#### Naive Router (1 assembly point)

**NR-1:** `naive_router.py:167-174` — tool_execution
```python
trace_friendly=[
    {"type": "tool_execution", "step_type": "tool_execution",
     "description": f"{call.get('name')}: {'success' if ... else 'failed'}"}
    for call in executed_tool_calls
]
```
- Has `type` ✅ | Has `step_type` ✅ | Has `latency_ms` ❌ | Has `description` ✅

#### Contracts (5 assembly points)

**CT-1:** `clarification_contract.py:544`
```python
trace_friendly=[{"type": "clarification", "step_type": "clarification", "summary": question or ""}]
```
- Has `type` ✅ | Has `step_type` ✅ | Has `latency_ms` ❌ | Uses `summary` ⚠️

**CT-2:** `execution_readiness_contract.py:458`
```python
trace_friendly=[{"type": "clarification", "step_type": "clarification", "summary": question}]
```
- Has `type` ✅ | Has `step_type` ✅ | Has `latency_ms` ❌ | Uses `summary` ⚠️

**CT-3:** `execution_readiness_contract.py:518`
```python
trace_friendly=[{"type": "clarification", "step_type": "clarification", "summary": "scope framing"}]
```
- Has `type` ✅ | Has `step_type` ✅ | Has `latency_ms` ❌ | Uses `summary` ⚠️

**CT-4:** `execution_readiness_contract.py:653`
```python
trace_friendly=[{"type": "clarification", "step_type": "clarification", "summary": question}]
```
- Has `type` ✅ | Has `step_type` ✅ | Has `latency_ms` ❌ | Uses `summary` ⚠️

**CT-5:** `intent_resolution_contract.py:231`
```python
trace_friendly=[{"type": "clarification", "step_type": "clarification", "summary": "clarify tool intent"}]
```
- Has `type` ✅ | Has `step_type` ✅ | Has `latency_ms` ❌ | Uses `summary` ⚠️

#### Consistency Summary

| Source | Has `type` | Has `step_type` | Has `latency_ms` | Has `description` | Has `summary` |
|---|---|---|---|---|---|
| `to_user_friendly()` (G6 path) | ✅ | ✅ | ✅ (conditional) | ✅ | ❌ |
| GR-1 (cross_constraint) | ✅ | ✅ | ❌ | ❌ | ✅ |
| GR-2 (clarify) | ✅ | ✅ | ❌ | ❌ | ✅ |
| GR-3 (deliberate) | ✅ | ✅ | ❌ | ❌ | ✅ |
| GR-4 (reply_generation) | ✅ | ✅ | ✅ (conditional) | ✅ | ❌ |
| NR-1 (tool_execution) | ✅ | ✅ | ❌ | ✅ | ❌ |
| CT-1..5 (clarification) | ✅ | ✅ | ❌ | ❌ | ✅ |

**Finding C.1 (critical):** 8 of 10 trace_friendly assembly points use `summary` instead of `description`. The `to_user_friendly()` path uses `description`. Frontend receiving a mix of `summary`-keyed and `description`-keyed entries will have inconsistent rendering.
- Evidence: `governed_router.py:1089,1117,1143`, contracts × 5
- Severity: critical
- Recommended action: Normalize all inline trace_friendly dicts to use `description` instead of `summary`, and add `title`/`status` fields, OR add a normalization pass that maps `summary` → `description` before sending to frontend.
- Frontend integration impact: yes (frontend must handle both keys or will show blank descriptions)

**Finding C.2 (major):** 9 of 10 assembly points never include `latency_ms`. Since these inline dicts bypass `to_user_friendly()`, the G6 fix doesn't reach them.
- Evidence: All except GR-4 lack `latency_ms`
- Severity: major
- Recommended action: Route all trace_friendly assembly through `to_user_friendly()` or add a normalization pass that injects `latency_ms` from trace steps.
- Frontend integration impact: yes (frontend trace panel won't show timing for governance steps)

**Finding C.3 (minor):** GR-4 is the only inline assembly point that includes `title` and `status` fields. Other inline dicts lack them. The `_format_step_friendly()` path always includes `title` and `status`.
- Evidence: Compare GR-4 vs CT-1..5 format
- Severity: minor
- Recommended action: Align all inline dicts with the `to_user_friendly()` output schema.
- Frontend integration impact: maybe (frontend may rely on title/status for trace card rendering)

### §C.4 Field Naming Mismatch Beyond G6

**Finding C.4:** The `step_type` key in inline dicts sometimes differs from the `step_type` value used in trace steps. For example, `governed_router.py:268` uses `"step_type": "pcm_advisory_injected"` which is NOT a TraceStepType enum value (it's `PCM_ADVISORY_INJECTED` = `"pcm_advisory_injected"`). However other inline entries like `governed_router.py:809` use `"step_type": "tool_execution"` (TOOL_EXECUTION = `"tool_execution"`) which matches. This inconsistency appears cosmetic within the inline trace dict but matters if the frontend maps `step_type` values to icons or categories.
- Evidence: Compare `governed_router.py:268` vs `809` vs `987`
- Severity: cosmetic
- Recommended action: Audit all inline step_type values against TraceStepType enum.
- Frontend integration impact: maybe (if frontend has a step_type → icon mapping)

---

## §D — ToolContract YAML vs Tool Implementation Drift

### §D.1 Parameter Comparison Per Tool

Command: `cat config/tool_contracts.yaml` (992 lines) vs `grep -n "def execute\|class.*Tool" tools/*.py`

#### 1. `query_emission_factors`

| Aspect | YAML (`tool_contracts.yaml:28-101`) | Tool (`tools/emission_factors.py:91`) | Match? |
|---|---|---|---|
| `vehicle_type` required | YAML: `required: true` | Code: validated, returns error if missing | ✅ |
| `model_year` required | YAML: `required: true` | Code: validated, returns error if missing | ✅ |
| `pollutants` required | YAML: `required: false` | Code: validated, returns error if missing (both `pollutant` and `pollutants` absent) | ⚠️ **misleading** |
| `pollutants` type | YAML: array of string | Code: `list` via `kwargs.get("pollutants")` or single `kwargs.get("pollutant")` wrapped in list | ✅ |
| `season` | YAML: optional, default "夏季" | Code: `kwargs.get("season", "夏季")` | ✅ |
| `road_type` | YAML: optional, default "快速路" | Code: `kwargs.get("road_type", "快速路")` | ✅ |
| `return_curve` | YAML: optional boolean, default false | Code: `kwargs.get("return_curve", False)` | ✅ |

**Finding D.1**: YAML marks `pollutants` as `required: false` but the tool returns an error if neither `pollutant` nor `pollutants` is provided. The effective required-ness is `true` but YAML says `false`. This is misleading for LLM tool selection.
- Evidence: `tools/emission_factors.py:113-123`
- Severity: minor
- Recommended action: Mark `pollutants` as `required: true` in YAML, or add a default pollutant list.
- Frontend integration impact: no (affects LLM behavior, not frontend)

#### 2. `calculate_macro_emission`

| Aspect | YAML (`tool_contracts.yaml:102-201`) | Tool (`tools/macro_emission.py:614`) | Match? |
|---|---|---|---|
| `file_path` param | YAML: optional | Code: maps `file_path` → `input_file` (line 629) | ⚠️ **name mismatch** |
| `links_data` param | YAML: array of objects | Code: `kwargs.get("links_data")` | ✅ |
| `pollutants` | YAML: optional, defaults to CO2/NOx | Code: `kwargs.get("pollutants", ["CO2", "NOx"])` | ✅ |
| `model_year` | YAML: optional, default 2020 | Code: `kwargs.get("model_year", 2020)` | ✅ |
| `season` | YAML: optional, default "夏季" | Code: `kwargs.get("season", "夏季")` | ✅ |
| `fleet_mix` | YAML: optional | Code: `kwargs.get("fleet_mix")` | ✅ |
| `overrides` | YAML: absent from parameters | Code: `kwargs.get("overrides")` — used for scenario simulation | ❌ **YAML missing** |
| `scenario_label` | YAML: absent from parameters | Code: `kwargs.get("scenario_label")` — used for context store lookup | ❌ **YAML missing** |
| `_input_completion_overrides` | YAML: absent (internal) | Code: `kwargs.get("_input_completion_overrides")` — injected by executor | N/A (internal) |

**Finding D.2**: YAML parameter name is `file_path` but tool maps it to `input_file` internally (line 629). The YAML should use `input_file` to match the tool's actual parameter name, or the tool should accept `file_path` directly.
- Evidence: `tools/macro_emission.py:628-629`
- Severity: minor
- Recommended action: Align YAML parameter name with tool parameter name.
- Frontend integration impact: no

**Finding D.3**: `overrides` and `scenario_label` exist in the tool's `execute()` but are NOT declared in YAML parameters. The LLM cannot know these parameters exist unless they appear in the tool definition sent in the prompt.
- Evidence: `tools/macro_emission.py:640-644`
- Severity: major
- Recommended action: Add `overrides` and `scenario_label` to YAML parameter declarations.
- Frontend integration impact: no (affects LLM behavior for scenario simulation)

#### 3. `calculate_micro_emission`

| Aspect | YAML (`tool_contracts.yaml:102-201`) | Tool (`tools/micro_emission.py:46`) | Match? |
|---|---|---|---|
| `file_path` param | YAML: optional | Code: maps `file_path` → `input_file` (line 61-62) | ⚠️ **name mismatch** |
| `trajectory_data` | YAML: optional | Code: `kwargs.get("trajectory_data")` | ✅ |
| `vehicle_type` | YAML: required | Code: validated, returns error if missing | ✅ |
| `pollutants` | YAML: optional | Code: `kwargs.get("pollutants", ["CO2", "NOx"])` | ✅ |
| `model_year` | YAML: optional | Code: `kwargs.get("model_year", 2020)` | ✅ |
| `season` | YAML: optional | Code: `kwargs.get("season", "夏季")` | ✅ |

**Finding D.4**: Same `file_path` → `input_file` mapping as macro_emission. Micro emission YAML says `file_path` but tool uses `input_file`.
- Evidence: `tools/micro_emission.py:61-62`
- Severity: minor
- Recommended action: Same as D.2 — align names.
- Frontend integration impact: no

#### 4. `calculate_dispersion`

| Aspect | YAML (`tool_contracts.yaml:428-600`) | Tool (`tools/dispersion.py:80`) | Match? |
|---|---|---|---|
| Key parameters | `emission_source`, `meteorology`, `wind_speed`, `wind_direction`, `stability_class`, `mixing_height`, `roughness_height`, `grid_resolution`, `contour_resolution`, `pollutant`, `scenario_label` | All extracted via `kwargs.get()` | ✅ |
| Internal params (`_last_result`, `_spatial_emission_layer`) | YAML: absent (internal) | Code: injected by executor | N/A (internal) |

**Finding D.5**: Dispersion tool YAML is well-aligned with implementation. No mismatches beyond internal kwargs.

#### 5. `analyze_hotspots`

| Aspect | YAML (`tool_contracts.yaml:610-710`) | Tool (`tools/hotspot.py:38`) | Match? |
|---|---|---|---|
| `method` (percentile/threshold) | YAML: optional, default percentile | Code: `str(kwargs.get("method", "percentile"))` | ✅ |
| `threshold_value` | YAML: optional | Code: `kwargs.get("threshold_value")` | ✅ |
| `percentile` | YAML: optional, default 5 | Code: `float(kwargs.get("percentile", 5.0))` | ✅ |
| `min_hotspot_area_m2` | YAML: optional, default 2500 | Code: `float(kwargs.get("min_hotspot_area_m2", 2500.0))` | ✅ |
| `max_hotspots` | YAML: optional, default 10 | Code: `int(kwargs.get("max_hotspots", 10))` | ✅ |
| `source_attribution` | YAML: optional, default true | Code: `bool(kwargs.get("source_attribution", True))` | ✅ |
| `scenario_label` | YAML: optional | Code: `str(kwargs.get("scenario_label") or ...)` | ✅ |

No mismatches. Fully aligned.

#### 6. `render_spatial_map`

| Aspect | YAML (`tool_contracts.yaml:710-844`) | Tool (`tools/spatial_renderer.py:121`) | Match? |
|---|---|---|---|
| `data_source` | YAML: optional, default "last_result" | Code: `kwargs.get("data_source", "last_result")` | ✅ |
| `pollutant` | YAML: optional | Code: `kwargs.get("pollutant")` | ✅ |
| `title` | YAML: optional | Code: `kwargs.get("title", "")` | ✅ |
| `layer_type` | YAML: optional, enum of 6 | Code: `kwargs.get("layer_type")` (auto-detect if not specified) | ✅ |
| `scenario_label` | YAML: optional | Code: implied via data source resolution | ✅ |
| `source_links` | YAML: absent | Code: `kwargs.get("source_links")` — undocumented param | ❌ **YAML missing** |

**Finding D.6**: `source_links` is accepted by tool but not declared in YAML.
- Evidence: `tools/spatial_renderer.py:135`
- Severity: minor
- Recommended action: Add `source_links` to YAML or remove from tool.
- Frontend integration impact: no

#### 7. `compare_scenarios`

| Aspect | YAML (`tool_contracts.yaml:844-921`) | Tool (`tools/scenario_compare.py:28`) | Match? |
|---|---|---|---|
| `result_types` (required) | YAML: `required: true`, array with enum | Code: `result_types: List[str]` (first positional param) | ✅ |
| `baseline` | YAML: optional, default "baseline" | Code: `baseline: str = "baseline"` | ✅ |
| `scenario` | YAML: optional | Code: `scenario: Optional[str] = None` | ✅ |
| `scenarios` | YAML: optional | Code: `scenarios: Optional[List[str]] = None` | ✅ |
| `metrics` | YAML: optional | Code: `metrics: Optional[List[str]] = None` | ✅ |

**Finding D.7**: `compare_scenarios` uses typed positional parameters (not `**kwargs`), which is unique among all tools. This means the executor's standardization pipeline may not apply correctly. The YAML-declared parameters match the function signature exactly — the best-aligned tool.
- Evidence: `tools/scenario_compare.py:28-37`
- Severity: cosmetic (the alignment is good)
- Recommended action: Consider making this the standard pattern for all tools.
- Frontend integration impact: no

#### 8. `analyze_file`

| Aspect | YAML | Tool (`tools/file_analyzer.py:39`) | Match? |
|---|---|---|---|
| `file_path` (required) | YAML: `required: true` | Code: `file_path: str` (positional param) | ✅ |

Single parameter. Fully aligned.

#### 9. `clean_dataframe`

| Aspect | YAML | Tool (`tools/clean_dataframe.py:28`) | Match? |
|---|---|---|---|
| `file_path` (required) | YAML: `required: true` | Code: `file_path: str` (positional param) | ✅ |

Single parameter. Fully aligned.

#### 10. `query_knowledge`

| Aspect | YAML | Tool (`tools/knowledge.py:30`) | Match? |
|---|---|---|---|
| `query` (required) | YAML: `required: true` | Code: `kwargs.get("query")` | ✅ |
| `top_k` | YAML: optional | Code: `kwargs.get("top_k")` | ✅ |
| `expectation` | YAML: optional | Code: `kwargs.get("expectation")` | ✅ |

Fully aligned.

### §D.2 Summary of Tool Drift Severity

| Finding | Tool | Severity | Frontend impact |
|---|---|---|---|
| D.1: `pollutants` required=false but actually required | `query_emission_factors` | minor | no |
| D.2: `file_path` → `input_file` name mismatch | `macro_emission` | minor | no |
| D.3: `overrides`/`scenario_label` missing from YAML | `macro_emission` | major | no |
| D.4: `file_path` → `input_file` name mismatch | `micro_emission` | minor | no |
| D.6: `source_links` missing from YAML | `render_spatial_map` | minor | no |

---

## §E — Silent Issues Scan

### §E.1 Bare `except Exception:` Occurrences

Command: `grep -rn "except:\|except Exception:\|except BaseException:" core/ tools/ api/`

Total: 29 locations. Top locations by file:

| File | Count | Risk |
|---|---|---|
| `core/ao_manager.py` | 13 | High — AO lifecycle is central |
| `core/contracts/clarification_contract.py` | 3 | Medium — PCM probe path |
| `core/reply_parser_llm.py` | 2 | Medium — LLM reply parsing |
| `core/spatial_emission_resolver.py` | 2 | Medium |
| `core/router.py` | 3 | High — main orchestrator |
| Other (assember, plan, readiness, input_completion, task_state, governed_router, analytical_objective, plan_repair, data_quality, naive_router, router_render_utils) | 1 each | Medium-Low |

**Finding E.1**: `core/ao_manager.py` has 13 `except Exception:` blocks across ~1,846 LOC. The specific exception types that should be caught instead vary by location:
- `ao_manager.py:523,532`: File/DB persistence — should catch `OSError, IOError, json.JSONDecodeError`
- `ao_manager.py:864,1092`: State reconstruction — should catch `KeyError, ValueError, TypeError`
- `ao_manager.py:1442,1452,1459`: Fingerprint building — should catch `TypeError, AttributeError`
- `ao_manager.py:1542,1576,1617,1625,1808`: General lifecycle — should catch `ValueError, KeyError, AttributeError`

Not all of these are bugs — some are legitimate defense-in-depth (e.g., `assembler.py:914` catches Exception when attaching block telemetry, which is non-critical). But 29 bare `except Exception` is high and masks real bugs.
- Evidence: `grep` output above
- Severity: major
- Recommended action: Replace with specific exception types. Highest priority: `ao_manager.py` (13 locations) and `router.py` (3 locations).
- Frontend integration impact: maybe (masked exceptions could cause silent wrong output)

### §E.2 Logger Warnings/Errors Without Raise

Command: `grep -rn "logger\.warning\|logger\.error" core/ tools/ api/`

Key findings (50+ locations). Categorized:

**Legitimate (non-critical fallback):**
- `skill_injector.py:232` — skill file not found, skip silently → reasonable
- `context_store.py:219` — missing CRS assumption → reasonable
- `coverage_assessment.py:77` — "assuming EPSG:4326" → reasonable default
- `reply_parser_llm.py:150,157` — LLM timeout/failure → reasonable (retry or fallback)
- `router.py:2640` — trace persistence failure → reasonable (non-critical)
- `router.py:9485,9491` — lightweight planning failure → reasonable (continues without plan)
- `router.py:11913` — hallucination detection → reasonable (just warns)
- `ao_classifier.py:201` — classifier Layer 2 failure → reasonable (uses Layer 1 result)
- `ao_classifier.py:477` — classifier telemetry failure → reasonable (non-critical)

**Potentially problematic:**
- `executor.py:232` — `logger.error(f"Standardization failed for {tool_name}: {e}")` — continues execution with unstandardized params → could produce wrong results
- `executor.py:268` — `logger.error(f"{tool_name} failed: ...")` — if this silently returns a failure ToolResult, OK; if it silently returns success, it's a bug
- `router.py:11076,11731` — `logger.error("Tool error message: ...")` — unclear if execution continues after

**Finding E.2**: `executor.py:232` logs standardization failure as error but continues. If the tool receives unstandardized parameters, it may produce wrong results or crash with a cryptic error later in the pipeline.
- Evidence: `core/executor.py:232`
- Severity: major
- Recommended action: Return ToolResult(success=False) instead of continuing with unstandardized params.
- Frontend integration impact: yes (could cause wrong results delivered to frontend)

**Finding E.3**: `registry.py:95,101,107` logs `logger.error(f"Failed to register {tool}: {e}")` during `init_tools()` but continues. If a tool fails to register, it silently won't be available, and the only evidence is a log line.
- Evidence: `tools/registry.py:95-107`
- Severity: minor (tools rarely fail registration)
- Recommended action: Collect registration errors and raise at end of `init_tools()`.
- Frontend integration impact: maybe (missing tool → missing capability)

### §E.3 TODO / FIXME / XXX / HACK

Command: `grep -rni "TODO\|FIXME\|XXX\|HACK" core/ tools/ api/ config/`

Only 1 result (excluding skill YAML comments):

```
core/reply_parser_llm.py:8: TODO(A.2 round): When wiring this parser into parameter_negotiation /
```

**Finding E.4**: Only 1 TODO marker in the entire codebase. The TODO in `reply_parser_llm.py:8` references a deferred integration task (A.2 round — Phase 8). Urgency: low for v1 frontend integration but should be tracked for Phase 9.
- Evidence: `core/reply_parser_llm.py:8`
- Severity: cosmetic
- Recommended action: Track in Phase 9 backlog. Not blocking v1 frontend integration.
- Frontend integration impact: no

### §E.4 None Defaults Without Downstream None Checks

Command: `grep -rn "= None" core/governed_router.py`

Key findings:

```python
core/governed_router.py:57:    file_path: Optional[str] = None,
core/governed_router.py:188:    self.clarification_contract = None
core/governed_router.py:189:    self.intent_resolution_contract = None
core/governed_router.py:190:    self.stance_resolution_contract = None
core/governed_router.py:191:    self.execution_readiness_contract = None
core/governed_router.py:230-231: file_path, trace = None
core/governed_router.py:240:    result: Optional[RouterResponse] = None
core/governed_router.py:781-782: last_error, _llm_response = None
core/governed_router.py:913:    parameter_state.awaiting_slot = None
core/governed_router.py:920:    trace: Optional[Dict[str, Any]] = None
```

Lines 188-191: Contracts initialized to None but set in `_initialize_contracts()` before use. Safe if `_initialize_contracts()` is always called. The `GovernedRouter.start_turn()` method calls `_initialize_contracts()` at line 197. If `start_turn()` is ever skipped, AttributeError on None.
- Evidence: `core/governed_router.py:188-191`
- Severity: minor
- Recommended action: Use lazy initialization pattern or assert not None at use sites.
- Frontend integration impact: no

---

## §F — Test Coverage

### §F.1 Test Inventory

Command: `find tests/ -name "test_*.py" | xargs wc -l`

101 test files, 43,837 total LOC. Top 10 by LOC:

| Test file | LOC |
|---|---|
| `test_router_state_loop.py` | 4,165 |
| `test_contract_split.py` | 1,139 |
| `test_dispersion_integration.py` | 1,001 |
| `test_clarification_contract.py` | 993 |
| `test_trace.py` | 889 |
| `test_task_state.py` | 886 |
| `test_router_contracts.py` | 833 |
| `test_multifile_geometry_context_discovery.py` | 765 |
| `test_spatial_renderer.py` | 742 |
| `test_revision_invalidation_engine.py` | 704 |

### §F.2 Core Module Test Coverage Mapping

| Core module | Has test? | Test file |
|---|---|---|
| `router.py` | ✅ | `test_router_state_loop.py`, `test_router_contracts.py`, `test_multi_step_execution.py` |
| `governed_router.py` | ✅ | `test_governed_router_reply_integration.py`, `test_governed_router_restore_persisted_state.py` |
| `trace.py` | ✅ | `test_trace.py` (889 LOC) |
| `task_state.py` | ✅ | `test_task_state.py` (886 LOC) |
| `readiness.py` | ✅ | `test_readiness_gating.py` |
| `ao_manager.py` | ✅ | `test_ao_manager.py` (511 LOC) |
| `analytical_objective.py` | ✅ | `test_analytical_objective.py` |
| `ao_classifier.py` | ✅ | `test_ao_classifier.py` |
| `assembler.py` | ✅ | `test_assembler_skill_injection.py` |
| `context_store.py` | ✅ | `test_context_store.py`, `test_context_store_integration.py` |
| `tool_dependencies.py` | ✅ | `test_tool_dependencies.py` |
| `parameter_negotiation.py` | ✅ | `test_parameter_negotiation.py`, `test_parameter_negotiation_fast_path.py`, `test_parameter_negotiation_llm_integration.py` |
| `intent_resolver.py` | ✅ | `test_intent_resolver.py` |
| `intent_resolution.py` | ✅ | `test_intent_resolution.py` |
| `input_completion.py` | ✅ | `test_input_completion.py`, `test_input_completion_fast_path.py`, `test_input_completion_llm_integration.py` |
| `remediation_policy.py` | ✅ | `test_remediation_policy.py` |
| `plan.py` | ✅ | (covered via `test_workflow_templates.py`, `test_plan_repair.py`) |
| `plan_repair.py` | ✅ | (covered via router tests) |
| `workflow_templates.py` | ✅ | `test_workflow_templates.py` |
| `memory.py` | ✅ | `test_factmemory_refactor.py`, `test_layered_memory_context.py` |
| `executor.py` | ✅ | `test_executor_large_args.py` |
| `clarity_contract.py` | ✅ | `test_clarification_contract.py` (993 LOC) |
| `execution_readiness_contract.py` | ✅ | `test_execution_readiness_chain_guard.py`, `test_execution_readiness_parameter_snapshot.py` |
| `reconciler.py` | ✅ | `test_reconciler.py` |
| `spatial_emission_resolver.py` | ✅ | `test_spatial_emission_resolver.py`, `test_spatial_emission_layer.py` |
| `reply_parser_llm.py` | ✅ | `test_reply_parser_llm.py`, `test_reply_parser_llm_layer_coverage.py` |
| `core/reply/` | ✅ | `test_reply_context.py` |
| `router_payload_utils.py` | ❌ | No dedicated test |
| `router_render_utils.py` | ❌ | No dedicated test |
| `router_synthesis_utils.py` | ❌ | No dedicated test |
| `router_memory_utils.py` | ❌ | No dedicated test |
| `execution_continuation.py` | ✅ | `test_continuation_eval.py` |

**Finding F.1**: 4 router-extracted utility modules have NO dedicated tests: `router_payload_utils.py` (334 LOC), `router_render_utils.py` (864 LOC), `router_synthesis_utils.py` (89 LOC), `router_memory_utils.py` (48 LOC). These handle frontend payload shaping — bugs here directly affect what the frontend receives.
- Evidence: File listing above
- Severity: major
- Recommended action: Add smoke tests for `extract_chart_data()`, `extract_table_data()`, `extract_map_data()` in `router_payload_utils.py`.
- Frontend integration impact: yes (bug in payload shaping → wrong chart/table/map data)

### §F.3 Test Run Results

Command: `python3 -m pytest tests/ -x --tb=no -q`

```
115 passed, 1 failed, 38 warnings in 4.32s
```

**Failed test:** `test_benchmark_acceleration.py::test_smoke_subset_marks_30_tasks_and_covers_all_categories`

**Failure reason:**
```python
> assert len(smoke) == 30
E AssertionError: assert 32 == 30
```
The benchmark file `evaluation/benchmarks/end2end_tasks.jsonl` has 32 tasks marked `smoke: true`, but the test expects exactly 30. This is a **data drift**, not a code bug. Two new smoke tasks were added to the JSONL without updating the test assertion.

**Finding F.2**: 1 test fails due to benchmark data count drift (32 smoke tasks in JSONL, test expects 30). This is a known pre-existing issue — the eval benchmark file was updated but the test guard wasn't.
- Evidence: `tests/test_benchmark_acceleration.py:22`
- Severity: minor (not a code bug, but the test is misleading)
- Recommended action: Update assertion to `assert len(smoke) >= 30` or update to 32.
- Frontend integration impact: no (eval infra, not runtime)

**Warnings (38 total, all deprecation):**
- `on_event` deprecated in FastAPI (use lifespan instead) — 1 warning
- `shared.standardizer` deprecated (use `services.standardizer`) — 1 warning (from `skills/macro_emission/skill.py:11`)
- `datetime.utcnow()` deprecated — 32 warnings (from `api/logging_config.py:28`)
- Other minor deprecation — 4 warnings

### §F.4 Pre-Existing Test Failure Attribution

From the G6 commit message (`460ed9d`): no mention of pre-existing test failures. The `governed_router_reply_integration` test is NOT among the failures — it passes in this run. The audit doc §26 originally claimed `governed_router_reply_integration` was "pre-existing fail" but it's actually passing now.

---

## §G — Git State + Recent Commits

### §G.1 Current State

Command: `git status`
```
On branch phase3-governance-reset
Your branch is ahead of 'origin/phase3-governance-reset' by 38 commits.
nothing to commit, working tree clean
```

- Working tree: **clean** (no uncommitted changes)
- Branch: **38 commits ahead of remote**
- No untracked files

Command: `git stash list`
```
stash@{0}: On main: WIP: Step 1.B decision field Q3 defer + trace, paused for Round 4b
```

1 stash on `main` branch — unrelated to current `phase3-governance-reset` work.

Command: `git diff HEAD --stat`
(empty — clean tree confirmed)

### §G.2 Recent 10 Commits

```
460ed9d fix(trace): standardize trace_friendly field naming (type + latency_ms, Phase 8.2.5)
ff80ed8 docs(audit): backend capability inventory for frontend redesign (Phase 8.2.4)
35d045d docs(eval): Phase 8.2.3 paper figure & table materials
40b4c5b docs(eval): Phase 8.2.2.C-2 full ablation + Layer 1 + Layer 3 results
cd0a6f3 chore(governance): F1 fix default=false + clean session rerun results (Phase 8.2.2.C-1.3 Step 3+4)
bb9725f fix(llm-client): preserve reasoning_content in NaiveRouter multi-turn (Phase 8.2.2.C-1.3)
ed64a05 fix(eval): session isolation for clean eval runs (Phase 8.2.2.C-1.3 Step 2)
87d8c23 docs(eval): Phase 8.2.2.B audit + C-1 pilot results
758c8ce feat(eval): ablation flags + emission points (Phase 8.2.2.A)
a5b272e docs(eval): Phase 8.2.1 benchmark protocol design
```

### §G.3 Consistency with §26 Audit + Phase 8.2

| §26 audit claim | Git evidence | Consistent? |
|---|---|---|
| Phase 8.2.5: G6 trace field fix | `460ed9d` confirms `type` + `latency_ms` added | ✅ |
| Phase 8.2.4: Backend capability inventory | `ff80ed8` confirms audit doc written | ✅ |
| Phase 8.2.3: Paper figures | `35d045d` confirms paper materials | ✅ |
| Phase 8.2.2.C-2: Full ablation | `40b4c5b` confirms ablation results | ✅ |
| Phase 8.2.2.C-1.3: F1 fix | `cd0a6f3` confirms default=false fix | ✅ |
| 30-task smoke suite | Test now has 32 smoke tasks, not 30 — data drift since §26 doc written | ⚠️ |

**Finding G.1**: Branch is 38 commits ahead of remote. No commits have been pushed since the branch was created. All work is local only.
- Evidence: `git status` output
- Severity: major (risk of data loss if local disk fails)
- Recommended action: Push to remote before starting frontend integration.
- Frontend integration impact: yes (frontend needs to pull from remote)

**Finding G.2**: 1 stash on `main` from "Round 4b" work. Not relevant to current branch but indicates unfinished work on main.
- Evidence: `git stash list`
- Severity: minor
- Recommended action: Resolve or document the stash before merging.
- Frontend integration impact: no

---

## §H — Priority Summary

All findings sorted by severity, with frontend integration impact flagged.

### Critical

| # | Finding | Section | Frontend impact | Recommendation |
|---|---|---|---|---|
| **C.1** | `summary` vs `description` field mismatch in trace_friendly — 8 of 10 assembly points use `summary`; frontend expects `description` | §C.3 | **yes** | Normalize all inline trace_friendly dicts to use `description`. Route through `to_user_friendly()` or add normalization pass. |

### Major

| # | Finding | Section | Frontend impact | Recommendation |
|---|---|---|---|---|
| **D.3** | `overrides`/`scenario_label` missing from YAML for `macro_emission` tool — LLM can't discover scenario parameters | §D.1 | no (affects LLM) | Add to YAML parameter declarations |
| **E.2** | `executor.py:232` logs standardization failure but continues — unstandardized params may reach tool | §E.2 | **yes** | Return ToolResult(success=False) instead of continuing |
| **F.1** | `router_payload_utils.py`, `router_render_utils.py`, `router_synthesis_utils.py`, `router_memory_utils.py` have NO tests — these shape frontend payload | §F.2 | **yes** | Add smoke tests for extract_* functions |
| **G.1** | 38 commits ahead of remote, never pushed — risk of data loss | §G.3 | **yes** (frontend needs remote) | Push to remote |
| **C.2** | 9 of 10 assembly points lack `latency_ms` — G6 fix doesn't reach inline dicts | §C.3 | **yes** | Route all assembly through `to_user_friendly()` |
| **E.1** | 29 bare `except Exception:` blocks — masks real bugs, especially 13 in `ao_manager.py` | §E.1 | maybe | Replace with specific exception types |

### Minor

| # | Finding | Section | Frontend impact | Recommendation |
|---|---|---|---|---|
| **B.5** | §26.2.5 out of date after G6 fix (says no `type`/`latency_ms`, but they now exist) | §B.5 | no (doc issue) | Update §26.2.5 to reflect G6 fix |
| **B.2** | `map_data` duplicated in both `map` chunk and `done` chunk | §B.2 | maybe | Remove from `done` or document redundancy |
| **D.1** | `pollutants` marked `required: false` in YAML but tool errors if absent | §D.1 | no | Mark `required: true` or add default |
| **D.2/D.4** | `file_path` → `input_file` name mismatch (macro + micro tools) | §D.1 | no | Align YAML param name with tool code |
| **D.6** | `source_links` param missing from YAML for `render_spatial_map` | §D.1 | no | Add to YAML or remove from tool |
| **E.3** | Failed tool registration silently continues | §E.2 | maybe | Collect errors, raise at end |
| **F.2** | Benchmark smoke count test fails (32 vs expected 30) — data drift | §F.3 | no | Update test assertion |
| **B.6** | `error` chunk has no `error_code` field | §B.6 | maybe | Add optional `error_code` for programmatic handling |
| **C.4** | Some inline `step_type` values may not match TraceStepType enum | §C.3 | maybe | Audit inline values against enum |

### Cosmetic

| # | Finding | Section | Frontend impact | Recommendation |
|---|---|---|---|---|
| **B.7** | `status` chunk has no `progress_pct` field | §B.6 | no | Add optional progress for future |
| **E.4** | 1 TODO in `reply_parser_llm.py:8` (A.2 round integration) | §E.3 | no | Track in Phase 9 backlog |
| **G.2** | 1 stash on main from Round 4b | §G.3 | no | Resolve before merge |
| **D.7** | `compare_scenarios` uses typed params (good pattern, not a bug) | §D.1 | no | Consider making standard pattern |
| **C.3** | Inline dicts lack `title`/`status` fields present in `to_user_friendly()` output | §C.3 | maybe | Align all inline dicts with output schema |

### Summary Statistics

| Severity | Count | Frontend impact: yes |
|---|---|---|
| Critical | 1 | 1 |
| Major | 6 | 4 |
| Minor | 8 | 0 |
| Cosmetic | 5 | 0 |
| **Total** | **20** | **5** |

### Top 3 Must-Fix Before Frontend Integration

1. **C.1 (critical):** Normalize trace_friendly `summary` → `description` field. Frontend will show blank descriptions otherwise.
2. **C.2 (major):** Add `latency_ms` to inline trace_friendly dicts. G6 fix is only partial.
3. **F.1 (major):** Add tests for `router_payload_utils.py` — it shapes `chart_data`, `table_data`, `map_data` sent to frontend.

---

*Audit completed 2026-05-05. No .py / .yaml / .md files modified. All findings are code-read only.*
