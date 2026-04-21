# OA Architecture Reality Check

## Section 0: Critical Findings

1. `ENABLE_CONTRACT_SPLIT` is off by default, so Wave 2/3/4/5a split-contract logic is not the default production path. Evidence: `config.py:80-96` defaults `ENABLE_CONTRACT_SPLIT=false`; `core/governed_router.py:46-75` uses legacy `ClarificationContract` when that flag is off. Impact: absent an env override, production falls through the legacy clarification path.

2. Restored governed sessions silently revert to the legacy clarification chain even if split mode was enabled at router construction time. Evidence: `api/session.py:147-161` always calls `restore_persisted_state(...)` when a saved router state exists; `core/governed_router.py:538-556` rebuilds `[OASCContract, ClarificationContract, DependencyContract]` and does not reconstruct `IntentResolutionContract`, `StanceResolutionContract`, or `ExecutionReadinessContract`. Impact: Wave 2/3/4/5a code is not stable across resumed production sessions.

3. `mode=full` is usually not a raw `UnifiedRouter` path; it resolves to `GovernedRouter` by default. Evidence: `api/routes.py:290-327` defaults requests to `full`; `api/session.py:48-58` calls `build_router(..., router_mode="full")`; `core/governed_router.py:565-569` returns `GovernedRouter` when `ENABLE_GOVERNED_ROUTER=true`; `config.py:157` defaults that flag to `true`. Impact: mode labels are a conflicting truth source, and "full" does not reliably mean "legacy/unwrapped router."

4. `ENABLE_DEPENDENCY_CONTRACT` is a misleading flag: the dependency contract is a stub and is inserted regardless of the flag. Evidence: `config.py:153-154` defines the flag, `core/governed_router.py:76-92` always appends `DependencyContract`, `core/contracts/dependency_contract.py:1-13` is a placeholder/no-op, and grep found no runtime readers of `enable_dependency_contract` outside config. Impact: feature-flag state does not correspond to actual behavior, and the module contributes no production logic today.

## Section 1: OA Component Inventory

Ground-truth grep outputs requested for this audit:

### 1.1 `grep -rn "AnalyticalObjective" --include="*.py" core/ api/`

```text
core/memory.py:12:from core.analytical_objective import AOStatus, AnalyticalObjective, ToolCallRecord
core/memory.py:92:    ao_history: List[AnalyticalObjective] = field(default_factory=list)
core/memory.py:831:        legacy_ao = AnalyticalObjective(
core/memory.py:984:                    AnalyticalObjective.from_dict(item)
core/ao_manager.py:11:    AnalyticalObjective,
core/ao_manager.py:93:    def get_current_ao(self) -> Optional[AnalyticalObjective]:
core/ao_manager.py:99:    def get_ao_by_id(self, ao_id: Optional[str]) -> Optional[AnalyticalObjective]:
core/ao_manager.py:107:    def get_completed_aos(self) -> List[AnalyticalObjective]:
core/ao_manager.py:120:    ) -> AnalyticalObjective:
core/ao_manager.py:175:        ao = AnalyticalObjective(
core/ao_manager.py:193:    def activate_ao(self, ao_id: str) -> AnalyticalObjective:
core/ao_manager.py:276:    ) -> AnalyticalObjective:
core/ao_manager.py:361:        ao: AnalyticalObjective,
core/ao_manager.py:372:        ao: AnalyticalObjective,
core/ao_manager.py:414:        ao: AnalyticalObjective,
core/ao_manager.py:447:    def _sync_tool_intent_from_tool_call(ao: AnalyticalObjective, tool_call: ToolCallRecord) -> None:
core/ao_manager.py:483:    def _tool_intent_confidence(ao: AnalyticalObjective) -> Optional[str]:
core/ao_manager.py:490:    def _parameter_state_collection_mode(ao: AnalyticalObjective) -> Optional[bool]:
core/ao_manager.py:499:    def _parameter_state_awaiting_slot(ao: AnalyticalObjective) -> Optional[str]:
core/ao_manager.py:521:        ao: AnalyticalObjective,
core/ao_manager.py:547:    def _ao_objective_satisfied(self, ao: AnalyticalObjective) -> bool:
core/stance_resolver.py:11:    AnalyticalObjective,
core/stance_resolver.py:53:        ao: Optional[AnalyticalObjective],
core/analytical_objective.py:199:class AnalyticalObjective:
core/analytical_objective.py:258:    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AnalyticalObjective":
core/analytical_objective.py:263:                "AnalyticalObjective payload is missing Phase 2R stance fields "
```

### 1.2 `grep -rn "from core.contracts" --include="*.py" core/ api/`

```text
core/contracts/split_contract_utils.py:10:from core.contracts.clarification_contract import ClarificationContract
core/contracts/clarification_contract.py:17:from core.contracts.base import BaseContract, ContractContext, ContractInterception
core/contracts/intent_resolution_contract.py:6:from core.contracts.base import ContractContext, ContractInterception
core/contracts/intent_resolution_contract.py:7:from core.contracts.split_contract_utils import SplitContractSupport
core/contracts/oasc_contract.py:11:from core.contracts.base import BaseContract, ContractContext, ContractInterception
core/contracts/execution_readiness_contract.py:8:from core.contracts.base import ContractContext, ContractInterception
core/contracts/execution_readiness_contract.py:9:from core.contracts.runtime_defaults import has_runtime_default
core/contracts/execution_readiness_contract.py:10:from core.contracts.split_contract_utils import SplitContractSupport
core/contracts/stance_resolution_contract.py:9:from core.contracts.base import BaseContract, ContractContext, ContractInterception
core/contracts/dependency_contract.py:9:from core.contracts.base import BaseContract
core/governed_router.py:11:from core.contracts import (
```

### 1.3 `grep -rn "ENABLE_CONTRACT_SPLIT" --include="*.py" .`

```text
./tests/test_ao_manager.py:391:    os.environ["ENABLE_CONTRACT_SPLIT"] = "true"
./tests/test_ao_manager.py:434:    os.environ.pop("ENABLE_CONTRACT_SPLIT", None)
./tests/test_ao_manager.py:439:    os.environ["ENABLE_CONTRACT_SPLIT"] = "true"
./tests/test_ao_manager.py:476:    os.environ.pop("ENABLE_CONTRACT_SPLIT", None)
./tests/test_ao_manager.py:481:    os.environ["ENABLE_CONTRACT_SPLIT"] = "true"
./tests/test_ao_manager.py:501:    os.environ.pop("ENABLE_CONTRACT_SPLIT", None)
./tests/test_contract_split.py:34:    old = os.environ.get("ENABLE_CONTRACT_SPLIT")
./tests/test_contract_split.py:37:        os.environ.pop("ENABLE_CONTRACT_SPLIT", None)
./tests/test_contract_split.py:39:        os.environ["ENABLE_CONTRACT_SPLIT"] = old
./tests/test_contract_split.py:77:    os.environ["ENABLE_CONTRACT_SPLIT"] = "true"
./config.py:81:            os.getenv("ENABLE_CONTRACT_SPLIT", "false").lower() == "true"
./evaluation/run_oasc_matrix.py:45:            "ENABLE_CONTRACT_SPLIT": "true",
./evaluation/run_oasc_matrix.py:65:            "ENABLE_CONTRACT_SPLIT": "true",
./evaluation/run_oasc_matrix.py:85:            "ENABLE_CONTRACT_SPLIT": "true",
./evaluation/run_oasc_matrix.py:108:            "ENABLE_CONTRACT_SPLIT": "true",
./evaluation/run_oasc_matrix.py:128:            "ENABLE_CONTRACT_SPLIT": "true",
./evaluation/run_oasc_matrix.py:148:            "ENABLE_CONTRACT_SPLIT": "true",
```

### 1.4 `grep -rn "execution_continuation" --include="*.py" core/ api/`

```text
core/intent_resolver.py:11:from core.execution_continuation import PendingObjective
core/intent_resolver.py:12:from core.execution_continuation_utils import load_execution_continuation
core/intent_resolver.py:153:        continuation = load_execution_continuation(ao)
core/intent_resolver.py:179:        continuation = load_execution_continuation(ao)
core/contracts/intent_resolution_contract.py:9:from core.execution_continuation import PendingObjective
core/contracts/intent_resolution_contract.py:10:from core.execution_continuation_utils import load_execution_continuation
core/contracts/intent_resolution_contract.py:37:        continuation = load_execution_continuation(current_ao)
core/contracts/oasc_contract.py:12:from core.execution_continuation import ExecutionContinuation, PendingObjective
core/contracts/oasc_contract.py:13:from core.execution_continuation_utils import (
core/contracts/oasc_contract.py:17:    load_execution_continuation,
core/contracts/oasc_contract.py:18:    save_execution_continuation,
core/contracts/oasc_contract.py:92:                self._refresh_split_execution_continuation(context, result, current_ao)
core/contracts/oasc_contract.py:108:    def _refresh_split_execution_continuation(
core/contracts/oasc_contract.py:119:        transition_meta = dict(context.metadata.get("execution_continuation_transition") or {})
core/contracts/oasc_contract.py:120:        continuation_before = load_execution_continuation(current_ao)
core/contracts/oasc_contract.py:189:            save_execution_continuation(current_ao, continuation_after)
core/contracts/oasc_contract.py:191:        context.metadata["execution_continuation_transition"] = {
core/contracts/execution_readiness_contract.py:11:from core.execution_continuation import ExecutionContinuation, PendingObjective
core/contracts/execution_readiness_contract.py:12:from core.execution_continuation_utils import (
core/contracts/execution_readiness_contract.py:13:    clear_execution_continuation,
core/contracts/execution_readiness_contract.py:15:    load_execution_continuation,
core/contracts/execution_readiness_contract.py:17:    save_execution_continuation,
core/contracts/execution_readiness_contract.py:43:        continuation_before = load_execution_continuation(current_ao)
core/contracts/execution_readiness_contract.py:60:            save_execution_continuation(current_ao, continuation_before)
core/contracts/execution_readiness_contract.py:158:            clear_execution_continuation(current_ao, updated_turn=self._current_turn_index())
core/contracts/execution_readiness_contract.py:159:            continuation_after = load_execution_continuation(current_ao)
core/contracts/execution_readiness_contract.py:174:            save_execution_continuation(current_ao, continuation_after)
core/contracts/execution_readiness_contract.py:237:                save_execution_continuation(current_ao, continuation_after)
core/contracts/execution_readiness_contract.py:273:                save_execution_continuation(current_ao, continuation_after)
core/contracts/execution_readiness_contract.py:295:                context.metadata["execution_continuation_transition"] = {
core/contracts/execution_readiness_contract.py:333:            context.metadata["execution_continuation_transition"] = {
core/contracts/execution_readiness_contract.py:366:                save_execution_continuation(current_ao, continuation_after)
core/contracts/execution_readiness_contract.py:388:                save_execution_continuation(current_ao, continuation_after)
core/contracts/execution_readiness_contract.py:416:                context.metadata["execution_continuation_transition"] = {
core/contracts/execution_readiness_contract.py:461:            save_execution_continuation(current_ao, continuation_after)
core/contracts/execution_readiness_contract.py:469:            save_execution_continuation(current_ao, continuation_after)
core/contracts/execution_readiness_contract.py:492:        context.metadata["execution_continuation_transition"] = {
core/contracts/execution_readiness_contract.py:508:        context.metadata["execution_continuation_plan"] = {
core/contracts/execution_readiness_contract.py:519:        transition_meta = dict(context.metadata.get("execution_continuation_transition") or {})
core/contracts/execution_readiness_contract.py:520:        telemetry["execution_continuation"] = {
core/contracts/execution_readiness_contract.py:523:                or continuation_snapshot(load_execution_continuation(self.ao_manager.get_current_ao() if self.ao_manager else None))
core/contracts/execution_readiness_contract.py:527:                or continuation_snapshot(load_execution_continuation(self.ao_manager.get_current_ao() if self.ao_manager else None))
core/contracts/execution_readiness_contract.py:618:            "execution_continuation": {
core/ao_manager.py:15:from core.execution_continuation_utils import load_execution_continuation
core/ao_manager.py:152:                "execution_continuation_active",
core/ao_manager.py:380:        continuation_state = load_execution_continuation(ao)
core/ao_manager.py:387:                return False, "execution_continuation_active", check_results
core/ao_manager.py:429:            "execution_continuation_active": bool(load_execution_continuation(ao).is_active()),
core/ao_manager.py:430:            "execution_continuation": load_execution_continuation(ao).to_dict(),
core/analytical_objective.py:7:from core.execution_continuation import ExecutionContinuation
core/analytical_objective.py:396:        continuation_state = metadata.get("execution_continuation")
core/analytical_objective.py:398:            metadata["execution_continuation"] = ExecutionContinuation.from_dict(
core/execution_continuation_utils.py:5:from core.execution_continuation import ExecutionContinuation, PendingObjective
core/execution_continuation_utils.py:8:def load_execution_continuation(ao: Any) -> ExecutionContinuation:
core/execution_continuation_utils.py:11:    payload = ao.metadata.get("execution_continuation")
core/execution_continuation_utils.py:15:def save_execution_continuation(ao: Any, continuation: ExecutionContinuation) -> None:
core/execution_continuation_utils.py:20:    ao.metadata["execution_continuation"] = continuation.to_dict()
core/execution_continuation_utils.py:23:def clear_execution_continuation(ao: Any, *, updated_turn: Optional[int] = None) -> None:
core/execution_continuation_utils.py:26:    save_execution_continuation(ao, continuation)
```

### 1.5 `grep -rn "ao_manager\|AOManager" --include="*.py" core/ api/`

```text
core/contracts/clarification_contract.py:118:        ao_manager: Any = None,
core/contracts/clarification_contract.py:122:        self.ao_manager = ao_manager
core/contracts/clarification_contract.py:139:        self.intent_resolver = IntentResolver(inner_router, ao_manager)
core/contracts/clarification_contract.py:145:        if self.inner_router is None or self.ao_manager is None:
core/contracts/clarification_contract.py:150:        current_ao = self.ao_manager.get_current_ao()
core/contracts/clarification_contract.py:470:            current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
core/contracts/clarification_contract.py:525:            and self.ao_manager is not None
core/contracts/clarification_contract.py:527:            parent = self.ao_manager.get_ao_by_id(current_ao.parent_ao_id)
core/contracts/clarification_contract.py:607:            and self.ao_manager is not None
core/contracts/clarification_contract.py:609:            parent = self.ao_manager.get_ao_by_id(current_ao.parent_ao_id)
core/contracts/intent_resolution_contract.py:20:    def __init__(self, inner_router: Any = None, ao_manager: Any = None, runtime_config: Any = None):
core/contracts/intent_resolution_contract.py:21:        super().__init__(inner_router=inner_router, ao_manager=ao_manager, runtime_config=runtime_config)
core/contracts/intent_resolution_contract.py:22:        self.intent_resolver = IntentResolver(inner_router, ao_manager)
core/contracts/intent_resolution_contract.py:32:        current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
core/contracts/intent_resolution_contract.py:163:            "ao_id": getattr(self.ao_manager.get_current_ao(), "ao_id", None) if self.ao_manager else None,
core/contracts/oasc_contract.py:10:from core.ao_manager import AOManager, TurnOutcome
core/contracts/oasc_contract.py:28:    def __init__(self, inner_router: Any, ao_manager: AOManager, runtime_config: Optional[Any] = None):
core/contracts/oasc_contract.py:30:        self.ao_manager = ao_manager
core/contracts/oasc_contract.py:39:            self.ao_manager,
core/contracts/oasc_contract.py:46:        ao_telemetry_start = self.ao_manager.telemetry_size()
core/contracts/oasc_contract.py:90:            current_ao = self.ao_manager.get_current_ao()
core/contracts/oasc_contract.py:94:                self.ao_manager.complete_ao(
core/contracts/oasc_contract.py:105:            ao_lifecycle_events=self.ao_manager.telemetry_slice(ao_telemetry_start),
core/contracts/oasc_contract.py:246:        current = self.ao_manager.get_current_ao()
core/contracts/oasc_contract.py:249:                self.ao_manager.create_ao(
core/contracts/oasc_contract.py:256:            self.ao_manager.revise_ao(
core/contracts/oasc_contract.py:262:        self.ao_manager.create_ao(
core/contracts/oasc_contract.py:274:        current = self.ao_manager.get_current_ao()
core/contracts/oasc_contract.py:281:            current = self.ao_manager.create_ao(
core/contracts/oasc_contract.py:307:            self.ao_manager.append_tool_call(current.ao_id, record)
core/contracts/oasc_contract.py:311:                self.ao_manager.register_artifact(current.ao_id, artifact_type, label or artifact_type)
core/contracts/oasc_contract.py:457:            "current_ao_id": self.ao_manager.get_current_ao().ao_id if self.ao_manager.get_current_ao() else None,
core/contracts/execution_readiness_contract.py:28:    def __init__(self, inner_router: Any = None, ao_manager: Any = None, runtime_config: Any = None):
core/contracts/execution_readiness_contract.py:29:        super().__init__(inner_router=inner_router, ao_manager=ao_manager, runtime_config=runtime_config)
core/contracts/execution_readiness_contract.py:30:        self.intent_resolver = IntentResolver(inner_router, ao_manager)
core/contracts/execution_readiness_contract.py:40:        current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
core/contracts/execution_readiness_contract.py:523:                or continuation_snapshot(load_execution_continuation(self.ao_manager.get_current_ao() if self.ao_manager else None))
core/contracts/execution_readiness_contract.py:527:                or continuation_snapshot(load_execution_continuation(self.ao_manager.get_current_ao() if self.ao_manager else None))
core/contracts/execution_readiness_contract.py:551:        current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
core/contracts/execution_readiness_contract.py:605:            "ao_id": getattr(self.ao_manager.get_current_ao(), "ao_id", None) if self.ao_manager else None,
core/contracts/stance_resolution_contract.py:21:    def __init__(self, inner_router: Any = None, ao_manager: Any = None, runtime_config: Any = None):
core/contracts/stance_resolution_contract.py:23:        self.ao_manager = ao_manager
core/contracts/stance_resolution_contract.py:34:        current_ao = self.ao_manager.get_current_ao() if self.ao_manager is not None else None
core/ao_manager.py:67:class AOManager:
core/ao_manager.py:491:        if AOManager._contract_split_enabled():
core/ao_manager.py:500:        if AOManager._contract_split_enabled():
core/governed_router.py:10:from core.ao_manager import AOManager
core/governed_router.py:39:        self.ao_manager = AOManager(self.inner_router.memory.fact_memory)
core/governed_router.py:43:            ao_manager=self.ao_manager,
core/governed_router.py:55:                    ao_manager=self.ao_manager,
core/governed_router.py:61:                    ao_manager=self.ao_manager,
core/governed_router.py:67:                    ao_manager=self.ao_manager,
core/governed_router.py:73:                ao_manager=self.ao_manager,
core/governed_router.py:306:        current_ao = self.ao_manager.get_current_ao()
core/governed_router.py:333:        current_ao = self.ao_manager.get_current_ao()
core/governed_router.py:351:        current_ao = self.ao_manager.get_current_ao()
core/governed_router.py:540:        self.ao_manager = AOManager(self.inner_router.memory.fact_memory)
core/governed_router.py:544:            ao_manager=self.ao_manager,
core/governed_router.py:549:            ao_manager=self.ao_manager,
core/ao_classifier.py:17:from core.ao_manager import AOManager
core/ao_classifier.py:116:    def __init__(self, ao_manager: AOManager, llm_client: Any = None, config: Any = None):
core/ao_classifier.py:117:        self.ao_manager = ao_manager
core/ao_classifier.py:207:        current_ao = self.ao_manager.get_current_ao()
core/ao_classifier.py:208:        ao_history = list(getattr(getattr(self.ao_manager, "_memory", None), "ao_history", []) or [])
core/ao_classifier.py:272:        current = self.ao_manager.get_current_ao()
core/ao_classifier.py:288:        completed = self.ao_manager.get_completed_aos()
core/ao_classifier.py:397:        ao_summary = self.ao_manager.get_summary_for_classifier()
core/ao_classifier.py:454:        return int(getattr(getattr(self.ao_manager, "_memory", None), "last_turn_index", 0) or 0) + 1
```

### 1.6 `ls core/contracts/`

```text
__init__.py
__pycache__
base.py
clarification_contract.py
dependency_contract.py
execution_readiness_contract.py
intent_resolution_contract.py
oasc_contract.py
runtime_defaults.py
split_contract_utils.py
stance_resolution_contract.py
```

Inventory takeaways from the greps:

- OA core state is real code, not just docs: `AnalyticalObjective`, `AOManager`, and `OAScopeClassifier` are all instantiated from the governed path (`core/governed_router.py:39-45`, `core/contracts/oasc_contract.py:28-42`).
- The split-contract files exist and are imported into the governed router, but whether they run is flag-dependent (`core/governed_router.py:46-89`).
- `ExecutionContinuation` is wired across intent, readiness, AO lifecycle checks, and OASC post-turn sync, but all meaningful writes happen in the split path (`core/contracts/execution_readiness_contract.py:32-512`, `core/contracts/oasc_contract.py:108-196`).

## Section 2: Production Path Trace

### Hot-path answer up front

Default API traffic is OA-wrapped by default, because `mode=full` still resolves to `GovernedRouter` when `ENABLE_GOVERNED_ROUTER=true` (`api/routes.py:290-327`, `api/session.py:48-58`, `core/governed_router.py:565-569`, `config.py:157`). The split Wave 2/3/4/5a path is not the default hot path because `ENABLE_CONTRACT_SPLIT` defaults false (`config.py:80-96`), and resumed governed sessions are forced back to legacy clarification (`core/governed_router.py:538-556`).

### Branch A: `/api/chat/stream` with default `mode=full`

Step 1: `chat_stream` at `api/routes.py:270-414`
- What it does: receives the streaming request, normalizes `mode`, and delegates the actual turn to `ChatSessionService.process_turn(...)`.
- Does it use OA? `NO` directly.
- Does it use feature flag? `NO` here; mode comes from request/query and defaults to `full`.
- Fallback path if flag off: none at this layer.

Step 2: `ChatSessionService.process_turn` at `services/chat_session_service.py:148-248`
- What it does: stages upload, builds the router-facing message, and calls `session.chat(..., mode=router_mode)`.
- Does it use OA? `NO` directly.
- Does it use feature flag? `NO` here.
- Fallback path if flag off: none at this layer.

Step 3: `Session.chat` at `api/session.py:83-110`
- What it does: dispatches by mode to `naive_router`, `governed_router`, or `router`.
- Does it use OA? `PARTIAL`; `full` may still go through OA depending on `ENABLE_GOVERNED_ROUTER`.
- Does it use feature flag? `YES`, indirectly via `Session.router` -> `build_router(...)`.
- Fallback path if flag off: if `ENABLE_GOVERNED_ROUTER=false`, `full` uses `UnifiedRouter` directly (`core/governed_router.py:565-570`).

Step 4: `Session.router` at `api/session.py:48-58`
- What it does: lazily constructs the "full" router with `build_router(session_id=..., router_mode="full")`.
- Does it use OA? `PARTIAL`; depends on `ENABLE_GOVERNED_ROUTER`.
- Does it use feature flag? `YES`, `ENABLE_GOVERNED_ROUTER`.
- Fallback path if flag off: raw `UnifiedRouter`.

Step 5: `build_router` at `core/governed_router.py:559-570`
- What it does: chooses `GovernedRouter` for `governed_v2`, or for `full` when `enable_governed_router` is true.
- Does it use OA? `YES` when the flag is on.
- Does it use feature flag? `YES`, `ENABLE_GOVERNED_ROUTER`.
- Fallback path if flag off: `UnifiedRouter(session_id=..., memory_storage_dir=...)`.

Step 6: `GovernedRouter.__init__` at `core/governed_router.py:32-92`
- What it does: wraps `UnifiedRouter`, creates `AOManager`, `StanceResolver`, `OASCContract`, and then chooses either split contracts or legacy `ClarificationContract`.
- Does it use OA? `YES`, definitively; this is where AO state and OASC are instantiated.
- Does it use feature flag? `YES`, `ENABLE_CONTRACT_SPLIT`, `ENABLE_SPLIT_INTENT_CONTRACT`, `ENABLE_SPLIT_STANCE_CONTRACT`, `ENABLE_SPLIT_READINESS_CONTRACT`.
- Fallback path if flag off: contract chain becomes `[OASCContract, ClarificationContract, DependencyContract]`.

Step 7: `GovernedRouter.chat` at `core/governed_router.py:97-149`
- What it does: runs `before_turn(...)` on each contract, possibly short-circuits with a clarification response, otherwise either direct-executes from a snapshot or falls through to `inner_router.chat(...)`.
- Does it use OA? `YES`; OASC runs first on every governed request.
- Does it use feature flag? `PARTIAL`; split-vs-legacy contract chain already decided in `__init__`.
- Fallback path if flag off: legacy clarification branch instead of split branch.

Step 8A: `OASCContract.before_turn` at `core/contracts/oasc_contract.py:44-72`
- What it does: classifies the incoming message against AO state and writes AO metadata into `context.metadata["oasc"]`.
- Does it use OA? `YES`.
- Does it use feature flag? `YES`, `ENABLE_AO_AWARE_MEMORY`, `ENABLE_AO_CLASSIFIER_LLM_LAYER`.
- Fallback path if flag off: if `ENABLE_AO_AWARE_MEMORY=false`, OASC skips classification and only contributes empty metadata.

Step 8B default-off branch: `ClarificationContract.before_turn` at `core/contracts/clarification_contract.py:142-440`
- What it does: runs legacy intent/slot clarification and may emit `direct_execution` metadata or block with a clarification question.
- Does it use OA? `PARTIAL`; it consumes AO state via `ao_manager`, but it is the legacy path.
- Does it use feature flag? `YES`, `ENABLE_CLARIFICATION_CONTRACT`.
- Fallback path if flag off: if disabled, the request falls through to `UnifiedRouter.chat(...)`.

Step 8C split-on branch: `IntentResolutionContract.before_turn` -> `StanceResolutionContract.before_turn` -> `ExecutionReadinessContract.before_turn` at `core/contracts/intent_resolution_contract.py:24-132`, `core/contracts/stance_resolution_contract.py:27-87`, `core/contracts/execution_readiness_contract.py:32-512`
- What they do: resolve tool intent, resolve stance, and decide whether to clarify or proceed; readiness may emit `direct_execution` and continuation metadata.
- Does it use OA? `YES`.
- Does it use feature flag? `YES`, `ENABLE_CONTRACT_SPLIT`, `ENABLE_SPLIT_INTENT_CONTRACT`, `ENABLE_SPLIT_STANCE_CONTRACT`, `ENABLE_SPLIT_READINESS_CONTRACT`, `ENABLE_RUNTIME_DEFAULT_AWARE_READINESS`, `ENABLE_SPLIT_CONTINUATION_STATE`.
- Fallback path if flag off: governed router uses legacy `ClarificationContract` instead.

Step 9 direct-execution fork: `GovernedRouter._maybe_execute_from_snapshot` -> `_execute_from_snapshot` at `core/governed_router.py:151-204` and `core/governed_router.py:206-296`
- What it does: if clarification/readiness already produced a concrete snapshot, the governed wrapper bypasses normal router planning and calls `self.inner_router.executor.execute(...)` directly.
- Does it use OA? `YES/PARTIAL`; OA contracts decided the snapshot, but actual tool execution happens on the wrapped `UnifiedRouter.executor`.
- Does it use feature flag? `NO` locally; it depends on upstream contract metadata.
- Fallback path if flag off: if no valid `direct_execution` metadata exists, fall through to `UnifiedRouter.chat(...)`.
- First tool execution: `core/governed_router.py:225-230`.

Step 10 fall-through fork: `UnifiedRouter.chat` at `core/router.py:2372-2390`
- What it does: clears turn-local context, optionally tries conversation fast path, then enters either the state loop or legacy loop.
- Does it use OA? `NO` directly; this is the inner router after governed contracts.
- Does it use feature flag? `YES`, `ENABLE_STATE_ORCHESTRATION`, `ENABLE_CONVERSATION_FAST_PATH`.
- Fallback path if flag off: if `ENABLE_STATE_ORCHESTRATION=false`, use `_run_legacy_loop(...)`; if fast path not allowed, use `_run_state_loop(...)`.

Step 11A fast-path fork: `_maybe_handle_conversation_fast_path` at `core/router.py:623-734`
- What it does: classifies low-risk conversational turns and may directly answer or execute `query_knowledge`.
- Does it use OA? `PARTIAL`; only after OA/governed contracts have already fallen through.
- Does it use feature flag? `YES`, `ENABLE_CONVERSATION_FAST_PATH`.
- Fallback path if flag off: returns `None` and the router continues into `_run_state_loop(...)`.
- First tool execution on this fork: `core/router.py:685-688` (`query_knowledge`).

Step 11B state-loop fork: `_run_state_loop` -> `_state_handle_input` -> `_state_handle_grounded` -> `_state_handle_executing` at `core/router.py:2552-2627`, `core/router.py:10015-10610`, `core/router.py:10612-10667`, `core/router.py:10669-11191`
- What they do: assemble context, ask the LLM for tool calls, validate readiness/dependencies, and execute the selected tools.
- Does it use OA? `NO` directly; this is the legacy/state router under the governed shell.
- Does it use feature flag? `YES`, `ENABLE_STATE_ORCHESTRATION` and various router flags, but not OA-specific split flags.
- Fallback path if flag off: legacy loop if state orchestration is disabled.
- First tool execution on this fork: `core/router.py:10944-10948`.

### Branch B: `/api/chat/stream` with explicit `mode=governed_v2`

This branch converges with Branch A after `Session.chat(...)`.

Step 1-3: same as Branch A through `Session.chat` (`api/routes.py:270-327`, `services/chat_session_service.py:148-248`, `api/session.py:83-110`).

Step 4: `Session.governed_router` at `api/session.py:60-70`
- What it does: always calls `build_router(..., router_mode="governed_v2")`.
- Does it use OA? `YES`.
- Does it use feature flag? `NO` for the wrapper choice; explicit `governed_v2` forces `GovernedRouter`.
- Fallback path if flag off: none for router choice; the OA wrapper still exists.

Step 5 onward: same as Branch A from `GovernedRouter.__init__` / `GovernedRouter.chat`.

### Branch C: `/api/chat/stream` with explicit `mode=naive`

Step 1-3: same route/service/session entrypoints.

Step 4: `Session.chat(..., mode="naive")` at `api/session.py:91-93`
- What it does: calls `self.naive_router.chat(...)`.
- Does it use OA? `NO`.
- Does it use feature flag? `NO`.
- Fallback path if flag off: none.

Step 5: `NaiveRouter.chat` at `core/naive_router.py:117-184`
- What it does: runs a plain tool-calling loop with no governed/OA layer.
- Does it use OA? `NO`.
- Does it use feature flag? `NO`.
- Fallback path if flag off: none.
- First tool execution: `core/naive_router.py:230-258`.

### Production-path conclusion

OA is on the default production hot path as a wrapper, because default `full` mode typically resolves to `GovernedRouter`. But split OA is not the default architecture: by default the governed wrapper still uses legacy `ClarificationContract`, and resumed governed sessions currently force that legacy path even when split flags were originally enabled.

## Section 3: Each OA Component's Real Status

| Component | File | Status | Production path uses it? | Evidence |
|---|---|---|---|---|
| `AnalyticalObjective` | `core/analytical_objective.py` | ALIVE | YES | AO objects are created and managed by `AOManager.create_ao(...)` (`core/ao_manager.py:114-191`), and `AOManager` is instantiated in `GovernedRouter` (`core/governed_router.py:39-45`). |
| `OASCContract` | `core/contracts/oasc_contract.py` | ALIVE | YES | `GovernedRouter` always constructs and prepends it (`core/governed_router.py:41-45`, `core/governed_router.py:77-92`). |
| `OAScopeClassifier` (`AOClassifier` file) | `core/ao_classifier.py` | ALIVE | YES | `OASCContract.__init__` creates `OAScopeClassifier(...)` (`core/contracts/oasc_contract.py:32-42`), and `before_turn(...)` always uses it when `ENABLE_AO_AWARE_MEMORY=true` (`core/contracts/oasc_contract.py:50-61`). |
| `AOManager` | `core/ao_manager.py` | ALIVE | YES | Instantiated in `GovernedRouter` (`core/governed_router.py:39-45`) and used in OASC/clarification/split contracts throughout the request path. |
| `GovernedRouter` | `core/governed_router.py` | ALIVE | YES | Default `full` mode uses `build_router(...)`, which returns `GovernedRouter` when `ENABLE_GOVERNED_ROUTER=true` (`api/session.py:48-58`, `core/governed_router.py:565-569`, `config.py:157`). |
| `ClarificationContract` (legacy) | `core/contracts/clarification_contract.py` | ALIVE | YES | Default chain when split is off (`core/governed_router.py:46-75`), and resumed governed sessions rebuild this chain unconditionally (`core/governed_router.py:547-556`). |
| `IntentResolutionContract` | `core/contracts/intent_resolution_contract.py` | PARTIAL | YES, but only on fresh split-enabled governed routers | Constructed only when split flags are on (`core/governed_router.py:51-57`), skipped by default because `ENABLE_CONTRACT_SPLIT=false` (`config.py:80-96`), and omitted by `restore_persisted_state(...)` (`core/governed_router.py:538-556`). |
| `StanceResolutionContract` | `core/contracts/stance_resolution_contract.py` | PARTIAL | YES, but only on fresh split-enabled governed routers | Same gating and restore limitation as above (`core/governed_router.py:58-63`, `config.py:80-96`, `core/governed_router.py:538-556`). |
| `ExecutionReadinessContract` | `core/contracts/execution_readiness_contract.py` | PARTIAL | YES, but only on fresh split-enabled governed routers | Same gating and restore limitation as above (`core/governed_router.py:64-69`, `config.py:80-96`, `core/governed_router.py:538-556`). |
| `ExecutionContinuation` (Wave 3) | `core/execution_continuation.py` | PARTIAL | PARTIAL | Read and written by split contracts and OASC (`core/contracts/execution_readiness_contract.py:32-512`, `core/contracts/oasc_contract.py:108-196`), but split mode is off by default and restored governed sessions regress to legacy clarification. |
| `DependencyContract` | `core/contracts/dependency_contract.py` | PARTIAL | Technically YES, functionally NO | Always appended (`core/governed_router.py:76-92`), but the file is a placeholder subclass with no logic (`core/contracts/dependency_contract.py:1-13`). |
| `conversation_fast_path` | `core/router.py` | ALIVE | YES | `UnifiedRouter.chat(...)` calls `_maybe_handle_conversation_fast_path(...)` before the state loop (`core/router.py:2378-2388`), and it can directly answer or execute `query_knowledge` (`core/router.py:623-734`). |

Status interpretation:

- `ALIVE` means the current codebase puts the component on an auditable production route without needing a speculative env override.
- `PARTIAL` here usually means "implemented, but only active behind non-default split flags and/or broken by the restore path."

## Section 4: Feature Flag Reality

The table below focuses on OA and OA-adjacent flags that change the governed architecture itself.

| Flag | Default from code | Who reads it | What it gates | Production state from code |
|---|---|---|---|---|
| `ENABLE_GOVERNED_ROUTER` | `true` (`config.py:157`) | `core/governed_router.py:565-569` | Whether `mode=full` resolves to `GovernedRouter` instead of raw `UnifiedRouter` | `UNVERIFIED` in deployed env; absent env override, ON |
| `ENABLE_AO_AWARE_MEMORY` | `true` (`config.py:57`) | `core/contracts/oasc_contract.py:50-61`, `core/contracts/oasc_contract.py:88-99` | Whether OASC classification/AO sync actually runs | `UNVERIFIED`; absent env override, ON |
| `ENABLE_AO_CLASSIFIER_RULE_LAYER` | `true` (`config.py:58-60`) | `core/ao_classifier.py:129-147` | Rule layer in `OAScopeClassifier` | `UNVERIFIED`; absent env override, ON |
| `ENABLE_AO_CLASSIFIER_LLM_LAYER` | `true` (`config.py:61-63`) | `core/contracts/oasc_contract.py:32-37`, `core/ao_classifier.py:149-176` | Whether OASC creates/uses the LLM classifier layer | `UNVERIFIED`; absent env override, ON |
| `ENABLE_AO_BLOCK_INJECTION` | `true` (`config.py:71-73`) | `core/assembler.py:272-321`, `core/assembler.py:330-331` | AO-shaped state block injected into prompts | `UNVERIFIED`; absent env override, ON |
| `ENABLE_AO_PERSISTENT_FACTS` | `true` (`config.py:74-76`) | `core/assembler.py:421-451`, `core/assembler.py:546-549` | Whether AO persistent facts appear in the AO session-state block | `UNVERIFIED`; absent env override, ON |
| `ENABLE_CLARIFICATION_CONTRACT` | `true` (`config.py:77-79`) | `core/contracts/clarification_contract.py:143-146` | Whether legacy clarification logic runs when the legacy contract is instantiated | `UNVERIFIED`; absent env override, ON; note this flag is irrelevant when split contracts are the active chain |
| `ENABLE_CONTRACT_SPLIT` | `false` (`config.py:80-82`) | `core/governed_router.py:46-75`, `core/contracts/intent_resolution_contract.py:25-28`, `core/contracts/stance_resolution_contract.py:28-31`, `core/contracts/execution_readiness_contract.py:33-36`, `core/contracts/oasc_contract.py:114-117`, `core/ao_manager.py:474-480`, `core/analytical_objective.py:403-409` | Legacy clarification vs split-contract path | `UNVERIFIED`; absent env override, OFF |
| `ENABLE_SPLIT_INTENT_CONTRACT` | `true` (`config.py:83-85`) | `core/governed_router.py:52-57`, `core/contracts/intent_resolution_contract.py:27-28`, `core/contracts/execution_readiness_contract.py:66-71` | Construction/use of `IntentResolutionContract` | `UNVERIFIED`; only matters when split mode is on |
| `ENABLE_SPLIT_STANCE_CONTRACT` | `true` (`config.py:86-88`) | `core/governed_router.py:58-63`, `core/governed_router.py:117-123`, `core/governed_router.py:354-355`, `core/contracts/stance_resolution_contract.py:30-31`, `core/contracts/execution_readiness_contract.py:142-145` | Construction/use of `StanceResolutionContract`, or wrapper fallback stance logic if disabled | `UNVERIFIED`; only matters when split mode is on |
| `ENABLE_SPLIT_READINESS_CONTRACT` | `true` (`config.py:89-91`) | `core/governed_router.py:64-69`, `core/contracts/execution_readiness_contract.py:35-36` | Construction/use of `ExecutionReadinessContract` | `UNVERIFIED`; only matters when split mode is on |
| `ENABLE_RUNTIME_DEFAULT_AWARE_READINESS` | `true` (`config.py:92-94`) | `core/contracts/execution_readiness_contract.py:643-648` | Whether optional missing slots with runtime defaults are treated as operationally resolved | `UNVERIFIED`; only matters when split readiness is active |
| `ENABLE_SPLIT_CONTINUATION_STATE` | `true` (`config.py:95-97`) | `core/contracts/oasc_contract.py:114-117`, `core/contracts/intent_resolution_contract.py:40-44` | Whether split path writes/consumes `ExecutionContinuation` | `UNVERIFIED`; only matters when split mode is on |
| `ENABLE_LLM_INTENT_RESOLUTION` | `true` (`config.py:134-136`) | `core/intent_resolver.py:123-127` | Whether intent resolution can trust Stage 2 LLM hints | `UNVERIFIED`; absent env override, ON |
| `ENABLE_LIFECYCLE_CONTRACT_ALIGNMENT` | `true` (`config.py:137-139`) | `core/ao_manager.py:381-393`, `core/ao_manager.py:465-470` | Whether AO completion is blocked by unresolved intent or active continuation | `UNVERIFIED`; absent env override, ON |
| `ENABLE_CONVERSATIONAL_STANCE` | `true` (`config.py:140-142`) | `core/governed_router.py:345-404`, `core/stance_resolver.py:56-57`, `core/stance_resolver.py:105-106`, `core/stance_resolver.py:142-143` | Whether stance logic exists at all | `UNVERIFIED`; absent env override, ON |
| `ENABLE_STANCE_LLM_RESOLUTION` | `true` (`config.py:143-145`) | `core/stance_resolver.py:113-116` | Whether stance resolution uses LLM hints in addition to rules | `UNVERIFIED`; absent env override, ON |
| `ENABLE_STANCE_REVERSAL_DETECTION` | `true` (`config.py:146-148`) | `core/stance_resolver.py:144-145` | Whether continuation turns can flip stance on reversal signals | `UNVERIFIED`; absent env override, ON |
| `ENABLE_DEPENDENCY_CONTRACT` | `false` (`config.py:153-154`) | No runtime readers found by grep in `core/`, `api/`, `services/`, or `tests/` | Intended to gate dependency-contract behavior, but currently gates nothing | As coded, effectively irrelevant/misleading |

Special notes:

- `.env.example` does not define the OA split/governed flags; the operative defaults come from hardcoded `config.py` values.
- `evaluation/run_oasc_matrix.py:34-155` does set these flags for benchmark groups, but that is evaluation wiring, not production configuration evidence.

## Section 5: Wave-by-Wave Landing Verification

### Wave 2 (contract split)

Claim:
- Three split contracts replace the monolithic `ClarificationContract`.

Evidence the claim landed in code:
- Fresh governed routers do build the split chain when `ENABLE_CONTRACT_SPLIT=true` (`core/governed_router.py:46-89`).
- The three split contract classes are implemented in `core/contracts/intent_resolution_contract.py`, `core/contracts/stance_resolution_contract.py`, and `core/contracts/execution_readiness_contract.py`.

Evidence the claim did not fully land in production architecture:
- Default config leaves the split path off (`config.py:80-82`).
- Default/no-env governed requests therefore use legacy `ClarificationContract` (`core/governed_router.py:70-92`).
- Resumed governed sessions rebuild the legacy chain regardless of split state (`api/session.py:147-161`, `core/governed_router.py:538-556`).

Verdict:
- `PARTIAL`. Wave 2 landed as code and evaluation wiring, but not as the default production architecture, and not robustly across restored sessions.

### Wave 3 (`ExecutionContinuation`)

Claim:
- Split-native continuation state was added via `ExecutionContinuation`.

Evidence the claim landed in code:
- `ExecutionContinuation` exists with `pending_objective`, `pending_slot`, `pending_next_tool`, `pending_tool_queue`, `probe_count`, and `probe_limit` (`core/execution_continuation.py:8-87`).
- Non-test readers/writers exist in production code: `ExecutionReadinessContract` writes it (`core/contracts/execution_readiness_contract.py:227-308`, `core/contracts/execution_readiness_contract.py:348-512`), `OASCContract` advances it after tool execution (`core/contracts/oasc_contract.py:108-196`), `IntentResolutionContract` consumes it for short-circuit binding (`core/contracts/intent_resolution_contract.py:36-83`), and `AOManager` uses it to block AO completion (`core/ao_manager.py:379-410`).

Is the class reachable from production?
- `YES`, but only through split-enabled governed routers; default config keeps that path off (`config.py:80-96`), and restored sessions drop back to the legacy chain (`core/governed_router.py:538-556`).

Is `projected_chain` written and consumed anywhere non-test?
- `YES`.
- Written/propagated from intent hints into `ToolIntent.projected_chain` (`core/contracts/clarification_contract.py:723-745`, `core/intent_resolver.py:239-248`, `core/analytical_objective.py:48-99`).
- Consumed by readiness and OASC continuation logic (`core/contracts/execution_readiness_contract.py:78-82`, `core/contracts/oasc_contract.py:132-165`).

Verdict:
- `PARTIAL`. Wave 3 is real code with non-test reads/writes, but it is not on the default production path and is undermined by the restore-path fallback.

### Wave 4 (config migration: `clarification_followup_slots`, `confirm_first_slots`)

Claim:
- Split readiness should consume these config fields.

Evidence the config keys exist:
- `config/unified_mappings.yaml:556-593` defines `clarification_followup_slots` and `confirm_first_slots` for factor/micro/macro tools.

Evidence the split path consumes them:
- `ExecutionReadinessContract` reads `clarification_followup_slots` and `confirm_first_slots` from either prior `execution_readiness` metadata or tool config (`core/contracts/execution_readiness_contract.py:129-140`).
- It persists them back into split-native AO metadata (`core/contracts/execution_readiness_contract.py:671-698`).
- Missing confirm-first slots are explicitly recomputed (`core/contracts/execution_readiness_contract.py:711-727`).

Did the claim land in the default production path?
- `NO` by default, because split mode is off (`config.py:80-82`).

Verdict:
- `PARTIAL`. The Wave 4 config migration exists in code and is consumed by split readiness, but only when split mode is actually active on a fresh governed router.

### Wave 5a (`probe_limit` enforcement)

Claim:
- `probe_count` and `probe_limit` should be enforced.

Evidence the invariant exists in code:
- `ExecutionContinuation` defines `probe_count` and `probe_limit`, defaulting to `0` and `2` (`core/execution_continuation.py:20-21`).
- `ExecutionReadinessContract` checks `if optional_only_probe and probe_count_value >= probe_limit: force proceed` (`core/contracts/execution_readiness_contract.py:227-240`).
- Telemetry records the result under `force_proceed_reason`, `probe_count`, and `probe_limit` (`core/contracts/execution_readiness_contract.py:603-616`).

Consumer location:
- `core/contracts/execution_readiness_contract.py:227-240`, `core/contracts/execution_readiness_contract.py:348-429`.

Default value:
- `probe_limit=2` from `core/execution_continuation.py:20-21`, also normalized in `from_dict(...)` (`core/execution_continuation.py:75-76`).

Did it land in default production?
- `NO` by default, because the split readiness path is off unless `ENABLE_CONTRACT_SPLIT=true` (`config.py:80-96`).

Verdict:
- `PARTIAL`. Enforcement code landed, but it only executes on the split path and is therefore not the default production behavior.

## Section 6: Contradictions and Open Questions

### Contradictions

1. `paper_notes.md` still says "Wave 2 complete, Wave 3 planned" (`paper_notes.md:5-8`, `paper_notes.md:36`), but HEAD contains `ExecutionContinuation` and Wave 4/5a-era readiness logic (`core/execution_continuation.py:8-87`, `core/contracts/execution_readiness_contract.py:129-140`, `core/contracts/execution_readiness_contract.py:227-240`). This notes file is stale relative to the codebase.

2. `evaluation/run_oasc_matrix.py` still labels group E as "Full OASC + Wave 3 continuation" (`evaluation/run_oasc_matrix.py:97-114`), but current HEAD already includes Wave 4-style follow-up/confirm-first consumption and Wave 5a-style probe-limit enforcement (`core/contracts/execution_readiness_contract.py:129-140`, `core/contracts/execution_readiness_contract.py:227-240`). The evaluation label is stale relative to HEAD.

3. `evaluation/diagnostics/wave3_stage2_multiturn_gate_failure.md` says the split path "does not consume" follow-up / confirm-first semantics (`evaluation/diagnostics/wave3_stage2_multiturn_gate_failure.md:97-126`, `evaluation/diagnostics/wave3_stage2_multiturn_gate_failure.md:236-239`), but current code does consume both in `ExecutionReadinessContract` (`core/contracts/execution_readiness_contract.py:129-140`, `core/contracts/execution_readiness_contract.py:671-698`). The diagnosis describes an earlier checkpoint, not current HEAD.

4. `evaluation/reports/PHASE2R_WAVE2_REPORT.md` presents split routing as a clean feature-gated alternative to legacy clarification (`evaluation/reports/PHASE2R_WAVE2_REPORT.md:26-35`), but current restore logic forces legacy clarification back into resumed governed sessions even under split mode (`api/session.py:147-161`, `core/governed_router.py:538-556`). The feature-gate story is incomplete unless restore behavior is considered.

### Open questions

- `UNVERIFIED: whether deployed production actually sets ENABLE_CONTRACT_SPLIT=true.` Code only shows the hardcoded default (`config.py:80-82`) and evaluation overrides (`evaluation/run_oasc_matrix.py:34-155`), not deployed env.

- `UNVERIFIED: how often resumed governed sessions hit the restore-path regression in real usage.` The code path is real (`api/session.py:147-161`, `core/governed_router.py:538-556`), but read-only audit cannot measure how often existing session state files trigger it.

- `UNVERIFIED: whether "full" and "governed_v2" are intentionally meant to be behavioral aliases in production.` The code makes them nearly the same under default config (`api/session.py:48-70`, `core/governed_router.py:565-569`), but intent cannot be confirmed from code alone.

- `UNVERIFIED: how often conversation fast path materially bypasses the governed/state execution path in practice.` The code path exists (`core/router.py:623-734`), but runtime frequency would require trace sampling.

## Section 7: One-Paragraph Executive Summary

OA is not a dead parallel track: the default API hot path usually enters `GovernedRouter`, instantiates `AOManager`, and runs `OASCContract`, so OA as a wrapper architecture is live in production code. But the split OA architecture claimed by Wave 2/3/4/5a is not the default production path, because `ENABLE_CONTRACT_SPLIT` defaults to `false`, which leaves legacy `ClarificationContract` on the hot path. More importantly, even when split mode is enabled, resumed governed sessions currently rebuild the legacy clarification chain, so split-wave behavior is not stable across persisted session restores. Wave 2/3/4/5a therefore landed as real code, not fiction, but only partially as production architecture. The single most important fact from this audit is that the codebase has two OA realities at once: a live governed/OASC shell on the hot path, and a split-contract implementation that is neither default nor restore-safe.
