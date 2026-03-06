"""数据库模块 - SQLite 用户认证"""
import aiosqlite
import sqlite3
import asyncio
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, Any, List
import logging

logger = logging.getLogger(__name__)

# 数据库路径
DB_DIR = Path(__file__).parent.parent / "data"
DB_DIR.mkdir(exist_ok=True)
DB_PATH = DB_DIR / "users.db"


class Database:
    """数据库管理类"""

    def __init__(self, db_path: str = str(DB_PATH)):
        self.db_path = db_path
        self._lock = asyncio.Lock()

    async def init_db(self):
        """初始化数据库表"""
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY,
                    username TEXT UNIQUE NOT NULL,
                    password_hash TEXT NOT NULL,
                    email TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    last_login TEXT
                )
            """)
            await db.commit()
            logger.info(f"数据库初始化完成: {self.db_path}")

    async def get_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        """根据用户名获取用户"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM users WHERE username = ?",
                (username,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "id": row[0],
                        "username": row[1],
                        "password_hash": row[2],
                        "email": row[3],
                        "created_at": row[4],
                        "updated_at": row[5],
                        "last_login": row[6]
                    }
                return None

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """根据ID获取用户"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT * FROM users WHERE id = ?",
                (user_id,)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return {
                        "id": row[0],
                        "username": row[1],
                        "password_hash": row[2],
                        "email": row[3],
                        "created_at": row[4],
                        "updated_at": row[5],
                        "last_login": row[6]
                    }
                return None

    async def create_user(
        self,
        user_id: str,
        username: str,
        password_hash: str,
        email: Optional[str] = None
    ) -> bool:
        """创建新用户"""
        try:
            now = datetime.utcnow().isoformat()
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute(
                    """
                    INSERT INTO users (id, username, password_hash, email, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (user_id, username, password_hash, email, now, now)
                )
                await db.commit()
                logger.info(f"用户创建成功: {username}")
                return True
        except aiosqlite.IntegrityError:
            logger.warning(f"用户名已存在: {username}")
            return False

    async def update_last_login(self, user_id: str):
        """更新最后登录时间"""
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute(
                "UPDATE users SET last_login = ? WHERE id = ?",
                (now, user_id)
            )
            await db.commit()

    async def list_users(self) -> List[Dict[str, Any]]:
        """列出所有用户（管理员功能）"""
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(
                "SELECT id, username, email, created_at, last_login FROM users"
            ) as cursor:
                rows = await cursor.fetchall()
                return [
                    {
                        "id": row[0],
                        "username": row[1],
                        "email": row[2],
                        "created_at": row[3],
                        "last_login": row[4]
                    }
                    for row in rows
                ]


# 全局数据库实例
db = Database()


async def get_db() -> Database:
    """获取数据库实例"""
    return db
