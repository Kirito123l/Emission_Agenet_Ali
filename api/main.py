"""FastAPI application entrypoint"""
import logging
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes import router

LOG_DIR = Path(__file__).parent.parent / "logs"
LOG_DIR.mkdir(exist_ok=True)
REQUEST_LOG_FILE = LOG_DIR / "requests.log"


def _write_request_log(line: str) -> None:
    try:
        with open(REQUEST_LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        # Avoid crashing on logging failures
        pass


logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)
request_logger = logging.getLogger("request")
request_logger.setLevel(logging.INFO)

app = FastAPI(
    title="Emission Agent API",
    description="Vehicle emission assistant API",
    version="2.2.0",
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    print("\n" + "=" * 60, flush=True)
    print(f"[REQUEST] {request.method} {request.url.path}", flush=True)
    print("=" * 60, flush=True)
    _write_request_log(f"[REQUEST] {request.method} {request.url.path}")

    response = await call_next(request)

    print(f"[RESPONSE] {response.status_code}", flush=True)
    print("=" * 60 + "\n", flush=True)
    _write_request_log(f"[RESPONSE] {response.status_code} {request.url.path}")

    return response


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
    _write_request_log("[TEST] /test called")
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
    print(f"Request log file: {REQUEST_LOG_FILE}")
    print("=" * 60 + "\n")
    logger.info("=" * 60)
    logger.info("Emission Agent API started")
    logger.info("=" * 60)


@app.on_event("shutdown")
async def shutdown_event():
    logger.info("API server shut down")
