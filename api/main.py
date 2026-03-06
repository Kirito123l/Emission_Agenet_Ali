"""FastAPI application entrypoint"""
import logging
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .routes import router
from .logging_config import (
    CachedBodyMiddleware,
    AccessLogMiddleware,
    access_logger,
    log_request_summary
)
from .database import db

# 简单的控制台日志（用于启动/关闭事件）
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Emission Agent API",
    description="Vehicle emission assistant API",
    version="2.2.0",
)

# 添加中间件（注意：FastAPI 中间件是后进先出 LIFO）
# 1. 访问日志中间件（最后添加，最先执行记录响应）
app.add_middleware(AccessLogMiddleware)

# 2. 请求体缓存中间件（先添加，后执行，在日志中间件前缓存请求体）
app.add_middleware(CachedBodyMiddleware)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router, prefix="/api")


@app.get("/test")
async def root_test():
    access_logger.info("[TEST] /test endpoint called")
    return {"status": "ok", "message": "root test ok"}


@app.get("/login")
async def login_page():
    """登录/注册页面"""
    login_file = Path(__file__).parent.parent / "web" / "login.html"
    if login_file.exists():
        return FileResponse(login_file)
    return {"error": "Login page not found"}


web_dir = Path(__file__).parent.parent / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")


@app.on_event("startup")
async def startup_event():
    # 初始化数据库
    await db.init_db()

    print("\n" + "=" * 60)
    print("Emission Agent API started")
    print("=" * 60)
    print("If you see no request logs, ensure you access http://localhost:8000")
    log_request_summary()
    logger.info("=" * 60)
    logger.info("Emission Agent API started")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("API server shut down")
