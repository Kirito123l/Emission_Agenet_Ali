"""
Specialized smoke script for knowledge/RAG asset wiring.

This path stays useful for verifying local knowledge-index availability and tool
registration, but it is not the main app entrypoint.
"""
import sys
import logging
from pathlib import Path

# Setup logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

def test_knowledge_tool_import():
    """Test if knowledge tool can be imported"""
    try:
        from tools.knowledge import KnowledgeTool
        logger.info("✅ KnowledgeTool imported successfully")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to import KnowledgeTool: {e}")
        return False

def test_tool_registration():
    """Test if knowledge tool is registered"""
    try:
        from tools.registry import init_tools, get_registry

        # Initialize tools
        init_tools()

        # Get registry
        registry = get_registry()
        tools = registry.list_tools()

        logger.info(f"Registered tools: {tools}")

        if "query_knowledge" in tools:
            logger.info("✅ query_knowledge tool is registered")
            return True
        else:
            logger.error("❌ query_knowledge tool is NOT registered")
            return False

    except Exception as e:
        logger.error(f"❌ Failed to test tool registration: {e}")
        return False

def test_knowledge_base_files():
    """Test if knowledge base files exist"""
    base_dir = PROJECT_ROOT / "skills" / "knowledge" / "index"

    faiss_file = base_dir / "dense_index.faiss"
    chunks_file = base_dir / "chunks.jsonl"

    results = []

    if faiss_file.exists():
        logger.info(f"✅ FAISS index found: {faiss_file}")
        results.append(True)
    else:
        logger.error(f"❌ FAISS index NOT found: {faiss_file}")
        results.append(False)

    if chunks_file.exists():
        logger.info(f"✅ Chunks file found: {chunks_file}")
        results.append(True)
    else:
        logger.error(f"❌ Chunks file NOT found: {chunks_file}")
        results.append(False)

    return all(results)

def test_tool_definition():
    """Test if query_knowledge is in tool definitions"""
    try:
        from tools.definitions import TOOL_DEFINITIONS

        tool_names = [t["function"]["name"] for t in TOOL_DEFINITIONS]
        logger.info(f"Tool definitions: {tool_names}")

        if "query_knowledge" in tool_names:
            logger.info("✅ query_knowledge is in tool definitions")
            return True
        else:
            logger.error("❌ query_knowledge is NOT in tool definitions")
            return False

    except Exception as e:
        logger.error(f"❌ Failed to test tool definitions: {e}")
        return False

def main():
    """Run all tests"""
    logger.info("=" * 60)
    logger.info("RAG Integration Test")
    logger.info("=" * 60)

    tests = [
        ("Knowledge Tool Import", test_knowledge_tool_import),
        ("Knowledge Base Files", test_knowledge_base_files),
        ("Tool Definition", test_tool_definition),
        ("Tool Registration", test_tool_registration),
    ]

    results = []
    for name, test_func in tests:
        logger.info(f"\n--- Testing: {name} ---")
        result = test_func()
        results.append((name, result))

    # Summary
    logger.info("\n" + "=" * 60)
    logger.info("Test Summary")
    logger.info("=" * 60)

    for name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        logger.info(f"{status}: {name}")

    all_passed = all(r for _, r in results)

    if all_passed:
        logger.info("\n🎉 All tests passed! RAG integration is complete.")
        return 0
    else:
        logger.error("\n⚠️ Some tests failed. Please check the errors above.")
        return 1

if __name__ == "__main__":
    sys.exit(main())
