"""Conservative conversation-intent classifier tests."""

from core.conversation_intent import ConversationIntent, ConversationIntentClassifier


def test_classifier_allows_simple_chitchat_fast_path():
    result = ConversationIntentClassifier().classify("你好")

    assert result.intent == ConversationIntent.CHITCHAT
    assert result.fast_path_allowed is True


def test_classifier_allows_result_explanation_when_prior_result_exists():
    result = ConversationIntentClassifier().classify(
        "解释一下刚才的结果",
        has_last_tool_name=True,
    )

    assert result.intent == ConversationIntent.EXPLAIN_RESULT
    assert result.fast_path_allowed is True


def test_classifier_allows_knowledge_question_without_task_cues():
    result = ConversationIntentClassifier().classify("PM2.5 是什么")

    assert result.intent == ConversationIntent.KNOWLEDGE_QA
    assert result.fast_path_allowed is True


def test_classifier_blocks_fast_path_when_active_negotiation_exists():
    result = ConversationIntentClassifier().classify(
        "你好",
        has_active_negotiation=True,
    )

    assert result.intent == ConversationIntent.CHITCHAT
    assert result.fast_path_allowed is False
    assert "active_parameter_negotiation" in result.blocking_signals


def test_classifier_blocks_fast_path_when_file_relationship_clarification_exists():
    result = ConversationIntentClassifier().classify(
        "PM2.5 是什么",
        has_file_relationship_clarification=True,
    )

    assert result.intent == ConversationIntent.KNOWLEDGE_QA
    assert result.fast_path_allowed is False
    assert "file_relationship_clarification" in result.blocking_signals


def test_classifier_routes_output_mode_requests_back_to_state_loop():
    result = ConversationIntentClassifier().classify(
        "帮我可视化一下",
        has_last_tool_name=True,
        has_active_file=True,
    )

    assert result.intent == ConversationIntent.CONTINUE_TASK
    assert result.fast_path_allowed is False
    assert "output_mode_request" in result.blocking_signals


def test_classifier_treats_confirmation_like_reply_as_non_fast_path():
    result = ConversationIntentClassifier().classify("1")

    assert result.intent == ConversationIntent.CONFIRM
    assert result.fast_path_allowed is False


def test_classifier_blocks_explanation_fast_path_when_residual_workflow_exists():
    result = ConversationIntentClassifier().classify(
        "解释一下刚才的结果",
        has_last_tool_name=True,
        has_residual_workflow=True,
    )

    assert result.intent == ConversationIntent.EXPLAIN_RESULT
    assert result.fast_path_allowed is False
    assert "residual_workflow" in result.blocking_signals
