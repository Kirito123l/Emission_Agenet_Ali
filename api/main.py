"""FastAPI application entrypoint"""
import logging
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import router
from .logging_config import AccessLogMiddleware, access_logger, log_request_summary

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

# 添加访问日志中间件（记录所有HTTP请求/响应）
app.add_middleware(AccessLogMiddleware)


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


web_dir = Path(__file__).parent.parent / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")


@app.on_event("startup")
async def startup_event():
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
