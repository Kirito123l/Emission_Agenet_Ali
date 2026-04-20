"""会话管理 - 使用JSON持久化"""
import uuid
import json
from typing import Dict, Optional, List, Any
from datetime import datetime, timedelta
from pathlib import Path

# Import new architecture components
from config import get_config
from core.context_store import SessionContextStore
from core.governed_router import build_router
from core.naive_router import NaiveRouter
from core.router import UnifiedRouter


class Session:
    """单个会话"""
    def __init__(
        self,
        session_id: str,
        title: str = "新对话",
        created_at: Optional[str] = None,
        message_count: int = 0,
        storage_dir: Optional[str | Path] = None,
    ):
        self.session_id = session_id
        self.title = title
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
        self.message_count = message_count
        self.last_result_file: Optional[Any] = None
        self._storage_dir = Path(storage_dir) if storage_dir else Path("data/sessions")
        self._router_state_dir = self._storage_dir / "router_state"
        self._naive_router_state_dir = self._storage_dir / "naive_router_state"
        self._memory_dir = self._storage_dir / "memory"
        self._router_state_dir.mkdir(parents=True, exist_ok=True)
        self._naive_router_state_dir.mkdir(parents=True, exist_ok=True)
        self._memory_dir.mkdir(parents=True, exist_ok=True)

        # Router对象延迟创建，不序列化
        self._router: Optional[UnifiedRouter] = None
        self._governed_router: Optional[Any] = None
        self._naive_router: Optional[NaiveRouter] = None

        # 对话历史缓存（用于持久化）
        self._history: List[Dict] = []

    @property
    def router(self) -> UnifiedRouter:
        """延迟创建Router"""
        if self._router is None:
            self._router = build_router(
                session_id=self.session_id,
                memory_storage_dir=self._memory_dir,
                router_mode="full",
            )
            self._restore_router_state()
        return self._router

    @property
    def governed_router(self):
        """延迟创建 GovernedRouter wrapper."""
        if self._governed_router is None:
            self._governed_router = build_router(
                session_id=self.session_id,
                memory_storage_dir=self._memory_dir,
                router_mode="governed_v2",
            )
            self._restore_router_state(router_obj=self._governed_router)
        return self._governed_router

    @property
    def naive_router(self) -> NaiveRouter:
        """延迟创建NaiveRouter baseline。"""
        if self._naive_router is None:
            self._naive_router = NaiveRouter(
                session_id=self.session_id,
                tool_call_log_path=self._storage_dir / "naive_router_tool_calls.jsonl",
            )
            self._restore_naive_router_state()
        return self._naive_router

    async def chat(self, message: str, file_path: Optional[str] = None, mode: str = "full") -> Dict:
        """
        异步聊天接口

        Returns:
            Dict with keys: text, chart_data, table_data, map_data, download_file, trace, trace_friendly
        """
        trace = {} if get_config().enable_trace else None
        if mode == "naive":
            result = await self.naive_router.chat(user_message=message, file_path=file_path, trace=trace)
            self.save_naive_router_state()
        elif mode == "governed_v2":
            result = await self.governed_router.chat(user_message=message, file_path=file_path, trace=trace)
            self.save_router_state(router_obj=self.governed_router)
        else:
            result = await self.router.chat(user_message=message, file_path=file_path, trace=trace)
            self.save_router_state(router_obj=self.router)

        return {
            "text": result.text,
            "chart_data": result.chart_data,
            "table_data": result.table_data,
            "map_data": result.map_data,
            "download_file": result.download_file,
            "executed_tool_calls": result.executed_tool_calls,
            "trace": result.trace,
            "trace_friendly": result.trace_friendly,
        }

    def save_router_state(self, router_obj: Optional[Any] = None) -> None:
        """Persist router state required for follow-up turns after process restarts."""
        router_obj = router_obj or self._router or self._governed_router
        if router_obj is None:
            return

        state_path = self._router_state_dir / f"{self.session_id}.json"
        if get_config().enable_live_state_persistence and hasattr(router_obj, "to_persisted_state"):
            payload = router_obj.to_persisted_state()
            payload["saved_at"] = datetime.now().isoformat()
        else:
            payload = {
                "context_store": router_obj.context_store.to_persisted_dict(),
                "saved_at": datetime.now().isoformat(),
            }
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"Warning: Failed to persist router state for session {self.session_id}: {exc}")

    def save_naive_router_state(self) -> None:
        """Persist NaiveRouter's simple history list."""
        if self._naive_router is None:
            return

        state_path = self._naive_router_state_dir / f"{self.session_id}.json"
        payload = self._naive_router.to_persisted_state()
        payload["saved_at"] = datetime.now().isoformat()
        try:
            with open(state_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False, indent=2)
        except Exception as exc:
            print(f"Warning: Failed to persist naive router state for session {self.session_id}: {exc}")

    def _restore_router_state(self, router_obj: Optional[Any] = None) -> None:
        """Restore persisted router state for an existing session."""
        router_obj = router_obj or self._router or self._governed_router
        if router_obj is None:
            return

        state_path = self._router_state_dir / f"{self.session_id}.json"
        if not state_path.exists():
            return

        try:
            with open(state_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            if get_config().enable_live_state_persistence and hasattr(router_obj, "restore_persisted_state"):
                router_obj.restore_persisted_state(payload)
            else:
                context_payload = payload.get("context_store")
                if isinstance(context_payload, dict):
                    router_obj.context_store = SessionContextStore.from_persisted_dict(context_payload)
        except Exception as exc:
            print(f"Warning: Failed to restore router state for session {self.session_id}: {exc}")

    def _restore_naive_router_state(self) -> None:
        """Restore NaiveRouter's simple history state for an existing session."""
        if self._naive_router is None:
            return

        state_path = self._naive_router_state_dir / f"{self.session_id}.json"
        if not state_path.exists():
            return

        try:
            with open(state_path, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._naive_router.restore_persisted_state(payload)
        except Exception as exc:
            print(f"Warning: Failed to restore naive router state for session {self.session_id}: {exc}")

    def save_turn(
        self,
        user_input: str,
        assistant_response: str,
        file_name: Optional[str] = None,
        file_path: Optional[str] = None,
        file_size: Optional[int] = None,
        chart_data: Optional[Dict] = None,
        table_data: Optional[Dict] = None,
        map_data: Optional[Dict] = None,
        data_type: Optional[str] = None,
        file_id: Optional[str] = None,  # 添加 file_id 参数
        download_file: Optional[Dict] = None,
        message_id: Optional[str] = None,
        trace_friendly: Optional[List[Dict[str, Any]]] = None,
    ):
        """保存一轮对话到历史"""
        assistant_message_id = message_id or uuid.uuid4().hex[:12]
        user_message = {
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat()
        }
        if file_name:
            user_message["file_name"] = file_name
        if file_path:
            user_message["file_path"] = file_path
        if file_size is not None:
            user_message["file_size"] = file_size
        self._history.append(user_message)
        self._history.append({
            "role": "assistant",
            "content": assistant_response,
            "chart_data": chart_data,
            "table_data": table_data,
            "map_data": map_data,
            "data_type": data_type,
            "message_id": assistant_message_id,
            "file_id": file_id,  # 保存 file_id
            "download_file": download_file,  # 保存下载文件元数据
            "trace_friendly": trace_friendly,
            "timestamp": datetime.now().isoformat()
        })
        self.message_count += 1
        self.updated_at = datetime.now().isoformat()
        return assistant_message_id

    def to_dict(self) -> Dict:
        """转换为可序列化的字典"""
        return {
            "session_id": self.session_id,
            "title": self.title,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "message_count": self.message_count,
            "last_result_file": self.last_result_file
        }


class SessionManager:
    """会话管理器 - 使用JSON持久化"""
    SESSION_TTL_HOURS = 72

    def __init__(self, storage_dir: str = "data/sessions"):
        self._sessions: Dict[str, Session] = {}
        self._storage_dir = Path(storage_dir)
        self._storage_dir.mkdir(parents=True, exist_ok=True)

        self._meta_file = self._storage_dir / "sessions_meta.json"
        self._history_dir = self._storage_dir / "history"
        self._history_dir.mkdir(exist_ok=True)

        self._load_from_disk()

    def create_session(self) -> str:
        """创建新会话"""
        session_id = str(uuid.uuid4())[:8]
        self._sessions[session_id] = Session(session_id, storage_dir=self._storage_dir)
        self._save_to_disk()
        return session_id

    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        return self._sessions.get(session_id)

    def get_or_create_session(self, session_id: Optional[str]) -> Session:
        """获取或创建会话"""
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]

        new_id = session_id or str(uuid.uuid4())[:8]
        self._sessions[new_id] = Session(new_id, storage_dir=self._storage_dir)
        self._save_to_disk()
        return self._sessions[new_id]

    def update_session_title(self, session_id: str, first_message: str):
        """根据第一条消息更新会话标题"""
        session = self._sessions.get(session_id)
        if session and session.message_count == 1:
            # 取前20个字符作为标题
            session.title = first_message[:20] + ("..." if len(first_message) > 20 else "")
            self._save_to_disk()

    def set_session_title(self, session_id: str, title: str) -> bool:
        """手动设置会话标题"""
        session = self._sessions.get(session_id)
        if not session:
            return False
        clean_title = (title or "").strip()
        if not clean_title:
            return False
        session.title = clean_title[:80]
        session.updated_at = datetime.now().isoformat()
        self._save_to_disk()
        return True

    def list_sessions(self) -> list:
        """列出所有会话"""
        return sorted(
            self._sessions.values(),
            key=lambda s: s.updated_at,
            reverse=True
        )

    def delete_session(self, session_id: str):
        """删除会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]
            # 删除历史文件
            history_file = self._history_dir / f"{session_id}.json"
            if history_file.exists():
                history_file.unlink()
            router_state_file = self._storage_dir / "router_state" / f"{session_id}.json"
            if router_state_file.exists():
                router_state_file.unlink()
            memory_file = self._storage_dir / "memory" / f"{session_id}.json"
            if memory_file.exists():
                memory_file.unlink()
            naive_router_state_file = self._storage_dir / "naive_router_state" / f"{session_id}.json"
            if naive_router_state_file.exists():
                naive_router_state_file.unlink()
            self._save_to_disk()

    def cleanup_idle_sessions(self, ttl_hours: Optional[int] = None) -> int:
        """Remove idle sessions from memory without deleting persisted files."""
        ttl = ttl_hours if ttl_hours is not None else self.SESSION_TTL_HOURS
        cutoff = datetime.now() - timedelta(hours=ttl)
        to_remove: List[str] = []
        for session_id, session in self._sessions.items():
            try:
                updated_at = datetime.fromisoformat(session.updated_at)
            except Exception:
                continue
            if updated_at < cutoff:
                to_remove.append(session_id)

        for session_id in to_remove:
            del self._sessions[session_id]
        return len(to_remove)

    def save_session(self):
        """手动保存会话状态（用于更新计数或时间后）"""
        self._save_to_disk()

    @property
    def sessions(self):
        """获取所有会话字典（用于调试）"""
        return self._sessions

    def _load_from_disk(self):
        """从磁盘加载会话元数据和历史"""
        if not self._meta_file.exists():
            return

        try:
            with open(self._meta_file, "r", encoding="utf-8") as f:
                meta_list = json.load(f)

            for meta in meta_list:
                session_id = meta["session_id"]
                # 重新创建Session对象（Agent会在需要时延迟创建）
                session = Session(
                    session_id=session_id,
                    title=meta.get("title", "新对话"),
                    created_at=meta.get("created_at"),
                    message_count=meta.get("message_count", 0),
                    storage_dir=self._storage_dir,
                )
                session.updated_at = meta.get("updated_at", session.created_at)
                session.last_result_file = meta.get("last_result_file")

                # 加载对话历史
                history_file = self._history_dir / f"{session_id}.json"
                if history_file.exists():
                    with open(history_file, "r", encoding="utf-8") as f:
                        session._history = json.load(f)

                self._sessions[session_id] = session

            print(f"Successfully loaded {len(self._sessions)} sessions")
        except Exception as e:
            print(f"Warning: Failed to load sessions: {e}")
            self._sessions = {}

    def _save_to_disk(self):
        """保存会话元数据和历史到磁盘"""
        try:
            # 保存元数据
            meta_list = []
            for session_id, session in self._sessions.items():
                meta_list.append(session.to_dict())

            with open(self._meta_file, "w", encoding="utf-8") as f:
                json.dump(meta_list, f, ensure_ascii=False, indent=2)

            # 保存各会话的对话历史
            for session_id, session in self._sessions.items():
                if session._history:
                    history_file = self._history_dir / f"{session_id}.json"
                    with open(history_file, "w", encoding="utf-8") as f:
                        json.dump(session._history, f, ensure_ascii=False, indent=2)
                session.save_router_state()
                session.save_naive_router_state()

            # Success - no message to avoid log pollution
        except Exception as e:
            print(f"Error: Failed to save sessions: {e}")


class SessionRegistry:
    """Per-user SessionManager registry.

    Each user_id gets its own SessionManager with isolated storage
    under ``data/sessions/{user_id}/``.
    """

    _managers: Dict[str, SessionManager] = {}

    @classmethod
    def get(cls, user_id: str) -> SessionManager:
        if user_id not in cls._managers:
            storage = f"data/sessions/{user_id}"
            cls._managers[user_id] = SessionManager(storage_dir=storage)
        return cls._managers[user_id]
