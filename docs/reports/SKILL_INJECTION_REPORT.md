# Skill Injection Architecture - Implementation Report

**Date**: 2026-03-22
**Status**: Complete

---

## 1. Change Summary

### New Files Created

| File | Purpose |
|------|---------|
| `core/skill_injector.py` | Intent detection + skill/tool selection engine |
| `config/prompts/core_v3.yaml` | Slim core prompt with `{situational_prompt}` placeholder |
| `config/skills/dispersion_skill.yaml` | Dispersion analysis guidance (meteorology, coverage) |
| `config/skills/hotspot_skill.yaml` | Hotspot identification guidance |
| `config/skills/emission_skill.yaml` | Emission calculation guidance |
| `config/skills/spatial_skill.yaml` | Map visualization guidance |
| `config/skills/post_emission_guide.yaml` | Post-emission next-step suggestions |
| `config/skills/post_dispersion_guide.yaml` | Post-dispersion next-step suggestions |
| `config/skills/post_hotspot_guide.yaml` | Post-hotspot next-step suggestions |
| `config/skills/meteorology_guide.yaml` | Meteorology preset reference table |
| `config/skills/file_upload_guide.yaml` | File upload handling rules |
| `tests/test_skill_injector.py` | 41 unit tests for SkillInjector |
| `tests/test_assembler_skill_injection.py` | 11 integration tests for assembler |

### Modified Files

| File | Change |
|------|--------|
| `config.py` | Added `enable_skill_injection` config flag (default: `true`) |
| `core/assembler.py` | Split into `_assemble_with_skills()` / `_assemble_legacy()` with shared `_build_messages()` |
| `tools/definitions.py` | Slimmed `calculate_dispersion` desc (1094->228 chars) and `analyze_hotspots` desc (627->194 chars) |
| `tests/test_dispersion_integration.py` | Updated schema validation test for slimmed description |

### Preserved Files (not modified)

- `config/prompts/core.yaml` - Legacy prompt preserved for rollback
- `core/router.py` - No changes needed (passes through `context.tools`)
- `calculators/*`, `tools/*` (except definitions.py), `web/*` - Untouched

---

## 2. SkillInjector Design

### Intent Detection Rules

```
INTENT_RULES:
  dispersion: 扩散, 浓度, dispersion, concentration, 大气, ...
  hotspot:    热点, hotspot, 高浓度, 浓度最高, 溯源, 贡献, 哪条路, ...
  emission:   排放, emission, 计算排放, 宏观, 微观, 路段排放
  visualization: 地图, 可视化, visualization, map, 展示, 显示, 渲染, 看看
  query_ef:   排放因子, 曲线, emission factor, 因子
  knowledge:  知识, 标准, 法规, 什么是, 解释

POST_TOOL_GUIDES:
  calculate_macro_emission  -> post_emission_guide
  calculate_micro_emission  -> post_emission_guide
  calculate_dispersion      -> post_dispersion_guide
  analyze_hotspots          -> post_hotspot_guide
```

### Decision Tree

```
User message arrives
  |-- Keyword match?
  |   |-- Yes -> Add matching intent(s)
  |   '-- No  -> Continue
  |-- File context with task_type?
  |   |-- micro/macro_emission -> Add "emission" + "file_upload"
  |   '-- unknown -> Add "file_upload" only
  |-- Dependency expansion (recursive):
  |   |-- dispersion needs emission_result?
  |   |   |-- last_tool provides it? -> Skip
  |   |   '-- Not available? -> Auto-add "emission" intent
  |   '-- hotspot needs dispersion_result?
  |       '-- Not available? -> Auto-add "dispersion" (+ "emission")
  |-- No intent matched?
  |   |-- last_tool has post-guide? -> Add "post_{tool}" intent
  |   '-- Nothing at all? -> "_fallback_all" (all tools, no skills)
  '-- Build context:
      |-- Layer 1: core_v3.yaml system prompt
      |-- Layer 2: Skill files from matched intents
      |-- Layer 3: Post-tool guide from last_tool_name
      '-- Tools: Only schemas for matched intent tools + defaults
```

---

## 3. Skill Files

| Skill File | Injection Trigger | Key Content |
|------------|------------------|-------------|
| `dispersion_skill` | "扩散", "浓度" keywords | Meteorology must-ask rule, coverage explanation, preset+override |
| `hotspot_skill` | "热点", "贡献" keywords | Percentile/threshold methods, source attribution, sparse warning |
| `emission_skill` | "排放", "计算" keywords | Macro vs micro, vehicle type rules, next-step suggestions |
| `spatial_skill` | "地图", "可视化" keywords | data_source="last_result", auto-detect layer type |
| `post_emission_guide` | After macro/micro emission | Suggest visualization or dispersion analysis |
| `post_dispersion_guide` | After dispersion | Suggest hotspot analysis or map visualization |
| `post_hotspot_guide` | After hotspot analysis | Suggest map or threshold adjustment |
| `meteorology_guide` | With dispersion_skill | Preset reference table (6 presets with wind/stability details) |
| `file_upload_guide` | File uploaded | task_type routing rules |

---

## 4. Token Reduction Measurements

### Tool Schema Size (after description slimming)

| Tool | Before (chars) | After (chars) | Reduction |
|------|---------------|--------------|-----------|
| calculate_dispersion | 3,909 | 1,591 | 59.3% |
| analyze_hotspots | 1,921 | 1,029 | 46.4% |
| All 8 tools total | 10,738 | 7,842 | 27.0% |

### Per-Scenario Tool Injection

| Scenario | Tools Injected | Schema Size (chars) | vs Full (7,842) |
|----------|---------------|--------------------|--------------------|
| Dispersion (has emission) | 4 | 3,471 | **55.7% reduction** |
| Emission | 4 | 2,979 | **62.0% reduction** |
| Hotspot (has dispersion) | 4 | 2,918 | **62.8% reduction** |
| Emission factor query | 5 | 4,140 | **47.2% reduction** |
| Fallback (unknown intent) | 8 | 7,842 | 0% (full) |

### Complete Context Size Comparison (Dispersion Scenario)

| Component | Legacy | Skill Mode | Change |
|-----------|--------|------------|--------|
| System prompt | 1,192 chars | ~800 chars + ~1,100 chars skill | +708 chars (skills add guidance) |
| Tool schemas | 7,842 chars | 3,471 chars | **-4,371 chars (55.7%)** |
| Fact + working memory | ~630 chars | ~630 chars | Same |
| **Net total** | **~9,664 chars** | **~6,001 chars** | **-3,663 chars (37.9%)** |

The key improvement is not just size reduction but **signal concentration**: meteorology and coverage instructions are now in the system prompt where they are much more prominent, rather than buried in a 1,094-char tool description.

---

## 5. Test Results

```
====================== 464 passed, 19 warnings in 43.77s =======================
```

### New Test Coverage

- `tests/test_skill_injector.py`: 41 tests
  - Intent detection: 22 tests (Chinese/English keywords, multi-intent, file context, post-tool, dependencies, fallback)
  - Tool selection: 6 tests (filtering, fallback, defaults, union)
  - Situational prompt: 8 tests (post-tool guides, skill loading, combinations)
  - Skill file loading: 5 tests (existence, content, caching, missing)

- `tests/test_assembler_skill_injection.py`: 11 tests
  - Mode switching (v3 prompt vs legacy)
  - Tool injection per scenario
  - Post-tool situational prompts
  - Token reduction verification
  - File context integration
  - Message structure compatibility

---

## 6. Known Limitations

1. **Keyword-based intent detection**: Simple substring matching. May miss intent for paraphrased queries (e.g., "这些数据怎么用" won't match any intent). Mitigated by `_fallback_all`.

2. **No negative intent**: Can't suppress tools. If user says "不要做扩散", "扩散" keyword still triggers dispersion intent.

3. **Skill file size**: Skills add ~100-1000 chars to system prompt. For multi-intent scenarios (emission + dispersion), the combined skills can be lengthy. Net token savings still positive due to tool schema reduction.

4. **ConfigLoader cache**: `ConfigLoader._prompts_cache` is class-level. Tests must clear it between runs with different configs.

---

## 7. Rollback Plan

Set environment variable:
```bash
ENABLE_SKILL_INJECTION=false
```

This fully restores legacy behavior: `core.yaml` prompt, all 8 tool schemas, no skill injection. The slimmed tool descriptions in `definitions.py` still apply, but they are functionally equivalent (same parameters, just shorter descriptions).

---

## 8. Next Steps (Sub-task B)

1. **A/B Testing**: Call Qwen-Plus API with legacy vs skill-injected prompts for the dispersion scenario. Measure whether LLM asks about meteorology conditions more reliably.

2. **LLM-based intent detection**: For ambiguous messages, use a lightweight LLM call to classify intent instead of keyword matching.

3. **Dynamic tool schema expansion**: If LLM tries to call a tool not in the injected set, intercept and re-call with the needed schema added.

4. **Metrics**: Add logging to track which intents fire most often, enabling data-driven keyword tuning.
