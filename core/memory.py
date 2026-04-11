"""
Memory Manager - Three-layer memory structure
Manages conversation history and context
"""
import json
import logging
from typing import Dict, List, Optional, Any
from datetime import datetime
from dataclasses import dataclass, field
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
    session_topic: Optional[str] = None
    user_language_preference: Optional[str] = None
    cumulative_tools_used: List[str] = field(default_factory=list)
    key_findings: List[str] = field(default_factory=list)
    user_corrections: List[str] = field(default_factory=list)


@dataclass
class Turn:
    """Conversation turn"""
    user: str
    assistant: str
    tool_calls: Optional[List[Dict]] = None
    turn_index: Optional[int] = None
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SummarySegment:
    """Mid-term summary segment covering a bounded turn range."""
    start_turn: int
    end_turn: int
    summary: str
    timestamp: datetime = field(default_factory=datetime.now)


class MemoryManager:
    """
    Memory manager with three-layer structure:
    1. Working memory - Recent complete conversations
    2. Fact memory - Structured facts (vehicle, pollutants, etc.)
    3. Compressed memory - Summary of old conversations
    """

    MAX_WORKING_MEMORY_TURNS = 5  # Keep last 5 turns
    MID_TERM_SUMMARY_INTERVAL = 3
    MAX_MID_TERM_SEGMENTS = 5
    MAX_MID_TERM_SUMMARY_CHARS = 200
    MAX_MEMORY_CONTEXT_CHARS = 1800
    MAX_CONTEXT_SUMMARY_SEGMENTS = 5
    MAX_CUMULATIVE_TOOLS = 20
    MAX_KEY_FINDINGS = 8
    MAX_USER_CORRECTIONS = 8
    MAX_CHAT_HISTORY_TURNS = 5
    MAX_CHAT_ASSISTANT_CHARS = 1200

    def __init__(self, session_id: str, storage_dir: Optional[str | Path] = None):
        self.session_id = session_id
        self._storage_dir = Path(storage_dir) if storage_dir else Path("data/sessions/history")
        self._storage_dir.mkdir(parents=True, exist_ok=True)
        self.working_memory: List[Turn] = []
        self.fact_memory = FactMemory()
        self.mid_term_memory: List[SummarySegment] = []
        self.compressed_memory: str = ""
        self.turn_counter: int = 0

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

    def build_conversational_messages(
        self,
        user_message: str,
        *,
        max_turns: int = MAX_CHAT_HISTORY_TURNS,
        assistant_char_limit: int = MAX_CHAT_ASSISTANT_CHARS,
    ) -> List[Dict[str, str]]:
        """Build bounded short-term message history for both fast path and state-loop helpers."""
        messages: List[Dict[str, str]] = []
        for turn in self.working_memory[-max_turns:]:
            user_text = str(turn.user or "").strip()
            assistant_text = str(turn.assistant or "").strip()
            if user_text:
                messages.append({"role": "user", "content": user_text})
            if assistant_text:
                if len(assistant_text) > assistant_char_limit:
                    assistant_text = assistant_text[:assistant_char_limit].rstrip() + "...(truncated)"
                messages.append({"role": "assistant", "content": assistant_text})

        messages.append({"role": "user", "content": user_message})
        return messages

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
            "session_topic": self.fact_memory.session_topic,
            "user_language_preference": self.fact_memory.user_language_preference,
            "cumulative_tools_used": list(self.fact_memory.cumulative_tools_used),
            "key_findings": list(self.fact_memory.key_findings),
            "user_corrections": list(self.fact_memory.user_corrections),
        }

    def build_context_for_prompt(self, max_chars: int = MAX_MEMORY_CONTEXT_CHARS) -> str:
        """Build bounded mid-term + long-term memory context for prompt injection."""
        sections: List[str] = []

        fact_lines: List[str] = []
        if self.fact_memory.session_topic:
            fact_lines.append(f"Session topic: {self.fact_memory.session_topic}")
        if self.fact_memory.active_file:
            fact_lines.append(f"Active file: {self.fact_memory.active_file}")
        if self.fact_memory.recent_vehicle:
            fact_lines.append(f"Recent vehicle type: {self.fact_memory.recent_vehicle}")
        if self.fact_memory.recent_pollutants:
            fact_lines.append(f"Recent pollutants: {', '.join(self.fact_memory.recent_pollutants[:5])}")
        if self.fact_memory.recent_year is not None:
            fact_lines.append(f"Recent model year: {self.fact_memory.recent_year}")
        if self.fact_memory.last_tool_name:
            fact_lines.append(f"Last successful tool: {self.fact_memory.last_tool_name}")
        if self.fact_memory.last_tool_summary:
            summary = str(self.fact_memory.last_tool_summary)
            fact_lines.append(f"Last tool summary: {summary[:260]}")
        if self.fact_memory.user_language_preference:
            fact_lines.append(f"User language preference: {self.fact_memory.user_language_preference}")
        if self.fact_memory.cumulative_tools_used:
            fact_lines.append(
                "Cumulative tools used: "
                + ", ".join(self.fact_memory.cumulative_tools_used[-8:])
            )
        if self.fact_memory.key_findings:
            fact_lines.append(
                "Key findings: " + " | ".join(self.fact_memory.key_findings[-5:])
            )
        if self.fact_memory.user_corrections:
            fact_lines.append(
                "User corrections: " + " | ".join(self.fact_memory.user_corrections[-5:])
            )
        if fact_lines:
            sections.append("[Session facts]\n" + "\n".join(fact_lines))

        summary_lines = []
        for segment in self.mid_term_memory[-self.MAX_CONTEXT_SUMMARY_SEGMENTS:]:
            summary_lines.append(
                f"- Turns {segment.start_turn}-{segment.end_turn}: {segment.summary}"
            )
        if not summary_lines and self.compressed_memory:
            summary_lines.append(f"- Legacy summary: {self.compressed_memory[:600]}")
        if summary_lines:
            sections.append("[Conversation summaries]\n" + "\n".join(summary_lines))

        context = "\n\n".join(sections)
        if len(context) <= max_chars:
            return context
        return context[: max_chars - 16].rstrip() + "\n...(truncated)"

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
        self.turn_counter += 1

        # 1. Add to working memory
        turn = Turn(
            user=user_message,
            assistant=assistant_response,
            tool_calls=tool_calls,
            turn_index=self.turn_counter,
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
                task_type = file_analysis.get("task_type") or file_analysis.get("detected_type")
                if task_type:
                    self.fact_memory.session_topic = str(task_type)

        # 4. Detect user corrections
        self._detect_correction(user_message)
        self._detect_language_preference(user_message)

        # 5. Build a mid-term summary every N turns
        if self.turn_counter % self.MID_TERM_SUMMARY_INTERVAL == 0:
            recent_turns = self.working_memory[-self.MID_TERM_SUMMARY_INTERVAL:]
            if recent_turns:
                self._append_mid_term_summary(recent_turns)

        # 6. Compress old memory if needed
        if len(self.working_memory) > self.MAX_WORKING_MEMORY_TURNS * 2:
            self._compress_old_memory()

        # 7. Persist
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
                if tool_name not in self.fact_memory.cumulative_tools_used:
                    self.fact_memory.cumulative_tools_used.append(tool_name)
                self.fact_memory.cumulative_tools_used = self.fact_memory.cumulative_tools_used[-self.MAX_CUMULATIVE_TOOLS:]
                inferred_topic = self._infer_topic_from_tool_name(tool_name)
                if inferred_topic:
                    self.fact_memory.session_topic = inferred_topic
            if result.get("summary"):
                self.fact_memory.last_tool_summary = str(result["summary"])
                self.fact_memory.key_findings.append(str(result["summary"])[: self.MAX_MID_TERM_SUMMARY_CHARS])
                self.fact_memory.key_findings = self.fact_memory.key_findings[-self.MAX_KEY_FINDINGS:]

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

        self.fact_memory.user_corrections.append(user_message[: self.MAX_MID_TERM_SUMMARY_CHARS])
        self.fact_memory.user_corrections = self.fact_memory.user_corrections[-self.MAX_USER_CORRECTIONS:]

        # Simple correction detection
        # In production, could use LLM to understand corrections better
        vehicle_keywords = ["小汽车", "公交车", "货车", "轿车", "客车"]
        for kw in vehicle_keywords:
            if kw in user_message:
                self.fact_memory.recent_vehicle = kw
                logger.info(f"Detected correction: vehicle -> {kw}")
                break

    def _detect_language_preference(self, user_message: str) -> None:
        """Infer a coarse user language preference for reply shaping."""
        if not user_message:
            return
        chinese_chars = sum(1 for ch in user_message if "\u4e00" <= ch <= "\u9fff")
        ascii_letters = sum(1 for ch in user_message if ch.isascii() and ch.isalpha())
        if chinese_chars and ascii_letters:
            self.fact_memory.user_language_preference = "mixed"
        elif chinese_chars:
            self.fact_memory.user_language_preference = "zh"
        elif ascii_letters:
            self.fact_memory.user_language_preference = "en"

    @staticmethod
    def _infer_topic_from_tool_name(tool_name: str) -> Optional[str]:
        topic_map = {
            "calculate_macro_emission": "macro_emission",
            "calculate_micro_emission": "micro_emission",
            "calculate_dispersion": "dispersion",
            "analyze_hotspots": "hotspot_analysis",
            "render_spatial_map": "spatial_visualization",
            "compare_scenarios": "scenario_comparison",
            "query_knowledge": "knowledge_qa",
        }
        return topic_map.get(tool_name)

    def _append_mid_term_summary(self, turns: List[Turn]) -> None:
        """Append a bounded mid-term summary segment for the provided turns."""
        start_turn = turns[0].turn_index or max(1, self.turn_counter - len(turns) + 1)
        end_turn = turns[-1].turn_index or self.turn_counter
        if self.mid_term_memory and self.mid_term_memory[-1].end_turn == end_turn:
            return

        segment = SummarySegment(
            start_turn=start_turn,
            end_turn=end_turn,
            summary=self._generate_segment_summary(turns),
        )
        self.mid_term_memory.append(segment)
        self.mid_term_memory = self.mid_term_memory[-self.MAX_MID_TERM_SEGMENTS:]
        self._sync_legacy_compressed_memory()

    def _generate_segment_summary(self, turns: List[Turn]) -> str:
        """Generate a bounded rule-based summary for a short turn span."""
        parts: List[str] = []
        for turn in turns:
            if turn.tool_calls:
                tool_parts: List[str] = []
                for call in turn.tool_calls[:2]:
                    tool_name = str(call.get("name") or "unknown")
                    result = call.get("result", {}) if isinstance(call, dict) else {}
                    summary = str(
                        (result.get("summary") if isinstance(result, dict) else None)
                        or ""
                    ).strip()
                    tool_parts.append(
                        f"{tool_name}: {summary[:80]}" if summary else tool_name
                    )
                if tool_parts:
                    parts.append("执行 " + "; ".join(tool_parts))
                    continue

            user_text = str(turn.user or "").strip()
            if user_text:
                parts.append("用户: " + user_text[:60])

        summary = "; ".join(parts) if parts else "会话继续推进。"
        if len(summary) > self.MAX_MID_TERM_SUMMARY_CHARS:
            summary = summary[: self.MAX_MID_TERM_SUMMARY_CHARS - 16].rstrip() + "...(truncated)"
        return summary

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
            elif turn.user:
                summaries.append(f"- User: {str(turn.user)[:60]}")

        if summaries and old_turns:
            self._append_mid_term_summary(old_turns[-self.MID_TERM_SUMMARY_INTERVAL :])
        self.working_memory = self.working_memory[-self.MAX_WORKING_MEMORY_TURNS:]
        if summaries:
            self.compressed_memory = "\n".join(summaries[-10:])
        self._sync_legacy_compressed_memory()
        logger.info(f"Compressed memory, kept {len(self.working_memory)} recent turns")

    def _sync_legacy_compressed_memory(self) -> None:
        """Mirror mid-term summaries into the legacy compressed_memory string field."""
        if self.mid_term_memory:
            self.compressed_memory = "\n".join(
                f"Turns {segment.start_turn}-{segment.end_turn}: {segment.summary}"
                for segment in self.mid_term_memory[-self.MAX_MID_TERM_SEGMENTS:]
            )

    def clear_topic_memory(self):
        """Clear topic-related memory (when topic changes)"""
        self.fact_memory.active_file = None
        self.fact_memory.file_analysis = None
        self.fact_memory.last_tool_name = None
        self.fact_memory.last_tool_summary = None
        self.fact_memory.last_tool_snapshot = None
        self.fact_memory.last_spatial_data = None
        self.fact_memory.session_topic = None
        self.fact_memory.key_findings = []
        self.mid_term_memory = []
        self._sync_legacy_compressed_memory()
        logger.info("Cleared topic memory")

    def _save(self):
        """Persist memory to disk"""
        data = {
            "session_id": self.session_id,
            "turn_counter": self.turn_counter,
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
                "session_topic": self.fact_memory.session_topic,
                "user_language_preference": self.fact_memory.user_language_preference,
                "cumulative_tools_used": self.fact_memory.cumulative_tools_used,
                "key_findings": self.fact_memory.key_findings,
                "user_corrections": self.fact_memory.user_corrections,
            },
            "mid_term_memory": [
                {
                    "start_turn": segment.start_turn,
                    "end_turn": segment.end_turn,
                    "summary": segment.summary,
                    "timestamp": segment.timestamp.isoformat(),
                }
                for segment in self.mid_term_memory[-self.MAX_MID_TERM_SEGMENTS:]
            ],
            "compressed_memory": self.compressed_memory,
            "working_memory": [
                {
                    "user": t.user,
                    "assistant": t.assistant,
                    "tool_calls": _convert_paths_to_strings(t.tool_calls),
                    "turn_index": t.turn_index,
                    "timestamp": t.timestamp.isoformat()
                }
                for t in self.working_memory[-10:]  # Save max 10 turns
            ]
        }

        path = self._storage_dir / f"{self.session_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)

        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Failed to save memory: {e}")

    def _load(self):
        """Load persisted memory from disk"""
        path = self._storage_dir / f"{self.session_id}.json"
        legacy_path = Path("data/sessions/history") / f"{self.session_id}.json"
        if not path.exists() and legacy_path.exists():
            path = legacy_path

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
                self.fact_memory.session_topic = fm.get("session_topic")
                self.fact_memory.user_language_preference = fm.get("user_language_preference")
                self.fact_memory.cumulative_tools_used = list(fm.get("cumulative_tools_used", []))
                self.fact_memory.key_findings = list(fm.get("key_findings", []))
                self.fact_memory.user_corrections = list(fm.get("user_corrections", []))

            self.turn_counter = int(data.get("turn_counter", 0) or 0)

            if "mid_term_memory" in data and isinstance(data["mid_term_memory"], list):
                for item in data["mid_term_memory"]:
                    if not isinstance(item, dict):
                        continue
                    timestamp = item.get("timestamp")
                    parsed_timestamp = datetime.now()
                    if isinstance(timestamp, str):
                        try:
                            parsed_timestamp = datetime.fromisoformat(timestamp)
                        except ValueError:
                            parsed_timestamp = datetime.now()
                    self.mid_term_memory.append(
                        SummarySegment(
                            start_turn=int(item.get("start_turn", 0) or 0),
                            end_turn=int(item.get("end_turn", 0) or 0),
                            summary=str(item.get("summary") or ""),
                            timestamp=parsed_timestamp,
                        )
                    )

            # Load compressed memory
            self.compressed_memory = data.get("compressed_memory", "")

            # Load working memory
            if "working_memory" in data:
                for item in data["working_memory"]:
                    timestamp = item.get("timestamp")
                    parsed_timestamp = datetime.now()
                    if isinstance(timestamp, str):
                        try:
                            parsed_timestamp = datetime.fromisoformat(timestamp)
                        except ValueError:
                            parsed_timestamp = datetime.now()
                    self.working_memory.append(Turn(
                        user=item["user"],
                        assistant=item["assistant"],
                        tool_calls=item.get("tool_calls"),
                        turn_index=item.get("turn_index"),
                        timestamp=parsed_timestamp,
                    ))

            if self.turn_counter <= 0:
                max_working_turn = max((turn.turn_index or 0) for turn in self.working_memory) if self.working_memory else 0
                max_summary_turn = max((segment.end_turn or 0) for segment in self.mid_term_memory) if self.mid_term_memory else 0
                self.turn_counter = max(max_working_turn, max_summary_turn, len(self.working_memory))

            logger.info(f"Loaded memory for session {self.session_id}")

        except Exception as e:
            logger.warning(f"Failed to load memory: {e}")
            # Continue with empty memory
