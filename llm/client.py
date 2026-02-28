import json
import re
import logging
import httpx
from typing import Dict, List, Any, Optional
from openai import OpenAI
from openai import APIConnectionError
from config import get_config

logger = logging.getLogger(__name__)

class LLMClient:
    def __init__(self, assignment, purpose: str):
        config = get_config()
        provider = config.providers[assignment.provider]
        self.assignment = assignment
        self._api_key = provider["api_key"]
        self._base_url = provider["base_url"]
        self._proxy = config.https_proxy or config.http_proxy
        self._timeout = 60.0

        self._client_proxy = self._create_client(use_proxy=True) if self._proxy else None
        self._client_direct = self._create_client(use_proxy=False)
        self.client = self._client_proxy or self._client_direct

    def _create_client(self, use_proxy: bool) -> OpenAI:
        if not self._api_key:
            raise ValueError(
                "LLM API key not configured. "
                "Please set QWEN_API_KEY environment variable."
            )
        http_client = None
        if use_proxy and self._proxy:
            http_client = httpx.Client(proxy=self._proxy, timeout=self._timeout)
            logging.info(f"使用代理: {self._proxy}")
        return OpenAI(
            api_key=self._api_key,
            base_url=self._base_url,
            http_client=http_client
        )

    @staticmethod
    def _is_connection_error(exc: Exception) -> bool:
        if isinstance(exc, (APIConnectionError, httpx.ConnectError, httpx.ReadTimeout, httpx.ConnectTimeout)):
            return True
        text = str(exc).lower()
        return any(k in text for k in ["connection error", "unexpected eof", "ssl", "tls", "timed out"])

    def _request_with_failover(self, request_fn, op_name: str):
        clients = []
        if self.client is self._client_proxy and self._client_proxy:
            clients = [("proxy", self._client_proxy), ("direct", self._client_direct)]
        else:
            clients = [("direct", self._client_direct)]
            if self._client_proxy:
                clients.append(("proxy", self._client_proxy))

        last_error = None
        for mode, c in clients:
            try:
                resp = request_fn(c)
                self.client = c
                if mode == "direct" and self._client_proxy:
                    logger.warning(f"{op_name}: 已切换到直连模式")
                return resp
            except Exception as e:
                last_error = e
                if self._is_connection_error(e):
                    logger.warning(f"{op_name} 经 {mode} 失败（连接问题）: {e}")
                    continue
                raise
        raise last_error if last_error else RuntimeError(f"{op_name} failed")

    def chat(self, prompt: str, system: str = None, temperature: float = None) -> str:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self._request_with_failover(
            lambda cli: cli.chat.completions.create(
                model=self.assignment.model,
                messages=messages,
                temperature=temperature or self.assignment.temperature,
                max_tokens=self.assignment.max_tokens,
            ),
            "LLM chat"
        )
        return response.choices[0].message.content

    def chat_json(self, prompt: str, system: str = None) -> Dict:
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        response = self._request_with_failover(
            lambda cli: cli.chat.completions.create(
                model=self.assignment.model,
                messages=messages,
                temperature=0.3,
                response_format={"type": "json_object"},
            ),
            "LLM chat_json"
        )
        content = response.choices[0].message.content
        return self._parse_json_response(content)

    def chat_json_with_history(self, messages: List[Dict]) -> Dict:
        response = self._request_with_failover(
            lambda cli: cli.chat.completions.create(
                model=self.assignment.model,
                messages=messages,
                temperature=0.3,
                response_format={"type": "json_object"},
            ),
            "LLM chat_json_with_history"
        )
        content = response.choices[0].message.content
        return self._parse_json_response(content)

    def _parse_json_response(self, content: str) -> Dict:
        """
        容错JSON解析

        处理常见问题：
        1. 带```json```代码块
        2. 前后有多余文字
        3. 单引号代替双引号
        4. 尾部多余逗号
        5. [skill_name: param: value] 简写格式
        """
        if not content:
            return self._default_plan_response("空响应")

        original_content = content

        # 0. 检测并转换简写格式 [skill_name: param: value]
        shorthand_match = re.match(r'\[(\w+):\s*(\w+):\s*(.+)\]', content.strip())
        if shorthand_match:
            skill_name = shorthand_match.group(1)
            param_name = shorthand_match.group(2)
            param_value = shorthand_match.group(3).strip()
            logger.info(f"检测到简写格式，转换为标准JSON: {skill_name}")
            return {
                "understanding": f"使用{skill_name}技能",
                "plan": [{
                    "skill": skill_name,
                    "params": {param_name: param_value},
                    "purpose": f"执行{skill_name}"
                }],
                "needs_clarification": False,
                "clarification_message": None
            }

        # 1. 提取```json```代码块
        json_block = re.search(r'```(?:json)?\s*([\s\S]*?)```', content)
        if json_block:
            content = json_block.group(1).strip()

        # 2. 尝试直接解析
        try:
            parsed = json.loads(content)
            # 如果解析出数组，尝试包装成标准格式
            if isinstance(parsed, list):
                logger.warning("LLM返回了数组，包装成标准格式")
                return {
                    "understanding": "执行计划",
                    "plan": parsed,
                    "needs_clarification": False
                }
            return parsed
        except json.JSONDecodeError:
            pass

        # 3. 尝试提取第一个{...}结构
        json_match = re.search(r'\{[\s\S]*\}', content)
        if json_match:
            try:
                return json.loads(json_match.group())
            except json.JSONDecodeError:
                pass

        # 4. 修复常见格式问题
        content = self._fix_json_format(content)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

        # 5. 全部失败，返回默认响应
        logger.warning(f"JSON解析失败，原始内容: {original_content[:200]}")
        return self._default_plan_response("JSON解析失败")

    def _fix_json_format(self, content: str) -> str:
        """修复常见JSON格式问题"""
        # 提取JSON部分
        json_match = re.search(r'\{[\s\S]*\}', content)
        if not json_match:
            return content

        json_str = json_match.group()

        # 修复尾部逗号: ,} -> }
        json_str = re.sub(r',\s*}', '}', json_str)
        json_str = re.sub(r',\s*]', ']', json_str)

        # 修复单引号（简单情况）
        # 注意：这个修复不完美，但能处理大多数情况
        if "'" in json_str and '"' not in json_str:
            json_str = json_str.replace("'", '"')

        return json_str

    def _default_plan_response(self, reason: str) -> Dict:
        """返回默认的plan响应"""
        return {
            "understanding": f"无法解析响应: {reason}",
            "plan": [],
            "needs_clarification": True,
            "clarification_message": "抱歉，我没有完全理解您的问题，请再说一遍或提供更多细节。"
        }

class LLMManager:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._clients = {}
        return cls._instance

    def get_client(self, purpose: str) -> LLMClient:
        if purpose not in self._clients:
            config = get_config()
            assignment_map = {
                "agent": config.agent_llm,
                "standardizer": config.standardizer_llm,
                "synthesis": config.synthesis_llm,
                "rag_refiner": config.rag_refiner_llm,
            }
            self._clients[purpose] = LLMClient(assignment_map[purpose], purpose)
        return self._clients[purpose]

def get_llm(purpose: str) -> LLMClient:
    return LLMManager().get_client(purpose)
