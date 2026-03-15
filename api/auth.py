"""认证服务模块 - 密码哈希和 JWT"""
import os
import jwt
import hashlib
import uuid
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, Dict, Any
from passlib.context import CryptContext
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)

# JWT 配置
# SECURITY: Secret key MUST be set via environment variable in production.
# A default is provided ONLY for local development convenience.
# Load the project-root .env here so auth does not depend on some other module
# importing config.py first. Explicit environment variables still take precedence.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
_DEFAULT_SECRET = "local-dev-only-change-me-in-production"
SECRET_KEY = os.getenv("JWT_SECRET_KEY", _DEFAULT_SECRET)
if SECRET_KEY == _DEFAULT_SECRET:
    logger.warning(
        "JWT_SECRET_KEY is not set -- using insecure default. "
        "Set JWT_SECRET_KEY in .env for production deployments."
    )
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60 * 24 * 7  # 7天

# 密码哈希配置
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class AuthService:
    """认证服务类"""

    @staticmethod
    def hash_password(password: str) -> str:
        """哈希密码"""
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(plain_password: str, hashed_password: str) -> bool:
        """验证密码"""
        return pwd_context.verify(plain_password, hashed_password)

    @staticmethod
    def create_access_token(data: Dict[str, Any], expires_delta: Optional[timedelta] = None) -> str:
        """创建 JWT Token"""
        to_encode = data.copy()

        if expires_delta:
            expire = datetime.utcnow() + expires_delta
        else:
            expire = datetime.utcnow() + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

        to_encode.update({
            "exp": expire,
            "iat": datetime.utcnow()
        })

        encoded_jwt = jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)
        return encoded_jwt

    @staticmethod
    def decode_token(token: str) -> Optional[Dict[str, Any]]:
        """解码 JWT Token"""
        try:
            payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
            return payload
        except jwt.ExpiredSignatureError:
            logger.warning("Token 已过期")
            return None
        except jwt.JWTError as e:
            logger.warning(f"Token 解码失败: {e}")
            return None

    @staticmethod
    def generate_user_id() -> str:
        """生成用户 ID"""
        return str(uuid.uuid4())


auth_service = AuthService()
