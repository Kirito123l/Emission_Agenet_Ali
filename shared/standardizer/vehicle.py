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
