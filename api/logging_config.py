"""日志配置模块 - 增强版HTTP访问日志"""
import json
import logging
import logging.handlers
import sys
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.types import ASGIApp
import time


# ==================== 日志目录配置 ====================
LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
ACCESS_LOG_FILE = LOG_DIR / "access.log"


# ==================== JSON格式化器 ====================
class JSONFormatter(logging.Formatter):
    """JSON格式化器，输出结构化日志"""

    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # 添加额外的字段
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        # 异常信息
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": self.formatException(record.exc_info) if record.exc_info else None,
            }

        return json.dumps(log_data, ensure_ascii=False)


# ==================== 日志处理器配置 ====================
def setup_logging() -> logging.Logger:
    """配置日志系统，支持控制台和文件输出，按天轮转"""
    # 创建logger
    logger = logging.getLogger("access")
    logger.setLevel(logging.INFO)

    # 避免重复添加handler
    if logger.handlers:
        return logger

    # 1. 控制台处理器 - 简洁格式
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)
    console_formatter = logging.Formatter(
        '%(asctime)s [%(levelname)s] %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    # 2. 文件处理器 - JSON格式，按天轮转，保留7天
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=str(ACCESS_LOG_FILE),
        when='midnight',  # 每天午夜轮转
        interval=1,  # 每天一个文件
        backupCount=7,  # 保留7天
        encoding='utf-8',
    )
    file_handler.setLevel(logging.INFO)
    file_handler.suffix = "%Y-%m-%d"  # 日志文件后缀：access.log.2025-03-05
    file_handler.setFormatter(JSONFormatter())
    logger.addHandler(file_handler)

    return logger


# 初始化logger
access_logger = setup_logging()


# ==================== 辅助函数 ====================
def _get_client_ip(request: Request) -> str:
    """获取客户端真实IP"""
    # 优先从代理头获取
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()

    real_ip = request.headers.get("X-Real-IP")
    if real_ip:
        return real_ip

    # 回退到直接连接
    if request.client:
        return request.client.host

    return "unknown"


def _sanitize_headers(headers: dict) -> dict:
    """清理请求头，移除敏感信息"""
    sensitive_keys = {
        "authorization", "api-key", "apikey", "x-api-key",
        "cookie", "set-cookie", "x-auth-token"
    }

    sanitized = {}
    for key, value in headers.items():
        if key.lower() in sensitive_keys:
            sanitized[key] = "***REDACTED***"
        else:
            sanitized[key] = value

    return sanitized


async def _extract_request_body(request: Request) -> Optional[dict]:
    """提取请求体（仅对特定端点）"""
    if request.url.path in ["/api/chat", "/api/chat/stream"]:
        try:
            # 对于表单数据
            if request.headers.get("content-type", "").startswith("multipart/form-data"):
                form = await request.form()
                return {
                    "message": form.get("message", "")[:200] if form.get("message") else None,
                    "session_id": form.get("session_id"),
                    "has_file": "file" in form
                }
        except Exception:
            pass

    return None


def _format_response_time(ms: float) -> str:
    """格式化响应时间"""
    if ms < 1000:
        return f"{ms:.0f}ms"
    return f"{ms/1000:.2f}s"


# ==================== HTTP访问日志中间件 ====================
class AccessLogMiddleware(BaseHTTPMiddleware):
    """HTTP访问日志中间件 - 记录详细的请求/响应信息"""

    def __init__(self, app: ASGIApp):
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        start_time = time.time()
        request_id = f"{int(start_time * 1000)}-{hash(str(start_time)) % 10000:04d}"

        # ==================== 记录请求信息 ====================
        client_ip = _get_client_ip(request)
        user_agent = request.headers.get("user-agent", "unknown")

        request_log = {
            "type": "request",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "query": str(request.url.query) if request.url.query else None,
            "client_ip": client_ip,
            "user_agent": user_agent,
            "user_id": request.headers.get("X-User-ID", "default"),
        }

        # 添加请求体（仅特定端点）
        if request.method in ["POST", "PUT", "PATCH"]:
            body = await _extract_request_body(request)
            if body:
                request_log["body"] = body

        # 记录请求
        access_logger.info(
            f"{request.method} {request.url.path}",
            extra={"extra_data": request_log}
        )

        # ==================== 处理请求 ====================
        response = None
        status_code = 500
        error_info = None

        try:
            response = await call_next(request)
            status_code = response.status_code

        except Exception as e:
            # 捕获未处理的异常
            status_code = 500
            error_info = {
                "type": type(e).__name__,
                "message": str(e),
                "traceback": traceback.format_exc()
            }

            # 创建错误响应
            from fastapi.responses import JSONResponse
            response = JSONResponse(
                status_code=500,
                content={"detail": f"Internal Server Error: {str(e)}"}
            )

        # ==================== 记录响应信息 ====================
        response_time = (time.time() - start_time) * 1000  # 转换为毫秒

        response_log = {
            "type": "response",
            "request_id": request_id,
            "method": request.method,
            "path": request.url.path,
            "status_code": status_code,
            "response_time_ms": round(response_time, 2),
            "response_time_formatted": _format_response_time(response_time),
            "client_ip": client_ip,
        }

        # 添加错误信息（如果有）
        if error_info:
            response_log["error"] = error_info

        # 记录响应
        log_level = logging.ERROR if status_code >= 500 else logging.WARNING if status_code >= 400 else logging.INFO
        access_logger.log(
            log_level,
            f"{request.method} {request.url.path} - {status_code} - {_format_response_time(response_time)}",
            extra={"extra_data": response_log}
        )

        return response


# ==================== 便捷函数 ====================
def log_request_summary(logger: logging.Logger = access_logger):
    """输出日志摘要"""
    separator = "=" * 60
    logger.info(separator)
    logger.info("Access Log Middleware Enabled")
    logger.info(f"Log file: {ACCESS_LOG_FILE}")
    logger.info(f"Rotation: Daily, keeping 7 days")
    logger.info(f"Format: JSON (file) + Text (console)")
    logger.info(separator)
