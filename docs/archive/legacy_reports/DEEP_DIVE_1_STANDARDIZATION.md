# DEEP_DIVE_1_STANDARDIZATION

## 0. 范围说明

本文件只描述当前实现现状，不包含改造建议。实现/配置/测试/评估文件的盘点集中放在第 1 节；运行时消费者和所有调用点集中放在第 6 节。

---

## 1. 所有标准化相关文件清单

### 1.1 实现 / 配置主文件

#### `services/standardizer.py`

- 文件路径与行数：`services/standardizer.py`，758 行。证据：`services/standardizer.py:1-758`。
- 主要类 / 函数列表：
  - `StandardizationResult`，`services/standardizer.py:33`
  - `StandardizationResult.to_dict()`，`services/standardizer.py:43`
  - `UnifiedStandardizer`，`services/standardizer.py:56`
  - `UnifiedStandardizer.__init__()`，`services/standardizer.py:64`
  - `UnifiedStandardizer._build_lookup_tables()`，`services/standardizer.py:70`
  - `UnifiedStandardizer._fuzzy_ratio()`，`services/standardizer.py:163`
  - `UnifiedStandardizer._try_local_standardization()`，`services/standardizer.py:167`
  - `UnifiedStandardizer._rank_standard_names()`，`services/standardizer.py:213`
  - `UnifiedStandardizer.standardize_vehicle_detailed()`，`services/standardizer.py:231`
  - `UnifiedStandardizer.standardize_vehicle()`，`services/standardizer.py:290`
  - `UnifiedStandardizer.standardize_pollutant_detailed()`，`services/standardizer.py:300`
  - `UnifiedStandardizer.standardize_pollutant()`，`services/standardizer.py:359`
  - `UnifiedStandardizer.standardize_season()`，`services/standardizer.py:369`
  - `UnifiedStandardizer.standardize_road_type()`，`services/standardizer.py:418`
  - `UnifiedStandardizer.standardize_meteorology()`，`services/standardizer.py:467`
  - `UnifiedStandardizer.standardize_stability_class()`，`services/standardizer.py:527`
  - `UnifiedStandardizer.get_vehicle_suggestions()`，`services/standardizer.py:578`
  - `UnifiedStandardizer.get_pollutant_suggestions()`，`services/standardizer.py:615`
  - `UnifiedStandardizer.map_columns()`，`services/standardizer.py:631`
  - `UnifiedStandardizer.get_required_columns()`，`services/standardizer.py:691`
  - `UnifiedStandardizer.get_column_patterns_for_display()`，`services/standardizer.py:710`
  - `UnifiedStandardizer._get_local_model()`，`services/standardizer.py:725`
  - `get_standardizer()`，`services/standardizer.py:753`
- 被哪些文件 import：
  - `core/file_analysis_fallback.py:7`，`from services.standardizer import get_standardizer`
  - `tools/file_analyzer.py:15`，`from services.standardizer import get_standardizer`
  - `tools/macro_emission.py:146`，`from services.standardizer import get_standardizer`
  - `evaluation/eval_normalization.py:26`，`from services.standardizer import get_standardizer`
  - `tests/test_standardizer.py:6`，`from services.standardizer import UnifiedStandardizer`
  - `tests/test_standardizer_enhanced.py:11` 等多处按函数内局部导入，`from services.standardizer import get_standardizer`
  - `tests/test_standardization_engine.py:12`，`from services.standardizer import StandardizationResult, get_standardizer`
  - `tests/test_dispersion_integration.py:18`，`from services.standardizer import UnifiedStandardizer`
  - `services/standardization_engine.py:30`，`from services.standardizer import StandardizationResult, UnifiedStandardizer, get_standardizer`
- 它 import 的内部模块：
  - `services/config_loader.ConfigLoader`，`services/standardizer.py:11`
  - 惰性导入 `config.get_config`，`services/standardizer.py:734`
  - 惰性导入 `shared.standardizer.local_client.get_local_standardizer_client`，`services/standardizer.py:738`

#### `services/standardization_engine.py`

- 文件路径与行数：`services/standardization_engine.py`，1029 行。证据：`services/standardization_engine.py:1-1029`。
- 主要类 / 函数列表：
  - `_merge_config()`，`services/standardization_engine.py:109`
  - `_clean_string()`，`services/standardization_engine.py:121`
  - `_dedupe()`，`services/standardization_engine.py:127`
  - `BatchStandardizationError`，`services/standardization_engine.py:138`
  - `BatchStandardizationError.__init__()`，`services/standardization_engine.py:141`
  - `StandardizationBackend`，`services/standardization_engine.py:160`
  - `StandardizationBackend.standardize()`，`services/standardization_engine.py:164`
  - `RuleBackend`，`services/standardization_engine.py:175`
  - `RuleBackend.__init__()`，`services/standardization_engine.py:184`
  - `RuleBackend.rule_standardizer`，`services/standardization_engine.py:190`
  - `RuleBackend.standardize()`，`services/standardization_engine.py:193`
  - `RuleBackend._needs_custom_threshold()`，`services/standardization_engine.py:219`
  - `RuleBackend._threshold_for()`，`services/standardization_engine.py:226`
  - `RuleBackend._lookup_for()`，`services/standardization_engine.py:234`
  - `RuleBackend._standardize_with_custom_threshold()`，`services/standardization_engine.py:245`
  - `RuleBackend._legacy_blank_result()`，`services/standardization_engine.py:354`
  - `LLMBackend`，`services/standardization_engine.py:366`
  - `LLMBackend.__init__()`，`services/standardization_engine.py:374`
  - `LLMBackend.standardize()`，`services/standardization_engine.py:383`
  - `LLMBackend._get_client()`，`services/standardization_engine.py:431`
  - `LLMBackend._call_llm()`，`services/standardization_engine.py:446`
  - `LLMBackend._build_prompt()`，`services/standardization_engine.py:471`
  - `StandardizationEngine`，`services/standardization_engine.py:505`
  - `StandardizationEngine.__init__()`，`services/standardization_engine.py:508`
  - `StandardizationEngine.rule_backend`，`services/standardization_engine.py:518`
  - `StandardizationEngine.rule_standardizer`，`services/standardization_engine.py:522`
  - `StandardizationEngine._init_llm_backend()`，`services/standardization_engine.py:525`
  - `StandardizationEngine._load_param_registry()`，`services/standardization_engine.py:528`
  - `StandardizationEngine._load_catalog()`，`services/standardization_engine.py:531`
  - `StandardizationEngine.standardize()`，`services/standardization_engine.py:615`
  - `StandardizationEngine.standardize_batch()`，`services/standardization_engine.py:687`
  - `StandardizationEngine.get_candidates()`，`services/standardization_engine.py:758`
  - `StandardizationEngine.register_param_type()`，`services/standardization_engine.py:764`
  - `StandardizationEngine.get_param_type()`，`services/standardization_engine.py:767`
  - `StandardizationEngine._get_aliases()`，`services/standardization_engine.py:770`
  - `StandardizationEngine.get_candidate_aliases()`，`services/standardization_engine.py:776`
  - `StandardizationEngine.resolve_candidate_value()`，`services/standardization_engine.py:782`
  - `StandardizationEngine._should_passthrough()`，`services/standardization_engine.py:809`
  - `StandardizationEngine._passthrough_value()`，`services/standardization_engine.py:816`
  - `StandardizationEngine._standardize_list()`，`services/standardization_engine.py:826`
  - `StandardizationEngine._standardize_list_param()`，`services/standardization_engine.py:883`
  - `StandardizationEngine._should_accept_rule_result()`，`services/standardization_engine.py:909`
  - `StandardizationEngine._can_try_llm()`，`services/standardization_engine.py:924`
  - `StandardizationEngine._is_llm_enabled_for()`，`services/standardization_engine.py:933`
  - `StandardizationEngine._get_suggestions()`，`services/standardization_engine.py:938`
  - `StandardizationEngine._build_failure_message()`，`services/standardization_engine.py:955`
  - `StandardizationEngine._build_negotiation_message()`，`services/standardization_engine.py:963`
  - `StandardizationEngine._parameter_negotiation_enabled()`，`services/standardization_engine.py:970`
  - `StandardizationEngine._parameter_negotiation_threshold()`，`services/standardization_engine.py:973`
  - `StandardizationEngine._parameter_negotiation_max_candidates()`，`services/standardization_engine.py:976`
  - `StandardizationEngine._build_negotiation_suggestions()`，`services/standardization_engine.py:979`
  - `StandardizationEngine._should_trigger_parameter_negotiation()`，`services/standardization_engine.py:992`
  - `StandardizationEngine._build_negotiation_trigger_reason()`，`services/standardization_engine.py:1014`
  - `StandardizationEngine._should_record_passthrough()`，`services/standardization_engine.py:1020`
- 被哪些文件 import：
  - `core/executor.py:9`，`from services.standardization_engine import BatchStandardizationError, StandardizationEngine`
  - `tests/test_standardization_engine.py:7-10`，`from services.standardization_engine import ( BatchStandardizationError, PARAM_TYPE_REGISTRY, StandardizationEngine, )`
  - `tests/test_parameter_negotiation.py:11`，`from services.standardization_engine import BatchStandardizationError, StandardizationEngine`
- 它 import 的内部模块：
  - `config.get_config`，`services/standardization_engine.py:28`
  - `services.config_loader.ConfigLoader`，`services/standardization_engine.py:29`
  - `services.standardizer.StandardizationResult / UnifiedStandardizer / get_standardizer`，`services/standardization_engine.py:30`
  - 动态导入 `services.llm_client.LLMClientService`，`services/standardization_engine.py:435`

#### `services/config_loader.py`

- 文件路径与行数：`services/config_loader.py`，152 行。证据：`services/config_loader.py:1-152`。
- 主要类 / 函数列表：
  - `ConfigLoader`，`services/config_loader.py:19`
  - `ConfigLoader.load_mappings()`，`services/config_loader.py:26`
  - `ConfigLoader.load_prompts()`，`services/config_loader.py:45`
  - `ConfigLoader.load_tool_definitions()`，`services/config_loader.py:64`
  - `ConfigLoader.get_vehicle_types()`，`services/config_loader.py:76`
  - `ConfigLoader.get_pollutants()`，`services/config_loader.py:82`
  - `ConfigLoader.get_column_patterns()`，`services/config_loader.py:88`
  - `ConfigLoader.get_defaults()`，`services/config_loader.py:103`
  - `ConfigLoader.get_vsp_params()`，`services/config_loader.py:109`
  - `ConfigLoader.get_vsp_bins()`，`services/config_loader.py:126`
  - `ConfigLoader.reload()`，`services/config_loader.py:132`
  - `get_config_loader()`，`services/config_loader.py:140`
  - `load_mappings()`，`services/config_loader.py:145`
  - `load_prompts()`，`services/config_loader.py:150`
- 被哪些文件 import：
  - `services/standardizer.py:11`，`from services.config_loader import ConfigLoader`
  - `services/standardization_engine.py:29`，`from services.config_loader import ConfigLoader`
  - `core/assembler.py:16`，`from services.config_loader import ConfigLoader`
  - `tests/test_assembler_skill_injection.py:16`，`from services.config_loader import ConfigLoader`
  - `scripts/utils/test_new_architecture.py:44`，`from services.config_loader import ConfigLoader`
- 它 import 的内部模块：
  - `tools.definitions.TOOL_DEFINITIONS` 的延迟导入，`services/config_loader.py:72`
- 与 `config/unified_mappings.yaml` 的关系：
  - `MAPPINGS_FILE = CONFIG_DIR / "unified_mappings.yaml"`，`services/config_loader.py:15`
  - `load_mappings()` 通过 `yaml.safe_load(f)` 读取该 YAML，`services/config_loader.py:33-37`

#### `shared/standardizer/__init__.py`

- 文件路径与行数：`shared/standardizer/__init__.py`，1 行。证据：`shared/standardizer/__init__.py:1`。
- 主要内容：只有注释 `# Standardizer Module`，`shared/standardizer/__init__.py:1`。
- 被哪些文件 import：未看到 `from shared.standardizer import ...` 的直接静态导入；已确认的引用都落在子模块上，见 `shared/standardizer/*` 子模块调用点和第 6 节。
- 它 import 的内部模块：无。

#### `shared/standardizer/constants.py`

- 文件路径与行数：`shared/standardizer/constants.py`，84 行。证据：`shared/standardizer/constants.py:1-84`。
- 主要常量列表：
  - `VEHICLE_TYPE_MAPPING`，`shared/standardizer/constants.py:1`
  - `VEHICLE_ALIAS_TO_STANDARD`，`shared/standardizer/constants.py:17`
  - `STANDARD_VEHICLE_TYPES`，`shared/standardizer/constants.py:24`
  - `POLLUTANT_MAPPING`，`shared/standardizer/constants.py:26`
  - `POLLUTANT_ALIAS_TO_STANDARD`，`shared/standardizer/constants.py:35`
  - `STANDARD_POLLUTANTS`，`shared/standardizer/constants.py:42`
  - `SEASON_MAPPING`，`shared/standardizer/constants.py:44`
  - `VSP_PARAMETERS`，`shared/standardizer/constants.py:52`
  - `VSP_BINS`，`shared/standardizer/constants.py:69`
- 被哪些文件 import：
  - `skills/macro_emission/skill.py:7`，`from shared.standardizer.constants import SEASON_MAPPING`
  - `skills/micro_emission/skill.py:12`，`from shared.standardizer.constants import SEASON_MAPPING`
  - `calculators/vsp.py:5`，`from shared.standardizer.constants import VSP_PARAMETERS, VSP_BINS`
  - `skills/micro_emission/vsp.py:5`，`from shared.standardizer.constants import VSP_PARAMETERS, VSP_BINS`
- 它 import 的内部模块：无。

#### `shared/standardizer/local_client.py`

- 文件路径与行数：`shared/standardizer/local_client.py`，253 行。证据：`shared/standardizer/local_client.py:1-253`。
- 主要类 / 函数列表：
  - `LocalStandardizerClient`，`shared/standardizer/local_client.py:16`
  - `LocalStandardizerClient.__init__()`，`shared/standardizer/local_client.py:19`
  - `LocalStandardizerClient._init_direct_mode()`，`shared/standardizer/local_client.py:37`
  - `LocalStandardizerClient._init_vllm_mode()`，`shared/standardizer/local_client.py:82`
  - `LocalStandardizerClient._switch_adapter()`，`shared/standardizer/local_client.py:103`
  - `LocalStandardizerClient._generate_direct()`，`shared/standardizer/local_client.py:133`
  - `LocalStandardizerClient._generate_vllm()`，`shared/standardizer/local_client.py:166`
  - `LocalStandardizerClient.standardize_vehicle()`，`shared/standardizer/local_client.py:188`
  - `LocalStandardizerClient.standardize_pollutant()`，`shared/standardizer/local_client.py:201`
  - `LocalStandardizerClient.map_columns()`，`shared/standardizer/local_client.py:214`
  - `get_local_standardizer_client()`，`shared/standardizer/local_client.py:239`
- 被哪些文件 import：
  - `services/standardizer.py:738`，`from shared.standardizer.local_client import get_local_standardizer_client`
  - `shared/standardizer/vehicle.py:43`，`from .local_client import get_local_standardizer_client`
  - `shared/standardizer/pollutant.py:43`，`from .local_client import get_local_standardizer_client`
- 它 import 的内部模块：
  - 惰性导入 `config.get_config`，`shared/standardizer/local_client.py:245`

#### `shared/standardizer/cache.py`

- 文件路径与行数：`shared/standardizer/cache.py`，29 行。证据：`shared/standardizer/cache.py:1-29`。
- 主要类 / 函数列表：
  - `LRUCache`，`shared/standardizer/cache.py:4`
  - `LRUCache.__init__()`，`shared/standardizer/cache.py:6`
  - `LRUCache.get()`，`shared/standardizer/cache.py:10`
  - `LRUCache.put()`，`shared/standardizer/cache.py:17`
  - `LRUCache.clear()`，`shared/standardizer/cache.py:25`
  - `LRUCache.size()`，`shared/standardizer/cache.py:28`
- 被哪些文件 import：除定义本身 `shared/standardizer/cache.py:4-28` 外，当前静态代码中未看到其他引用位置。
- 它 import 的内部模块：无。

#### `shared/standardizer/vehicle.py`

- 文件路径与行数：`shared/standardizer/vehicle.py`，150 行。证据：`shared/standardizer/vehicle.py:1-150`。
- 主要类 / 函数列表：
  - `StandardizationResult`，`shared/standardizer/vehicle.py:13`
  - `VehicleStandardizer`，`shared/standardizer/vehicle.py:33`
  - `VehicleStandardizer.__new__()`，`shared/standardizer/vehicle.py:36`
  - `VehicleStandardizer.standardize()`，`shared/standardizer/vehicle.py:62`
  - `VehicleStandardizer._rule_match()`，`shared/standardizer/vehicle.py:90`
  - `VehicleStandardizer._llm_standardize()`，`shared/standardizer/vehicle.py:102`
  - `VehicleStandardizer._log()`，`shared/standardizer/vehicle.py:133`
  - `get_vehicle_standardizer()`，`shared/standardizer/vehicle.py:149`
- 被哪些文件 import：
  - `skills/macro_emission/skill.py:5`，`from shared.standardizer.vehicle import get_vehicle_standardizer`
  - `skills/micro_emission/skill.py:10`，`from shared.standardizer.vehicle import get_vehicle_standardizer`
- 它 import 的内部模块：
  - `.constants`，`shared/standardizer/vehicle.py:5`
  - `llm.client.get_llm`，`shared/standardizer/vehicle.py:6`
  - `llm.data_collector.get_collector`，`shared/standardizer/vehicle.py:7`
  - `config.get_config`，`shared/standardizer/vehicle.py:8`
  - 惰性导入 `.local_client.get_local_standardizer_client`，`shared/standardizer/vehicle.py:43`

#### `shared/standardizer/pollutant.py`

- 文件路径与行数：`shared/standardizer/pollutant.py`，150 行。证据：`shared/standardizer/pollutant.py:1-150`。
- 主要类 / 函数列表：
  - `StandardizationResult`，`shared/standardizer/pollutant.py:13`
  - `PollutantStandardizer`，`shared/standardizer/pollutant.py:33`
  - `PollutantStandardizer.__new__()`，`shared/standardizer/pollutant.py:36`
  - `PollutantStandardizer.standardize()`，`shared/standardizer/pollutant.py:62`
  - `PollutantStandardizer._rule_match()`，`shared/standardizer/pollutant.py:90`
  - `PollutantStandardizer._llm_standardize()`，`shared/standardizer/pollutant.py:102`
  - `PollutantStandardizer._log()`，`shared/standardizer/pollutant.py:133`
  - `get_pollutant_standardizer()`，`shared/standardizer/pollutant.py:149`
- 被哪些文件 import：
  - `skills/macro_emission/skill.py:6`，`from shared.standardizer.pollutant import get_pollutant_standardizer`
  - `skills/micro_emission/skill.py:11`，`from shared.standardizer.pollutant import get_pollutant_standardizer`
- 它 import 的内部模块：
  - `.constants`，`shared/standardizer/pollutant.py:5`
  - `llm.client.get_llm`，`shared/standardizer/pollutant.py:6`
  - `llm.data_collector.get_collector`，`shared/standardizer/pollutant.py:7`
  - `config.get_config`，`shared/standardizer/pollutant.py:8`
  - 惰性导入 `.local_client.get_local_standardizer_client`，`shared/standardizer/pollutant.py:43`

#### `config/unified_mappings.yaml`

- 文件路径与行数：`config/unified_mappings.yaml`，598 行。证据：`config/unified_mappings.yaml:1-598`。
- 顶层结构：
  - `version`，`config/unified_mappings.yaml:6`
  - `vehicle_types`，`config/unified_mappings.yaml:9`
  - `pollutants`，`config/unified_mappings.yaml:213`
  - `seasons`，`config/unified_mappings.yaml:263`
  - `road_types`，`config/unified_mappings.yaml:289`
  - `meteorology`，`config/unified_mappings.yaml:326`
  - `stability_classes`，`config/unified_mappings.yaml:375`
  - `column_patterns`，`config/unified_mappings.yaml:428`
  - `defaults`，`config/unified_mappings.yaml:539`
  - `vsp_bins`，`config/unified_mappings.yaml:556`
- 被哪些文件 import：该文件不是 Python 模块，没有 `import` 语句；当前读取入口是 `services/config_loader.py:15,33-37`。
- 它 import 的内部模块：不适用。

#### `core/executor.py`

- 文件路径与行数：`core/executor.py`，383 行。证据：`core/executor.py:1-383`。
- 标准化相关类 / 函数列表：
  - `ToolExecutor`，`core/executor.py:152`
  - `ToolExecutor.__init__()`，`core/executor.py:163`
  - `ToolExecutor.execute()`，`core/executor.py:176`
  - `ToolExecutor._standardize_arguments()`，`core/executor.py:317`
  - `StandardizationError`，`core/executor.py:357`
  - `StandardizationError.__init__()`，`core/executor.py:360`
- 被哪些文件 import：
  - `core/router.py:15`，`from core.executor import ToolExecutor`
  - `evaluation/eval_normalization.py:14`，`from core.executor import StandardizationError, ToolExecutor`
  - `tests/test_standardizer_enhanced.py:180` 等函数内导入，`from core.executor import ToolExecutor`
  - `tests/test_dispersion_integration.py:16`，`from core.executor import ToolExecutor`
- 它 import 的内部模块：
  - `config.get_config`，`core/executor.py:7`
  - `tools.registry.get_registry`，`core/executor.py:8`
  - `services.standardization_engine.BatchStandardizationError / StandardizationEngine`，`core/executor.py:9`

#### `core/parameter_negotiation.py`

- 文件路径与行数：`core/parameter_negotiation.py`，435 行。证据：`core/parameter_negotiation.py:1-435`。
- 主要类 / 函数列表：
  - `NegotiationDecisionType`，`core/parameter_negotiation.py:10`
  - `NegotiationCandidate`，`core/parameter_negotiation.py:17`
  - `NegotiationCandidate.to_dict()`，`core/parameter_negotiation.py:26`
  - `NegotiationCandidate.from_dict()`，`core/parameter_negotiation.py:38`
  - `ParameterNegotiationRequest`，`core/parameter_negotiation.py:60`
  - `ParameterNegotiationRequest.to_dict()`，`core/parameter_negotiation.py:71`
  - `ParameterNegotiationRequest.from_dict()`，`core/parameter_negotiation.py:85`
  - `ParameterNegotiationRequest.create()`，`core/parameter_negotiation.py:108`
  - `ParameterNegotiationDecision`，`core/parameter_negotiation.py:134`
  - `ParameterNegotiationDecision.to_dict()`，`core/parameter_negotiation.py:143`
  - `ParameterNegotiationDecision.from_dict()`，`core/parameter_negotiation.py:155`
  - `ParameterNegotiationParseResult`，`core/parameter_negotiation.py:174`
  - `ParameterNegotiationParseResult.to_dict()`，`core/parameter_negotiation.py:180`
  - `_normalize_text()`，`core/parameter_negotiation.py:209`
  - `_extract_parenthetical_parts()`，`core/parameter_negotiation.py:213`
  - `_extract_indices()`，`core/parameter_negotiation.py:229`
  - `_extract_index()`，`core/parameter_negotiation.py:262`
  - `reply_looks_like_confirmation_attempt()`，`core/parameter_negotiation.py:269`
  - `parse_parameter_negotiation_reply()`，`core/parameter_negotiation.py:293`
  - `format_parameter_negotiation_prompt()`，`core/parameter_negotiation.py:377`
  - `build_candidate_aliases()`，`core/parameter_negotiation.py:426`
- 被哪些文件 import：
  - `core/task_state.py:25-27`，`from core.parameter_negotiation import ( ParameterNegotiationDecision, ParameterNegotiationRequest, )`
  - `core/router.py:83-92`，`from core.parameter_negotiation import ( ... format_parameter_negotiation_prompt, parse_parameter_negotiation_reply, reply_looks_like_confirmation_attempt, )`
  - `tests/test_parameter_negotiation.py:5-9`，`from core.parameter_negotiation import ( NegotiationDecisionType, ParameterNegotiationRequest, parse_parameter_negotiation_reply, reply_looks_like_confirmation_attempt, )`
- 它 import 的内部模块：无项目内模块导入。

#### `core/router.py`

- 文件路径与行数：`core/router.py`，9999 行。证据：`core/router.py:1-9999`。
- 本文件内与标准化 / 参数协商直接相关的方法：
  - `_build_parameter_negotiation_request()`，`core/router.py:4142`
  - `_save_active_parameter_negotiation_bundle()`，`core/router.py:4234`
  - `_activate_parameter_confirmation_state()`，`core/router.py:6577`
  - `_should_handle_parameter_confirmation()`，`core/router.py:6618`
  - `_parse_parameter_confirmation_reply()`，`core/router.py:6624`
  - `_build_parameter_confirmation_resume_decision()`，`core/router.py:6637`
  - `_inject_parameter_confirmation_guidance()`，`core/router.py:6694`
  - `_handle_active_parameter_confirmation()`，`core/router.py:6725`
  - 工具执行结果中检测标准化失败并触发协商的逻辑，`core/router.py:9079-9134`
- 被哪些文件 import：当前未看到其他模块直接 `import core.router`；运行入口位置本节未展开。
- 它 import 的内部模块：
  - `core.executor.ToolExecutor`，`core/router.py:15`
  - `core.parameter_negotiation.*`，`core/router.py:83-92`
  - 其余与标准化无关的导入见文件开头 `core/router.py:12-186`

#### `core/task_state.py`

- 文件路径与行数：`core/task_state.py`，971 行。证据：`core/task_state.py:1-971`。
- 与参数协商 / 参数锁定直接相关的方法：
  - `TaskState.set_active_parameter_negotiation()`，`core/task_state.py:663`
  - `TaskState.set_latest_parameter_negotiation_decision()`，`core/task_state.py:669`
  - `TaskState.apply_parameter_lock()`，`core/task_state.py:869`
  - `TaskState.get_parameter_locks_summary()`，`core/task_state.py:890`
- 被哪些文件 import：`core/router.py:138-152` 从 `core.task_state` 导入 `TaskState` 及相关类型。
- 它 import 的内部模块：
  - `core.parameter_negotiation`，`core/task_state.py:25-27`
  - 其余导入见 `core/task_state.py:7-40`

#### `config.py`

- 文件路径与行数：`config.py`，277 行。证据：`config.py:1-277`。
- 与标准化 / 本地模型直接相关的方法与配置承载点：
  - `Config.__post_init__()`，`config.py:18`
  - `Config.is_macro_mapping_mode_enabled()`，`config.py:262`
  - `get_config()`，`config.py:267`
  - `reset_config()`，`config.py:274`
  - 标准化开关位于 `config.py:44-55,189-247`
- 被哪些文件 import：
  - `services/standardization_engine.py:28`，`from config import get_config`
  - `core/executor.py:7`，`from config import get_config`
  - `services/standardization_engine.py` / `services/standardizer.py` / `shared/standardizer/vehicle.py` / `shared/standardizer/pollutant.py` / `shared/standardizer/local_client.py` / `llm/data_collector.py` 等均经 `get_config()` 读取标准化或本地模型配置，具体见各文件 import 行。
- 它 import 的内部模块：无项目内模块导入。

#### `llm/data_collector.py`

- 文件路径与行数：`llm/data_collector.py`，84 行。证据：`llm/data_collector.py:1-84`。
- 主要类 / 函数列表：
  - `DataCollector`，`llm/data_collector.py:6`
  - `DataCollector.__new__()`，`llm/data_collector.py:9`
  - `DataCollector.log()`，`llm/data_collector.py:17`
  - `DataCollector.get_statistics()`，`llm/data_collector.py:37`
  - `DataCollector.export_for_finetune()`，`llm/data_collector.py:55`
  - `get_collector()`，`llm/data_collector.py:83`
- 被哪些文件 import：
  - `shared/standardizer/vehicle.py:7`，`from llm.data_collector import get_collector`
  - `shared/standardizer/pollutant.py:7`，`from llm.data_collector import get_collector`
- 它 import 的内部模块：
  - `config.get_config`，`llm/data_collector.py:4`

### 1.2 测试 / 评估文件

#### `tests/test_standardizer.py`

- 文件路径与行数：`tests/test_standardizer.py`，94 行。证据：`tests/test_standardizer.py:1-94`。
- 主要测试函数：
  - `_make_standardizer()`，`tests/test_standardizer.py:9`
  - `TestVehicleStandardization.*`，`tests/test_standardizer.py:14-49`
  - `TestPollutantStandardization.*`，`tests/test_standardizer.py:52-79`
  - `TestColumnMapping.*`，`tests/test_standardizer.py:82-93`
- 被哪些文件 import：未看到其他文件 import 此测试模块。
- 它 import 的内部模块：
  - `services.standardizer.UnifiedStandardizer`，`tests/test_standardizer.py:6`

#### `tests/test_standardizer_enhanced.py`

- 文件路径与行数：`tests/test_standardizer_enhanced.py`，229 行。证据：`tests/test_standardizer_enhanced.py:1-229`。
- 主要测试类 / 函数：
  - `TestStandardizationResult.*`，`tests/test_standardizer_enhanced.py:8-46`
  - `TestSeasonStandardization.*`，`tests/test_standardizer_enhanced.py:51-77`
  - `TestRoadTypeStandardization.*`，`tests/test_standardizer_enhanced.py:80-111`
  - `TestPasquillStabilityMapping.*`，`tests/test_standardizer_enhanced.py:114-173`
  - `TestExecutorStandardizationRecords.*`，`tests/test_standardizer_enhanced.py:177-228`
- 被哪些文件 import：未看到其他文件 import 此测试模块。
- 它 import 的内部模块：
  - 局部导入 `services.standardizer.get_standardizer`，见 `tests/test_standardizer_enhanced.py:11,22,32,42,53,60,67,74,82,89,95,101,108,135,142,149,156,165`
  - 局部导入 `core.executor.ToolExecutor / StandardizationError`，见 `tests/test_standardizer_enhanced.py:180,194,207,221`

#### `tests/test_standardization_engine.py`

- 文件路径与行数：`tests/test_standardization_engine.py`，358 行。证据：`tests/test_standardization_engine.py:1-358`。
- 主要测试类 / 函数：
  - `_assert_result_matches()`，`tests/test_standardization_engine.py:15`
  - `TestEngineRuleBackendParity.*`，`tests/test_standardization_engine.py:24-125`
  - `TestEngineLLMBackend.*`，`tests/test_standardization_engine.py:128-237`
  - `TestEngineBatchStandardization.*`，`tests/test_standardization_engine.py:243-300`
  - `TestEngineConfiguration.*`，`tests/test_standardization_engine.py:307-324`
  - `TestDeclarativeRegistry.*`，`tests/test_standardization_engine.py:329-357`
- 被哪些文件 import：未看到其他文件 import 此测试模块。
- 它 import 的内部模块：
  - `services.standardization_engine.BatchStandardizationError / PARAM_TYPE_REGISTRY / StandardizationEngine`，`tests/test_standardization_engine.py:7-10`
  - `services.standardizer.StandardizationResult / get_standardizer`，`tests/test_standardization_engine.py:12`

#### `tests/test_parameter_negotiation.py`

- 文件路径与行数：`tests/test_parameter_negotiation.py`，127 行。证据：`tests/test_parameter_negotiation.py:1-127`。
- 主要测试函数：
  - `_build_request()`，`tests/test_parameter_negotiation.py:14`
  - `test_parse_parameter_negotiation_reply_supports_index_and_label_and_none()`，`tests/test_parameter_negotiation.py:47`
  - `test_reply_looks_like_confirmation_attempt_is_bounded()`，`tests/test_parameter_negotiation.py:69`
  - `test_low_confidence_llm_match_raises_negotiation_eligible_batch_error()`，`tests/test_parameter_negotiation.py:78`
  - `test_high_confidence_alias_auto_accepts_without_negotiation()`，`tests/test_parameter_negotiation.py:104`
  - `test_resolve_candidate_value_handles_display_label_and_alias()`，`tests/test_parameter_negotiation.py:122`
- 被哪些文件 import：未看到其他文件 import 此测试模块。
- 它 import 的内部模块：
  - `core.parameter_negotiation.*`，`tests/test_parameter_negotiation.py:5-9`
  - `services.standardization_engine.BatchStandardizationError / StandardizationEngine`，`tests/test_parameter_negotiation.py:11`

#### `tests/test_dispersion_integration.py`

- 文件路径与行数：`tests/test_dispersion_integration.py`，923 行。证据：`tests/test_dispersion_integration.py:1-923`。
- 与标准化直接相关的测试类 / 函数：
  - `standardizer()` fixture，`tests/test_dispersion_integration.py:258`
  - `TestMeteorologyStandardization.*`，`tests/test_dispersion_integration.py:563-612`
  - `TestExecutorDispersionStandardization.*`，`tests/test_dispersion_integration.py:618-657`
- 被哪些文件 import：未看到其他文件 import 此测试模块。
- 它 import 的内部模块：
  - `core.executor.ToolExecutor`，`tests/test_dispersion_integration.py:16`
  - `services.standardizer.UnifiedStandardizer`，`tests/test_dispersion_integration.py:18`

#### `evaluation/eval_normalization.py`

- 文件路径与行数：`evaluation/eval_normalization.py`，160 行。证据：`evaluation/eval_normalization.py:1-160`。
- 主要函数：
  - `_check_param_legality()`，`evaluation/eval_normalization.py:32`
  - `run_normalization_evaluation()`，`evaluation/eval_normalization.py:56`
  - `main()`，`evaluation/eval_normalization.py:132`
- 被哪些文件 import：未看到其他文件 import 此评估脚本。
- 它 import 的内部模块：
  - `core.executor.StandardizationError / ToolExecutor`，`evaluation/eval_normalization.py:14`
  - `evaluation.utils.*`，`evaluation/eval_normalization.py:15-25`
  - `services.standardizer.get_standardizer`，`evaluation/eval_normalization.py:26`

---

## 2. `UnifiedStandardizer` 完整接口

### 2.1 `StandardizationResult` 完整定义

来源：`services/standardizer.py`，`StandardizationResult`，`L33-L53`。

```python
@dataclass
class StandardizationResult:
    """Structured result of a parameter standardization operation."""

    success: bool
    original: str
    normalized: Optional[str] = None
    strategy: str = "none"  # exact / alias / fuzzy / abstain / default
    confidence: float = 0.0
    suggestions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        result = {
            "success": self.success,
            "original": self.original,
            "normalized": self.normalized,
            "strategy": self.strategy,
            "confidence": self.confidence,
        }
        if self.suggestions:
            result["suggestions"] = self.suggestions
        return result
```

### 2.2 `UnifiedStandardizer.__init__()` 完整代码

来源：`services/standardizer.py`，`UnifiedStandardizer.__init__`，`L64-L68`。

```python
def __init__(self):
    self.mappings = ConfigLoader.load_mappings()
    self.config = self.mappings
    self._build_lookup_tables()
    self._local_model = None  # Lazy load
```

### 2.3 所有 public 方法签名 / 返回类型 / docstring

来源：`services/standardizer.py`，各方法定义行。

- `standardize_vehicle_detailed(self, raw_input: str) -> StandardizationResult`，docstring：`"Standardize vehicle type with full result details."`。证据：`services/standardizer.py:231-232`
- `standardize_vehicle(self, raw_input: str) -> Optional[str]`，docstring：
  - `Standardize vehicle type. Returns standard name or None.`
  - `This is the backward-compatible interface. For detailed results`
  - `including confidence and strategy, use standardize_vehicle_detailed().`
  证据：`services/standardizer.py:290-296`
- `standardize_pollutant_detailed(self, raw_input: str) -> StandardizationResult`，docstring：`"Standardize pollutant with full result details."`。证据：`services/standardizer.py:300-301`
- `standardize_pollutant(self, raw_input: str) -> Optional[str]`，docstring：
  - `Standardize pollutant. Returns standard name or None.`
  - `This is the backward-compatible interface. For detailed results`
  - `including confidence and strategy, use standardize_pollutant_detailed().`
  证据：`services/standardizer.py:359-365`
- `standardize_season(self, raw_input: str) -> StandardizationResult`，docstring：`"Standardize season parameter."`。证据：`services/standardizer.py:369-370`
- `standardize_road_type(self, raw_input: str) -> StandardizationResult`，docstring：`"Standardize road type parameter."`。证据：`services/standardizer.py:418-419`
- `standardize_meteorology(self, value: str) -> StandardizationResult`，docstring：`"Standardize meteorology preset names or pass through custom/path inputs."`。证据：`services/standardizer.py:467-468`
- `standardize_stability_class(self, value: str) -> StandardizationResult`，docstring：`"Standardize atmospheric stability class aliases to canonical abbreviations."`。证据：`services/standardizer.py:527-528`
- `get_vehicle_suggestions(self, raw_input: str = None, top_k: int = 6) -> List[str]`，docstring见 `services/standardizer.py:578-588`
- `get_pollutant_suggestions(self, raw_input: str = None, top_k: int = 6) -> List[str]`，docstring见 `services/standardizer.py:615-625`
- `map_columns(self, columns: List[str], task_type: str) -> Dict[str, str]`，docstring见 `services/standardizer.py:631-645`
- `get_required_columns(self, task_type: str) -> List[str]`，docstring见 `services/standardizer.py:691-700`
- `get_column_patterns_for_display(self, task_type: str, field_name: str) -> List[str]`，docstring见 `services/standardizer.py:710-720`

### 2.4 `_build_lookup_tables()` 完整代码

来源：`services/standardizer.py`，`UnifiedStandardizer._build_lookup_tables`，`L70-L161`。

```python
def _build_lookup_tables(self):
    """Build fast lookup tables from configuration."""
    self.vehicle_lookup: Dict[str, str] = {}
    self.vehicle_catalog: Dict[str, Dict[str, Any]] = {}
    for vtype in self.config.get("vehicle_types", []):
        std_name = vtype["standard_name"]
        self.vehicle_catalog[std_name] = vtype
        self.vehicle_lookup[std_name.lower().strip()] = std_name

        display_name = vtype.get("display_name_zh")
        if display_name:
            self.vehicle_lookup[display_name.lower().strip()] = std_name

        for alias in vtype.get("aliases", []):
            self.vehicle_lookup[str(alias).lower().strip()] = std_name

    logger.info(f"Built vehicle lookup table with {len(self.vehicle_lookup)} entries")

    self.pollutant_lookup: Dict[str, str] = {}
    self.pollutant_catalog: Dict[str, Dict[str, Any]] = {}
    for pollutant in self.config.get("pollutants", []):
        std_name = pollutant["standard_name"]
        self.pollutant_catalog[std_name] = pollutant
        self.pollutant_lookup[std_name.lower().strip()] = std_name

        display_name = pollutant.get("display_name_zh")
        if display_name:
            self.pollutant_lookup[display_name.lower().strip()] = std_name

        for alias in pollutant.get("aliases", []):
            self.pollutant_lookup[str(alias).lower().strip()] = std_name

    logger.info(f"Built pollutant lookup table with {len(self.pollutant_lookup)} entries")

    self.column_patterns = self.config.get("column_patterns", {})

    self.season_lookup: Dict[str, str] = {}
    seasons_config = self.mappings.get("seasons", {})
    if isinstance(seasons_config, dict):
        for standard_name, aliases in seasons_config.items():
            for alias in aliases if isinstance(aliases, list) else []:
                self.season_lookup[str(alias).lower().strip()] = standard_name
            self.season_lookup[standard_name.lower().strip()] = standard_name
    elif isinstance(seasons_config, list):
        for entry in seasons_config:
            if not isinstance(entry, dict):
                continue
            standard_name = entry.get("standard_name")
            if not standard_name:
                continue
            for alias in entry.get("aliases", []):
                self.season_lookup[str(alias).lower().strip()] = standard_name
            self.season_lookup[standard_name.lower().strip()] = standard_name
    self.season_default = self.mappings.get("defaults", {}).get("season", "夏季")

    self.road_type_lookup: Dict[str, str] = {}
    road_types_config = self.mappings.get("road_types", {})
    if isinstance(road_types_config, dict):
        for standard_name, info in road_types_config.items():
            if isinstance(info, dict):
                aliases = info.get("aliases", [])
            elif isinstance(info, list):
                aliases = info
            else:
                aliases = []
            for alias in aliases:
                self.road_type_lookup[str(alias).lower().strip()] = standard_name
            self.road_type_lookup[standard_name.lower().strip()] = standard_name
    self.road_type_default = self.mappings.get("defaults", {}).get("road_type", "快速路")

    self.meteorology_lookup: Dict[str, str] = {}
    meteorology_config = self.mappings.get("meteorology", {})
    presets_config = meteorology_config.get("presets", {}) if isinstance(meteorology_config, dict) else {}
    self.meteorology_presets: List[str] = []
    if isinstance(presets_config, dict):
        for standard_name, info in presets_config.items():
            self.meteorology_presets.append(standard_name)
            self.meteorology_lookup[standard_name.lower().strip()] = standard_name
            aliases = info.get("aliases", []) if isinstance(info, dict) else []
            for alias in aliases:
                self.meteorology_lookup[str(alias).lower().strip()] = standard_name

    self.stability_lookup: Dict[str, str] = {}
    stability_config = self.mappings.get("stability_classes", {})
    self.stability_classes: List[str] = []
    if isinstance(stability_config, dict):
        for standard_name, info in stability_config.items():
            self.stability_classes.append(standard_name)
            self.stability_lookup[standard_name.lower().strip()] = standard_name
            aliases = info.get("aliases", []) if isinstance(info, dict) else []
            for alias in aliases:
                self.stability_lookup[str(alias).lower().strip()] = standard_name
```

### 2.5 `standardize_*_detailed()` / 相关方法完整代码

#### `standardize_vehicle_detailed()`

来源：`services/standardizer.py`，`UnifiedStandardizer.standardize_vehicle_detailed`，`L231-L288`。

```python
def standardize_vehicle_detailed(self, raw_input: str) -> StandardizationResult:
    """Standardize vehicle type with full result details."""
    if raw_input is None or not str(raw_input).strip():
        return StandardizationResult(success=False, original=raw_input or "", strategy="none")

    cleaned = str(raw_input).strip()
    cleaned_lower = cleaned.lower()

    if cleaned_lower in self.vehicle_lookup:
        normalized = self.vehicle_lookup[cleaned_lower]
        strategy = "exact" if cleaned == normalized else "alias"
        confidence = 1.0 if strategy == "exact" else 0.95
        logger.debug(f"Vehicle {strategy} match: '{cleaned}' -> '{normalized}'")
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=normalized,
            strategy=strategy,
            confidence=confidence,
        )

    best_match = None
    best_score = 0
    for alias, standard_name in self.vehicle_lookup.items():
        score = self._fuzzy_ratio(cleaned, alias)
        if score > best_score:
            best_score = score
            best_match = standard_name

    if best_score >= 70 and best_match:
        logger.debug(f"Vehicle fuzzy match: '{cleaned}' -> '{best_match}' (score: {best_score})")
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=best_match,
            strategy="fuzzy",
            confidence=round(best_score / 100, 2),
        )

    local_result = self._try_local_standardization(cleaned, self.vehicle_lookup, "standardize_vehicle")
    if local_result:
        logger.info(
            "Vehicle local model: '%s' -> '%s' (confidence: %s)",
            cleaned,
            local_result.normalized,
            local_result.confidence,
        )
        return local_result

    suggestions = self.get_vehicle_suggestions(cleaned, top_k=5)
    logger.warning(f"Cannot standardize vehicle: '{cleaned}'")
    return StandardizationResult(
        success=False,
        original=cleaned,
        strategy="abstain",
        confidence=0.0,
        suggestions=suggestions,
    )
```

#### `standardize_pollutant_detailed()`

来源：`services/standardizer.py`，`UnifiedStandardizer.standardize_pollutant_detailed`，`L300-L357`。

```python
def standardize_pollutant_detailed(self, raw_input: str) -> StandardizationResult:
    """Standardize pollutant with full result details."""
    if raw_input is None or not str(raw_input).strip():
        return StandardizationResult(success=False, original=raw_input or "", strategy="none")

    cleaned = str(raw_input).strip()
    cleaned_lower = cleaned.lower()

    if cleaned_lower in self.pollutant_lookup:
        normalized = self.pollutant_lookup[cleaned_lower]
        strategy = "exact" if cleaned == normalized else "alias"
        confidence = 1.0 if strategy == "exact" else 0.95
        logger.debug(f"Pollutant {strategy} match: '{cleaned}' -> '{normalized}'")
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=normalized,
            strategy=strategy,
            confidence=confidence,
        )

    best_match = None
    best_score = 0
    for alias, standard_name in self.pollutant_lookup.items():
        score = self._fuzzy_ratio(cleaned, alias)
        if score > best_score:
            best_score = score
            best_match = standard_name

    if best_score >= 80 and best_match:
        logger.debug(f"Pollutant fuzzy match: '{cleaned}' -> '{best_match}' (score: {best_score})")
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=best_match,
            strategy="fuzzy",
            confidence=round(best_score / 100, 2),
        )

    local_result = self._try_local_standardization(cleaned, self.pollutant_lookup, "standardize_pollutant")
    if local_result:
        logger.info(
            "Pollutant local model: '%s' -> '%s' (confidence: %s)",
            cleaned,
            local_result.normalized,
            local_result.confidence,
        )
        return local_result

    suggestions = self.get_pollutant_suggestions(cleaned, top_k=5)
    logger.warning(f"Cannot standardize pollutant: '{cleaned}'")
    return StandardizationResult(
        success=False,
        original=cleaned,
        strategy="abstain",
        confidence=0.0,
        suggestions=suggestions,
    )
```

#### `standardize_season()`

来源：`services/standardizer.py`，`UnifiedStandardizer.standardize_season`，`L369-L416`。

```python
def standardize_season(self, raw_input: str) -> StandardizationResult:
    """Standardize season parameter."""
    if raw_input is None or not str(raw_input).strip():
        return StandardizationResult(
            success=True,
            original=raw_input or "",
            normalized=self.season_default,
            strategy="default",
            confidence=1.0,
        )

    cleaned = str(raw_input).strip()
    cleaned_lower = cleaned.lower()

    if cleaned_lower in self.season_lookup:
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=self.season_lookup[cleaned_lower],
            strategy="alias",
            confidence=0.95,
        )

    best_match = None
    best_score = 0
    for alias, standard_name in self.season_lookup.items():
        score = self._fuzzy_ratio(cleaned_lower, alias)
        if score > best_score:
            best_score = score
            best_match = standard_name

    if best_score >= 60 and best_match:
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=best_match,
            strategy="fuzzy",
            confidence=round(best_score / 100, 2),
        )

    return StandardizationResult(
        success=True,
        original=cleaned,
        normalized=self.season_default,
        strategy="default",
        confidence=0.5,
        suggestions=sorted(set(self.season_lookup.values())),
    )
```

#### `standardize_road_type()`

来源：`services/standardizer.py`，`UnifiedStandardizer.standardize_road_type`，`L418-L465`。

```python
def standardize_road_type(self, raw_input: str) -> StandardizationResult:
    """Standardize road type parameter."""
    if raw_input is None or not str(raw_input).strip():
        return StandardizationResult(
            success=True,
            original=raw_input or "",
            normalized=self.road_type_default,
            strategy="default",
            confidence=1.0,
        )

    cleaned = str(raw_input).strip()
    cleaned_lower = cleaned.lower()

    if cleaned_lower in self.road_type_lookup:
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=self.road_type_lookup[cleaned_lower],
            strategy="alias",
            confidence=0.95,
        )

    best_match = None
    best_score = 0
    for alias, standard_name in self.road_type_lookup.items():
        score = self._fuzzy_ratio(cleaned_lower, alias)
        if score > best_score:
            best_score = score
            best_match = standard_name

    if best_score >= 60 and best_match:
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=best_match,
            strategy="fuzzy",
            confidence=round(best_score / 100, 2),
        )

    return StandardizationResult(
        success=True,
        original=cleaned,
        normalized=self.road_type_default,
        strategy="default",
        confidence=0.5,
        suggestions=sorted(set(self.road_type_lookup.values())),
    )
```

#### `standardize_meteorology()`

来源：`services/standardizer.py`，`UnifiedStandardizer.standardize_meteorology`，`L467-L525`。

```python
def standardize_meteorology(self, value: str) -> StandardizationResult:
    """Standardize meteorology preset names or pass through custom/path inputs."""
    if value is None or not str(value).strip():
        return StandardizationResult(
            success=False,
            original=value or "",
            strategy="abstain",
            confidence=0.0,
            suggestions=list(self.meteorology_presets),
        )

    cleaned = str(value).strip()
    cleaned_lower = cleaned.lower()

    if cleaned_lower == "custom" or cleaned_lower.endswith(".sfc"):
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=cleaned,
            strategy="exact",
            confidence=1.0,
        )

    if cleaned_lower in self.meteorology_lookup:
        normalized = self.meteorology_lookup[cleaned_lower]
        strategy = "exact" if cleaned == normalized else "alias"
        confidence = 1.0 if strategy == "exact" else 0.95
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=normalized,
            strategy=strategy,
            confidence=confidence,
        )

    best_match = None
    best_score = 0
    for alias, standard_name in self.meteorology_lookup.items():
        score = self._fuzzy_ratio(cleaned, alias)
        if score > best_score:
            best_score = score
            best_match = standard_name

    if best_score >= 75 and best_match:
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=best_match,
            strategy="fuzzy",
            confidence=round(best_score / 100, 2),
        )

    return StandardizationResult(
        success=False,
        original=cleaned,
        strategy="abstain",
        confidence=0.0,
        suggestions=list(self.meteorology_presets),
    )
```

#### `standardize_stability_class()`

来源：`services/standardizer.py`，`UnifiedStandardizer.standardize_stability_class`，`L527-L576`。

```python
def standardize_stability_class(self, value: str) -> StandardizationResult:
    """Standardize atmospheric stability class aliases to canonical abbreviations."""
    if value is None or not str(value).strip():
        return StandardizationResult(
            success=False,
            original=value or "",
            strategy="abstain",
            confidence=0.0,
            suggestions=list(self.stability_classes),
        )

    cleaned = str(value).strip()
    cleaned_lower = cleaned.lower()

    if cleaned_lower in self.stability_lookup:
        normalized = self.stability_lookup[cleaned_lower]
        strategy = "exact" if cleaned == normalized else "alias"
        confidence = 1.0 if strategy == "exact" else 0.95
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=normalized,
            strategy=strategy,
            confidence=confidence,
        )

    best_match = None
    best_score = 0
    for alias, standard_name in self.stability_lookup.items():
        score = self._fuzzy_ratio(cleaned, alias)
        if score > best_score:
            best_score = score
            best_match = standard_name

    if best_score >= 75 and best_match:
        return StandardizationResult(
            success=True,
            original=cleaned,
            normalized=best_match,
            strategy="fuzzy",
            confidence=round(best_score / 100, 2),
        )

    return StandardizationResult(
        success=False,
        original=cleaned,
        strategy="abstain",
        confidence=0.0,
        suggestions=list(self.stability_classes),
    )
```

---

## 3. `StandardizationEngine` 完整接口

### 3.1 `StandardizationEngine.__init__()` 完整代码

来源：`services/standardization_engine.py`，`StandardizationEngine.__init__`，`L508-L515`。

```python
def __init__(self, config: Optional[Dict[str, Any]] = None):
    runtime_config = get_config()
    base_config = getattr(runtime_config, "standardization_config", {})
    self._config = _merge_config(base_config, config)
    self._rule_backend = RuleBackend(config=self._config)
    self._llm_backend = self._init_llm_backend()
    self._param_registry = self._load_param_registry()
    self._catalog = self._load_catalog()
```

### 3.2 `standardize()` 完整代码

来源：`services/standardization_engine.py`，`StandardizationEngine.standardize`，`L615-L685`。

```python
def standardize(
    self,
    param_type: str,
    raw_value: Any,
    context: Optional[Dict[str, Any]] = None,
) -> StandardizationResult:
    type_config = PARAM_TYPE_CONFIG.get(param_type)
    original = raw_value if raw_value is not None else ""

    if type_config is None:
        return StandardizationResult(
            success=True,
            original=original,
            normalized=raw_value,
            strategy="passthrough",
            confidence=1.0,
        )

    if self._should_passthrough(param_type, raw_value, type_config):
        normalized = self._passthrough_value(param_type, raw_value)
        return StandardizationResult(
            success=True,
            original=original,
            normalized=normalized,
            strategy="passthrough",
            confidence=1.0,
        )

    if type_config.get("is_list"):
        return self._standardize_list(param_type, raw_value, type_config, context)

    candidates = self.get_candidates(param_type)
    aliases = self._get_aliases(param_type)
    rule_result = self._rule_backend.standardize(param_type, raw_value, candidates, aliases, context)

    if rule_result is None:
        return StandardizationResult(
            success=True,
            original=original,
            normalized=raw_value,
            strategy="passthrough",
            confidence=1.0,
        )

    if self._should_accept_rule_result(param_type, raw_value, rule_result):
        return rule_result

    if self._can_try_llm(param_type, raw_value, type_config):
        llm_result = self._llm_backend.standardize(param_type, raw_value, candidates, aliases, context) if self._llm_backend else None
        if llm_result is not None and llm_result.success:
            logger.info(
                "LLM resolved %s=%r -> %r (confidence=%.2f)",
                param_type,
                raw_value,
                llm_result.normalized,
                llm_result.confidence,
            )
            return llm_result

    if rule_result.success:
        return rule_result

    suggestions = rule_result.suggestions or self._get_suggestions(param_type, raw_value)
    return StandardizationResult(
        success=False,
        original=rule_result.original,
        normalized=None,
        strategy="abstain",
        confidence=0.0,
        suggestions=suggestions,
    )
```

### 3.3 它内部如何调用 `UnifiedStandardizer`

#### 调用链代码 1：`RuleBackend.standardize()`

来源：`services/standardization_engine.py`，`RuleBackend.standardize`，`L193-L217`。

```python
def standardize(
    self,
    param_type: str,
    raw_value: str,
    candidates: List[str],
    aliases: Dict[str, List[str]],
    context: Optional[Dict[str, Any]] = None,
) -> Optional[StandardizationResult]:
    method_map = {
        "vehicle_type": self._standardizer.standardize_vehicle_detailed,
        "pollutant": self._standardizer.standardize_pollutant_detailed,
        "season": self._standardizer.standardize_season,
        "road_type": self._standardizer.standardize_road_type,
        "meteorology": self._standardizer.standardize_meteorology,
        "stability_class": self._standardizer.standardize_stability_class,
    }
    method = method_map.get(param_type)
    if method is None:
        return None

    legacy_result = method(raw_value)
    if not self._needs_custom_threshold(param_type):
        return legacy_result

    return self._standardize_with_custom_threshold(param_type, raw_value)
```

#### 调用链代码 2：执行入口从 executor 进入 engine

来源：`core/executor.py`，`ToolExecutor._standardize_arguments`，`L317-L354`。

```python
def _standardize_arguments(
    self,
    tool_name: str,
    arguments: Dict[str, Any],
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Standardize tool arguments using domain-specific rules.

    Args:
        tool_name: Tool name (for context)
        arguments: Raw arguments from LLM

    Returns:
        Tuple of (standardized_arguments, standardization_records).

    Raises:
        StandardizationError: If standardization fails
    """
    if not self.runtime_config.enable_executor_standardization:
        return dict(arguments or {}), []
    try:
        standardized, records = self._std_engine.standardize_batch(
            params=arguments,
            tool_name=tool_name,
        )
        self._last_standardization_records = list(records)
        return standardized, records
    except BatchStandardizationError as exc:
        self._last_standardization_records = list(exc.records)
        raise StandardizationError(
            str(exc),
            suggestions=exc.suggestions,
            records=exc.records,
            param_name=exc.param_name,
            original_value=exc.original_value,
            negotiation_eligible=exc.negotiation_eligible,
            trigger_reason=exc.trigger_reason,
        ) from exc
```

---

### 3.4 它如何决定哪些参数需要标准化、哪些不需要

#### 参数注册表

来源：`services/standardization_engine.py`，`PARAM_TYPE_REGISTRY`，`L35-L43`。

```python
PARAM_TYPE_REGISTRY: Dict[str, str] = {
    "vehicle_type": "vehicle_type",
    "pollutant": "pollutant",
    "pollutants": "pollutant_list",
    "season": "season",
    "road_type": "road_type",
    "meteorology": "meteorology",
    "stability_class": "stability_class",
}
```

#### 参数类型配置

来源：`services/standardization_engine.py`，`PARAM_TYPE_CONFIG`，`L54-L99`。

```python
PARAM_TYPE_CONFIG: Dict[str, Dict[str, Any]] = {
    "vehicle_type": {
        "has_default": False,
        "fuzzy_enabled": True,
        "llm_enabled": True,
        "description": "MOVES vehicle source type",
    },
    "pollutant": {
        "has_default": False,
        "fuzzy_enabled": True,
        "llm_enabled": True,
        "description": "Emission pollutant species",
    },
    "pollutant_list": {
        "is_list": True,
        "element_type": "pollutant",
        "description": "List of pollutants",
    },
    "season": {
        "has_default": True,
        "default_value": "夏季",
        "fuzzy_enabled": True,
        "llm_enabled": True,
        "description": "Season for emission factor selection",
    },
    "road_type": {
        "has_default": True,
        "default_value": "快速路",
        "fuzzy_enabled": True,
        "llm_enabled": True,
        "description": "Road functional classification",
    },
    "meteorology": {
        "has_default": False,
        "fuzzy_enabled": True,
        "llm_enabled": True,
        "passthrough_patterns": [r"\.sfc$", r"^custom$"],
        "description": "Meteorological condition preset or mode",
    },
    "stability_class": {
        "has_default": False,
        "fuzzy_enabled": True,
        "llm_enabled": True,
        "description": "Atmospheric stability class (Pasquill-Gifford)",
    },
}
```

#### 批量标准化入口如何筛选参数

来源：`services/standardization_engine.py`，`StandardizationEngine.standardize_batch`，`L687-L756`。

```python
def standardize_batch(
    self,
    params: Dict[str, Any],
    tool_name: Optional[str] = None,
) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    standardized: Dict[str, Any] = {}
    records: List[Dict[str, Any]] = []

    for key, value in dict(params or {}).items():
        param_type = self._param_registry.get(key)
        if param_type is None or value is None:
            standardized[key] = value
            continue

        type_config = PARAM_TYPE_CONFIG.get(param_type, {})
        if type_config.get("is_list"):
            if not isinstance(value, list):
                standardized[key] = value
                continue
            standardized[key] = self._standardize_list_param(key, value, tool_name, records)
            continue

        if not isinstance(value, str):
            standardized[key] = value
            continue

        context = {"tool": tool_name, "param_name": key}
        result = self.standardize(param_type, value, context)

        if not self._should_record_passthrough(key, param_type, value, result):
            standardized[key] = result.normalized if result.success else value
            continue

        record = {"param": key, **result.to_dict()}
        records.append(record)

        if self._should_trigger_parameter_negotiation(param_type, value, result):
            suggestions = self._build_negotiation_suggestions(param_type, value, result)
            record["suggestions"] = suggestions
            raise BatchStandardizationError(
                message=self._build_negotiation_message(key, value, suggestions),
                param_name=key,
                original_value=value,
                suggestions=suggestions,
                records=records,
                negotiation_eligible=True,
                trigger_reason=self._build_negotiation_trigger_reason(result),
            )

        if result.success:
            standardized[key] = result.normalized
            continue

        suggestions = result.suggestions
        negotiation_eligible = self._should_trigger_parameter_negotiation(param_type, value, result)
        raise BatchStandardizationError(
            message=self._build_failure_message(key, value, suggestions),
            param_name=key,
            original_value=value,
            suggestions=suggestions,
            records=records,
            negotiation_eligible=negotiation_eligible,
            trigger_reason=(
                self._build_negotiation_trigger_reason(result)
                if negotiation_eligible
                else "standardization_abstain_no_safe_candidates"
            ),
        )

    return standardized, records
```

---

## 4. `shared/standardizer/` 完整内容

### 4.1 当前引用情况

- `shared/standardizer/constants.py` 当前被以下运行时代码直接引用：
  - `skills/macro_emission/skill.py:7`，`from shared.standardizer.constants import SEASON_MAPPING`
  - `skills/micro_emission/skill.py:12`，`from shared.standardizer.constants import SEASON_MAPPING`
  - `calculators/vsp.py:5`，`from shared.standardizer.constants import VSP_PARAMETERS, VSP_BINS`
  - `skills/micro_emission/vsp.py:5`，`from shared.standardizer.constants import VSP_PARAMETERS, VSP_BINS`
- `shared/standardizer/vehicle.py` 当前被以下运行时代码直接引用：
  - `skills/macro_emission/skill.py:5`，`from shared.standardizer.vehicle import get_vehicle_standardizer`
  - `skills/micro_emission/skill.py:10`，`from shared.standardizer.vehicle import get_vehicle_standardizer`
- `shared/standardizer/pollutant.py` 当前被以下运行时代码直接引用：
  - `skills/macro_emission/skill.py:6`，`from shared.standardizer.pollutant import get_pollutant_standardizer`
  - `skills/micro_emission/skill.py:11`，`from shared.standardizer.pollutant import get_pollutant_standardizer`
- `shared/standardizer/local_client.py` 当前被以下代码直接或惰性引用：
  - `services/standardizer.py:738`，`from shared.standardizer.local_client import get_local_standardizer_client`
  - `shared/standardizer/vehicle.py:43`，`from .local_client import get_local_standardizer_client`
  - `shared/standardizer/pollutant.py:43`，`from .local_client import get_local_standardizer_client`
- `shared/standardizer/cache.py` 除自身定义 `shared/standardizer/cache.py:4-28` 外，当前静态代码里未看到其他引用位置。
- 已确认同时引用 `services/standardizer.py` 和 `shared/standardizer/*` 的代码点只有 `services/standardizer.py:725-747`，因为该文件在 `_get_local_model()` 中惰性导入 `shared.standardizer.local_client.get_local_standardizer_client`。

### 4.2 与 `services/standardizer.py` / `config/unified_mappings.yaml` 的映射一致性

- 车辆标准名集合一致：`shared/standardizer/constants.py:1-24` 与 `config/unified_mappings.yaml:9-210` 都包含 13 个标准车型；静态比较未发现只存在于单侧的标准名。
- 污染物标准名集合一致：`shared/standardizer/constants.py:26-42` 与 `config/unified_mappings.yaml:213-260` 都包含 6 个标准污染物；静态比较未发现只存在于单侧的标准名。
- `shared/standardizer/constants.py` 中没有 `road_types`、`meteorology`、`stability_classes` 对应常量；这些维度只出现在 `config/unified_mappings.yaml:289-425`，并由 `services/standardizer.py:125-161` 装载。
- `shared/standardizer/constants.py` 中的季节映射只覆盖 4 个季节和 12 个别名：`SEASON_MAPPING` 定义见 `shared/standardizer/constants.py:44-49`；`config/unified_mappings.yaml:263-287` 还额外包含 `"autumn"`，因此 `秋季` 的 YAML 别名数比 shared 常量多 1。
- `shared/standardizer/constants.py` 中的车辆别名整体少于 YAML：
  - `Passenger Car`：shared 只含 `["小汽车", "轿车", "私家车", "SUV", "网约车", "出租车", "滴滴"]`，`shared/standardizer/constants.py:2`；YAML 额外包含 `"passenger car"`, `"car"`, `"轻型汽油车"`, `"汽油车"`, `"乘用车"`, `"轻型车"`，`config/unified_mappings.yaml:28-41`
  - `Transit Bus`：shared 只含 `["城市公交", "公交"]`，`shared/standardizer/constants.py:5`；YAML 额外包含 `"巴士"`, `"市内公交"`, `"transit bus"`, `"bus"`，`config/unified_mappings.yaml:98-104`
  - `Combination Long-haul Truck`：shared 只含 `["重卡", "大货车", "挂车"]`，`shared/standardizer/constants.py:13`；YAML 额外包含 `"组合长途货车"`, `"半挂长途"`, `"货车"`, `"combination long-haul"`, `"heavy truck"`，`config/unified_mappings.yaml:196-204`
- `shared/standardizer/constants.py` 中的污染物别名整体少于 YAML：
  - `CO2`：shared 只含 `["碳排放", "温室气体"]`，`shared/standardizer/constants.py:27`；YAML 额外包含 `"co2"`, `"carbon dioxide"`，`config/unified_mappings.yaml:217-221`
  - `NOx`：shared 只含 `["氮氧"]`，`shared/standardizer/constants.py:29`；YAML 额外包含 `"nox"`, `"nitrogen oxides"`，`config/unified_mappings.yaml:233-236`
  - `PM2.5`：shared 只含 `["颗粒物"]`，`shared/standardizer/constants.py:30`；YAML 额外包含 `"pm2.5"`, `"pm25"`, `"fine particulate matter"`，`config/unified_mappings.yaml:241-245`
- VSP 参数和 VSP 分箱当前一致：`shared/standardizer/constants.py:52-84` 与 `config/unified_mappings.yaml:18-23,42-47,57-62,73-78,88-93,105-110,118-123,131-136,146-151,159-164,173-178,186-191,205-210,556-598` 的数值比较结果未发现差异。

### 4.3 目录中文件完整代码

#### `shared/standardizer/__init__.py`

来源：`shared/standardizer/__init__.py`，`L1-L1`。

```python
# Standardizer Module
```

#### `shared/standardizer/constants.py`

来源：`shared/standardizer/constants.py`，`L1-L84`。

```python
VEHICLE_TYPE_MAPPING = {
    "Passenger Car": ("乘用车", ["小汽车", "轿车", "私家车", "SUV", "网约车", "出租车", "滴滴"]),
    "Passenger Truck": ("皮卡", ["轻型客货车", "pickup"]),
    "Light Commercial Truck": ("轻型货车", ["小货车", "面包车", "轻卡"]),
    "Transit Bus": ("公交车", ["城市公交", "公交"]),
    "Intercity Bus": ("城际客车", ["长途大巴", "旅游巴士"]),
    "School Bus": ("校车", ["学生巴士"]),
    "Refuse Truck": ("垃圾车", ["环卫车"]),
    "Single Unit Short-haul Truck": ("中型货车", ["城配货车", "中卡"]),
    "Single Unit Long-haul Truck": ("长途货车", []),
    "Motor Home": ("房车", ["旅居车"]),
    "Combination Short-haul Truck": ("半挂短途", []),
    "Combination Long-haul Truck": ("重型货车", ["重卡", "大货车", "挂车"]),
    "Motorcycle": ("摩托车", ["电动摩托", "机车"]),
}

VEHICLE_ALIAS_TO_STANDARD = {}
for std, (cn, aliases) in VEHICLE_TYPE_MAPPING.items():
    VEHICLE_ALIAS_TO_STANDARD[std.lower()] = std
    VEHICLE_ALIAS_TO_STANDARD[cn] = std
    for a in aliases:
        VEHICLE_ALIAS_TO_STANDARD[a] = std

STANDARD_VEHICLE_TYPES = list(VEHICLE_TYPE_MAPPING.keys())

POLLUTANT_MAPPING = {
    "CO2": ("二氧化碳", ["碳排放", "温室气体"]),
    "CO": ("一氧化碳", []),
    "NOx": ("氮氧化物", ["氮氧"]),
    "PM2.5": ("细颗粒物", ["颗粒物"]),
    "PM10": ("可吸入颗粒物", []),
    "THC": ("总碳氢化合物", ["总烃"]),
}

POLLUTANT_ALIAS_TO_STANDARD = {}
for std, (cn, aliases) in POLLUTANT_MAPPING.items():
    POLLUTANT_ALIAS_TO_STANDARD[std.lower()] = std
    POLLUTANT_ALIAS_TO_STANDARD[cn] = std
    for a in aliases:
        POLLUTANT_ALIAS_TO_STANDARD[a.lower()] = std

STANDARD_POLLUTANTS = list(POLLUTANT_MAPPING.keys())

SEASON_MAPPING = {
    "春": "春季", "春天": "春季", "spring": "春季",
    "夏": "夏季", "夏天": "夏季", "summer": "夏季",
    "秋": "秋季", "秋天": "秋季", "fall": "秋季",
    "冬": "冬季", "冬天": "冬季", "winter": "冬季",
}

# VSP计算参数（MOVES Atlanta 2014+）
VSP_PARAMETERS = {
    11: {"A": 0.0251, "B": 0.0, "C": 0.000315, "M": 0.285, "m": 0.285},      # Motorcycle
    21: {"A": 0.156461, "B": 0.002001, "C": 0.000492, "M": 1.4788, "m": 1.4788}, # Passenger Car
    31: {"A": 0.22112, "B": 0.002837, "C": 0.000698, "M": 1.86686, "m": 1.8668}, # Passenger Truck
    32: {"A": 0.235008, "B": 0.003038, "C": 0.000747, "M": 2.05979, "m": 2.0597}, # Light Commercial Truck
    41: {"A": 1.23039, "B": 0.0, "C": 0.003714, "M": 17.1, "m": 19.593},        # Intercity Bus
    42: {"A": 1.03968, "B": 0.0, "C": 0.003587, "M": 17.1, "m": 16.556},        # Transit Bus
    43: {"A": 0.709382, "B": 0.0, "C": 0.002175, "M": 17.1, "m": 9.0698},       # School Bus
    51: {"A": 1.50429, "B": 0.0, "C": 0.003572, "M": 17.1, "m": 23.113},        # Refuse Truck
    52: {"A": 0.596526, "B": 0.0, "C": 0.001603, "M": 17.1, "m": 8.5389},       # Single-Unit Short Haul
    53: {"A": 0.529399, "B": 0.0, "C": 0.001473, "M": 17.1, "m": 6.9844},       # Single-Unit Long Haul
    54: {"A": 0.655376, "B": 0.0, "C": 0.002105, "M": 17.1, "m": 7.5257},       # Motor Home
    61: {"A": 1.43052, "B": 0.0, "C": 0.003792, "M": 17.1, "m": 22.828},        # Combination Short Haul
    62: {"A": 1.47389, "B": 0.0, "C": 0.003681, "M": 17.1, "m": 24.419},        # Combination Long Haul
}

# VSP分箱
VSP_BINS = {
    1: (-float('inf'), -2),
    2: (-2, 0),
    3: (0, 1),
    4: (1, 4),
    5: (4, 7),
    6: (7, 10),
    7: (10, 13),
    8: (13, 16),
    9: (16, 19),
    10: (19, 23),
    11: (23, 28),
    12: (28, 33),
    13: (33, 39),
    14: (39, float('inf'))
}
```

#### `shared/standardizer/local_client.py`

来源：`shared/standardizer/local_client.py`，`L1-L253`。

```python
"""
本地标准化模型客户端

支持两种模式：
1. direct: 直接加载模型和LoRA适配器
2. vllm: 通过VLLM服务调用
"""
import json
import logging
import torch
from typing import Optional, Dict, List
from pathlib import Path

logger = logging.getLogger(__name__)

class LocalStandardizerClient:
    """本地标准化模型客户端"""

    def __init__(self, config: Dict):
        self.config = config
        self.mode = config.get("mode", "direct")
        self.enabled = config.get("enabled", False)

        if not self.enabled:
            logger.info("本地标准化模型未启用")
            return

        logger.info(f"初始化本地标准化模型（模式: {self.mode}）...")

        if self.mode == "direct":
            self._init_direct_mode()
        elif self.mode == "vllm":
            self._init_vllm_mode()
        else:
            raise ValueError(f"Unknown mode: {self.mode}")

    def _init_direct_mode(self):
        """初始化直接加载模式"""
        try:
            from transformers import AutoTokenizer, AutoModelForCausalLM
            from peft import PeftModel

            device = self.config.get("device", "cuda")
            base_model_path = self.config.get("base_model")

            logger.info(f"加载基础模型: {base_model_path}")

            # 加载tokenizer
            self.tokenizer = AutoTokenizer.from_pretrained(base_model_path)

            # 加载基础模型
            self.base_model = AutoModelForCausalLM.from_pretrained(
                base_model_path,
                torch_dtype=torch.float16 if device == "cuda" else torch.float32,
                device_map=device
            )

            # LoRA适配器路径
            self.unified_lora_path = self.config.get("unified_lora")
            self.column_lora_path = self.config.get("column_lora")

            # 验证路径存在
            if not Path(self.unified_lora_path).exists():
                logger.warning(f"Unified LoRA路径不存在: {self.unified_lora_path}")
            if not Path(self.column_lora_path).exists():
                logger.warning(f"Column LoRA路径不存在: {self.column_lora_path}")

            # 当前加载的适配器
            self.current_adapter = None
            self.model = None

            logger.info("本地标准化模型初始化完成（直接加载模式）")

        except ImportError as e:
            logger.error(f"缺少依赖库: {e}")
            logger.error("请安装: pip install transformers peft torch")
            raise
        except Exception as e:
            logger.error(f"初始化失败: {e}")
            raise

    def _init_vllm_mode(self):
        """初始化VLLM模式"""
        self.vllm_url = self.config.get("vllm_url", "http://localhost:8001")
        logger.info(f"VLLM服务地址: {self.vllm_url}")

        # 测试连接（不使用代理）
        try:
            import requests
            response = requests.get(
                f"{self.vllm_url}/health",
                timeout=2,
                proxies={"http": None, "https": None}  # 禁用代理
            )
            if response.status_code == 200:
                logger.info("VLLM服务连接成功")
            else:
                logger.warning(f"VLLM服务响应异常: {response.status_code}")
        except Exception as e:
            logger.warning(f"无法连接到VLLM服务: {e}")
            logger.warning("请确保VLLM服务已启动")

    def _switch_adapter(self, adapter_type: str):
        """切换LoRA适配器"""
        if self.mode == "vllm":
            # VLLM模式不需要切换适配器
            return

        if self.current_adapter == adapter_type:
            return

        logger.info(f"切换LoRA适配器: {adapter_type}")

        try:
            from peft import PeftModel

            if adapter_type == "unified":
                lora_path = self.unified_lora_path
            elif adapter_type == "column":
                lora_path = self.column_lora_path
            else:
                raise ValueError(f"Unknown adapter type: {adapter_type}")

            # 加载LoRA适配器
            self.model = PeftModel.from_pretrained(self.base_model, lora_path)
            self.current_adapter = adapter_type
            logger.info(f"LoRA适配器加载完成: {lora_path}")

        except Exception as e:
            logger.error(f"切换适配器失败: {e}")
            raise

    def _generate_direct(self, prompt: str) -> str:
        """直接生成（非VLLM）"""
        if self.model is None:
            raise RuntimeError("模型未加载，请先调用_switch_adapter")

        messages = [
            {"role": "system", "content": "你是标准化助手。根据任务类型，将用户输入标准化为标准值。只返回标准值，不要其他内容。"},
            {"role": "user", "content": prompt}
        ]

        text = self.tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=True
        )

        inputs = self.tokenizer([text], return_tensors="pt").to(self.model.device)

        with torch.no_grad():
            outputs = self.model.generate(
                **inputs,
                max_new_tokens=self.config.get("max_length", 256),
                temperature=0.1,
                do_sample=False,
                pad_token_id=self.tokenizer.eos_token_id
            )

        response = self.tokenizer.decode(
            outputs[0][len(inputs.input_ids[0]):],
            skip_special_tokens=True
        )
        return response.strip()

    def _generate_vllm(self, prompt: str, adapter: str) -> str:
        """通过VLLM生成"""
        import requests

        try:
            response = requests.post(
                f"{self.vllm_url}/v1/completions",
                json={
                    "model": adapter,  # "unified" or "column"
                    "prompt": prompt,
                    "max_tokens": self.config.get("max_length", 256),
                    "temperature": 0.1
                },
                timeout=30,
                proxies={"http": None, "https": None}  # 禁用代理
            )
            response.raise_for_status()
            return response.json()["choices"][0]["text"].strip()
        except Exception as e:
            logger.error(f"VLLM调用失败: {e}")
            raise

    def standardize_vehicle(self, input_text: str) -> str:
        """标准化车型"""
        if not self.enabled:
            raise RuntimeError("本地标准化模型未启用")

        self._switch_adapter("unified")
        prompt = f"[vehicle] {input_text}"

        if self.mode == "direct":
            return self._generate_direct(prompt)
        else:
            return self._generate_vllm(prompt, "unified")

    def standardize_pollutant(self, input_text: str) -> str:
        """标准化污染物"""
        if not self.enabled:
            raise RuntimeError("本地标准化模型未启用")

        self._switch_adapter("unified")
        prompt = f"[pollutant] {input_text}"

        if self.mode == "direct":
            return self._generate_direct(prompt)
        else:
            return self._generate_vllm(prompt, "unified")

    def map_columns(self, columns: List[str], task_type: str) -> Dict[str, str]:
        """映射列名"""
        if not self.enabled:
            raise RuntimeError("本地标准化模型未启用")

        self._switch_adapter("column")

        # 构建prompt（与训练数据格式一致）
        prompt = json.dumps(columns, ensure_ascii=False)

        if self.mode == "direct":
            result = self._generate_direct(prompt)
        else:
            result = self._generate_vllm(prompt, "column")

        try:
            return json.loads(result)
        except json.JSONDecodeError:
            logger.error(f"JSON解析失败: {result}")
            return {}


# 单例模式
_local_client = None

def get_local_standardizer_client(config: Dict = None) -> Optional[LocalStandardizerClient]:
    """获取本地标准化客户端（单例）"""
    global _local_client

    if config is None:
        from config import get_config
        config = get_config().local_standardizer_config

    if not config.get("enabled", False):
        return None

    if _local_client is None:
        _local_client = LocalStandardizerClient(config)

    return _local_client
```

#### `shared/standardizer/cache.py`

来源：`shared/standardizer/cache.py`，`L1-L29`。

```python
from collections import OrderedDict
from typing import Optional

class LRUCache:
    """Simple LRU Cache implementation"""
    def __init__(self, capacity: int = 1000):
        self.cache = OrderedDict()
        self.capacity = capacity

    def get(self, key: str) -> Optional[str]:
        if key not in self.cache:
            return None
        # Move to end to mark as recently used
        self.cache.move_to_end(key)
        return self.cache[key]

    def put(self, key: str, value: str):
        if key in self.cache:
            self.cache.move_to_end(key)
        self.cache[key] = value
        if len(self.cache) > self.capacity:
            # Remove oldest item
            self.cache.popitem(last=False)

    def clear(self):
        self.cache.clear()

    def size(self) -> int:
        return len(self.cache)
```

#### `shared/standardizer/vehicle.py`

来源：`shared/standardizer/vehicle.py`，`L1-L150`。

```python
import json
import logging
from dataclasses import dataclass
from typing import Optional, Dict
from .constants import VEHICLE_TYPE_MAPPING, VEHICLE_ALIAS_TO_STANDARD, STANDARD_VEHICLE_TYPES
from llm.client import get_llm
from llm.data_collector import get_collector
from config import get_config

logger = logging.getLogger(__name__)

@dataclass
class StandardizationResult:
    input: str
    standard: Optional[str]
    confidence: float
    method: str
    error: Optional[str] = None

VEHICLE_PROMPT = """你是车型标准化助手。将用户输入映射到MOVES标准车型。

## 标准车型（13种）
{vehicle_list}

## 任务
将"{user_input}"映射到最匹配的标准车型。

## 输出
仅返回JSON：{{"standard": "英文名", "confidence": 0.0-1.0}}
无法识别时：{{"standard": null, "confidence": 0}}
"""

class VehicleStandardizer:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            config = get_config()

            # 选择使用本地模型还是API
            if config.use_local_standardizer:
                from .local_client import get_local_standardizer_client
                cls._instance._local_client = get_local_standardizer_client()
                cls._instance._use_local = True
                cls._instance._llm = None  # 本地模型不使用LLM
                logger.info("使用本地标准化模型（车型）")
            else:
                cls._instance._llm = get_llm("standardizer") if config.enable_llm_standardization else None
                cls._instance._use_local = False
                cls._instance._local_client = None
                logger.info("使用API标准化模型（车型）")

            cls._instance._collector = get_collector()
            cls._instance._enable_llm = config.enable_llm_standardization or config.use_local_standardizer
            cls._instance._vehicle_list = "\n".join(
                f"- {std} ({cn}): {', '.join(aliases[:3])}"
                for std, (cn, aliases) in VEHICLE_TYPE_MAPPING.items()
            )
        return cls._instance

    def standardize(self, user_input: str, context: Dict = None) -> StandardizationResult:
        user_input = user_input.strip()
        if not user_input:
            return StandardizationResult(user_input, None, 0, "failed", "输入为空")

        # 规则匹配
        rule_result = self._rule_match(user_input)
        if rule_result and rule_result.confidence >= 0.9:
            self._log(user_input, rule_result, context)
            return rule_result

        # LLM标准化
        if self._enable_llm and self._llm:
            llm_result = self._llm_standardize(user_input)
            if llm_result and llm_result.standard:
                self._log(user_input, llm_result, context)
                return llm_result

        # 回退
        if rule_result:
            rule_result.method = "rule_fallback"
            self._log(user_input, rule_result, context)
            return rule_result

        result = StandardizationResult(user_input, None, 0, "failed", "无法识别")
        self._log(user_input, result, context)
        return result

    def _rule_match(self, user_input: str) -> Optional[StandardizationResult]:
        input_lower = user_input.lower().strip()

        if input_lower in VEHICLE_ALIAS_TO_STANDARD:
            return StandardizationResult(user_input, VEHICLE_ALIAS_TO_STANDARD[input_lower], 1.0, "rule")

        for alias, std in VEHICLE_ALIAS_TO_STANDARD.items():
            if alias in input_lower or input_lower in alias:
                return StandardizationResult(user_input, std, 0.8, "rule")

        return None

    def _llm_standardize(self, user_input: str) -> Optional[StandardizationResult]:
        # 使用本地模型
        if hasattr(self, '_use_local') and self._use_local:
            try:
                standard = self._local_client.standardize_vehicle(user_input)
                # 验证返回的标准值
                if standard in STANDARD_VEHICLE_TYPES:
                    return StandardizationResult(user_input, standard, 0.95, "local_llm")
                else:
                    logger.warning(f"本地模型返回了无效的车型: {standard}")
                    return None
            except Exception as e:
                logger.error(f"本地模型标准化失败: {e}")
                return None

        # 使用API模型
        prompt = VEHICLE_PROMPT.format(vehicle_list=self._vehicle_list, user_input=user_input)
        try:
            response = self._llm.chat(prompt, temperature=0.1)
            response = response.strip()
            if response.startswith("```"):
                response = "\n".join(response.split("\n")[1:-1])
            result = json.loads(response)
            std = result.get("standard")
            if std and std not in STANDARD_VEHICLE_TYPES:
                return None
            return StandardizationResult(user_input, std, result.get("confidence", 0), "llm")
        except Exception as e:
            logger.error(f"LLM标准化失败: {e}")
            return None

    def _log(self, user_input: str, result: StandardizationResult, context: Dict = None):
        model_name = None
        if hasattr(self, '_use_local') and self._use_local:
            model_name = "local_qwen3-4b"  # 更新为实际使用的模型
        elif self._llm:
            model_name = self._llm.assignment.model

        self._collector.log(
            task="vehicle_type",
            input_value=user_input,
            output={"standard": result.standard, "confidence": result.confidence},
            method=result.method,
            model=model_name,
            context=context
        )

def get_vehicle_standardizer():
    return VehicleStandardizer()
```

#### `shared/standardizer/pollutant.py`

来源：`shared/standardizer/pollutant.py`，`L1-L150`。

```python
import json
import logging
from dataclasses import dataclass
from typing import Optional, Dict
from .constants import POLLUTANT_MAPPING, POLLUTANT_ALIAS_TO_STANDARD, STANDARD_POLLUTANTS
from llm.client import get_llm
from llm.data_collector import get_collector
from config import get_config

logger = logging.getLogger(__name__)

@dataclass
class StandardizationResult:
    input: str
    standard: Optional[str]
    confidence: float
    method: str
    error: Optional[str] = None

POLLUTANT_PROMPT = """你是污染物标准化助手。将用户输入映射到标准污染物。

## 标准污染物
{pollutant_list}

## 任务
将"{user_input}"映射到最匹配的标准污染物。

## 输出
仅返回JSON：{{"standard": "英文名", "confidence": 0.0-1.0}}
无法识别时：{{"standard": null, "confidence": 0}}
"""

class PollutantStandardizer:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            config = get_config()

            # 选择使用本地模型还是API
            if config.use_local_standardizer:
                from .local_client import get_local_standardizer_client
                cls._instance._local_client = get_local_standardizer_client()
                cls._instance._use_local = True
                cls._instance._llm = None  # 本地模型不使用LLM
                logger.info("使用本地标准化模型（污染物）")
            else:
                cls._instance._llm = get_llm("standardizer") if config.enable_llm_standardization else None
                cls._instance._use_local = False
                cls._instance._local_client = None
                logger.info("使用API标准化模型（污染物）")

            cls._instance._collector = get_collector()
            cls._instance._enable_llm = config.enable_llm_standardization or config.use_local_standardizer
            cls._instance._pollutant_list = "\n".join(
                f"- {std} ({cn}): {', '.join(aliases)}" if aliases else f"- {std} ({cn})"
                for std, (cn, aliases) in POLLUTANT_MAPPING.items()
            )
        return cls._instance

    def standardize(self, user_input: str, context: Dict = None) -> StandardizationResult:
        user_input = user_input.strip()
        if not user_input:
            return StandardizationResult(user_input, None, 0, "failed", "输入为空")

        # 规则匹配
        rule_result = self._rule_match(user_input)
        if rule_result and rule_result.confidence >= 0.9:
            self._log(user_input, rule_result, context)
            return rule_result

        # LLM标准化
        if self._enable_llm and self._llm:
            llm_result = self._llm_standardize(user_input)
            if llm_result and llm_result.standard:
                self._log(user_input, llm_result, context)
                return llm_result

        # 回退
        if rule_result:
            rule_result.method = "rule_fallback"
            self._log(user_input, rule_result, context)
            return rule_result

        result = StandardizationResult(user_input, None, 0, "failed", "无法识别")
        self._log(user_input, result, context)
        return result

    def _rule_match(self, user_input: str) -> Optional[StandardizationResult]:
        input_lower = user_input.lower().strip()

        if input_lower in POLLUTANT_ALIAS_TO_STANDARD:
            return StandardizationResult(user_input, POLLUTANT_ALIAS_TO_STANDARD[input_lower], 1.0, "rule")

        for alias, std in POLLUTANT_ALIAS_TO_STANDARD.items():
            if alias in input_lower or input_lower in alias:
                return StandardizationResult(user_input, std, 0.8, "rule")

        return None

    def _llm_standardize(self, user_input: str) -> Optional[StandardizationResult]:
        # 使用本地模型
        if hasattr(self, '_use_local') and self._use_local:
            try:
                standard = self._local_client.standardize_pollutant(user_input)
                # 验证返回的标准值
                if standard in STANDARD_POLLUTANTS:
                    return StandardizationResult(user_input, standard, 0.95, "local_llm")
                else:
                    logger.warning(f"本地模型返回了无效的污染物: {standard}")
                    return None
            except Exception as e:
                logger.error(f"本地模型标准化失败: {e}")
                return None

        # 使用API模型
        prompt = POLLUTANT_PROMPT.format(pollutant_list=self._pollutant_list, user_input=user_input)
        try:
            response = self._llm.chat(prompt, temperature=0.1)
            response = response.strip()
            if response.startswith("```"):
                response = "\n".join(response.split("\n")[1:-1])
            result = json.loads(response)
            std = result.get("standard")
            if std and std not in STANDARD_POLLUTANTS:
                return None
            return StandardizationResult(user_input, std, result.get("confidence", 0), "llm")
        except Exception as e:
            logger.error(f"LLM标准化失败: {e}")
            return None

    def _log(self, user_input: str, result: StandardizationResult, context: Dict = None):
        model_name = None
        if hasattr(self, '_use_local') and self._use_local:
            model_name = "local_qwen3-4b"  # 更新为实际使用的模型
        elif self._llm:
            model_name = self._llm.assignment.model

        self._collector.log(
            task="pollutant",
            input_value=user_input,
            output={"standard": result.standard, "confidence": result.confidence},
            method=result.method,
            model=model_name,
            context=context
        )

def get_pollutant_standardizer():
    return PollutantStandardizer()
```

---

## 5. `unified_mappings.yaml` 完整结构

### 5.1 顶层结构

- 顶层 key 共 10 个：`version`、`vehicle_types`、`pollutants`、`seasons`、`road_types`、`meteorology`、`stability_classes`、`column_patterns`、`defaults`、`vsp_bins`。证据：`config/unified_mappings.yaml:6,9,213,263,289,326,375,428,539,556`

### 5.2 每个维度的 schema 与条目数 / 别名数

- `vehicle_types`：
  - schema 示例：`{id, standard_name, display_name_zh, aliases, vsp_params}`，见 `config/unified_mappings.yaml:10-23`
  - 条目总数：13
  - `aliases` 列表总数：59
  - `display_name_zh` 条目数：13
  - 证据：`config/unified_mappings.yaml:9-210`
- `pollutants`：
  - schema 示例：`{id, standard_name, display_name_zh, aliases}`，见 `config/unified_mappings.yaml:214-221`
  - 条目总数：6
  - `aliases` 列表总数：18
  - `display_name_zh` 条目数：6
  - 证据：`config/unified_mappings.yaml:213-260`
- `seasons`：
  - schema 示例：`{standard_name, aliases}`，见 `config/unified_mappings.yaml:264-268`
  - 条目总数：4
  - `aliases` 列表总数：13
  - 证据：`config/unified_mappings.yaml:263-287`
- `road_types`：
  - schema 示例：`标准名 -> {aliases: [...]}`，见 `config/unified_mappings.yaml:289-295`
  - 条目总数：5
  - `aliases` 列表总数：24
  - 证据：`config/unified_mappings.yaml:289-323`
- `meteorology.presets`：
  - schema 示例：`标准名 -> {aliases: [...]}`，见 `config/unified_mappings.yaml:327-336`
  - 条目总数：6
  - `aliases` 列表总数：34
  - 证据：`config/unified_mappings.yaml:326-374`
- `stability_classes`：
  - schema 示例：`标准码 -> {aliases: [...]}`，见 `config/unified_mappings.yaml:375-384`
  - 条目总数：6
  - `aliases` 列表总数：38
  - 证据：`config/unified_mappings.yaml:375-425`
- `column_patterns`：
  - `micro_emission` 字段数：4，pattern 总数：19。证据：`config/unified_mappings.yaml:429-471`
  - `macro_emission` 字段数：4，pattern 总数：40。证据：`config/unified_mappings.yaml:473-536`

### 5.3 每个维度的完整条目示例

#### `vehicle_types` 示例

来源：`config/unified_mappings.yaml`，`L10-L23`。

```yaml
- id: 11
  standard_name: "Motorcycle"
  display_name_zh: "摩托车"
  aliases:
    - "摩托车"
    - "电动摩托"
    - "机车"
    - "motorcycle"
  vsp_params:
    A: 0.0251
    B: 0.0
    C: 0.000315
    M: 0.285
    m: 0.285
```

#### `pollutants` 示例

来源：`config/unified_mappings.yaml`，`L214-L221`。

```yaml
- id: 90
  standard_name: "CO2"
  display_name_zh: "二氧化碳"
  aliases:
    - "碳排放"
    - "温室气体"
    - "co2"
    - "carbon dioxide"
```

#### `seasons` 示例

来源：`config/unified_mappings.yaml`，`L264-L268`。

```yaml
- standard_name: "春季"
  aliases:
    - "春"
    - "春天"
    - "spring"
```

#### `road_types` 示例

来源：`config/unified_mappings.yaml`，`L289-L295`。

```yaml
快速路:
  aliases:
    - 城市快速路
    - 快速路
    - urban expressway
    - expressway
```

#### `meteorology.presets` 示例

来源：`config/unified_mappings.yaml`，`L327-L336`。

```yaml
urban_summer_day:
  aliases:
    - 城市夏季白天
    - 夏季白天
    - 夏天白天
    - 城市夏天
    - summer day
    - urban summer
    - urban summer daytime
```

#### `stability_classes` 示例

来源：`config/unified_mappings.yaml`，`L375-L384`。

```yaml
VS:
  aliases:
    - very stable
    - 非常稳定
    - 强稳定
    - "F"
    - "f"
    - pasquill f
    - class f
```

### 5.4 `column_patterns` 完整内容

来源：`config/unified_mappings.yaml`，`L428-L536`。

```yaml
column_patterns:
  micro_emission:
    speed:
      standard: "speed_kph"
      required: true
      patterns:
        - "speed_kph"
        - "speed_kmh"
        - "speed"
        - "车速"
        - "速度"
        - "velocity"
      description: "Vehicle speed in km/h"

    time:
      standard: "time"
      required: false  # Can be auto-generated
      patterns:
        - "t"
        - "time"
        - "time_sec"
        - "时间"
      description: "Time in seconds"

    acceleration:
      standard: "acceleration_mps2"
      required: false  # Can be calculated from speed
      patterns:
        - "acceleration"
        - "acc"
        - "acceleration_mps2"
        - "acceleration_m_s2"
        - "加速度"
      description: "Acceleration in m/s²"

    grade:
      standard: "grade_pct"
      required: false  # Defaults to 0
      patterns:
        - "grade_pct"
        - "grade"
        - "坡度"
        - "slope"
      description: "Road grade in percentage"

  macro_emission:
    length:
      standard: "link_length_km"
      required: true
      patterns:
        - "link_length_km"
        - "length_km"
        - "length"
        - "路段长度"
        - "长度"
        - "distance_km"
        - "road_length"
      description: "Link length in kilometers"

    flow:
      standard: "traffic_flow_vph"
      required: true
      patterns:
        - "traffic_flow_vph"
        - "flow_vph"
        - "flow"
        - "traffic"
        - "daily_traffic"
        - "traffic_flow"
        - "traffic_count"
        - "link_volume_veh_per_hour"
        - "volume_veh_per_hour"
        - "volume"
        - "交通流量"
        - "流量"
        - "traffic_volume"
        - "vehicle_flow"
        - "aadt"
        - "vph"
      description: "Traffic flow in vehicles per hour"

    speed:
      standard: "avg_speed_kph"
      required: true
      patterns:
        - "avg_speed_kph"
        - "avg_speed"
        - "speed_kph"
        - "speed"
        - "link_avg_speed_kmh"
        - "avg_speed_kmh"
        - "speed_kmh"
        - "mean_speed"
        - "平均速度"
        - "速度"
        - "average_speed"
      description: "Average speed in km/h"

    link_id:
      standard: "link_id"
      required: false  # Auto-generated if missing
      patterns:
        - "link_id"
        - "segment_id"
        - "road_id"
        - "id"
        - "路段ID"
        - "路段编号"
      description: "Link identifier"
```

### 5.5 是否包含任何交叉约束信息

- 在 `config/unified_mappings.yaml:1-598` 中，用关键字 `constraint|constraints|cross|compatible|allowed_` 做静态检索未命中任何条目；当前 YAML 中没有显式命名为交叉约束、组合约束或兼容性约束的字段。

---

## 6. 标准化在系统中的所有调用点

### 6.1 `UnifiedStandardizer` 方法调用点

#### 运行时代码

- `tools/file_analyzer.py`，`FileAnalyzerTool._analyze_structure()`，`L113-L118`
  - `self.standardizer.map_columns(columns, "micro_emission")`
  - `self.standardizer.map_columns(columns, "macro_emission")`
  - `self.standardizer.get_required_columns("micro_emission")`
  - `self.standardizer.get_required_columns("macro_emission")`
- `tools/file_analyzer.py`，`FileAnalyzerTool._build_missing_field_diagnostics()`，`L273`
  - `self.standardizer.get_required_columns(task_type)`
- `tools/file_analyzer.py`，`FileAnalyzerTool._identify_task_type()`，`L818-L821`
  - `std.map_columns(...)`
  - `std.get_required_columns(...)`
- `tools/file_analyzer.py`，`FileAnalyzerTool._analyze_shapefile_structure()`，`L1065-L1068`
  - `self.standardizer.map_columns(...)`
  - `self.standardizer.get_required_columns(...)`
- `tools/file_analyzer.py`，`FileAnalyzerTool._analyze_geojson_structure()`，`L1303-L1306`
  - `self.standardizer.map_columns(...)`
  - `self.standardizer.get_required_columns(...)`
- `core/file_analysis_fallback.py`，`_has_required_columns_for_task()`，`L565`
  - `standardizer.get_required_columns(task_type)`
- `tools/macro_emission.py`，`MacroEmissionTool._standardize_fleet_mix()`，`L158`
  - `standardizer.standardize_vehicle(str(raw_name))`
- `evaluation/eval_normalization.py`，`_check_param_legality()`，`L37`
  - `standardizer.standardize_vehicle(str(vehicle))`
- `evaluation/eval_normalization.py`，`_check_param_legality()`，`L41`
  - `standardizer.standardize_pollutant(str(item))`

#### 测试 / 评估代码

- `tests/test_standardizer.py`，`TestVehicleStandardization.*`，`L19-L47`
  - `standardize_vehicle()` 与 `get_vehicle_suggestions()` 调用集中在 `tests/test_standardizer.py:19,23,27,28,32,33,37,42,43,47`
- `tests/test_standardizer.py`，`TestPollutantStandardization.*`，`L57-L77`
  - `standardize_pollutant()` 与 `get_pollutant_suggestions()` 调用集中在 `tests/test_standardizer.py:57,58,59,63,64,68,69,73,77`
- `tests/test_standardizer.py`，`TestColumnMapping.*`，`L87-L93`
  - `map_columns()`，`tests/test_standardizer.py:87,93`
- `tests/test_standardizer_enhanced.py`：
  - `standardize_vehicle_detailed()`，`tests/test_standardizer_enhanced.py:14,25,35,45`
  - `standardize_season()`，`tests/test_standardizer_enhanced.py:55,62,69,76`
  - `standardize_road_type()`，`tests/test_standardizer_enhanced.py:84,91,97,103,110`
  - `standardize_stability_class()`，`tests/test_standardizer_enhanced.py:137,144,151,160,168,172`
- `tests/test_standardization_engine.py` 中用于对照 legacy standardizer 的调用：
  - `standardize_vehicle_detailed()`，`tests/test_standardization_engine.py:38,44,50`
  - `standardize_pollutant_detailed()`，`tests/test_standardization_engine.py:56,62`
  - `standardize_season()`，`tests/test_standardization_engine.py:68`
  - `standardize_stability_class()`，`tests/test_standardization_engine.py:74`
  - `standardize_meteorology()`，`tests/test_standardization_engine.py:80`
- `tests/test_dispersion_integration.py`，`TestMeteorologyStandardization.*`
  - `standardize_meteorology()`，`tests/test_dispersion_integration.py:565,576,587,594`
  - `standardize_stability_class()`，`tests/test_dispersion_integration.py:605,612`

### 6.2 `StandardizationEngine` 方法调用点

#### 运行时代码

- `core/executor.py`，`ToolExecutor._standardize_arguments()`，`L338-L341`
  - `self._std_engine.standardize_batch(params=arguments, tool_name=tool_name)`
- `core/router.py`，`UnifiedRouter._build_parameter_negotiation_request()`，`L4177`
  - `std_engine.get_candidate_aliases(param_name)`
- `core/router.py`，`UnifiedRouter._build_parameter_negotiation_request()`，`L4189`
  - `std_engine.resolve_candidate_value(param_name, display_label)`

#### 测试代码

- `tests/test_standardization_engine.py`
  - `engine.standardize(...)` 覆盖 `tests/test_standardization_engine.py:37,43,49,55,61,67,73,79,84,90,96,125,138,152,160,167,174,185,196,213,225,237,312,323,324`
  - `engine.standardize_batch(...)` 覆盖 `tests/test_standardization_engine.py:248,265,275,284,299,346,353`
  - `engine.register_param_type(...)` 位于 `tests/test_standardization_engine.py:352`
- `tests/test_parameter_negotiation.py`
  - `engine.standardize_batch(...)` 位于 `tests/test_parameter_negotiation.py:94,113`
  - `engine.resolve_candidate_value(...)` 位于 `tests/test_parameter_negotiation.py:125,126,127`

### 6.3 直接引用 `shared/standardizer/` 下模块的位置

- `skills/macro_emission/skill.py`
  - import：`shared.standardizer.vehicle / pollutant / constants`，`skills/macro_emission/skill.py:5-7`
  - `MacroEmissionSkill.__init__()`：`get_vehicle_standardizer()`、`get_pollutant_standardizer()`，`skills/macro_emission/skill.py:30-31`
  - `MacroEmissionSkill.execute()`：`self._pollutant_std.standardize(...)`，`skills/macro_emission/skill.py:260`
  - `MacroEmissionSkill.execute()`：`SEASON_MAPPING.get(...)`，`skills/macro_emission/skill.py:285`
  - `MacroEmissionSkill._standardize_fleet_mix()`：`self._vehicle_std.standardize(...)`，`skills/macro_emission/skill.py:392`
- `skills/micro_emission/skill.py`
  - import：`shared.standardizer.vehicle / pollutant / constants`，`skills/micro_emission/skill.py:10-12`
  - `MicroEmissionSkill.__init__()`：`get_vehicle_standardizer()`、`get_pollutant_standardizer()`，`skills/micro_emission/skill.py:34-35`
  - `MicroEmissionSkill.execute()`：`self._vehicle_std.standardize(...)`，`skills/micro_emission/skill.py:210`
  - `MicroEmissionSkill.execute()`：`self._pollutant_std.standardize(...)`，`skills/micro_emission/skill.py:225`
  - `MicroEmissionSkill.execute()`：`SEASON_MAPPING.get(...)`，`skills/micro_emission/skill.py:237`
- `calculators/vsp.py`
  - import：`from shared.standardizer.constants import VSP_PARAMETERS, VSP_BINS`，`calculators/vsp.py:5`
  - `VSPCalculator.__init__()`：`self.params = VSP_PARAMETERS`，`calculators/vsp.py:11`
  - `VSPCalculator.vsp_to_bin()`：遍历 `VSP_BINS.items()`，`calculators/vsp.py:49`
- `skills/micro_emission/vsp.py`
  - import：`from shared.standardizer.constants import VSP_PARAMETERS, VSP_BINS`，`skills/micro_emission/vsp.py:5`
  - `VSPCalculator.__init__()`：`self.params = VSP_PARAMETERS`，`skills/micro_emission/vsp.py:11`
  - `VSPCalculator.vsp_to_bin()`：遍历 `VSP_BINS.items()`，`skills/micro_emission/vsp.py:49`
- `services/standardizer.py`
  - `_get_local_model()` 中惰性导入 `shared.standardizer.local_client.get_local_standardizer_client`，`services/standardizer.py:738-740`

### 6.4 `core/executor.py` 中标准化的完整触发逻辑

来源：`core/executor.py`，`ToolExecutor.execute` 和 `ToolExecutor._standardize_arguments`，`L176-L354`。

```python
async def execute(
    self,
    tool_name: str,
    arguments: Dict[str, Any],
    file_path: str = None
) -> Dict:
    """
    Execute a tool call

    Flow:
    1. Get tool from registry
    2. Standardize parameters (transparent)
    3. Validate parameters
    4. Execute tool
    5. Format result

    Args:
        tool_name: Name of tool to execute
        arguments: Tool arguments from LLM
        file_path: Optional file path context

    Returns:
        Execution result dictionary
    """
    start_time = time.perf_counter()
    summarized_original_args = summarize_arguments(arguments or {})
    exec_trace = {
        "tool_name": tool_name,
        "original_arguments": summarized_original_args,
        "standardization_enabled": self.runtime_config.enable_executor_standardization,
        "file_path_context": file_path,
    }

    # 1. Get tool
    tool = self.registry.get(tool_name)
    if not tool:
        return {
            "success": False,
            "error": True,
            "message": f"Unknown tool: {tool_name}",
            "_trace": exec_trace,
        }

    # 2. Standardize parameters (transparent to LLM)
    std_records: List[Dict[str, Any]] = []
    try:
        if logger.isEnabledFor(logging.INFO):
            logger.info("[Executor] Original arguments for %s: %s", tool_name, summarized_original_args)
        standardized_args, std_records = self._standardize_arguments(tool_name, arguments or {})
        summarized_standardized_args = summarize_arguments(standardized_args)
        if logger.isEnabledFor(logging.INFO):
            logger.info("[Executor] Standardized arguments for %s: %s", tool_name, summarized_standardized_args)
        exec_trace["standardized_arguments"] = summarized_standardized_args
        exec_trace["standardization_records"] = std_records
    except StandardizationError as e:
        logger.error(f"Standardization failed for {tool_name}: {e}")
        return {
            "success": False,
            "error": True,
            "error_type": "standardization",
            "message": str(e),
            "suggestions": e.suggestions if hasattr(e, "suggestions") else None,
            "param_name": e.param_name if hasattr(e, "param_name") else None,
            "original_value": e.original_value if hasattr(e, "original_value") else None,
            "negotiation_eligible": bool(getattr(e, "negotiation_eligible", False)),
            "trigger_reason": getattr(e, "trigger_reason", None),
            "_standardization_records": e.records if hasattr(e, "records") else std_records,
            "_trace": {
                **exec_trace,
                "standardization_records": e.records if hasattr(e, "records") else std_records,
                "error": str(e),
                "duration_ms": round((time.perf_counter() - start_time) * 1000, 2),
            },
        }

    # 3. Add file path if needed
    if file_path and "file_path" not in standardized_args:
        standardized_args["file_path"] = file_path
        logger.info(f"[Executor] Auto-injected file_path: {file_path}")
        exec_trace["auto_injected_file_path"] = True
    else:
        exec_trace["auto_injected_file_path"] = False

    # 4. Execute tool
    try:
        logger.info(f"Executing {tool_name} with standardized args")
        result = await tool.execute(**standardized_args)

        logger.info(f"{tool_name} execution completed. Success: {result.success}")
        if not result.success:
            logger.error(f"{tool_name} failed: {result.data if result.error else 'Unknown error'}")

        # Convert ToolResult to dict
        return {
            "success": result.success,
            "data": result.data,
            "error": result.error,
            "summary": result.summary,
            "chart_data": result.chart_data,
            "table_data": result.table_data,
            "map_data": result.map_data,
            "download_file": result.download_file,
            "message": result.error if result.error else result.summary,
            "_standardization_records": std_records,
            "_trace": {
                **exec_trace,
                "standardization_records": std_records,
                "duration_ms": round((time.perf_counter() - start_time) * 1000, 2),
            },
        }

    except MissingParameterError as e:
        return {
            "success": False,
            "error": True,
            "error_type": "missing_parameter",
            "message": str(e),
            "missing_params": e.params if hasattr(e, 'params') else [],
            "_standardization_records": std_records,
            "_trace": {
                **exec_trace,
                "standardization_records": std_records,
                "duration_ms": round((time.perf_counter() - start_time) * 1000, 2),
            },
        }

    except Exception as e:
        logger.exception(f"Tool execution failed: {tool_name}")
        return {
            "success": False,
            "error": True,
            "error_type": "execution",
            "message": f"Execution failed: {str(e)}",
            "_standardization_records": std_records,
            "_trace": {
                **exec_trace,
                "standardization_records": std_records,
                "duration_ms": round((time.perf_counter() - start_time) * 1000, 2),
            },
        }

def _standardize_arguments(
    self,
    tool_name: str,
    arguments: Dict[str, Any],
) -> tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """
    Standardize tool arguments using domain-specific rules.

    Args:
        tool_name: Tool name (for context)
        arguments: Raw arguments from LLM

    Returns:
        Tuple of (standardized_arguments, standardization_records).

    Raises:
        StandardizationError: If standardization fails
    """
    if not self.runtime_config.enable_executor_standardization:
        return dict(arguments or {}), []
    try:
        standardized, records = self._std_engine.standardize_batch(
            params=arguments,
            tool_name=tool_name,
        )
        self._last_standardization_records = list(records)
        return standardized, records
    except BatchStandardizationError as exc:
        self._last_standardization_records = list(exc.records)
        raise StandardizationError(
            str(exc),
            suggestions=exc.suggestions,
            records=exc.records,
            param_name=exc.param_name,
            original_value=exc.original_value,
            negotiation_eligible=exc.negotiation_eligible,
            trigger_reason=exc.trigger_reason,
        ) from exc
```
## 7. 本地模型 / LoRA 相关

### 7.1 `shared/standardizer/local_client.py` 完整代码

- 完整代码已在第 4.3 节贴出，来源是 `shared/standardizer/local_client.py:1-253`。

### 7.2 `config.py` 中所有与本地模型相关的配置项

#### provider 与 standardizer LLM 配置

来源：`config.py`，`Config.__post_init__`，`L19-L33`。

```python
self.providers = {
    "qwen": {"api_key": os.getenv("QWEN_API_KEY"), "base_url": os.getenv("QWEN_BASE_URL")},
    "deepseek": {"api_key": os.getenv("DEEPSEEK_API_KEY"), "base_url": os.getenv("DEEPSEEK_BASE_URL")},
    "local": {"api_key": os.getenv("LOCAL_LLM_API_KEY"), "base_url": os.getenv("LOCAL_LLM_BASE_URL")},
}

self.agent_llm = LLMAssignment(
    provider=os.getenv("AGENT_LLM_PROVIDER", "qwen"),
    model=os.getenv("AGENT_LLM_MODEL", "qwen-plus"),
    temperature=0.0  # v2.0+: 降低temperature提高确定性
)
self.standardizer_llm = LLMAssignment(
    provider=os.getenv("STANDARDIZER_LLM_PROVIDER", "qwen"),
    model=os.getenv("STANDARDIZER_LLM_MODEL", "qwen-turbo-latest"),
    temperature=0.1, max_tokens=200
)
```

#### executor / engine 层标准化配置

来源：`config.py`，`Config.__post_init__`，`L44-L55,189-L221`。

```python
self.enable_llm_standardization = os.getenv("ENABLE_LLM_STANDARDIZATION", "true").lower() == "true"
self.enable_standardization_cache = os.getenv("ENABLE_STANDARDIZATION_CACHE", "true").lower() == "true"
self.enable_data_collection = os.getenv("ENABLE_DATA_COLLECTION", "true").lower() == "true"
self.enable_file_analyzer = os.getenv("ENABLE_FILE_ANALYZER", "true").lower() == "true"
self.enable_file_context_injection = os.getenv("ENABLE_FILE_CONTEXT_INJECTION", "true").lower() == "true"
self.enable_executor_standardization = os.getenv("ENABLE_EXECUTOR_STANDARDIZATION", "true").lower() == "true"
self.enable_state_orchestration = os.getenv("ENABLE_STATE_ORCHESTRATION", "true").lower() == "true"
self.enable_trace = os.getenv("ENABLE_TRACE", "true").lower() == "true"
self.enable_lightweight_planning = os.getenv("ENABLE_LIGHTWEIGHT_PLANNING", "false").lower() == "true"
self.enable_bounded_plan_repair = os.getenv("ENABLE_BOUNDED_PLAN_REPAIR", "false").lower() == "true"
self.enable_repair_aware_continuation = os.getenv("ENABLE_REPAIR_AWARE_CONTINUATION", "false").lower() == "true"
self.enable_parameter_negotiation = os.getenv("ENABLE_PARAMETER_NEGOTIATION", "false").lower() == "true"
self.enable_file_analysis_llm_fallback = os.getenv("ENABLE_FILE_ANALYSIS_LLM_FALLBACK", "false").lower() == "true"
self.enable_workflow_templates = os.getenv("ENABLE_WORKFLOW_TEMPLATES", "false").lower() == "true"

self.parameter_negotiation_confidence_threshold = float(
    os.getenv("PARAMETER_NEGOTIATION_CONFIDENCE_THRESHOLD", "0.85")
)
self.parameter_negotiation_max_candidates = int(
    os.getenv("PARAMETER_NEGOTIATION_MAX_CANDIDATES", "5")
)

self.standardization_config = {
    "llm_enabled": os.getenv(
        "STANDARDIZATION_LLM_ENABLED",
        "true" if self.enable_llm_standardization else "false",
    ).lower() == "true",
    "llm_backend": os.getenv("STANDARDIZATION_LLM_BACKEND", "api").lower(),
    "llm_model": os.getenv("STANDARDIZATION_LLM_MODEL") or None,
    "llm_timeout": float(os.getenv("STANDARDIZATION_LLM_TIMEOUT", "5.0")),
    "llm_max_retries": int(os.getenv("STANDARDIZATION_LLM_MAX_RETRIES", "1")),
    "fuzzy_threshold": float(os.getenv("STANDARDIZATION_FUZZY_THRESHOLD", "0.7")),
    "parameter_negotiation_enabled": self.enable_parameter_negotiation,
    "parameter_negotiation_confidence_threshold": self.parameter_negotiation_confidence_threshold,
    "parameter_negotiation_max_candidates": self.parameter_negotiation_max_candidates,
    "local_model_path": os.getenv("STANDARDIZATION_LOCAL_MODEL_PATH") or None,
}
```

#### 本地标准化模型配置

来源：`config.py`，`Config.__post_init__`，`L235-L247`。

```python
# ============ 本地标准化模型配置 ============
self.use_local_standardizer = os.getenv("USE_LOCAL_STANDARDIZER", "false").lower() == "true"

self.local_standardizer_config = {
    "enabled": self.use_local_standardizer,
    "mode": os.getenv("LOCAL_STANDARDIZER_MODE", "direct"),  # "direct" or "vllm"
    "base_model": os.getenv("LOCAL_STANDARDIZER_BASE_MODEL", "Qwen/Qwen2.5-3B-Instruct"),
    "unified_lora": os.getenv("LOCAL_STANDARDIZER_UNIFIED_LORA", "./LOCAL_STANDARDIZER_MODEL/models/unified_lora/final"),
    "column_lora": os.getenv("LOCAL_STANDARDIZER_COLUMN_LORA", "./LOCAL_STANDARDIZER_MODEL/models/column_lora/checkpoint-200"),
    "device": os.getenv("LOCAL_STANDARDIZER_DEVICE", "cuda"),  # "cuda" or "cpu"
    "max_length": int(os.getenv("LOCAL_STANDARDIZER_MAX_LENGTH", "256")),
    "vllm_url": os.getenv("LOCAL_STANDARDIZER_VLLM_URL", "http://localhost:8001"),
}
```

### 7.3 `LOCAL_STANDARDIZER_MODEL/` 目录结构

来源：`find LOCAL_STANDARDIZER_MODEL -maxdepth 3 | sort` 的当前结果，对应目录实体如下。

```text
LOCAL_STANDARDIZER_MODEL
LOCAL_STANDARDIZER_MODEL/INTEGRATION_ANALYSIS.md
LOCAL_STANDARDIZER_MODEL/INTEGRATION_GUIDE.md
LOCAL_STANDARDIZER_MODEL/INTEGRATION_SUMMARY.md
LOCAL_STANDARDIZER_MODEL/PROMPT.md
LOCAL_STANDARDIZER_MODEL/QUICKSTART.md
LOCAL_STANDARDIZER_MODEL/README.md
LOCAL_STANDARDIZER_MODEL/SUMMARY.md
LOCAL_STANDARDIZER_MODEL/TRAINING_GUIDE.md
LOCAL_STANDARDIZER_MODEL/TRAINING_STRATEGY.md
LOCAL_STANDARDIZER_MODEL/configs
LOCAL_STANDARDIZER_MODEL/configs/column_lora_config.yaml
LOCAL_STANDARDIZER_MODEL/configs/unified_lora_config.yaml
LOCAL_STANDARDIZER_MODEL/data
LOCAL_STANDARDIZER_MODEL/data/augmented
LOCAL_STANDARDIZER_MODEL/data/augmented/column_augmented.json
LOCAL_STANDARDIZER_MODEL/data/augmented/unified_augmented.json
LOCAL_STANDARDIZER_MODEL/data/final
LOCAL_STANDARDIZER_MODEL/data/final/column_eval.json
LOCAL_STANDARDIZER_MODEL/data/final/column_test.json
LOCAL_STANDARDIZER_MODEL/data/final/column_train.json
LOCAL_STANDARDIZER_MODEL/data/final/unified_eval.json
LOCAL_STANDARDIZER_MODEL/data/final/unified_test.json
LOCAL_STANDARDIZER_MODEL/data/final/unified_train.json
LOCAL_STANDARDIZER_MODEL/data/raw
LOCAL_STANDARDIZER_MODEL/data/raw/column_mapping_seed.json
LOCAL_STANDARDIZER_MODEL/data/raw/pollutant_seed.json
LOCAL_STANDARDIZER_MODEL/data/raw/vehicle_type_seed.json
LOCAL_STANDARDIZER_MODEL/models
LOCAL_STANDARDIZER_MODEL/models/column_lora
LOCAL_STANDARDIZER_MODEL/models/unified_lora
LOCAL_STANDARDIZER_MODEL/scripts
LOCAL_STANDARDIZER_MODEL/scripts/01_create_seed_data.py
LOCAL_STANDARDIZER_MODEL/scripts/02_augment_data.py
LOCAL_STANDARDIZER_MODEL/scripts/03_prepare_training_data.py
LOCAL_STANDARDIZER_MODEL/scripts/04_train_lora.py
LOCAL_STANDARDIZER_MODEL/scripts/06_evaluate.py
LOCAL_STANDARDIZER_MODEL/scripts/README.md
LOCAL_STANDARDIZER_MODEL/scripts/validate_data.py
LOCAL_STANDARDIZER_MODEL/setup_environment.bat
LOCAL_STANDARDIZER_MODEL/setup_environment.sh
LOCAL_STANDARDIZER_MODEL/start_vllm.bat
LOCAL_STANDARDIZER_MODEL/start_vllm.sh
LOCAL_STANDARDIZER_MODEL/tests
LOCAL_STANDARDIZER_MODEL/train_column.bat
LOCAL_STANDARDIZER_MODEL/train_unified.bat
```

- `LOCAL_STANDARDIZER_MODEL/models` 当前只看到两个子目录 `column_lora` 和 `unified_lora`，`find LOCAL_STANDARDIZER_MODEL/models -type f` 未返回文件。

### 7.4 本地模型在什么条件下被启用？在哪个代码路径中被调用？

- 启用条件 1：`config.use_local_standardizer` 来自环境变量 `USE_LOCAL_STANDARDIZER`，定义在 `config.py:236`。
- 启用条件 2：`local_standardizer_config["enabled"] = self.use_local_standardizer`，定义在 `config.py:238-247`。
- `services/standardizer.py` 路径：
  - `UnifiedStandardizer._get_local_model()` 在 `config.use_local_standardizer` 为真时才惰性导入并缓存 `get_local_standardizer_client()`，`services/standardizer.py:725-747`
  - `standardize_vehicle_detailed()` 在 exact / fuzzy 失败后调用 `_try_local_standardization(..., "standardize_vehicle")`，`services/standardizer.py:252-278`
  - `standardize_pollutant_detailed()` 在 exact / fuzzy 失败后调用 `_try_local_standardization(..., "standardize_pollutant")`，`services/standardizer.py:321-347`
- `services/standardization_engine.py` 路径：
  - 当使用自定义 fuzzy threshold 并进入 `RuleBackend._standardize_with_custom_threshold()` 时，`vehicle_type` 和 `pollutant` 分支也会调用 `_standardizer._try_local_standardization(...)`，`services/standardization_engine.py:282-305`
- `shared/standardizer/vehicle.py` 路径：
  - `VehicleStandardizer.__new__()` 判断 `config.use_local_standardizer`，为真时绑定 `_local_client = get_local_standardizer_client()`，`shared/standardizer/vehicle.py:36-59`
  - `VehicleStandardizer._llm_standardize()` 里优先走 `_local_client.standardize_vehicle(user_input)`，`shared/standardizer/vehicle.py:102-118`
- `shared/standardizer/pollutant.py` 路径：
  - `PollutantStandardizer.__new__()` 判断 `config.use_local_standardizer`，为真时绑定 `_local_client = get_local_standardizer_client()`，`shared/standardizer/pollutant.py:36-59`
  - `PollutantStandardizer._llm_standardize()` 里优先走 `_local_client.standardize_pollutant(user_input)`，`shared/standardizer/pollutant.py:102-118`

### 7.5 `llm/data_collector.py` 完整代码

来源：`llm/data_collector.py`，`L1-L84`。

```python
import json
from datetime import datetime
from pathlib import Path
from config import get_config

class DataCollector:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            config = get_config()
            cls._instance.base_dir = config.data_collection_dir
            cls._instance.enabled = config.enable_data_collection
        return cls._instance

    def log(self, task: str, input_value: str, output: dict, method: str,
            model: str = None, latency_ms: float = 0, context: dict = None):
        if not self.enabled:
            return

        entry = {
            "timestamp": datetime.now().isoformat(),
            "task": task,
            "input": input_value,
            "output": {"standard": output.get("standard"), "confidence": output.get("confidence", 0)},
            "method": method,
            "model": model,
            "latency_ms": round(latency_ms, 2),
            "context": context or {},
        }

        log_file = self.base_dir / f"{task}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_statistics(self, task: str) -> dict:
        log_file = self.base_dir / f"{task}.jsonl"
        if not log_file.exists():
            return {"total": 0}

        stats = {"total": 0, "by_method": {}, "confidences": []}
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                stats["total"] += 1
                method = entry.get("method", "unknown")
                stats["by_method"][method] = stats["by_method"].get(method, 0) + 1
                if conf := entry.get("output", {}).get("confidence"):
                    stats["confidences"].append(conf)

        stats["avg_confidence"] = sum(stats["confidences"]) / len(stats["confidences"]) if stats["confidences"] else 0
        return stats

    def export_for_finetune(self, task: str, output_file: str, min_confidence: float = 0.8) -> int:
        log_file = self.base_dir / f"{task}.jsonl"
        if not log_file.exists():
            return 0

        data, seen = [], set()
        instructions = {"vehicle_type": "将车型描述标准化为MOVES标准车型", "pollutant": "将污染物描述标准化"}

        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                if entry.get("method") not in ["llm", "rule"]:
                    continue
                if entry.get("output", {}).get("confidence", 0) < min_confidence:
                    continue
                standard = entry.get("output", {}).get("standard")
                if not standard:
                    continue
                key = f"{entry['input']}:{standard}"
                if key in seen:
                    continue
                seen.add(key)
                data.append({"instruction": instructions.get(task, ""), "input": entry["input"], "output": standard})

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return len(data)

def get_collector():
    return DataCollector()
```

---

## 8. 参数协商完整流程

### 8.1 `core/parameter_negotiation.py` 完整代码

来源：`core/parameter_negotiation.py`，`L1-L435`。

```python
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class NegotiationDecisionType(str, Enum):
    CONFIRMED = "confirmed"
    NONE_OF_ABOVE = "none_of_above"
    AMBIGUOUS_REPLY = "ambiguous_reply"


@dataclass
class NegotiationCandidate:
    index: int
    normalized_value: str
    display_label: str
    confidence: Optional[float] = None
    strategy: Optional[str] = None
    reason: Optional[str] = None
    aliases: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index": self.index,
            "normalized_value": self.normalized_value,
            "display_label": self.display_label,
            "confidence": self.confidence,
            "strategy": self.strategy,
            "reason": self.reason,
            "aliases": list(self.aliases),
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "NegotiationCandidate":
        payload = data if isinstance(data, dict) else {}
        return cls(
            index=int(payload.get("index") or 0),
            normalized_value=str(payload.get("normalized_value") or "").strip(),
            display_label=str(payload.get("display_label") or "").strip(),
            confidence=(
                float(payload["confidence"])
                if payload.get("confidence") is not None
                else None
            ),
            strategy=str(payload.get("strategy")).strip() if payload.get("strategy") is not None else None,
            reason=str(payload.get("reason")).strip() if payload.get("reason") is not None else None,
            aliases=[
                str(item).strip()
                for item in (payload.get("aliases") or [])
                if str(item).strip()
            ],
        )


@dataclass
class ParameterNegotiationRequest:
    request_id: str
    parameter_name: str
    raw_value: str
    confidence: Optional[float]
    trigger_reason: str
    tool_name: Optional[str] = None
    arg_name: Optional[str] = None
    strategy: Optional[str] = None
    candidates: List[NegotiationCandidate] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "request_id": self.request_id,
            "parameter_name": self.parameter_name,
            "raw_value": self.raw_value,
            "confidence": self.confidence,
            "trigger_reason": self.trigger_reason,
            "tool_name": self.tool_name,
            "arg_name": self.arg_name,
            "strategy": self.strategy,
            "candidates": [candidate.to_dict() for candidate in self.candidates],
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ParameterNegotiationRequest":
        payload = data if isinstance(data, dict) else {}
        return cls(
            request_id=str(payload.get("request_id") or "").strip(),
            parameter_name=str(payload.get("parameter_name") or "").strip(),
            raw_value=str(payload.get("raw_value") or "").strip(),
            confidence=(
                float(payload["confidence"])
                if payload.get("confidence") is not None
                else None
            ),
            trigger_reason=str(payload.get("trigger_reason") or "").strip(),
            tool_name=str(payload.get("tool_name")).strip() if payload.get("tool_name") is not None else None,
            arg_name=str(payload.get("arg_name")).strip() if payload.get("arg_name") is not None else None,
            strategy=str(payload.get("strategy")).strip() if payload.get("strategy") is not None else None,
            candidates=[
                NegotiationCandidate.from_dict(item)
                for item in (payload.get("candidates") or [])
                if isinstance(item, dict)
            ],
        )

    @classmethod
    def create(
        cls,
        *,
        parameter_name: str,
        raw_value: Any,
        trigger_reason: str,
        tool_name: Optional[str] = None,
        arg_name: Optional[str] = None,
        confidence: Optional[float] = None,
        strategy: Optional[str] = None,
        candidates: Optional[List[NegotiationCandidate]] = None,
    ) -> "ParameterNegotiationRequest":
        return cls(
            request_id=f"neg-{parameter_name}-{uuid.uuid4().hex[:8]}",
            parameter_name=parameter_name,
            raw_value=str(raw_value or "").strip(),
            confidence=confidence,
            trigger_reason=trigger_reason,
            tool_name=tool_name,
            arg_name=arg_name or parameter_name,
            strategy=strategy,
            candidates=list(candidates or []),
        )


@dataclass
class ParameterNegotiationDecision:
    parameter_name: str
    decision_type: NegotiationDecisionType
    user_reply: str
    selected_index: Optional[int] = None
    selected_value: Optional[str] = None
    request_id: Optional[str] = None
    selected_display_label: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "parameter_name": self.parameter_name,
            "decision_type": self.decision_type.value,
            "user_reply": self.user_reply,
            "selected_index": self.selected_index,
            "selected_value": self.selected_value,
            "request_id": self.request_id,
            "selected_display_label": self.selected_display_label,
        }

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "ParameterNegotiationDecision":
        payload = data if isinstance(data, dict) else {}
        decision_type = payload.get("decision_type") or NegotiationDecisionType.AMBIGUOUS_REPLY.value
        return cls(
            parameter_name=str(payload.get("parameter_name") or "").strip(),
            decision_type=NegotiationDecisionType(decision_type),
            user_reply=str(payload.get("user_reply") or "").strip(),
            selected_index=int(payload["selected_index"]) if payload.get("selected_index") is not None else None,
            selected_value=str(payload.get("selected_value")).strip() if payload.get("selected_value") is not None else None,
            request_id=str(payload.get("request_id")).strip() if payload.get("request_id") is not None else None,
            selected_display_label=(
                str(payload.get("selected_display_label")).strip()
                if payload.get("selected_display_label") is not None
                else None
            ),
        )


@dataclass
class ParameterNegotiationParseResult:
    is_resolved: bool
    decision: Optional[ParameterNegotiationDecision] = None
    needs_retry: bool = False
    error_message: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "is_resolved": self.is_resolved,
            "decision": self.decision.to_dict() if self.decision else None,
            "needs_retry": self.needs_retry,
            "error_message": self.error_message,
        }


_NONE_OF_ABOVE_PHRASES = (
    "none of the above",
    "none",
    "都不对",
    "都不是",
    "都不行",
    "none-of-above",
)

_CHINESE_INDEX_MAP = {
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
}


def _normalize_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).lower()


def _extract_parenthetical_parts(text: str) -> List[str]:
    cleaned = str(text or "").strip()
    if not cleaned:
        return []
    parts = [cleaned]
    match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", cleaned)
    if match:
        left = match.group(1).strip()
        right = match.group(2).strip()
        if left:
            parts.append(left)
        if right:
            parts.append(right)
    return parts


def _extract_indices(reply: str) -> List[int]:
    cleaned = str(reply or "").strip().lower()
    if not cleaned:
        return []

    indices: List[int] = []

    exact_digit = re.fullmatch(r"(\d+)", cleaned)
    if exact_digit:
        indices.append(int(exact_digit.group(1)))
        return indices

    patterns = (
        r"选第\s*(\d+)\s*个",
        r"第\s*(\d+)\s*个",
        r"option\s*(\d+)",
        r"choose\s*(\d+)",
    )
    for pattern in patterns:
        for match in re.finditer(pattern, cleaned):
            indices.append(int(match.group(1)))

    for char, index in _CHINESE_INDEX_MAP.items():
        if f"第{char}个" in cleaned or f"选第{char}个" in cleaned:
            indices.append(index)

    deduped: List[int] = []
    for index in indices:
        if index not in deduped:
            deduped.append(index)
    return deduped


def _extract_index(reply: str) -> Optional[int]:
    indices = _extract_indices(reply)
    if len(indices) == 1:
        return indices[0]
    return None


def reply_looks_like_confirmation_attempt(
    request: ParameterNegotiationRequest,
    user_reply: str,
) -> bool:
    normalized_reply = _normalize_text(user_reply)
    if not normalized_reply:
        return False
    if any(phrase in normalized_reply for phrase in _NONE_OF_ABOVE_PHRASES):
        return True
    if _extract_indices(user_reply):
        return True

    for candidate in request.candidates:
        terms = [candidate.display_label, candidate.normalized_value, *candidate.aliases]
        for term in terms:
            normalized_term = _normalize_text(term)
            if normalized_term and (
                normalized_reply == normalized_term
                or normalized_term in normalized_reply
            ):
                return True
    return False


def parse_parameter_negotiation_reply(
    request: ParameterNegotiationRequest,
    user_reply: str,
) -> ParameterNegotiationParseResult:
    reply = str(user_reply or "").strip()
    normalized_reply = _normalize_text(reply)
    if not normalized_reply:
        return ParameterNegotiationParseResult(
            is_resolved=False,
            needs_retry=True,
            error_message="Empty confirmation reply.",
        )

    if any(phrase in normalized_reply for phrase in _NONE_OF_ABOVE_PHRASES):
        return ParameterNegotiationParseResult(
            is_resolved=True,
            decision=ParameterNegotiationDecision(
                parameter_name=request.parameter_name,
                decision_type=NegotiationDecisionType.NONE_OF_ABOVE,
                user_reply=reply,
                request_id=request.request_id,
            ),
        )

    selected_index = _extract_index(reply)
    if selected_index is not None:
        for candidate in request.candidates:
            if candidate.index == selected_index:
                return ParameterNegotiationParseResult(
                    is_resolved=True,
                    decision=ParameterNegotiationDecision(
                        parameter_name=request.parameter_name,
                        decision_type=NegotiationDecisionType.CONFIRMED,
                        user_reply=reply,
                        selected_index=candidate.index,
                        selected_value=candidate.normalized_value,
                        selected_display_label=candidate.display_label,
                        request_id=request.request_id,
                    ),
                )
        return ParameterNegotiationParseResult(
            is_resolved=False,
            needs_retry=True,
            error_message=f"Candidate index {selected_index} is out of range.",
        )

    exact_matches: List[NegotiationCandidate] = []
    partial_matches: List[NegotiationCandidate] = []
    for candidate in request.candidates:
        terms = [candidate.display_label, candidate.normalized_value, *candidate.aliases]
        normalized_terms = {_normalize_text(term) for term in terms if _normalize_text(term)}
        if normalized_reply in normalized_terms:
            exact_matches.append(candidate)
            continue
        if any(term in normalized_reply for term in normalized_terms):
            partial_matches.append(candidate)

    matches = exact_matches or partial_matches
    unique_matches = {candidate.index: candidate for candidate in matches}
    if len(unique_matches) == 1:
        candidate = list(unique_matches.values())[0]
        return ParameterNegotiationParseResult(
            is_resolved=True,
            decision=ParameterNegotiationDecision(
                parameter_name=request.parameter_name,
                decision_type=NegotiationDecisionType.CONFIRMED,
                user_reply=reply,
                selected_index=candidate.index,
                selected_value=candidate.normalized_value,
                selected_display_label=candidate.display_label,
                request_id=request.request_id,
            ),
        )

    return ParameterNegotiationParseResult(
        is_resolved=False,
        needs_retry=True,
        error_message=(
            "The reply did not uniquely identify one candidate. "
            "Reply with the candidate index, canonical value, label, or '都不对'."
        ),
    )


def format_parameter_negotiation_prompt(
    request: ParameterNegotiationRequest,
    *,
    retry_message: Optional[str] = None,
) -> str:
    lines = [
        "参数确认 / Parameter Confirmation",
        (
            f"我不能安全地确定参数 `{request.parameter_name}` 的值。"
            f" 原始输入是 `{request.raw_value}`。"
        ),
    ]
    if request.tool_name:
        lines.append(f"相关工具: `{request.tool_name}`")
    if request.strategy or request.confidence is not None:
        confidence_text = (
            f"{request.confidence:.2f}"
            if request.confidence is not None
            else "n/a"
        )
        lines.append(
            f"触发原因: {request.trigger_reason} "
            f"(strategy={request.strategy or 'unknown'}, confidence={confidence_text})"
        )
    else:
        lines.append(f"触发原因: {request.trigger_reason}")

    lines.append("请在以下候选中确认一个：")
    for candidate in request.candidates:
        confidence_text = (
            f" · conf={candidate.confidence:.2f}"
            if candidate.confidence is not None
            else ""
        )
        strategy_text = f" · {candidate.strategy}" if candidate.strategy else ""
        lines.append(
            f"{candidate.index}. {candidate.display_label}"
            f" -> `{candidate.normalized_value}`{strategy_text}{confidence_text}"
        )

    if retry_message:
        lines.append(f"上次回复未能唯一确认: {retry_message}")

    lines.append(
        "回复方式：输入序号、候选标签、canonical value，或回复“都不对”/`none`。"
    )
    return "\n".join(lines)


def build_candidate_aliases(display_label: str, normalized_value: str, extra_aliases: Optional[List[str]] = None) -> List[str]:
    seen = set()
    aliases: List[str] = []
    for item in [display_label, normalized_value, *_extract_parenthetical_parts(display_label), *(extra_aliases or [])]:
        text = str(item or "").strip()
        lowered = text.lower()
        if text and lowered not in seen:
            seen.add(lowered)
            aliases.append(text)
    return aliases
```

### 8.2 router 中检测标准化失败并触发协商的代码段

来源：`core/router.py`，工具执行结果处理，`L9079-L9134`。

```python
std_records = result.get("_standardization_records", [])
if trace_obj and std_records:
    std_summary_parts = []
    for rec in std_records:
        param = rec.get("param", "?")
        original = rec.get("original", "?")
        normalized = rec.get("normalized", original)
        strategy = rec.get("strategy", "?")
        confidence = rec.get("confidence", 0)

        if original != normalized:
            std_summary_parts.append(
                f"{param}: '{original}' → '{normalized}' ({strategy}, conf={confidence:.2f})"
            )
        else:
            std_summary_parts.append(
                f"{param}: '{original}' ✓ ({strategy}, conf={confidence:.2f})"
            )

    if std_summary_parts:
        trace_obj.record(
            step_type=TraceStepType.PARAMETER_STANDARDIZATION,
            stage_before=TaskStage.EXECUTING.value,
            action="standardize_parameters",
            reasoning="; ".join(std_summary_parts),
            standardization_records=std_records,
        )

if result.get("error") and result.get("error_type") == "standardization":
    error_msg = result.get("message", "Parameter standardization failed")
    negotiation_request = self._build_parameter_negotiation_request(tool_call.name, result)
    if negotiation_request is not None:
        state.execution.last_error = error_msg
        self._activate_parameter_confirmation_state(
            state,
            negotiation_request,
            trace_obj=trace_obj,
        )
        return

    suggestions = result.get("suggestions", [])
    clarification = (
        f"{error_msg}\n\nDid you mean one of these? {', '.join(suggestions[:5])}"
        if suggestions else error_msg
    )

    state.control.needs_user_input = True
    state.control.parameter_confirmation_prompt = None
    state.control.clarification_question = clarification
    state.execution.last_error = error_msg
    self._transition_state(
        state,
        TaskStage.NEEDS_CLARIFICATION,
        reason="Standardization failed",
        trace_obj=trace_obj,
    )
```

### 8.3 router 中生成协商请求的代码段

来源：`core/router.py`，`UnifiedRouter._build_parameter_negotiation_request`，`L4142-L4232`。

```python
def _build_parameter_negotiation_request(
    self,
    tool_name: str,
    result: Dict[str, Any],
) -> Optional[ParameterNegotiationRequest]:
    if not getattr(self.runtime_config, "enable_parameter_negotiation", False):
        return None
    if not result.get("negotiation_eligible"):
        return None

    param_name = str(result.get("param_name") or "").strip()
    raw_value = result.get("original_value")
    records = list(result.get("_standardization_records") or [])
    target_record = None
    if param_name:
        for record in reversed(records):
            if record.get("param") == param_name:
                target_record = record
                break
    if target_record is None and records:
        target_record = records[-1]
        param_name = str(target_record.get("param") or param_name).strip()
        raw_value = target_record.get("original", raw_value)

    if not param_name:
        return None

    record_suggestions = target_record.get("suggestions") if isinstance(target_record, dict) else []
    suggestions = list(result.get("suggestions") or record_suggestions or [])
    max_candidates = max(int(getattr(self.runtime_config, "parameter_negotiation_max_candidates", 5)), 1)
    suggestions = suggestions[:max_candidates]
    if not suggestions:
        return None

    std_engine = getattr(self.executor, "_std_engine", None)
    alias_map = std_engine.get_candidate_aliases(param_name) if std_engine is not None else {}
    trigger_reason = str(result.get("trigger_reason") or "standardization requires confirmation").strip()
    confidence = target_record.get("confidence") if isinstance(target_record, dict) else None
    strategy = target_record.get("strategy") if isinstance(target_record, dict) else None

    candidates: List[NegotiationCandidate] = []
    seen = set()
    for index, suggestion in enumerate(suggestions, start=1):
        display_label = str(suggestion).strip()
        if not display_label:
            continue
        normalized_value = (
            std_engine.resolve_candidate_value(param_name, display_label)
            if std_engine is not None
            else None
        )
        if not normalized_value:
            label_match = re.match(r"^(.*?)\s*\((.*?)\)\s*$", display_label)
            normalized_value = (
                label_match.group(2).strip()
                if label_match and label_match.group(2).strip()
                else display_label
            )
        dedupe_key = (display_label.lower(), normalized_value.lower())
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        candidates.append(
            NegotiationCandidate(
                index=index,
                normalized_value=normalized_value,
                display_label=display_label,
                confidence=confidence,
                strategy=strategy,
                reason=trigger_reason,
                aliases=build_candidate_aliases(
                    display_label,
                    normalized_value,
                    extra_aliases=list(alias_map.get(normalized_value, [])),
                ),
            )
        )

    if not candidates:
        return None

    return ParameterNegotiationRequest.create(
        parameter_name=param_name,
        raw_value=raw_value,
        confidence=confidence,
        trigger_reason=trigger_reason,
        tool_name=tool_name,
        arg_name=param_name,
        strategy=strategy,
        candidates=candidates,
    )
```

### 8.4 router 中接收用户协商回复并处理的代码段

#### 检测是否应处理回复

来源：`core/router.py`，`UnifiedRouter._should_handle_parameter_confirmation` 和 `_parse_parameter_confirmation_reply`，`L6618-L6635`。

```python
def _should_handle_parameter_confirmation(self, state: TaskState) -> bool:
    request = state.active_parameter_negotiation or self._load_active_parameter_negotiation_request()
    if request is None or not getattr(self.runtime_config, "enable_parameter_negotiation", False):
        return False
    return reply_looks_like_confirmation_attempt(request, state.user_message or "")

def _parse_parameter_confirmation_reply(
    self,
    state: TaskState,
) -> ParameterNegotiationParseResult:
    request = state.active_parameter_negotiation or self._load_active_parameter_negotiation_request()
    if request is None:
        return ParameterNegotiationParseResult(
            is_resolved=False,
            needs_retry=False,
            error_message="No active parameter negotiation request.",
        )
    return parse_parameter_negotiation_reply(request, state.user_message or "")
```

#### 处理确认 / 拒绝 / 歧义回复

来源：`core/router.py`，`UnifiedRouter._handle_active_parameter_confirmation`，`L6725-L6843`。

```python
def _handle_active_parameter_confirmation(
    self,
    state: TaskState,
    trace_obj: Optional[Trace] = None,
) -> Optional[ContinuationDecision]:
    request = self._load_active_parameter_negotiation_request()
    if request is None:
        return None

    state.set_active_parameter_negotiation(request)
    message = (state.user_message or "").strip()
    is_new_task, _signal, _reason = self._is_new_task_request(state)
    if is_new_task:
        self._clear_live_parameter_negotiation_state(clear_locks=True)
        state.set_active_parameter_negotiation(None)
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.PARAMETER_NEGOTIATION_REJECTED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                reasoning="Active parameter negotiation was superseded because the user explicitly started a new task.",
                input_summary={"request_id": request.request_id, "parameter_name": request.parameter_name},
            )
        return None

    if not self._should_handle_parameter_confirmation(state):
        return None

    parse_result = self._parse_parameter_confirmation_reply(state)
    if parse_result.is_resolved and parse_result.decision is not None:
        decision = parse_result.decision
        state.set_latest_parameter_negotiation_decision(decision)
        if decision.decision_type == NegotiationDecisionType.CONFIRMED and decision.selected_value:
            locked_entry = state.apply_parameter_lock(
                parameter_name=request.parameter_name,
                normalized_value=decision.selected_value,
                raw_value=request.raw_value,
                request_id=request.request_id,
            )
            bundle = self._ensure_live_parameter_negotiation_bundle()
            locked_parameters = dict(bundle.get("locked_parameters") or {})
            locked_parameters[request.parameter_name] = locked_entry.to_dict()
            bundle["locked_parameters"] = locked_parameters
            bundle["latest_confirmed_parameter"] = decision.to_dict()
            bundle["active_request"] = None
            state.set_active_parameter_negotiation(None)
            state.control.needs_user_input = False
            state.control.parameter_confirmation_prompt = None
            if trace_obj:
                trace_obj.record(
                    step_type=TraceStepType.PARAMETER_NEGOTIATION_CONFIRMED,
                    stage_before=TaskStage.INPUT_RECEIVED.value,
                    action=request.tool_name,
                    input_summary={
                        "request_id": request.request_id,
                        "parameter_name": request.parameter_name,
                        "selected_index": decision.selected_index,
                    },
                    output_summary={
                        "selected_value": decision.selected_value,
                        "lock_applied": True,
                    },
                    reasoning=(
                        f"Confirmed {request.parameter_name}={decision.selected_value} "
                        f"from reply '{decision.user_reply}'."
                    ),
                )
            return self._build_parameter_confirmation_resume_decision(state)

        self._clear_live_parameter_negotiation_state(clear_locks=False)
        state.set_active_parameter_negotiation(None)
        state.control.needs_user_input = True
        state.control.parameter_confirmation_prompt = None
        state.control.clarification_question = self._build_parameter_confirmation_clarification(request)
        self._transition_state(
            state,
            TaskStage.NEEDS_CLARIFICATION,
            reason="User rejected all parameter candidates",
            trace_obj=trace_obj,
        )
        if trace_obj:
            trace_obj.record(
                step_type=TraceStepType.PARAMETER_NEGOTIATION_REJECTED,
                stage_before=TaskStage.INPUT_RECEIVED.value,
                stage_after=TaskStage.NEEDS_CLARIFICATION.value,
                action=request.tool_name,
                input_summary={"request_id": request.request_id, "parameter_name": request.parameter_name},
                reasoning=(
                    f"User rejected all candidates for {request.parameter_name} "
                    f"with reply '{decision.user_reply}'."
                ),
            )
        return None

    state.control.needs_user_input = True
    prompt_text = format_parameter_negotiation_prompt(
        request,
        retry_message=parse_result.error_message,
    )
    state.control.parameter_confirmation_prompt = prompt_text
    self._transition_state(
        state,
        TaskStage.NEEDS_PARAMETER_CONFIRMATION,
        reason="Parameter confirmation reply was ambiguous",
        trace_obj=trace_obj,
    )
    if trace_obj:
        trace_obj.record(
            step_type=TraceStepType.PARAMETER_NEGOTIATION_FAILED,
            stage_before=TaskStage.INPUT_RECEIVED.value,
            stage_after=TaskStage.NEEDS_PARAMETER_CONFIRMATION.value,
            action=request.tool_name,
            input_summary={
                "request_id": request.request_id,
                "parameter_name": request.parameter_name,
                "user_reply": state.user_message,
            },
            reasoning=parse_result.error_message or "Parameter confirmation reply could not be parsed.",
        )
    return None
```

### 8.5 `apply_parameter_lock()` 被调用的所有位置

- `core/router.py`，`UnifiedRouter._handle_active_parameter_confirmation()`，`L6757-L6762`
  - `locked_entry = state.apply_parameter_lock(...)`
- `tests/test_task_state.py`，测试代码，`L192`
  - `state.apply_parameter_lock(...)`

#### `apply_parameter_lock()` 定义

来源：`core/task_state.py`，`TaskState.apply_parameter_lock`，`L869-L888`。

```python
def apply_parameter_lock(
    self,
    *,
    parameter_name: str,
    normalized_value: str,
    raw_value: Optional[str] = None,
    request_id: Optional[str] = None,
    lock_source: str = "user_confirmation",
) -> ParamEntry:
    entry = self.parameters.get(parameter_name, ParamEntry())
    entry.raw = raw_value if raw_value is not None else (entry.raw or normalized_value)
    entry.normalized = normalized_value
    entry.status = ParamStatus.OK
    entry.confidence = 1.0
    entry.strategy = "user_confirmed"
    entry.locked = True
    entry.lock_source = lock_source
    entry.confirmation_request_id = request_id
    self.parameters[parameter_name] = entry
    return entry
```

---

## 9. 现有标准化测试和评估

### 9.1 `tests/test_standardizer.py`

- `TestVehicleStandardization.test_exact_english`，`tests/test_standardizer.py:17`：验证英文标准车型 `"Passenger Car"` 直接映射成功。
- `TestVehicleStandardization.test_exact_chinese`，`tests/test_standardizer.py:21`：验证中文标准名 `"乘用车"` 映射到 `"Passenger Car"`。
- `TestVehicleStandardization.test_alias_chinese`，`tests/test_standardizer.py:25`：验证 `"小汽车"` / `"公交车"` 等中文别名映射。
- `TestVehicleStandardization.test_case_insensitive`，`tests/test_standardizer.py:30`：验证车型映射大小写不敏感。
- `TestVehicleStandardization.test_unknown_returns_none`，`tests/test_standardizer.py:35`：验证未知输入 `"飞机"` 返回 `None`。
- `TestVehicleStandardization.test_empty_returns_none`，`tests/test_standardizer.py:40`：验证空字符串和 `None` 返回 `None`。
- `TestVehicleStandardization.test_suggestions_non_empty`，`tests/test_standardizer.py:45`：验证车型建议列表非空且包含 `"Passenger Car"`。
- `TestPollutantStandardization.test_exact_english`，`tests/test_standardizer.py:55`：验证英文污染物标准名直接映射。
- `TestPollutantStandardization.test_case_insensitive`，`tests/test_standardizer.py:61`：验证污染物映射大小写不敏感。
- `TestPollutantStandardization.test_chinese_name`，`tests/test_standardizer.py:66`：验证中文污染物名称映射到标准英文值。
- `TestPollutantStandardization.test_unknown_returns_none`，`tests/test_standardizer.py:71`：验证未知污染物 `"oxygen"` 返回 `None`。
- `TestPollutantStandardization.test_suggestions_non_empty`，`tests/test_standardizer.py:75`：验证污染物建议列表包含 `"CO2"` 和 `"NOx"`。
- `TestColumnMapping.test_micro_speed_column`，`tests/test_standardizer.py:85`：验证 `micro_emission` 列名映射至少识别速度列。
- `TestColumnMapping.test_empty_columns`，`tests/test_standardizer.py:91`：验证空列输入返回空映射。

### 9.2 `tests/test_standardizer_enhanced.py`

- `TestStandardizationResult.test_vehicle_detailed_exact`，`tests/test_standardizer_enhanced.py:9`：验证 `standardize_vehicle_detailed()` exact 命中时的 `strategy` 和 `confidence`。
- `TestStandardizationResult.test_vehicle_detailed_alias`，`tests/test_standardizer_enhanced.py:20`：验证中文别名命中时返回 alias / exact 类策略。
- `TestStandardizationResult.test_vehicle_detailed_abstain`，`tests/test_standardizer_enhanced.py:30`：验证未知车型时 `success=False` 且带建议。
- `TestStandardizationResult.test_vehicle_detailed_to_dict`，`tests/test_standardizer_enhanced.py:40`：验证 `StandardizationResult.to_dict()` 输出可 JSON 序列化。
- `TestSeasonStandardization.test_chinese_summer`，`tests/test_standardizer_enhanced.py:52`：验证 `"夏天"` 映射到夏季。
- `TestSeasonStandardization.test_english_winter`，`tests/test_standardizer_enhanced.py:59`：验证 `"winter"` 映射到冬季。
- `TestSeasonStandardization.test_empty_returns_default`，`tests/test_standardizer_enhanced.py:66`：验证空季节输入走 default。
- `TestSeasonStandardization.test_unknown_returns_default`，`tests/test_standardizer_enhanced.py:73`：验证未知季节输入走 default。
- `TestRoadTypeStandardization.test_chinese_freeway`，`tests/test_standardizer_enhanced.py:81`：验证 `"高速公路"` 标准化成功。
- `TestRoadTypeStandardization.test_english_freeway`，`tests/test_standardizer_enhanced.py:88`：验证 `"freeway"` 标准化成功。
- `TestRoadTypeStandardization.test_chinese_expressway`，`tests/test_standardizer_enhanced.py:94`：验证 `"城市快速路"` 标准化成功。
- `TestRoadTypeStandardization.test_empty_returns_default`，`tests/test_standardizer_enhanced.py:100`：验证空道路类型输入走 default。
- `TestRoadTypeStandardization.test_english_local`，`tests/test_standardizer_enhanced.py:107`：验证 `"local road"` 标准化成功。
- `TestPasquillStabilityMapping.test_pasquill_letter`，`tests/test_standardizer_enhanced.py:134`：验证 Pasquill A-F 字母映射到内部稳定度编码。
- `TestPasquillStabilityMapping.test_pasquill_class_prefix`，`tests/test_standardizer_enhanced.py:141`：验证 `"Pasquill C"` 映射。
- `TestPasquillStabilityMapping.test_class_prefix`，`tests/test_standardizer_enhanced.py:148`：验证 `"class D"` 映射。
- `TestPasquillStabilityMapping.test_existing_codes_still_work`，`tests/test_standardizer_enhanced.py:155`：验证现有内部稳定度编码仍能直通。
- `TestPasquillStabilityMapping.test_existing_aliases_still_work`，`tests/test_standardizer_enhanced.py:164`：验证 `"very stable"` / `"不稳定"` 等旧别名仍可映射。
- `TestExecutorStandardizationRecords.test_standardize_returns_tuple`，`tests/test_standardizer_enhanced.py:178`：验证 `_standardize_arguments()` 返回 `(args, records)` 二元组。
- `TestExecutorStandardizationRecords.test_season_standardized`，`tests/test_standardizer_enhanced.py:192`：验证 executor 层会记录 season 标准化。
- `TestExecutorStandardizationRecords.test_road_type_standardized`，`tests/test_standardizer_enhanced.py:205`：验证 executor 层会记录 road_type 标准化。
- `TestExecutorStandardizationRecords.test_abstain_raises_with_suggestions`，`tests/test_standardizer_enhanced.py:219`：验证未知车型在 executor 层抛出带建议的 `StandardizationError`。

### 9.3 `tests/test_standardization_engine.py`

- `TestEngineRuleBackendParity.test_vehicle_type_exact`，`tests/test_standardization_engine.py:35`：验证 engine 对 `vehicle_type` exact 结果与 legacy standardizer 一致。
- `TestEngineRuleBackendParity.test_vehicle_type_alias_chinese`，`tests/test_standardization_engine.py:41`：验证 engine 对中文车型别名结果与 legacy 一致。
- `TestEngineRuleBackendParity.test_vehicle_type_fuzzy`，`tests/test_standardization_engine.py:47`：验证 engine 对车型 fuzzy 结果与 legacy 一致。
- `TestEngineRuleBackendParity.test_pollutant_exact`，`tests/test_standardization_engine.py:53`：验证 engine 对污染物 exact 结果与 legacy 一致。
- `TestEngineRuleBackendParity.test_pollutant_alias_chinese`，`tests/test_standardization_engine.py:59`：验证 engine 对中文污染物别名结果与 legacy 一致。
- `TestEngineRuleBackendParity.test_season_default`，`tests/test_standardization_engine.py:65`：验证 engine 对未知 season 的 default 行为与 legacy 一致。
- `TestEngineRuleBackendParity.test_stability_pasquill_c`，`tests/test_standardization_engine.py:71`：验证 engine 对稳定度 `"C"` 的结果与 legacy 一致。
- `TestEngineRuleBackendParity.test_meteorology_preset`，`tests/test_standardization_engine.py:77`：验证 engine 对气象预设 alias 的结果与 legacy 一致。
- `TestEngineRuleBackendParity.test_meteorology_sfc_passthrough`，`tests/test_standardization_engine.py:83`：验证 `.sfc` 路径 passthrough。
- `TestEngineRuleBackendParity.test_meteorology_custom_passthrough`，`tests/test_standardization_engine.py:89`：验证 `"custom"` passthrough。
- `TestEngineRuleBackendParity.test_abstain_with_suggestions`，`tests/test_standardization_engine.py:95`：验证未知车型返回 abstain 且带建议。
- `TestEngineRuleBackendParity.test_all_existing_test_cases_pass`，`tests/test_standardization_engine.py:101`：验证一组 legacy case 在 engine 中逐项保持一致。
- `TestEngineLLMBackend.test_llm_fires_when_rules_fail`，`tests/test_standardization_engine.py:131`：验证规则失败时触发 LLM fallback。
- `TestEngineLLMBackend.test_llm_skipped_when_rules_succeed`，`tests/test_standardization_engine.py:143`：验证规则成功时不会调用 LLM。
- `TestEngineLLMBackend.test_llm_failure_falls_through_to_abstain`，`tests/test_standardization_engine.py:157`：验证 LLM 抛异常后落回 abstain。
- `TestEngineLLMBackend.test_llm_timeout_falls_through`，`tests/test_standardization_engine.py:164`：验证 LLM timeout 后落回 abstain。
- `TestEngineLLMBackend.test_llm_invalid_response_ignored`，`tests/test_standardization_engine.py:171`：验证 LLM 返回非法 payload 时被忽略。
- `TestEngineLLMBackend.test_llm_returns_value_not_in_candidates`，`tests/test_standardization_engine.py:178`：验证 LLM 返回不在候选中的值时被忽略。
- `TestEngineLLMBackend.test_llm_confidence_capped`，`tests/test_standardization_engine.py:189`：验证 LLM confidence 被上限裁剪到 0.95。
- `TestEngineLLMBackend.test_llm_disabled_skips_llm`，`tests/test_standardization_engine.py:200`：验证配置关闭 LLM 后 backend 不会被调用。
- `TestEngineLLMBackend.test_llm_backend_diesel_truck`，`tests/test_standardization_engine.py:218`：验证 LLM 可把 `"柴油大卡车"` 归一到长途组合货车。
- `TestEngineLLMBackend.test_llm_backend_tesla_model3`，`tests/test_standardization_engine.py:230`：验证 LLM 可把 `"Tesla Model 3"` 归一到乘用车。
- `TestEngineBatchStandardization.test_batch_mixed_params`，`tests/test_standardization_engine.py:246`：验证 batch 混合参数时只标准化已注册参数并记录记录。
- `TestEngineBatchStandardization.test_batch_records_format`，`tests/test_standardization_engine.py:263`：验证 batch 记录字段格式。
- `TestEngineBatchStandardization.test_batch_passthrough_numeric`，`tests/test_standardization_engine.py:273`：验证数值参数 passthrough。
- `TestEngineBatchStandardization.test_batch_pollutant_list`，`tests/test_standardization_engine.py:282`：验证污染物列表逐项标准化。
- `TestEngineBatchStandardization.test_batch_raises_on_abstain`，`tests/test_standardization_engine.py:296`：验证 batch 遇到 abstain 抛 `BatchStandardizationError`。
- `TestEngineConfiguration.test_default_config`，`tests/test_standardization_engine.py:310`：验证默认配置可正确标准化污染物。
- `TestEngineConfiguration.test_llm_disabled_config`，`tests/test_standardization_engine.py:316`：验证配置禁用 LLM 后 `_is_llm_enabled_for()` 为假。
- `TestEngineConfiguration.test_custom_fuzzy_threshold`，`tests/test_standardization_engine.py:320`：验证自定义 fuzzy threshold 会改变匹配结果。
- `TestDeclarativeRegistry.test_all_known_params_registered`，`tests/test_standardization_engine.py:332`：验证注册表包含所有已知标准化参数名。
- `TestDeclarativeRegistry.test_unregistered_param_passthrough`，`tests/test_standardization_engine.py:344`：验证未注册参数 batch passthrough。
- `TestDeclarativeRegistry.test_register_new_param`，`tests/test_standardization_engine.py:350`：验证可动态注册新参数类型并参与标准化。

### 9.4 `tests/test_parameter_negotiation.py`

- `test_parse_parameter_negotiation_reply_supports_index_and_label_and_none`，`tests/test_parameter_negotiation.py:47`：验证协商回复支持序号、标签和“都不对”三类输入。
- `test_reply_looks_like_confirmation_attempt_is_bounded`，`tests/test_parameter_negotiation.py:69`：验证 bounded reply 识别不会把普通追问误判为确认。
- `test_low_confidence_llm_match_raises_negotiation_eligible_batch_error`，`tests/test_parameter_negotiation.py:78`：验证低置信度 LLM 匹配会抛出可协商的 batch 错误。
- `test_high_confidence_alias_auto_accepts_without_negotiation`，`tests/test_parameter_negotiation.py:104`：验证高置信度 alias 命中可直接接受。
- `test_resolve_candidate_value_handles_display_label_and_alias`，`tests/test_parameter_negotiation.py:122`：验证 `resolve_candidate_value()` 能解析展示标签和 alias。

### 9.5 `evaluation/eval_normalization.py` 完整代码

来源：`evaluation/eval_normalization.py`，`L1-L160`。

```python
"""Evaluate executor-layer parameter normalization."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.executor import StandardizationError, ToolExecutor
from evaluation.utils import (
    compare_expected_subset,
    classify_failure,
    classify_recoverability,
    load_jsonl,
    now_ts,
    runtime_overrides,
    safe_div,
    write_json,
    write_jsonl,
)
from services.standardizer import get_standardizer

SEASON_ALLOWED = {"春季", "夏季", "秋季", "冬季"}
ROAD_TYPE_ALLOWED = {"快速路", "地面道路"}


def _check_param_legality(arguments: Dict[str, Any]) -> Dict[str, bool]:
    standardizer = get_standardizer()
    legal = {}

    vehicle = arguments.get("vehicle_type")
    legal["vehicle_type"] = vehicle is None or standardizer.standardize_vehicle(str(vehicle)) is not None

    pollutants = arguments.get("pollutants", [])
    if isinstance(pollutants, list):
        legal["pollutants"] = all(standardizer.standardize_pollutant(str(item)) is not None for item in pollutants)
    else:
        legal["pollutants"] = False

    if "season" in arguments:
        legal["season"] = arguments.get("season") in SEASON_ALLOWED
    if "road_type" in arguments:
        legal["road_type"] = arguments.get("road_type") in ROAD_TYPE_ALLOWED
    if "model_year" in arguments:
        year = arguments.get("model_year")
        legal["model_year"] = isinstance(year, int) and 1995 <= year <= 2025

    return legal


def run_normalization_evaluation(
    samples_path: Path,
    output_dir: Path,
    enable_executor_standardization: bool = True,
) -> Dict[str, Any]:
    samples = load_jsonl(samples_path)
    output_dir.mkdir(parents=True, exist_ok=True)
    logs: List[Dict[str, Any]] = []
    field_total = 0
    field_matched = 0
    sample_success = 0
    legal_success = 0

    with runtime_overrides(enable_executor_standardization=enable_executor_standardization):
        executor = ToolExecutor()

        for sample in samples:
            raw_args = dict(sample["raw_arguments"])
            expected = sample["expected_standardized"]
            expected_success = bool(sample.get("expected_success", True))
            error_message = None
            actual_args = None
            actual_success = True
            try:
                actual_args = executor._standardize_arguments(sample["tool_name"], raw_args)
            except StandardizationError as exc:
                actual_success = False
                error_message = str(exc)
                actual_args = {}

            comparison = compare_expected_subset(actual_args, expected)
            legality = _check_param_legality(actual_args)
            field_total += len(sample.get("focus_params", []))
            for param in sample.get("focus_params", []):
                detail = comparison["details"].get(param)
                if detail and detail.get("matched"):
                    field_matched += 1

            sample_matched = (actual_success == expected_success) and comparison["matched"]
            sample_success += int(sample_matched)
            legal_success += int(all(legality.values()) if legality else False)

            record = {
                "sample_id": sample["sample_id"],
                "tool_name": sample["tool_name"],
                "input": raw_args,
                "expected_success": expected_success,
                "actual_success": actual_success,
                "expected_standardized": expected,
                "actual_standardized": actual_args,
                "comparison": comparison,
                "legality": legality,
                "success": sample_matched,
                "error": error_message,
                "error_type": None if sample_matched else "standardization",
            }
            failure_type = classify_failure(record)
            record["failure_type"] = failure_type
            record["recoverability"] = classify_recoverability(failure_type)
            logs.append(record)

    metrics = {
        "task": "normalization",
        "samples": len(samples),
        "sample_accuracy": round(safe_div(sample_success, len(samples)), 4),
        "field_accuracy": round(safe_div(field_matched, field_total), 4),
        "parameter_legal_rate": round(safe_div(legal_success, len(samples)), 4),
        "executor_standardization_enabled": enable_executor_standardization,
        "logs_path": str(output_dir / "normalization_logs.jsonl"),
    }

    write_jsonl(output_dir / "normalization_logs.jsonl", logs)
    write_json(output_dir / "normalization_metrics.json", metrics)
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate executor-layer normalization.")
    parser.add_argument(
        "--samples",
        type=Path,
        default=PROJECT_ROOT / "evaluation/normalization/samples.jsonl",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PROJECT_ROOT / f"evaluation/logs/normalization_{now_ts()}",
    )
    parser.add_argument(
        "--disable-executor-standardization",
        action="store_true",
        help="Bypass executor-layer parameter normalization.",
    )
    args = parser.parse_args()

    metrics = run_normalization_evaluation(
        samples_path=args.samples,
        output_dir=args.output_dir,
        enable_executor_standardization=not args.disable_executor_standardization,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
```

### 9.6 评估脚本当前状态补充

- `run_normalization_evaluation()` 里 `actual_args = executor._standardize_arguments(sample["tool_name"], raw_args)` 直接接收 `_standardize_arguments()` 返回值，位置在 `evaluation/eval_normalization.py:79-80`；而 `_standardize_arguments()` 当前定义返回 `tuple[Dict[str, Any], List[Dict[str, Any]]]`，定义在 `core/executor.py:317-354`。
- `ROAD_TYPE_ALLOWED = {"快速路", "地面道路"}` 位于 `evaluation/eval_normalization.py:28-29`；而 `config/unified_mappings.yaml:289-323` 当前 `road_types` 条目为 `快速路`、`高速公路`、`主干道`、`次干道`、`支路`。

---

## 自检

- [x] 所有标准化相关文件已列出且说明了互相引用关系
- [x] UnifiedStandardizer 所有方法的完整代码已贴出
- [x] StandardizationEngine 的调用链已完整追踪
- [x] shared/standardizer/ 的现状、引用情况、与 services/ 的重叠已说明
- [x] unified_mappings.yaml 结构已完整描述
- [x] 系统中所有标准化调用点已列出
- [x] 本地模型相关代码已完整贴出
- [x] 参数协商完整流程已贴出
- [x] 现有测试和评估脚本已说明

