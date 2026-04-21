# Dispersion Intent Without Upstream Data

## 1. Reproduction Trace with Code Pointers

### 1.1 Web UI default path is `full`, not `governed_v2`

The repo's current web UI defaults to `full` router mode, not `governed_v2`.

- Frontend default: [web/app.js](/home/kirito/Agent1/emission_agent/web/app.js#L5)
- Session wiring:
  - `full` uses `Session.router` -> `UnifiedRouter`: [api/session.py](/home/kirito/Agent1/emission_agent/api/session.py#L48)
  - `governed_v2` is a separate explicit mode: [api/session.py](/home/kirito/Agent1/emission_agent/api/session.py#L60)

So the exact web repro described by the user is most likely happening on the **UnifiedRouter / full-mode** path unless the router mode was manually switched.

### 1.2 Q1: What does the classifier / fast-path resolve on turn 1?

There is no `core/conversation_fast_path.py` file in the current repo. The relevant logic lives in:

- conversation intent classifier: [core/conversation_intent.py](/home/kirito/Agent1/emission_agent/core/conversation_intent.py#L167)
- fast-path gate: [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L623)

For the message `"我想做扩散分析"`:

1. `ConversationIntentClassifier` sees a task cue (`做扩散` / `扩散`) and returns:
   - intent = `NEW_TASK`
   - confidence = `0.7`
   - `fast_path_allowed = False`
   Code: [core/conversation_intent.py](/home/kirito/Agent1/emission_agent/core/conversation_intent.py#L193)

2. `UnifiedRouter._maybe_handle_conversation_fast_path()` records that classification, then exits early because fast path is not allowed.
   Code: [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L633), [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L668)

3. Inside the normal routing path, `_extract_message_execution_hints()` sets:
   - `wants_dispersion = True`
   - `desired_tool_chain = ["calculate_dispersion"]`
   Code: [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1666), [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1682)

4. On the split/governed path, the fast intent resolver would also resolve:
   - tool = `calculate_dispersion`
   - confidence = `HIGH`
   - `resolved_by = "rule:desired_chain"`
   Code: [core/intent_resolver.py](/home/kirito/Agent1/emission_agent/core/intent_resolver.py#L23)

So the first-turn tool intent is unambiguous in both paths: **`calculate_dispersion` with high rules-based confidence**. The problem is not intent misclassification; it is what happens **after** that intent is resolved.

### 1.3 What happens next in `full` mode

After intent extraction, the full router calls the LLM with skill-injected prompts. If the LLM returns tool calls, the router goes directly to `GROUNDED`:

- tool-call acceptance: [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L10577)
- transition to `GROUNDED`: [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L10590)

The important part is that the repo already contains the **correct** prerequisite clarification for this case:

> 做扩散分析前，我需要路网排放结果。你可以上传路网文件让我先算排放，或直接说明要基于哪一份排放结果继续。

Code: [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1786)

But that clarification is only used inside `_maybe_recover_missing_tool_call()`, which runs **only when the LLM returns no tool call / no content**:

- fallback-only hook: [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L1927)
- invoked only on empty no-tool reply: [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L10596)

So in full mode the upstream-data check exists, but it is misplaced: it is a **fallback recovery**, not a first-class readiness gate.

### 1.4 Why does meteorology confirmation appear first in `full` mode?

The meteorology-first behavior comes from **skill injection**, not from `confirm_first_slots`.

1. `SkillInjector` maps dispersion intent to:
   - tools: `calculate_dispersion`, `render_spatial_map`
   - skills: `dispersion_skill`, `meteorology_guide`
   Code: [core/skill_injector.py](/home/kirito/Agent1/emission_agent/core/skill_injector.py#L28)

2. The same injector also auto-expands unmet prerequisites, so `emission` intent is added when dispersion has no `emission` result yet.
   Code: [core/skill_injector.py](/home/kirito/Agent1/emission_agent/core/skill_injector.py#L111)

3. But `dispersion_skill.yaml` explicitly tells the LLM:
   - before calling `calculate_dispersion`, first present a meteorology confirmation block
   - give default preset details
   - wait for user confirmation
   Code: [config/skills/dispersion_skill.yaml](/home/kirito/Agent1/emission_agent/config/skills/dispersion_skill.yaml#L7)

4. The same skill does mention the real prerequisite:
   - “扩散分析需要排放数据。如果没有排放结果，先引导用户做排放计算。”
   Code: [config/skills/dispersion_skill.yaml](/home/kirito/Agent1/emission_agent/config/skills/dispersion_skill.yaml#L39)

In practice, the prompt gives the LLM two competing instructions:

- high-salience structured meteorology confirmation
- lower-salience prerequisite reminder

Because there is no earlier deterministic prerequisite gate, the meteorology branch can surface before the upstream-data branch.

### 1.5 Q2: Where is upstream-data requirement checked, or not checked?

#### Tool layer

The tool itself clearly expects upstream emission data:

- contract description says dispersion “Requires emission results”: [config/tool_contracts.yaml](/home/kirito/Agent1/emission_agent/config/tool_contracts.yaml#L347)
- tool implementation defaults `emission_source="last_result"` and fails if no emission data is available:
  [tools/dispersion.py](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L93),
  [tools/dispersion.py](/home/kirito/Agent1/emission_agent/tools/dispersion.py#L122)

So the prerequisite is real and already declared at the tool layer.

#### Dependency graph / readiness layer

The canonical dependency graph also knows that:

- `calculate_dispersion` requires `emission`
- validation function: `validate_tool_prerequisites()`
  [core/tool_dependencies.py](/home/kirito/Agent1/emission_agent/core/tool_dependencies.py#L119),
  [core/tool_dependencies.py](/home/kirito/Agent1/emission_agent/core/tool_dependencies.py#L181)

And the human-facing blocked reason is already implemented:

- “当前还没有可用的排放结果，因此不能直接执行 calculate_dispersion。”
  [core/readiness.py](/home/kirito/Agent1/emission_agent/core/readiness.py#L638)

#### Full router

In full mode, dependency validation happens too late:

- after tool selection, `GROUNDED` only checks `_identify_critical_missing()`, which does **not** inspect upstream result tokens:
  [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L10612),
  [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L2780)
- dependency validation happens later in execution:
  [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L10880)

And even that late dependency gate is softened for this exact tool:

- `_should_allow_tool_level_dependency_resolution()` explicitly allows `calculate_dispersion` to proceed with missing `["emission"]`
  [core/router.py](/home/kirito/Agent1/emission_agent/core/router.py#L9248)

So the full router can already look “execution-ready” before it notices the missing `emission` prerequisite, and in some paths it intentionally tolerates that missing prerequisite and lets the tool attempt inline resolution anyway.

#### Governed / split path

The split contracts have the same conceptual omission, but at a different layer:

- `calculate_dispersion` in `unified_mappings.yaml` has:
  - `required_slots: []`
  - `optional_slots: [meteorology, pollutant, scenario_label]`
  Code: [config/unified_mappings.yaml](/home/kirito/Agent1/emission_agent/config/unified_mappings.yaml#L595)

- `ExecutionReadinessContract` only reasons about slot snapshots, follow-up slots, confirm-first slots, and optional defaults. It does **not** consume prerequisite result tokens such as `emission`.
  Code: [core/contracts/execution_readiness_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/execution_readiness_contract.py#L84)

- `DependencyContract` is currently a placeholder and performs no check at all.
  Code: [core/contracts/dependency_contract.py](/home/kirito/Agent1/emission_agent/core/contracts/dependency_contract.py#L1)

So governed/split mode also lacks an early upstream-data gate. Its symptom would differ from full mode, but the omission is real there too.

## 2. Root Cause Analysis

### 2.1 Primary root cause for the observed web repro

The observed web bug is a **full-router pre-Wave-1 bug**:

1. web defaults to `full`
2. fast-path correctly classifies this as a task, not casual conversation
3. message hints correctly resolve the downstream tool as `calculate_dispersion`
4. the deterministic upstream-data clarification exists
5. but that clarification only runs as a **no-tool fallback**
6. meanwhile skill injection explicitly primes the LLM to do meteorology confirmation for dispersion

That is why turn 1 looks execution-ready: the prerequisite gate is **not positioned before** the meteorology-confirmation prompt path.

### 2.2 Secondary / parallel root cause in governed split path

The newer split architecture repeats the same conceptual bug in a different form:

- tool intent resolves to `calculate_dispersion`
- readiness sees zero required slots
- readiness has no notion of required upstream result tokens
- dependency contract is empty

If the same request is routed through `governed_v2`, the likely symptom is therefore not the exact same markdown/card UX as full mode. The more likely failure mode is **premature proceed / premature execute** with no upstream emission result.

So split readiness can also mark dispersion as locally ready before verifying that any emission result exists.

### 2.3 Q3: Is this a hardcoded dispersion→meteo path? Is it `confirm_first_slots`?

In current code:

- **Yes, effectively there is a hardcoded dispersion→meteorology path**, but it lives in prompt injection:
  [core/skill_injector.py](/home/kirito/Agent1/emission_agent/core/skill_injector.py#L28),
  [config/skills/dispersion_skill.yaml](/home/kirito/Agent1/emission_agent/config/skills/dispersion_skill.yaml#L7)

- **No, it is not coming from `confirm_first_slots`**:
  `calculate_dispersion` has no `confirm_first_slots` entry in `unified_mappings.yaml`
  [config/unified_mappings.yaml](/home/kirito/Agent1/emission_agent/config/unified_mappings.yaml#L595)

- **No active frontend detector currently turns replies into a meteo card** in the checked-in repo:
  `isMeteoConfirmMessage()` is hardcoded to `return false`
  [web/app.js](/home/kirito/Agent1/emission_agent/web/app.js#L581)

So the current repo state says:

- backend/source of the meteorology-first content = prompt injection
- frontend meteo-card widget exists, but its trigger is dormant in checked-in code

That means the user-facing “card” is either:

1. a locally diverged/cached frontend artifact, or
2. a markdown/table reply that looked like a confirmation card in the UI

Either way, the backend bug is the same: **meteorology confirmation surfaced before upstream-data validation**.

## 3. Fix Spec (Conceptual Only)

### 3.1 Correct behavior

For a fresh session and a first-turn message like `"我想做扩散分析"`:

- the system should resolve intent = `calculate_dispersion`
- then immediately check whether the prerequisite result token `emission` is available
- if not available, it should **not** surface meteorology confirmation
- it should instead ask for:
  - an upstream emission result, or
  - a road-network file so it can compute emissions first

The correct user-facing clarification is already present in code and can be reused:

> 做扩散分析前，我需要路网排放结果。你可以上传路网文件让我先算排放，或直接说明要基于哪一份排放结果继续。

### 3.2 Where the upstream-data check should go

Minimal fix spec:

1. **Full router path**
   - promote the existing dispersion prerequisite check out of `_maybe_recover_missing_tool_call()`
   - run it **before** accepting meteorology confirmation / tool planning as execution-ready
   - practical insertion point: after message-intent/tool-hint extraction, before skill-injected LLM planning is allowed to surface dispersion-parameter confirmation

2. **Governed / split path**
   - add prerequisite-result validation to `ExecutionReadinessContract.before_turn()`
   - use the same canonical dependency validator already used elsewhere:
     `validate_tool_prerequisites(tool_name, ..., context_store=...)`
   - for `calculate_dispersion` with missing `emission`, return `clarify` immediately instead of proceeding to optional-slot logic

3. **No meteorology confirmation before prerequisites**
   - meteorology confirmation should only be reachable after:
     - a usable emission result exists, or
     - a macro-emission file context has already been grounded into an emission-producing workflow

### 3.3 What should replace the meteo card / confirmation text

Replace the current execution-parameter-facing prompt with an upstream-data clarification, for example:

- “做扩散分析前，我需要路网排放结果。你可以上传路网文件让我先算排放，或直接说明要基于哪一份排放结果继续。”

If the user has uploaded a macro-capable road-network file but no emission result yet, the clarification can be slightly shorter:

- “我可以先基于你上传的路网文件计算排放，再继续扩散分析。要我先算排放吗？”

### 3.4 Q4: Pre-Wave-1 bug or later regression?

For the exact web repro in default UI mode, this is **pre-Wave-1 / pre-split**:

- web defaults to `full`
- the meteorology-first instruction is in the long-lived `dispersion_skill`
- the misplaced prerequisite gate is in the legacy UnifiedRouter state machine

However, later waves reproduced the same structural omission in the split path because prerequisite result tokens were never migrated into `ExecutionReadinessContract`. So:

- **observed web bug**: pre-Wave-1
- **same invariant missing in governed_v2**: later architecture still incomplete

## 4. Estimated Affected Categories

### Benchmark categories likely affected

This is a read-only estimate from code structure, not a measured benchmark result.

Most exposed categories:

- `multi_step`
  - downstream-only asks like “做扩散/做热点/画扩散图” without an upstream result
- `incomplete`
  - fresh requests missing file/result prerequisites
- `multi_turn_clarification`
  - first turn can ask the wrong thing (meteorology) before asking the real missing prerequisite
- `user_revision`
  - if a user pivots from an earlier AO into dispersion without valid carried context

Possible spillover:

- `ambiguous_colloquial`
- `code_switch_typo`

whenever the message still strongly triggers dispersion intent while omitting upstream data.

### Real-user impact

This affects real users who start a fresh session with any downstream analysis request such as:

- “我想做扩散分析”
- “帮我做浓度模拟”
- “看一下热点”
- “把扩散结果画出来”

when they have **not yet**:

- uploaded a usable road-network file, or
- produced / referenced an upstream emission result

The same family of bug likely also applies to:

- `analyze_hotspots` without prior `dispersion`
- `render_spatial_map` when the requested layer has no eligible upstream result

because the dependency graph already models those prerequisites, but the earliest user-facing readiness gate is not consistently enforcing them.
