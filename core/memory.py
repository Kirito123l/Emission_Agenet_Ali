"""
Memory Manager - Three-layer memory structure
Manages conversation history and context
"""
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field, asdict
from pathlib import Path

logger = logging.getLogger(__name__)


def _convert_paths_to_strings(obj: Any) -> Any:
    """Recursively convert Path objects to strings for JSON serialization"""
    if isinstance(obj, Path):
        return str(obj)
    elif isinstance(obj, dict):
        return {k: _convert_paths_to_strings(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_convert_paths_to_strings(item) for item in obj]
    else:
        return obj


@dataclass
class FactMemory:
    """Fact memory - Structured key facts"""
    recent_vehicle: Optional[str] = None
    recent_pollutants: List[str] = field(default_factory=list)
    recent_year: Optional[int] = None
    active_file: Optional[str] = None
    file_analysis: Optional[Dict] = None
    last_tool_name: Optional[str] = None
    last_tool_summary: Optional[str] = None
    last_tool_snapshot: Optional[Dict] = None
    user_preferences: Dict = field(default_factory=dict)
    last_spatial_data: Optional[Dict] = None  # Full spatial results with geometry (not compacted)


@dataclass
class Turn:
    """Conversation turn"""
    user: str
    assistant: str
    tool_calls: Optional[List[Dict]] = None
    timestamp: datetime = field(default_factory=datetime.now)


class MemoryManager:
    """
    Memory manager with three-layer structure:
    1. Working memory - Recent complete conversations
    2. Fact memory - Structured facts (vehicle, pollutants, etc.)
    3. Compressed memory - Summary of old conversations
    """

    MAX_WORKING_MEMORY_TURNS = 5  # Keep last 5 turns

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.working_memory: List[Turn] = []
        self.fact_memory = FactMemory()
        self.compressed_memory: str = ""

        # Load persisted memory if exists
        self._load()

    def get_working_memory(self) -> List[Dict]:
        """
        Get working memory (recent conversations)

        Returns:
            List of conversation turns
        """
        return [
            {"user": turn.user, "assistant": turn.assistant}
            for turn in self.working_memory[-self.MAX_WORKING_MEMORY_TURNS:]
        ]

    def get_fact_memory(self) -> Dict:
        """
        Get fact memory

        Returns:
            Dictionary of structured facts
        """
        return {
            "recent_vehicle": self.fact_memory.recent_vehicle,
            "recent_pollutants": self.fact_memory.recent_pollutants,
            "recent_year": self.fact_memory.recent_year,
            "active_file": self.fact_memory.active_file,
            "file_analysis": self.fact_memory.file_analysis,
            "last_tool_name": self.fact_memory.last_tool_name,
            "last_tool_summary": self.fact_memory.last_tool_summary,
            "last_tool_snapshot": self.fact_memory.last_tool_snapshot,
            "last_spatial_data": self.fact_memory.last_spatial_data,
        }

    def update(
        self,
        user_message: str,
        assistant_response: str,
        tool_calls: Optional[List[Dict]] = None,
        file_path: Optional[str] = None,
        file_analysis: Optional[Dict] = None
    ):
        """
        Update memory after a conversation turn

        Args:
            user_message: User's message
            assistant_response: Assistant's response
            tool_calls: Optional tool calls made
            file_path: Optional file path if file was uploaded
            file_analysis: Optional cached file analysis result
        """
        # 1. Add to working memory
        turn = Turn(
            user=user_message,
            assistant=assistant_response,
            tool_calls=tool_calls
        )
        self.working_memory.append(turn)

        # 2. Update fact memory from successful tool calls
        if tool_calls:
            self._extract_facts_from_tool_calls(tool_calls)

        # 3. Update active file and cache analysis
        if file_path:
            self.fact_memory.active_file = str(file_path)
            if file_analysis:
                # Convert any Path objects to strings before storing
                self.fact_memory.file_analysis = _convert_paths_to_strings(file_analysis)

        # 4. Detect user corrections
        self._detect_correction(user_message)

        # 5. Compress old memory if needed
        if len(self.working_memory) > self.MAX_WORKING_MEMORY_TURNS * 2:
            self._compress_old_memory()

        # 6. Persist
        self._save()

    def _extract_facts_from_tool_calls(self, tool_calls: List[Dict]):
        """Extract facts from successful tool calls"""
        for call in tool_calls:
            args = call.get("arguments", {})
            result = call.get("result", {})

            # Only update from successful calls
            if not result.get("success"):
                continue

            tool_name = call.get("name")
            if tool_name:
                self.fact_memory.last_tool_name = tool_name
            if result.get("summary"):
                self.fact_memory.last_tool_summary = str(result["summary"])

            data = result.get("data", {})
            if isinstance(data, dict):
                # Keep a compact snapshot for follow-up grounding.
                snapshot: Dict[str, Any] = {}
                for k in ("query_info", "summary", "fleet_mix_fill", "download_file", "row_count", "columns", "task_type", "detected_type"):
                    if k in data:
                        snapshot[k] = data[k]
                if snapshot:
                    self.fact_memory.last_tool_snapshot = snapshot

            # Full spatial results are captured in core.router before tool data compaction.
            # This method only sees compacted tool calls, so geometry-bearing results are unavailable here.

            # Extract vehicle type
            if "vehicle_type" in args:
                self.fact_memory.recent_vehicle = args["vehicle_type"]
            elif isinstance(data, dict):
                q = data.get("query_info", {})
                if isinstance(q, dict) and q.get("vehicle_type"):
                    self.fact_memory.recent_vehicle = q["vehicle_type"]
                elif data.get("vehicle_type"):
                    self.fact_memory.recent_vehicle = data["vehicle_type"]

            # Extract pollutant(s)
            if "pollutant" in args:
                pol = args["pollutant"]
                self._merge_recent_pollutants([pol])

            if "pollutants" in args:
                if isinstance(args["pollutants"], list):
                    self._merge_recent_pollutants(args["pollutants"])
            elif isinstance(data, dict):
                q = data.get("query_info", {})
                if isinstance(q, dict) and isinstance(q.get("pollutants"), list):
                    self._merge_recent_pollutants(q["pollutants"])
                elif isinstance(data.get("pollutants"), list):
                    self._merge_recent_pollutants(data["pollutants"])

            # Extract model year
            if "model_year" in args:
                self.fact_memory.recent_year = args["model_year"]
            elif isinstance(data, dict):
                q = data.get("query_info", {})
                if isinstance(q, dict) and q.get("model_year"):
                    self.fact_memory.recent_year = q["model_year"]
                elif data.get("model_year"):
                    self.fact_memory.recent_year = data["model_year"]

    def _merge_recent_pollutants(self, pollutants: List[Any]):
        """Merge pollutant list while keeping recent distinct entries."""
        for pol in pollutants:
            if not pol:
                continue
            pol_str = str(pol)
            if pol_str not in self.fact_memory.recent_pollutants:
                self.fact_memory.recent_pollutants.insert(0, pol_str)
        self.fact_memory.recent_pollutants = self.fact_memory.recent_pollutants[:5]

    def _detect_correction(self, user_message: str):
        """Detect user corrections and update fact memory"""
        correction_patterns = ["不对", "不是", "应该是", "我说的是", "换成", "改成"]

        if not any(p in user_message for p in correction_patterns):
            return

        # Simple correction detection
        # In production, could use LLM to understand corrections better
        vehicle_keywords = ["小汽车", "公交车", "货车", "轿车", "客车"]
        for kw in vehicle_keywords:
            if kw in user_message:
                self.fact_memory.recent_vehicle = kw
                logger.info(f"Detected correction: vehicle -> {kw}")
                break

    def _compress_old_memory(self):
        """Compress old memory to save space"""
        # Keep recent turns, compress older ones
        old_turns = self.working_memory[:-self.MAX_WORKING_MEMORY_TURNS]

        # Simple compression: extract tool call info
        summaries = []
        for turn in old_turns:
            if turn.tool_calls:
                for call in turn.tool_calls:
                    summaries.append(f"- Called {call.get('name')} with {call.get('arguments')}")

        self.compressed_memory = "\n".join(summaries)
        self.working_memory = self.working_memory[-self.MAX_WORKING_MEMORY_TURNS:]
        logger.info(f"Compressed memory, kept {len(self.working_memory)} recent turns")

    def clear_topic_memory(self):
        """Clear topic-related memory (when topic changes)"""
        self.fact_memory.active_file = None
        self.fact_memory.file_analysis = None
        self.fact_memory.last_tool_name = None
        self.fact_memory.last_tool_summary = None
        self.fact_memory.last_tool_snapshot = None
        self.fact_memory.last_spatial_data = None
        logger.info("Cleared topic memory")

    def _save(self):
        """Persist memory to disk"""
        data = {
            "session_id": self.session_id,
            "fact_memory": {
                "recent_vehicle": self.fact_memory.recent_vehicle,
                "recent_pollutants": self.fact_memory.recent_pollutants,
                "recent_year": self.fact_memory.recent_year,
                "active_file": self.fact_memory.active_file,
                "file_analysis": _convert_paths_to_strings(self.fact_memory.file_analysis),
                "last_tool_name": self.fact_memory.last_tool_name,
                "last_tool_summary": self.fact_memory.last_tool_summary,
                "last_tool_snapshot": _convert_paths_to_strings(self.fact_memory.last_tool_snapshot),
                "last_spatial_data": _convert_paths_to_strings(self.fact_memory.last_spatial_data),
            },
            "compressed_memory": self.compressed_memory,
            "working_memory": [
                {
                    "user": t.user,
                    "assistant": t.assistant,
                    "timestamp": t.timestamp.isoformat()
                }
                for t in self.working_memory[-10:]  # Save max 10 turns
            ]
        }

        path = Path(f"data/sessions/history/{self.session_id}.json")
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")

    def _load(self):
        """Load persisted memory from disk"""
        path = Path(f"data/sessions/history/{self.session_id}.json")
        if not path.exists():
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Load fact memory
            if "fact_memory" in data:
                fm = data["fact_memory"]
                self.fact_memory.recent_vehicle = fm.get("recent_vehicle")
                self.fact_memory.recent_pollutants = fm.get("recent_pollutants", [])
                self.fact_memory.recent_year = fm.get("recent_year")
                self.fact_memory.active_file = fm.get("active_file")
                self.fact_memory.file_analysis = fm.get("file_analysis")
                self.fact_memory.last_tool_name = fm.get("last_tool_name")
                self.fact_memory.last_tool_summary = fm.get("last_tool_summary")
                self.fact_memory.last_tool_snapshot = fm.get("last_tool_snapshot")
                self.fact_memory.last_spatial_data = fm.get("last_spatial_data")

            # Load compressed memory
            self.compressed_memory = data.get("compressed_memory", "")

            # Load working memory
            if "working_memory" in data:
                for item in data["working_memory"]:
                    self.working_memory.append(Turn(
                        user=item["user"],
                        assistant=item["assistant"]
                    ))

            logger.info(f"Loaded memory for session {self.session_id}")

        except Exception as e:
            logger.warning(f"Failed to load memory: {e}")
            # Continue with empty memory
