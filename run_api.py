"""Canonical local API/web entrypoint.

Starts the FastAPI app from `api.main` and serves the browser UI from `web/`.
Use this instead of invoking `uvicorn api.main:app` directly unless you need
custom server flags.
"""
import uvicorn
import logging
import sys
import os

# 配置根日志记录器
logging.basicConfig(
    level=logging.INFO,
    format='%(message)s',
    stream=sys.stdout,
    force=True  # 强制重新配置
)

# 配置所有相关的日志记录器
for logger_name in ['uvicorn', 'uvicorn.access', 'uvicorn.error', 'api', 'api.main', 'api.routes', '__main__']:
    logger = logging.getLogger(logger_name)
    logger.setLevel(logging.INFO)
    logger.propagate = True

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    print("=" * 60)
    print("🌿 Emission Agent API Server")
    print("=" * 60)
    print("服务器启动中...")
    print(f"访问地址: http://localhost:{port}")
    print(f"API文档: http://localhost:{port}/docs")
    print("=" * 60)

    # 配置 uvicorn 日志
    log_config = uvicorn.config.LOGGING_CONFIG
    log_config["formatters"]["default"]["fmt"] = "%(message)s"
    log_config["formatters"]["access"]["fmt"] = "%(message)s"

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info",
        access_log=True,
        log_config=log_config
    )
