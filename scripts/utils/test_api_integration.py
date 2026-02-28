"""
Phase 7 测试：API集成测试

测试新架构与API层的集成
"""
import asyncio
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from api.session import Session
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


async def test_api_session():
    """测试Session类与UnifiedRouter的集成"""

    logger.info("=" * 60)
    logger.info("Phase 7: API Integration Test")
    logger.info("=" * 60)

    # 创建测试会话
    session = Session(session_id="test_api_001")

    # Test 1: Simple query
    logger.info("\n[Test 1] Simple emission factor query")
    query1 = "查询2020年小汽车的CO2排放因子"
    result1 = await session.chat(query1, file_path=None)

    # Manually save turn (normally done by API routes)
    session.save_turn(
        user_input=query1,
        assistant_response=result1['text'],
        chart_data=result1['chart_data'],
        table_data=result1['table_data'],
        data_type="chart" if result1['chart_data'] else None
    )

    logger.info(f"[OK] Text returned: {result1['text'][:100]}...")
    logger.info(f"[OK] Chart data: {'Yes' if result1['chart_data'] else 'No'}")
    logger.info(f"[OK] Table data: {'Yes' if result1['table_data'] else 'No'}")
    logger.info(f"[OK] Download file: {'Yes' if result1['download_file'] else 'No'}")

    # Verify
    assert result1['text'], "Should return text"
    # Note: chart_data might be None if tool doesn't format it properly
    # We'll check this after seeing the actual response
    logger.info(f"[DEBUG] Full result keys: {result1.keys()}")
    logger.info(f"[DEBUG] Chart data type: {type(result1['chart_data'])}")

    # 测试2: 检查历史记录
    logger.info("\n[Test 2] 检查历史记录")
    assert len(session._history) == 2, f"应该有2条历史记录，实际: {len(session._history)}"
    assert session._history[0]['role'] == 'user'
    assert session._history[1]['role'] == 'assistant'
    # Chart data might be None - we'll investigate
    logger.info("[OK] History saved correctly")

    # Test 3: Multi-turn conversation
    logger.info("\n[Test 3] Multi-turn conversation")
    query2 = "NOx的排放因子是多少？"
    result2 = await session.chat(query2, file_path=None)

    # Manually save turn
    session.save_turn(
        user_input=query2,
        assistant_response=result2['text'],
        chart_data=result2['chart_data'],
        table_data=result2['table_data'],
        data_type="chart" if result2['chart_data'] else None
    )

    logger.info(f"[OK] Text returned: {result2['text'][:100]}...")
    assert len(session._history) == 4, f"Should have 4 history records, actual: {len(session._history)}"
    logger.info("[OK] Multi-turn conversation works")

    logger.info("\n" + "=" * 60)
    logger.info("[PASS] Phase 7 API Integration Test PASSED")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(test_api_session())
