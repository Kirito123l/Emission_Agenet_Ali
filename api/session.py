"""会话管理 - 使用JSON持久化"""
import uuid
import json
import asyncio
from typing import Dict, Optional, List, Any
from datetime import datetime
from pathlib import Path

# Import new architecture components
from core.router import UnifiedRouter


class Session:
    """单个会话"""
    def __init__(
        self,
        session_id: str,
        title: str = "新对话",
        created_at: Optional[str] = None,
        message_count: int = 0
    ):
        self.session_id = session_id
        self.title = title
        self.created_at = created_at or datetime.now().isoformat()
        self.updated_at = datetime.now().isoformat()
        self.message_count = message_count
        self.last_result_file: Optional[Any] = None

        # Router对象延迟创建，不序列化
        self._router: Optional[UnifiedRouter] = None

        # 对话历史缓存（用于持久化）
        self._history: List[Dict] = []

    @property
    def router(self) -> UnifiedRouter:
        """延迟创建Router"""
        if self._router is None:
            self._router = UnifiedRouter(session_id=self.session_id)
        return self._router

    async def chat(self, message: str, file_path: Optional[str] = None) -> Dict:
        """
        异步聊天接口

        Returns:
            Dict with keys: text, chart_data, table_data, download_file
        """
        result = await self.router.chat(user_message=message, file_path=file_path)

        return {
            "text": result.text,
            "chart_data": result.chart_data,
            "table_data": result.table_data,
            "download_file": result.download_file
        }

    def save_turn(
        self,
        user_input: str,
        assistant_response: str,
        chart_data: Optional[Dict] = None,
        table_data: Optional[Dict] = None,
        data_type: Optional[str] = None,
        file_id: Optional[str] = None,  # 添加 file_id 参数
        download_file: Optional[Dict] = None,
        message_id: Optional[str] = None
    ):
        """保存一轮对话到历史"""
        assistant_message_id = message_id or uuid.uuid4().hex[:12]
        self._history.append({
            "role": "user",
            "content": user_input,
            "timestamp": datetime.now().isoformat()
        })
        self._history.append({
            "role": "assistant",
            "content": assistant_response,
            "chart_data": chart_data,
            "table_data": table_data,
            "data_type": data_type,
            "message_id": assistant_message_id,
            "file_id": file_id,  # 保存 file_id
            "download_file": download_file,  # 保存下载文件元数据
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
        self._sessions[session_id] = Session(session_id)
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
        self._sessions[new_id] = Session(new_id)
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
            self._save_to_disk()

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
                    message_count=meta.get("message_count", 0)
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
