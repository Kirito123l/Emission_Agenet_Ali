# WP-CONV-1 Baseline Snapshot

Recorded at: 2026-04-11T03:33:37Z

## git status --short
```
 M .env.example
 M .gitignore
 M config.py
 M config/cross_constraints.yaml
 M core/router.py
 M evaluation/benchmarks/end2end_tasks.jsonl
 M evaluation/eval_ablation.py
 M evaluation/eval_end2end.py
 M evaluation/utils.py
 M services/cross_constraints.py
 M services/model_backend.py
 M services/standardization_engine.py
 M tests/test_config.py
 M tests/test_cross_constraints.py
 M tests/test_file_analyzer_targeted_enhancements.py
 M tools/file_analyzer.py
?? CODEBASE_AUDIT_FOR_PAPER.md
?? EMISSIONAGENT_CONVERSATION_UPGRADE_PLAN.md
?? MULTI_TURN_DIAGNOSTIC.md
?? POST_WP4_SNAPSHOT.md
?? SYSTEM_FOR_PAPER_REFACTOR.md
?? docs/upgrade/
?? evaluation/run_e2e_stable.py
```

## Pre-existing diffs for WP-CONV-1 touch files

### core/router.py
```diff
diff --git a/core/router.py b/core/router.py
index 6a8766f..1ed0024 100644
--- a/core/router.py
+++ b/core/router.py
@@ -1034,10 +1034,34 @@ class UnifiedRouter:
             if meteorology_result.success and meteorology_result.normalized:
                 standardized_params["meteorology"] = meteorology_result.normalized
 
+        if effective_arguments.get("pollutant"):
+            pollutant_raw = str(effective_arguments.get("pollutant"))
+            pollutant_result = standardizer.standardize_pollutant_detailed(pollutant_raw)
+            if pollutant_result.success and pollutant_result.normalized:
+                standardized_params["pollutant"] = pollutant_result.normalized
+
+        if isinstance(effective_arguments.get("pollutants"), list):
+            normalized_pollutants: List[Any] = []
+            for item in effective_arguments.get("pollutants", []):
+                if item is None or not isinstance(item, str):
+                    normalized_pollutants.append(item)
+                    continue
+                pollutant_result = standardizer.standardize_pollutant_detailed(item)
+                normalized_pollutants.append(
+                    pollutant_result.normalized
+                    if pollutant_result.success and pollutant_result.normalized
+                    else item
+                )
+            if normalized_pollutants:
+                standardized_params["pollutants"] = normalized_pollutants
+
         if not standardized_params:
             return False
 
-        constraint_result = get_cross_constraint_validator().validate(standardized_params)
+        constraint_result = get_cross_constraint_validator().validate(
+            standardized_params,
+            tool_name=tool_name,
+        )
         if constraint_result.warnings and trace_obj:
             trace_obj.record(
                 step_type=TraceStepType.CROSS_CONSTRAINT_WARNING,
```

### core/router_render_utils.py
```diff
```

### core/assembler.py
```diff
```

### services/llm_client.py
```diff
```

### api/session.py
```diff
```

### config.py
```diff
diff --git a/config.py b/config.py
index 221591e..0fd356e 100644
--- a/config.py
+++ b/config.py
@@ -74,7 +74,7 @@ class Config:
         self.enable_cross_constraint_validation = (
             os.getenv("ENABLE_CROSS_CONSTRAINT_VALIDATION", "true").lower() == "true"
         )
-        self.enable_parameter_negotiation = os.getenv("ENABLE_PARAMETER_NEGOTIATION", "false").lower() == "true"
+        self.enable_parameter_negotiation = os.getenv("ENABLE_PARAMETER_NEGOTIATION", "true").lower() == "true"
         self.enable_file_analysis_llm_fallback = os.getenv("ENABLE_FILE_ANALYSIS_LLM_FALLBACK", "false").lower() == "true"
         self.enable_workflow_templates = os.getenv("ENABLE_WORKFLOW_TEMPLATES", "false").lower() == "true"
         self.enable_capability_aware_synthesis = (
```

### .env.example
```diff
diff --git a/.env.example b/.env.example
index e5f2072..f00da30 100644
--- a/.env.example
+++ b/.env.example
@@ -102,7 +102,7 @@ MAX_ORCHESTRATION_STEPS=4
 # Enable post-standardization cross-constraint validation
 ENABLE_CROSS_CONSTRAINT_VALIDATION=true
 # Enable parameter negotiation when confidence is low
-ENABLE_PARAMETER_NEGOTIATION=false
+ENABLE_PARAMETER_NEGOTIATION=true
 # Negotiation threshold below which confirmation is required
 PARAMETER_NEGOTIATION_CONFIDENCE_THRESHOLD=0.85
 # Maximum number of negotiation candidates to surface
```

### tests/test_router_state_loop.py
```diff
```

### tests/test_router_contracts.py
```diff
```

### tests/test_assembler_skill_injection.py
```diff
```

### tests/test_session_persistence.py
```diff
```

### tests/test_config.py
```diff
diff --git a/tests/test_config.py b/tests/test_config.py
index 0ceb650..f0efb9e 100644
--- a/tests/test_config.py
+++ b/tests/test_config.py
@@ -42,7 +42,7 @@ class TestConfigLoading:
         assert config.standardization_fuzzy_enabled is True
         assert config.continuation_prompt_variant == "balanced_repair_aware"
         assert config.enable_cross_constraint_validation is True
-        assert config.enable_parameter_negotiation is False
+        assert config.enable_parameter_negotiation is True
         assert config.parameter_negotiation_confidence_threshold == 0.85
         assert config.parameter_negotiation_max_candidates == 5
         assert config.enable_capability_aware_synthesis is True
```
