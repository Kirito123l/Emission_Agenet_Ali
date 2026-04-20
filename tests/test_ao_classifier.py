import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from config import get_config, reset_config
from core.analytical_objective import AORelationship, AOStatus
from core.ao_classifier import AOClassType, OAScopeClassifier
from core.ao_manager import AOManager
from core.memory import FactMemory
from core.task_state import ContinuationDecision, TaskState


class AsyncMockLLM:
    def __init__(self, payload=None, error=None):
        self.payload = payload or {}
        self.error = error
        self.calls = []

    async def chat_json(self, *, messages, system=None, temperature=None):
        self.calls.append({"messages": messages, "system": system, "temperature": temperature})
        if self.error is not None:
            raise self.error
        return self.payload


def _make_classifier(*, llm_payload=None, llm_error=None):
    reset_config()
    config = get_config()
    memory = FactMemory(session_id="cls-session")
    manager = AOManager(memory)
    llm = AsyncMockLLM(payload=llm_payload, error=llm_error)
    classifier = OAScopeClassifier(manager, llm, config)
    return classifier, manager, memory, llm


@pytest.mark.anyio
async def test_rule_layer_hits_active_input_completion():
    classifier, manager, _memory, _llm = _make_classifier()
    manager.create_ao("算排放", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState()
    state.active_input_completion = SimpleNamespace(request_id="r1")

    result = await classifier.classify("冬天", [], state)

    assert result.classification == AOClassType.CONTINUATION
    assert result.layer == "rule"


@pytest.mark.anyio
async def test_rule_layer_first_message_is_new_ao_without_llm():
    classifier, _manager, _memory, llm = _make_classifier()

    result = await classifier.classify("查询2020年网约车的CO2排放因子", [], TaskState())

    assert result.classification == AOClassType.NEW_AO
    assert result.layer == "rule"
    assert result.reasoning == "first_message_in_session"
    assert len(llm.calls) == 0


@pytest.mark.anyio
async def test_rule_layer_hits_active_parameter_negotiation():
    classifier, manager, _memory, _llm = _make_classifier()
    manager.create_ao("算排放", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState()
    state.active_parameter_negotiation = SimpleNamespace(request_id="r2")

    result = await classifier.classify("第一个", [], state)

    assert result.classification == AOClassType.CONTINUATION
    assert result.reasoning == "active_parameter_negotiation"


@pytest.mark.anyio
async def test_rule_layer_no_active_ao_without_revision_signal_is_new_ao():
    classifier, manager, _memory, llm = _make_classifier()
    ao = manager.create_ao("查 CO2 因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.status = AOStatus.COMPLETED
    manager._memory.current_ao_id = None

    result = await classifier.classify("再查一个 NOx 排放因子", [], TaskState())

    assert result.classification == AOClassType.NEW_AO
    assert result.layer == "rule"
    assert result.reasoning == "no_active_ao_no_revision_signal"
    assert len(llm.calls) == 0


@pytest.mark.anyio
async def test_rule_layer_hits_continuation_pending():
    classifier, manager, _memory, _llm = _make_classifier()
    manager.create_ao("算排放并扩散", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState()
    state.set_continuation_decision(
        ContinuationDecision(
            residual_plan_exists=True,
            continuation_ready=True,
            should_continue=True,
            next_tool_name="calculate_dispersion",
        )
    )

    result = await classifier.classify("继续", [], state)

    assert result.classification == AOClassType.CONTINUATION
    assert result.reasoning == "continuation_pending"


@pytest.mark.anyio
async def test_rule_layer_hits_short_clarification_reply():
    classifier, manager, _memory, _llm = _make_classifier()
    manager.create_ao("算排放", AORelationship.INDEPENDENT, current_turn=1)

    result = await classifier.classify("冬季", [], TaskState())

    assert result.classification == AOClassType.CONTINUATION
    assert result.reasoning == "short_clarification"


@pytest.mark.anyio
async def test_rule_layer_hits_pure_file_upload_waiting_for_file():
    classifier, manager, _memory, _llm = _make_classifier()
    manager.create_ao("分析这个文件", AORelationship.INDEPENDENT, current_turn=1)
    state = TaskState()
    state.active_input_completion = SimpleNamespace(request_id="file")

    result = await classifier.classify(
        "\n\n文件已上传，路径: /tmp/a.csv\n请使用 input_file 参数处理此文件。",
        [],
        state,
    )

    assert result.classification == AOClassType.CONTINUATION


@pytest.mark.anyio
async def test_rule_layer_miss_uses_llm_layer():
    classifier, manager, _memory, llm = _make_classifier(
        llm_payload={
            "classification": "NEW_AO",
            "target_ao_id": None,
            "reference_ao_id": None,
            "new_objective_text": "新任务",
            "confidence": 0.9,
            "reasoning": "new goal",
        }
    )
    manager.create_ao("旧任务", AORelationship.INDEPENDENT, current_turn=1)

    result = await classifier.classify("顺便再查一个 CO2", [], TaskState())

    assert result.classification == AOClassType.NEW_AO
    assert result.layer == "llm"
    assert len(llm.calls) == 1


@pytest.mark.anyio
async def test_revision_signal_does_not_hit_new_ao_fast_path():
    classifier, manager, _memory, llm = _make_classifier(
        llm_payload={
            "classification": "REVISION",
            "target_ao_id": "AO#1",
            "reference_ao_id": None,
            "new_objective_text": "改成冬季再算",
            "confidence": 0.9,
            "reasoning": "revision",
        }
    )
    ao = manager.create_ao("查 CO2 因子", AORelationship.INDEPENDENT, current_turn=1)
    ao.status = AOStatus.COMPLETED
    manager._memory.current_ao_id = None

    result = await classifier.classify("改成冬季再算", [], TaskState())

    assert result.classification != AOClassType.NEW_AO or result.reasoning != "no_active_ao_no_revision_signal"


@pytest.mark.anyio
async def test_low_confidence_llm_falls_back():
    classifier, manager, _memory, _llm = _make_classifier(
        llm_payload={
            "classification": "CONTINUATION",
            "confidence": 0.2,
            "reasoning": "low confidence",
        }
    )
    manager.create_ao("旧任务", AORelationship.INDEPENDENT, current_turn=1)

    result = await classifier.classify("do something", [], TaskState())

    assert result.classification == AOClassType.NEW_AO
    assert result.layer == "fallback"


@pytest.mark.anyio
async def test_llm_error_falls_back():
    classifier, manager, _memory, _llm = _make_classifier(llm_error=TimeoutError("timeout"))
    manager.create_ao("旧任务", AORelationship.INDEPENDENT, current_turn=1)

    result = await classifier.classify("do something", [], TaskState())

    assert result.classification == AOClassType.NEW_AO
    assert result.layer == "fallback"


def test_short_reply_detection_variants():
    classifier, manager, _memory, _llm = _make_classifier()
    manager.create_ao("算排放", AORelationship.INDEPENDENT, current_turn=1)

    assert classifier._is_short_clarification_reply("冬季") is True
    assert classifier._is_short_clarification_reply("确认") is True
    assert classifier._is_short_clarification_reply("按刚才的") is True
    assert classifier._is_short_clarification_reply("这是一个很长的新任务描述，需要重新分析整个文件") is False


def test_pure_file_upload_detection():
    classifier, _manager, _memory, _llm = _make_classifier()

    assert classifier._is_pure_file_upload("\n\n文件已上传，路径: /tmp/a.csv\n请使用 input_file 参数处理此文件。") is True
    assert classifier._is_pure_file_upload("帮我分析\n\n文件已上传，路径: /tmp/a.csv\n请使用 input_file 参数处理此文件。") is False


@pytest.mark.anyio
async def test_manual_case_accuracy_at_least_thirteen_of_fifteen():
    cases_path = Path(__file__).resolve().parent / "ao_classifier_manual_cases.jsonl"
    lines = [
        json.loads(line)
        for line in cases_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    correct = 0

    for case in lines:
        reset_config()
        config = get_config()
        memory = FactMemory(session_id="manual-session")
        manager = AOManager(memory)
        for ao_payload in case.get("ao_history", []):
            relationship = AORelationship(ao_payload.get("relationship", "independent"))
            ao = manager.create_ao(
                ao_payload.get("objective_text", ""),
                relationship,
                parent_ao_id=ao_payload.get("parent_ao_id"),
                current_turn=ao_payload.get("start_turn", 1),
            )
            ao.status = getattr(ao.status.__class__, ao_payload.get("status", "ACTIVE").upper())
            ao.end_turn = ao_payload.get("end_turn")
        if case.get("current_ao_id"):
            memory.current_ao_id = case["current_ao_id"]

        llm = AsyncMockLLM(payload=case.get("llm_payload", {}))
        classifier = OAScopeClassifier(manager, llm, config)
        state = TaskState()
        if case.get("active_input_completion"):
            state.active_input_completion = SimpleNamespace(request_id="input")
        if case.get("active_parameter_negotiation"):
            state.active_parameter_negotiation = SimpleNamespace(request_id="negotiation")
        if case.get("continuation_pending"):
            state.set_continuation_decision(
                ContinuationDecision(
                    residual_plan_exists=True,
                    continuation_ready=True,
                    should_continue=True,
                    next_tool_name="next_tool",
                )
            )

        result = await classifier.classify(
            case["user_message"],
            case.get("recent_conversation", []),
            state,
        )
        if result.classification.value == case["expected_classification"]:
            correct += 1

    assert correct >= 13
