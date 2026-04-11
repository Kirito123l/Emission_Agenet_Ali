"""Layered memory regression tests for WP-CONV-3."""

from core.memory import MemoryManager, SummarySegment


def test_memory_manager_builds_mid_term_summaries_and_long_term_facts(tmp_path):
    memory = MemoryManager("layered-memory", storage_dir=tmp_path)

    memory.update("你好", "你好，我可以帮你分析。")
    memory.update(
        "请计算排放",
        "已完成宏观排放计算。",
        tool_calls=[
            {
                "name": "calculate_macro_emission",
                "arguments": {"vehicle_type": "Passenger Car", "pollutants": ["CO2"], "model_year": 2020},
                "result": {
                    "success": True,
                    "summary": "L1 路段排放最高。",
                    "data": {
                        "summary": {"total_emissions": {"CO2": 12.3}},
                        "pollutants": ["CO2"],
                    },
                },
            }
        ],
    )
    memory.update("把车型改成公交车", "好的，改成公交车。")

    fact_memory = memory.get_fact_memory()
    assert fact_memory["last_tool_name"] == "calculate_macro_emission"
    assert fact_memory["session_topic"] == "macro_emission"
    assert "calculate_macro_emission" in fact_memory["cumulative_tools_used"]
    assert fact_memory["user_corrections"]
    assert memory.mid_term_memory
    assert memory.mid_term_memory[-1].start_turn == 1
    assert memory.mid_term_memory[-1].end_turn == 3


def test_build_context_for_prompt_is_bounded_and_excludes_raw_spatial_payloads(tmp_path):
    memory = MemoryManager("bounded-context", storage_dir=tmp_path)
    memory.fact_memory.session_topic = "dispersion"
    memory.fact_memory.last_tool_summary = "热点集中在交叉口附近。"
    memory.fact_memory.last_spatial_data = {
        "raster_grid": {"matrix_mean": [[1] * 100 for _ in range(100)]},
    }
    memory.fact_memory.key_findings = ["发现 1", "发现 2"]
    for idx in range(1, 8):
        memory.mid_term_memory.append(
            SummarySegment(
                start_turn=idx,
                end_turn=idx,
                summary=f"摘要 {idx}" * 50,
            )
        )

    context = memory.build_context_for_prompt(max_chars=500)

    assert len(context) <= 500
    assert "Session topic: dispersion" in context
    assert "Key findings:" in context
    assert "raster_grid" not in context
    assert "matrix_mean" not in context


def test_build_conversational_messages_uses_bounded_short_term_history(tmp_path):
    memory = MemoryManager("chat-history", storage_dir=tmp_path)
    for idx in range(8):
        memory.update(f"user-{idx}", "a" * 2000)

    messages = memory.build_conversational_messages("current question")

    assert messages[-1] == {"role": "user", "content": "current question"}
    assert len(messages) == 11
    assert messages[1]["content"].endswith("...(truncated)")


def test_memory_manager_persists_layered_fields(tmp_path):
    memory = MemoryManager("persisted-memory", storage_dir=tmp_path)
    memory.update("hello", "world")
    memory.fact_memory.session_topic = "knowledge_qa"
    memory.fact_memory.user_language_preference = "mixed"
    memory.fact_memory.key_findings = ["finding"]
    memory.mid_term_memory = []
    memory.update("NOx 是什么", "NOx 是氮氧化物。")

    restored = MemoryManager("persisted-memory", storage_dir=tmp_path)

    fact_memory = restored.get_fact_memory()
    assert fact_memory["session_topic"] == "knowledge_qa"
    assert fact_memory["user_language_preference"] == "mixed"
    assert fact_memory["key_findings"] == ["finding"]
    assert restored.turn_counter >= 2
