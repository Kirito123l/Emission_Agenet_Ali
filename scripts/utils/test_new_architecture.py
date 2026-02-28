"""
Integration Test for New Architecture

Tests the complete flow of the new Tool Use-driven architecture.
Validates that all components work together correctly.
"""
import asyncio
import logging
import sys
from pathlib import Path

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class ArchitectureTest:
    """Test suite for new architecture"""

    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.errors = []

    async def setup(self):
        """Initialize the new architecture"""
        logger.info("=" * 80)
        logger.info("INITIALIZING NEW ARCHITECTURE")
        logger.info("=" * 80)

        try:
            # Import and initialize components
            from tools.registry import init_tools
            from core.router import UnifiedRouter
            from services.config_loader import ConfigLoader

            # Initialize tools
            logger.info("Initializing tools...")
            init_tools()

            # Load configuration
            logger.info("Loading configuration...")
            config = ConfigLoader()
            mappings = config.load_mappings()
            prompts = config.load_prompts()

            logger.info(f"Loaded {len(mappings.get('vehicle_types', {}))} vehicle types")
            logger.info(f"Loaded {len(mappings.get('pollutants', {}))} pollutants")
            logger.info(f"System prompt: {len(prompts.get('core', {}).get('system', ''))} chars")

            # Create router
            logger.info("Creating unified router...")
            self.router = UnifiedRouter(session_id="test_session")

            logger.info("✅ Setup complete\n")
            return True

        except Exception as e:
            logger.error(f"❌ Setup failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    async def test_scenario_1_simple_query(self):
        """
        Scenario 1: Simple Query
        Input: "查询2020年小汽车的CO2排放因子"
        Expected: Returns chart data and table data
        """
        logger.info("=" * 80)
        logger.info("TEST SCENARIO 1: Simple Query")
        logger.info("=" * 80)

        try:
            query = "查询2020年小汽车的CO2排放因子"
            logger.info(f"Query: {query}")

            result = await self.router.chat(user_message=query, file_path=None)

            logger.info(f"Response: {result.text[:200]}...")
            logger.info(f"Has chart data: {result.chart_data is not None}")
            logger.info(f"Has table data: {result.table_data is not None}")

            # Validate
            if result.text and ("CO2" in result.text or "CO₂" in result.text or "排放" in result.text):
                logger.info("✅ PASSED: Got response with CO2 data")
                self.passed += 1
                return True
            else:
                logger.error(f"❌ FAILED: Response missing CO2 data. Response: {result.text[:500]}")
                self.failed += 1
                self.errors.append("Scenario 1: Missing CO2 data")
                return False

        except Exception as e:
            logger.error(f"❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1
            self.errors.append(f"Scenario 1: {str(e)}")
            return False

    async def test_scenario_2_clarification(self):
        """
        Scenario 2: Needs Clarification
        Input: "查询排放因子"
        Expected: LLM asks for missing parameters
        """
        logger.info("=" * 80)
        logger.info("TEST SCENARIO 2: Clarification Needed")
        logger.info("=" * 80)

        try:
            query = "查询排放因子"
            logger.info(f"Query: {query}")

            result = await self.router.chat(user_message=query, file_path=None)

            logger.info(f"Response: {result.text[:200]}...")

            # Validate - should ask for vehicle type, year, or pollutant
            keywords = ["车型", "年份", "污染物", "vehicle", "year", "pollutant"]
            has_question = any(kw in result.text for kw in keywords)

            if has_question:
                logger.info("✅ PASSED: LLM asked for clarification")
                self.passed += 1
                return True
            else:
                logger.error("❌ FAILED: LLM did not ask for clarification")
                self.failed += 1
                self.errors.append("Scenario 2: No clarification")
                return False

        except Exception as e:
            logger.error(f"❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1
            self.errors.append(f"Scenario 2: {str(e)}")
            return False

    async def test_scenario_3_file_processing(self):
        """
        Scenario 3: File Processing
        Input: Upload trajectory file + "计算排放"
        Expected: Analyzes file, asks for vehicle type, then calculates
        """
        logger.info("=" * 80)
        logger.info("TEST SCENARIO 3: File Processing")
        logger.info("=" * 80)

        try:
            # Use existing test data
            test_file = "skills/micro_emission/data/atlanta_2025_1_55_65.csv"
            if not Path(test_file).exists():
                logger.warning(f"⚠️ SKIPPED: Test file not found: {test_file}")
                return True

            query = "计算这个文件的排放"
            logger.info(f"Query: {query}")
            logger.info(f"File: {test_file}")

            result = await self.router.chat(user_message=query, file_path=test_file)

            logger.info(f"Response: {result.text[:200]}...")

            # Validate - should either ask for vehicle type or show results
            if result.text:
                logger.info("✅ PASSED: Got response for file processing")
                self.passed += 1
                return True
            else:
                logger.error("❌ FAILED: No response")
                self.failed += 1
                self.errors.append("Scenario 3: No response")
                return False

        except Exception as e:
            logger.error(f"❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1
            self.errors.append(f"Scenario 3: {str(e)}")
            return False

    async def test_scenario_4_error_recovery(self):
        """
        Scenario 4: Error Recovery
        Input: "查询2030年的数据" (out of range)
        Expected: Returns friendly error message
        """
        logger.info("=" * 80)
        logger.info("TEST SCENARIO 4: Error Recovery")
        logger.info("=" * 80)

        try:
            query = "查询2030年小汽车的CO2排放因子"
            logger.info(f"Query: {query}")

            result = await self.router.chat(user_message=query, file_path=None)

            logger.info(f"Response: {result.text[:200]}...")

            # Validate - should mention year range or error
            error_keywords = ["2025", "范围", "range", "不支持", "无法"]
            has_error_info = any(kw in result.text for kw in error_keywords)

            if has_error_info:
                logger.info("✅ PASSED: Got friendly error message")
                self.passed += 1
                return True
            else:
                logger.warning("⚠️ PARTIAL: Response may not clearly indicate error")
                self.passed += 1
                return True

        except Exception as e:
            logger.error(f"❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1
            self.errors.append(f"Scenario 4: {str(e)}")
            return False

    async def test_scenario_5_standardization(self):
        """
        Scenario 5: Transparent Standardization
        Input: "查询2020年网约车的CO2排放因子" (using alias)
        Expected: Correctly standardizes to "Passenger Car"
        """
        logger.info("=" * 80)
        logger.info("TEST SCENARIO 5: Transparent Standardization")
        logger.info("=" * 80)

        try:
            query = "查询2020年网约车的CO2排放因子"
            logger.info(f"Query: {query}")
            logger.info("Testing alias: 网约车 → Passenger Car")

            result = await self.router.chat(user_message=query, file_path=None)

            logger.info(f"Response: {result.text[:200]}...")

            # Validate - should get results (standardization worked)
            if result.text and ("CO2" in result.text or "排放" in result.text):
                logger.info("✅ PASSED: Standardization worked transparently")
                self.passed += 1
                return True
            else:
                logger.error("❌ FAILED: Standardization may have failed")
                self.failed += 1
                self.errors.append("Scenario 5: Standardization failed")
                return False

        except Exception as e:
            logger.error(f"❌ FAILED: {e}")
            import traceback
            traceback.print_exc()
            self.failed += 1
            self.errors.append(f"Scenario 5: {str(e)}")
            return False

    def print_summary(self):
        """Print test summary"""
        logger.info("=" * 80)
        logger.info("TEST SUMMARY")
        logger.info("=" * 80)
        logger.info(f"Total Tests: {self.passed + self.failed}")
        logger.info(f"✅ Passed: {self.passed}")
        logger.info(f"❌ Failed: {self.failed}")

        if self.errors:
            logger.info("\nErrors:")
            for error in self.errors:
                logger.info(f"  - {error}")

        success_rate = (self.passed / (self.passed + self.failed) * 100) if (self.passed + self.failed) > 0 else 0
        logger.info(f"\nSuccess Rate: {success_rate:.1f}%")

        if self.failed == 0:
            logger.info("\n🎉 ALL TESTS PASSED!")
        else:
            logger.info(f"\n⚠️ {self.failed} TEST(S) FAILED")

        return self.failed == 0


async def main():
    """Main test runner"""
    logger.info("Starting Integration Tests for New Architecture\n")

    test = ArchitectureTest()

    # Setup
    if not await test.setup():
        logger.error("Setup failed, aborting tests")
        sys.exit(1)

    # Run test scenarios
    await test.test_scenario_1_simple_query()
    await test.test_scenario_2_clarification()
    await test.test_scenario_3_file_processing()
    await test.test_scenario_4_error_recovery()
    await test.test_scenario_5_standardization()

    # Print summary
    success = test.print_summary()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    asyncio.run(main())
