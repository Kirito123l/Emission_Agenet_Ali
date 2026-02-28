"""
Knowledge Query Tool

Wrapper for knowledge retrieval skill to query emission-related knowledge and regulations.
"""
from typing import Dict, Optional
from .base import BaseTool, ToolResult
from skills.knowledge.skill import KnowledgeSkill


class KnowledgeTool(BaseTool):
    """Query emission-related knowledge and regulations"""

    def __init__(self):
        self._skill = KnowledgeSkill()

    @property
    def name(self) -> str:
        return "query_knowledge"

    @property
    def description(self) -> str:
        return "Query emission-related knowledge, standards, and regulations from knowledge base"

    async def execute(self, **kwargs) -> ToolResult:
        """
        Execute knowledge query

        Parameters:
            query: str - The question to search for
            top_k: int (optional) - Number of results to return (default: 5)
            expectation: str (optional) - Expected type of information
        """
        try:
            # Validate required parameters
            query = kwargs.get("query")
            if not query:
                return self._error("Missing required parameter: query")

            # Execute skill
            skill_result = self._skill.execute(**kwargs)

            if not skill_result.success:
                return ToolResult(
                    success=False,
                    error=skill_result.error,
                    data=skill_result.data
                )

            # Extract data
            data = skill_result.data
            answer = data.get("answer", "")
            sources = data.get("sources", [])
            num_results = skill_result.metadata.get("num_results", 0)

            # Create summary - 使用完整的answer（包含参考文献）
            # 注意：summary会被用于synthesis，所以必须包含完整内容
            summary = answer  # 直接使用完整答案，不截断

            return ToolResult(
                success=True,
                data=data,
                summary=summary,
                error=None
            )

        except Exception as e:
            return self._error(f"Knowledge query failed: {str(e)}")
