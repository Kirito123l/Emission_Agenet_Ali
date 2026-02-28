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
