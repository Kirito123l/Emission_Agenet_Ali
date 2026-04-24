"""API路由"""
import os
import json
import re
import pandas as pd
import logging
import sys
import asyncio
import uuid
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request, Query
from fastapi.responses import FileResponse, StreamingResponse, Response, JSONResponse
from typing import Optional, Dict, Any

from .models import (
    ChatRequest, ChatResponse, FilePreviewResponse,
    SessionInfo, SessionListResponse, HistoryResponse, UpdateSessionTitleRequest,
    RegisterRequest, LoginRequest, AuthResponse, UserInfo
)
from .database import db
from .auth import auth_service
# Keep extracted helper names imported at module scope so `api.routes.<helper>`
# remains available during staged extraction passes.
from .chart_utils import (
    _pick_key_points,
    build_emission_chart_data,
    extract_key_points,
)
from .response_utils import (
    attach_download_to_table_data,
    clean_reply_text,
    friendly_error_message,
    normalize_download_file,
)


from .session import SessionRegistry
from core.analytical_objective import IncompatibleSessionError
from services.llm_client import LLMClientService
from services.chat_session_service import (
    TEMP_DIR,
    ChatSessionService,
    UnsupportedRouterMode,
    UploadedFileInput,
    build_router_user_message,
    build_session_title_source,
    normalize_router_mode,
    sanitize_uploaded_filename,
)


def get_user_id(request: Request) -> str:
    """Extract user_id from JWT Token or X-User-ID header.

    Priority:
    1. JWT Token (Authorization header) - for authenticated users
    2. X-User-ID header (for guest mode) - sent by frontend
    3. Generate temporary UUID - fallback for guests without frontend ID
    """
    # 1. Try to extract from JWT Token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header.split(" ")[1]
        try:
            payload = auth_service.decode_token(token)
            if payload and "sub" in payload:
                return payload["sub"]
        except Exception:
            pass  # Fall through to other methods

    # 2. Try X-User-ID header (sent by frontend)
    user_id = request.headers.get("X-User-ID")
    if user_id:
        return user_id.strip()

    # 3. Generate temporary UUID for guest
    return str(uuid.uuid4())

# 配置日志
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

# 确保有handler
if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(logging.INFO)
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    handler.setFormatter(formatter)
    logger.addHandler(handler)

router = APIRouter()
INCOMPATIBLE_SESSION_MESSAGE = (
    "Session format incompatible. Please create a new session or run migration script."
)

LEGACY_UPLOADED_FILE_RE = re.compile(
    r"(?P<content>.*?)(?:\n\n文件已上传，路径:\s*(?P<file_path>.+?)\n请使用 input_file 参数处理此文件。\s*)$",
    re.S,
)


def normalize_user_history_message(message: Dict[str, Any]) -> Dict[str, Any]:
    msg_copy = dict(message)
    if msg_copy.get("role") != "user":
        return msg_copy

    content = msg_copy.get("content") or ""
    file_path = msg_copy.get("file_path")
    file_name = sanitize_uploaded_filename(msg_copy.get("file_name"))

    if isinstance(content, str):
        match = LEGACY_UPLOADED_FILE_RE.match(content)
        if match:
            msg_copy["content"] = match.group("content").rstrip()
            file_path = file_path or match.group("file_path").strip()

    if file_path:
        msg_copy["file_path"] = str(file_path)
        if not file_name:
            file_name = sanitize_uploaded_filename(Path(str(file_path)).name)

    if file_name:
        msg_copy["file_name"] = file_name

    return msg_copy


def build_history_download_meta(
    download_candidate: Optional[Any],
    session_id: str,
    message_id: Optional[str],
    user_id: str,
) -> Optional[Dict[str, Any]]:
    normalized = normalize_download_file(download_candidate, session_id, message_id, user_id)
    if normalized:
        return normalized

    filename = None
    if isinstance(download_candidate, dict):
        filename = download_candidate.get("filename")
    elif isinstance(download_candidate, str):
        filename = Path(download_candidate).name if download_candidate else None

    if not filename:
        return None

    from config import get_config
    config = get_config()
    return normalize_download_file(
        {"path": str(config.outputs_dir / filename), "filename": filename},
        session_id,
        message_id,
        user_id,
    )


def resolve_download_path(filename: Optional[str], path_raw: Optional[str]) -> Optional[Path]:
    file_path = Path(path_raw) if path_raw else None
    if file_path and file_path.exists():
        return file_path

    if filename:
        from config import get_config
        candidate = get_config().outputs_dir / filename
        if candidate.exists():
            return candidate

    return file_path


def _truncate_history_snippet(content: Any, limit: int = 100) -> str:
    text = " ".join(str(content or "").split()).strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "..."


def _normalize_generated_session_title(raw_title: Optional[str]) -> Optional[str]:
    title = " ".join(str(raw_title or "").split()).strip()
    if not title:
        return None
    title = title.strip("\"'“”‘’`")
    title = title.rstrip("。！？!?,，：:；;、")
    if not title:
        return None
    has_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in title)
    max_length = 12 if has_cjk else 20
    return title[:max_length].strip() or None


def _build_session_title_prompt(history: list[Dict[str, Any]]) -> Optional[str]:
    snippets: list[str] = []
    for msg in history[:6]:
        role = msg.get("role")
        if role not in {"user", "assistant"}:
            continue
        content = _truncate_history_snippet(msg.get("content"))
        if not content:
            continue
        speaker = "用户" if role == "user" else "助手"
        snippets.append(f"{speaker}：{content}")

    if not snippets:
        return None

    joined = "\n".join(snippets)
    return (
        "请根据以下对话内容，生成一个简洁的对话标题（不超过12个汉字或20个英文字符，"
        "不加引号，不加标点，直接输出标题文字）：\n\n"
        f"{joined}"
    )

@router.post("/chat", response_model=ChatResponse, response_model_exclude_none=True)
async def chat(
    request: Request,
    message: str = Form(...),
    session_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    mode: Optional[str] = Form(None),
):
    """
    发送消息并获取回复

    支持：
    - 纯文本消息
    - 带Excel文件的消息（用于轨迹计算或路段计算）
    - `mode=full|naive|governed_v2`
    """
    try:
        router_mode = normalize_router_mode(mode or request.query_params.get("mode"))
    except UnsupportedRouterMode as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    logger.info(
        "Chat request: message=%r, session=%s, file=%s, mode=%s",
        message[:80],
        session_id,
        file.filename if file else None,
        router_mode,
    )

    try:
        user_id = get_user_id(request)
        mgr = SessionRegistry.get(user_id)

        upload = None
        if file:
            upload = UploadedFileInput(filename=file.filename, content=await file.read())

        logger.info("调用Router处理消息: mode=%s", router_mode)
        service = ChatSessionService(mgr, user_id=user_id)
        turn = await service.process_turn(
            message=message,
            session_id=session_id,
            upload=upload,
            mode=router_mode,
        )
        logger.info("Router回复: %s...", turn.raw_reply[:100] if turn.raw_reply else "None")

        logger.info(f"=== 请求处理完成 ===")
        return ChatResponse(**turn.to_api_response())

    except IncompatibleSessionError as e:
        logger.error("Session format incompatible: %s", str(e), exc_info=True)
        raise HTTPException(status_code=400, detail=INCOMPATIBLE_SESSION_MESSAGE) from e
    except Exception as e:
        logger.error(f"处理请求时出错: {str(e)}", exc_info=True)

        return ChatResponse(
            reply=f"抱歉，{friendly_error_message(e)}",
            session_id=session_id or "",
            success=False,
            error=str(e)
        )

@router.post("/chat/stream")
async def chat_stream(
    request: Request,
    message: str = Form(...),
    session_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    mode: Optional[str] = Form(None),
):
    """
    流式聊天接口 - 实时返回响应

    支持：
    - 实时状态更新
    - 逐步文本输出
    - 图表和表格数据
    - `mode=full|naive|governed_v2`
    """
    user_id = get_user_id(request)
    mgr = SessionRegistry.get(user_id)
    try:
        router_mode = normalize_router_mode(mode or request.query_params.get("mode"))
    except UnsupportedRouterMode as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if session_id and router_mode != "naive":
        try:
            mgr.get_or_create_session(session_id).agent_router
        except IncompatibleSessionError as exc:
            raise HTTPException(status_code=400, detail=INCOMPATIBLE_SESSION_MESSAGE) from exc

    async def generate():
        try:
            # 1. 发送"思考中"状态
            yield json.dumps({
                "type": "status",
                "content": "正在理解您的问题..."
            }, ensure_ascii=False) + "\n"
            await asyncio.sleep(0.1)

            upload = None
            if file:
                yield json.dumps({
                    "type": "status",
                    "content": "正在处理上传的文件..."
                }, ensure_ascii=False) + "\n"
                await asyncio.sleep(0.1)
                upload = UploadedFileInput(filename=file.filename, content=await file.read())

            # 4. Planning阶段
            yield json.dumps({
                "type": "status",
                "content": "正在分析任务..."
            }, ensure_ascii=False) + "\n"
            await asyncio.sleep(0.1)

            # 5. 调用Router处理（带心跳保活）
            heartbeat_msg = json.dumps({"type": "heartbeat"}, ensure_ascii=False) + "\n"
            service = ChatSessionService(mgr, user_id=user_id)
            chat_task = asyncio.create_task(
                service.process_turn(
                    message=message,
                    session_id=session_id,
                    upload=upload,
                    mode=router_mode,
                )
            )
            while not chat_task.done():
                try:
                    turn = await asyncio.wait_for(asyncio.shield(chat_task), timeout=15)
                    break
                except asyncio.TimeoutError:
                    yield heartbeat_msg
            else:
                turn = chat_task.result()

            # 6. 流式输出最终文本
            reply_text_clean = turn.reply
            chunk_size = 20  # 每次发送20个字符

            for i in range(0, len(reply_text_clean), chunk_size):
                chunk = reply_text_clean[i:i+chunk_size]
                yield json.dumps({
                    "type": "text",
                    "content": chunk
                }, ensure_ascii=False) + "\n"
                await asyncio.sleep(0.05)  # 模拟打字效果

            # 7. 处理图表/表格/地图数据（从RouterResponse直接获取）
            chart_data = turn.chart_data
            table_data = turn.table_data
            map_data = turn.map_data
            logger.debug(
                "stream: download_file=%s, table_data=%s, map_data=%s",
                bool(turn.download_file),
                bool(table_data),
                bool(map_data),
            )

            # 确定数据类型（优先级：chart > table > map）
            data_type = None
            if chart_data:
                data_type = "chart"
                yield json.dumps({
                    "type": "chart",
                    "content": chart_data
                }, ensure_ascii=False) + "\n"

            # 独立发送表格数据（可以与图表共存）
            if table_data:
                if not data_type:  # 如果没有图表，设置 data_type 为 table
                    data_type = "table"
                yield json.dumps({
                    "type": "table",
                    "content": table_data,
                    "download_file": turn.download_file,
                    "file_id": turn.file_id,
                }, ensure_ascii=False) + "\n"

            # 发送地图数据
            if map_data:
                if not data_type:
                    data_type = "map"
                elif data_type == "table":
                    data_type = "table_and_map"
                yield json.dumps({
                    "type": "map",
                    "content": map_data
                }, ensure_ascii=False) + "\n"

            # 10. 发送完成信号
            yield json.dumps({
                "type": "done",
                "session_id": turn.session_id,
                "mode": router_mode,
                "file_id": turn.file_id,
                "download_file": turn.download_file,
                "map_data": map_data,
                "message_id": turn.message_id,
                "trace_friendly": turn.trace_friendly,
            }, ensure_ascii=False) + "\n"

        except IncompatibleSessionError:
            logger.error("流式处理出错: incompatible session", exc_info=True)
            yield json.dumps({
                "type": "error",
                "content": INCOMPATIBLE_SESSION_MESSAGE
            }, ensure_ascii=False) + "\n"
        except Exception as e:
            logger.error(f"流式处理出错: {str(e)}", exc_info=True)
            yield json.dumps({
                "type": "error",
                "content": friendly_error_message(e)
            }, ensure_ascii=False) + "\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # 禁用nginx缓冲
        }
    )

@router.post("/file/preview", response_model=FilePreviewResponse)
async def preview_file(file: UploadFile = File(...)):
    """
    预览上传的Excel文件（前5行）或 Shapefile 压缩包

    用于在发送前让用户确认文件内容
    """
    logger.info(f"=== 文件预览请求 ===")
    logger.info(f"文件名: {file.filename}")

    try:
        # 读取文件
        content = await file.read()

        # 根据文件类型读取
        suffix = Path(file.filename).suffix.lower()

        # 处理 zip 文件（Shapefile）
        if suffix == ".zip":
            return FilePreviewResponse(
                filename=file.filename,
                size_kb=len(content) / 1024,
                rows_total=None,
                columns=[],
                preview_rows=[],
                detected_type="shapefile",
                warnings=["Shapefile 压缩包，将自动提取几何信息"]
            )

        # 处理 CSV 和 Excel 文件
        if suffix == ".csv":
            df = pd.read_csv(pd.io.common.BytesIO(content))
        else:
            df = pd.read_excel(pd.io.common.BytesIO(content))

        # 检测文件类型
        columns_lower = [c.lower() for c in df.columns]

        if any("speed" in c or "速度" in c or "车速" in c for c in columns_lower):
            detected_type = "trajectory"
            warnings = []
            if not any("acc" in c or "加速度" in c for c in columns_lower):
                warnings.append("未找到加速度列，将自动计算")
            if not any("grade" in c or "坡度" in c for c in columns_lower):
                warnings.append("未找到坡度列，默认使用0%")
        elif any("length" in c or "长度" in c for c in columns_lower):
            detected_type = "links"
            warnings = []
        else:
            detected_type = "unknown"
            warnings = ["无法识别文件类型"]

        return FilePreviewResponse(
            filename=file.filename,
            size_kb=len(content) / 1024,
            rows_total=len(df),
            columns=list(df.columns),
            preview_rows=df.head(5).to_dict(orient="records"),
            detected_type=detected_type,
            warnings=warnings
        )

    except Exception as e:
        raise HTTPException(status_code=400, detail=f"文件解析失败: {str(e)}")

# GIS底图缓存
_GIS_BASEMAP_CACHE = None
_GIS_ROADNETWORK_CACHE = None


@router.get("/gis/basemap")
async def get_gis_basemap():
    """
    获取上海市行政区划底图（GeoJSON格式）

    返回16个行政区划的多边形边界，用作地图底图参考层
    使用预处理的 GeoJSON 文件，无需实时读取 Shapefile
    """
    global _GIS_BASEMAP_CACHE

    # Return cached data if available
    if _GIS_BASEMAP_CACHE is not None:
        return _GIS_BASEMAP_CACHE

    try:
        from pathlib import Path

        # Path to preprocessed GeoJSON file
        geojson_path = Path("static_gis/basemap.geojson")

        if not geojson_path.exists():
            return JSONResponse(
                content={"error": "GIS底图文件不存在", "available": False},
                status_code=200  # Return 200 to prevent frontend errors
            )

        # Read preprocessed GeoJSON file
        with open(geojson_path, 'r', encoding='utf-8') as f:
            geojson_content = f.read()

        # Cache the result
        _GIS_BASEMAP_CACHE = Response(
            content=geojson_content,
            media_type="application/geo+json",
            headers={"Cache-Control": "public, max-age=86400"}  # Cache for 24 hours
        )

        return _GIS_BASEMAP_CACHE

    except Exception as e:
        logger.exception(f"[GIS] Failed to load basemap: {e}")
        return JSONResponse(
            content={"error": f"加载GIS底图失败: {str(e)}", "available": False},
            status_code=200
        )


@router.get("/gis/roadnetwork")
async def get_gis_roadnetwork():
    """
    获取上海市路网底图（简化版GeoJSON格式）

    返回简化后的道路网络，用作地图底图参考层
    使用预处理的 GeoJSON 文件，无需实时读取 Shapefile
    """
    global _GIS_ROADNETWORK_CACHE

    # Return cached data if available
    if _GIS_ROADNETWORK_CACHE is not None:
        return _GIS_ROADNETWORK_CACHE

    try:
        from pathlib import Path

        # Path to preprocessed GeoJSON file
        geojson_path = Path("static_gis/roadnetwork.geojson")

        if not geojson_path.exists():
            return JSONResponse(
                content={"error": "GIS路网文件不存在", "available": False},
                status_code=200
            )

        # Read preprocessed GeoJSON file
        with open(geojson_path, 'r', encoding='utf-8') as f:
            geojson_content = f.read()

        # Cache the result
        _GIS_ROADNETWORK_CACHE = Response(
            content=geojson_content,
            media_type="application/geo+json",
            headers={"Cache-Control": "public, max-age=86400"}  # Cache for 24 hours
        )

        return _GIS_ROADNETWORK_CACHE

    except Exception as e:
        logger.exception(f"[GIS] Failed to load road network: {e}")
        return JSONResponse(
            content={"error": f"加载GIS路网失败: {str(e)}", "available": False},
            status_code=200
        )


@router.get("/file/download/{file_id}")
async def download_file(file_id: str, request: Request, user_id: Optional[str] = Query(None)):
    """下载结果文件"""
    uid = user_id or get_user_id(request)
    session = SessionRegistry.get(uid).get_session(file_id)
    if not session or not session.last_result_file:
        raise HTTPException(status_code=404, detail="文件不存在")

    # 处理两种格式：dict (新格式) 或 str (旧格式)
    if isinstance(session.last_result_file, dict):
        filename = session.last_result_file.get('filename', f"emission_result_{file_id}.xlsx")
        file_path_raw = session.last_result_file.get('path')
        file_path = resolve_download_path(filename, file_path_raw)
    else:
        file_path = Path(session.last_result_file)
        filename = f"emission_result_{file_id}.xlsx"
        if not file_path.exists():
            file_path = resolve_download_path(filename, None)

    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )


@router.get("/file/download/message/{session_id}/{message_id}")
async def download_file_by_message(session_id: str, message_id: str, request: Request, user_id: Optional[str] = Query(None)):
    """按消息ID下载结果文件（消息级持久下载）"""
    uid = user_id or get_user_id(request)
    session = SessionRegistry.get(uid).get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在")

    target = None
    for idx, msg in enumerate(session._history):
        if msg.get("role") != "assistant":
            continue
        mid = msg.get("message_id")
        if mid == message_id:
            target = msg
            break
        if not mid and message_id == f"legacy-{idx}":
            target = msg
            break

    if not target:
        raise HTTPException(status_code=404, detail="消息不存在")

    download_meta = target.get("download_file")
    file_path = None
    filename = None

    if isinstance(download_meta, dict):
        filename = download_meta.get("filename")
        path_raw = download_meta.get("path")
        file_path = resolve_download_path(filename, path_raw)

    if not file_path or not file_path.exists():
        td = target.get("table_data")
        if isinstance(td, dict):
            td_download = td.get("download")
            if isinstance(td_download, dict):
                filename = filename or td_download.get("filename")
        if filename:
            file_path = resolve_download_path(filename, None)

    if not file_path or not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")

    if not filename:
        filename = file_path.name

    return FileResponse(
        path=file_path,
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@router.get("/download/{filename}")
async def download_result_file(filename: str):
    """下载计算结果文件（从outputs目录）"""
    from config import get_config
    config = get_config()
    outputs_dir = config.outputs_dir

    # 安全检查：只允许下载 outputs 目录下的文件
    file_path = outputs_dir / filename

    # 防止路径遍历攻击
    if not str(file_path.resolve()).startswith(str(outputs_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    return FileResponse(
        path=str(file_path),
        filename=filename,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@router.get("/file/template/{template_type}")
async def download_template(template_type: str):
    """下载模板文件"""
    templates = {
        "trajectory": {
            "columns": ["t", "speed_kph", "acceleration_mps2", "grade_pct"],
            "data": [
                [0, 0, 0, 0],
                [1, 5, 1.39, 0],
                [2, 12, 1.94, 0],
                [3, 20, 2.22, 0],
                [4, 28, 2.22, 0],
            ]
        },
        "links": {
            "columns": ["link_id", "link_length_km", "traffic_flow_vph", "avg_speed_kph", "乘用车%", "公交车%", "货车%"],
            "data": [
                ["Link_1", 2.5, 5000, 60, 70, 20, 10],
                ["Link_2", 1.8, 3500, 45, 60, 30, 10],
                ["Link_3", 3.2, 6000, 80, 80, 10, 10],
            ]
        }
    }

    if template_type not in templates:
        raise HTTPException(status_code=404, detail="模板不存在")

    template = templates[template_type]
    df = pd.DataFrame(template["data"], columns=template["columns"])

    # 保存到临时文件
    file_path = TEMP_DIR / f"template_{template_type}.xlsx"
    df.to_excel(file_path, index=False)

    return FileResponse(
        path=file_path,
        filename=f"{template_type}_template.xlsx",
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions(request: Request):
    """获取会话列表"""
    user_id = get_user_id(request)
    mgr = SessionRegistry.get(user_id)
    logger.info(f"\n{'='*60}")
    logger.info(f"🔵 收到会话列表请求 (user={user_id})")
    sessions = mgr.list_sessions()
    logger.info(f"📋 返回 {len(sessions)} 个会话")
    if sessions:
        logger.info(f"🆔 会话ID列表: {[s.session_id for s in sessions[:5]]}")
    logger.info(f"{'='*60}\n")
    return SessionListResponse(
        sessions=[
            SessionInfo(
                session_id=s.session_id,
                title=s.title,
                created_at=s.created_at,
                updated_at=s.updated_at,
                message_count=s.message_count
            )
            for s in sessions
        ]
    )

@router.post("/sessions/new")
async def create_session(request: Request):
    """创建新会话"""
    user_id = get_user_id(request)
    session_id = SessionRegistry.get(user_id).create_session()
    return {"session_id": session_id}

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str, request: Request):
    """删除会话"""
    user_id = get_user_id(request)
    SessionRegistry.get(user_id).delete_session(session_id)
    return {"status": "ok"}


@router.patch("/sessions/{session_id}/title")
async def update_session_title(session_id: str, payload: UpdateSessionTitleRequest, request: Request):
    """手动更新会话标题"""
    user_id = get_user_id(request)
    ok = SessionRegistry.get(user_id).set_session_title(session_id, payload.title)
    if not ok:
        raise HTTPException(status_code=400, detail="标题不能为空或会话不存在")
    return {"status": "ok", "session_id": session_id, "title": payload.title.strip()[:80]}


@router.post("/sessions/{session_id}/generate_title")
async def generate_session_title(session_id: str, request: Request):
    """基于会话前几轮历史生成一个简短语义标题。"""
    user_id = get_user_id(request)
    mgr = SessionRegistry.get(user_id)
    session = mgr.get_session(session_id)
    if not session:
        return {"session_id": session_id, "title": None}

    prompt = _build_session_title_prompt(session._history)
    if not prompt:
        return {"session_id": session_id, "title": None}

    try:
        llm = LLMClientService(purpose="synthesis")
        llm.max_tokens = min(int(getattr(llm, "max_tokens", 30) or 30), 30)
        response = await llm.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.0,
        )
        title = _normalize_generated_session_title(response.content)
        if not title:
            return {"session_id": session_id, "title": None}
        mgr.set_session_title(session_id, title)
        return {"session_id": session_id, "title": title}
    except Exception as exc:
        logger.warning("session title generation failed for %s: %s", session_id, exc)
        return {"session_id": session_id, "title": None}

@router.get("/sessions/{session_id}/history", response_model=HistoryResponse)
async def get_session_history(session_id: str, request: Request):
    """获取会话历史消息"""
    user_id = get_user_id(request)
    mgr = SessionRegistry.get(user_id)
    logger.info(f"\n{'='*60}")
    logger.info(f"🔵 收到历史记录请求 (user={user_id})")
    logger.info(f"🆔 会话ID: {session_id}")

    session = mgr.get_session(session_id)
    if not session:
        logger.error(f"❌ 会话不存在: {session_id}")
        logger.info(f"📋 当前会话列表: {list(mgr.sessions.keys())}")
        logger.info(f"{'='*60}\n")
        raise HTTPException(status_code=404, detail="Session not found")

    logger.info(f"✅ 会话找到，获取历史消息...")
    messages = session._history

    # 回填下载元数据（兼容旧历史记录）
    normalized_messages = []
    for idx, msg in enumerate(messages):
        msg_copy = normalize_user_history_message(msg)
        if msg_copy.get("role") == "assistant":
            if not msg_copy.get("message_id"):
                msg_copy["message_id"] = f"legacy-{idx}"
            download_meta = build_history_download_meta(
                msg_copy.get("download_file"),
                session_id,
                msg_copy["message_id"],
                user_id,
            )
            if not download_meta:
                td = msg_copy.get("table_data")
                if isinstance(td, dict):
                    td_download = td.get("download")
                    if isinstance(td_download, dict) and td_download.get("filename"):
                        from config import get_config
                        config = get_config()
                        filename = td_download.get("filename")
                        download_meta = build_history_download_meta(
                            {
                                "path": str(config.outputs_dir / filename),
                                "filename": filename,
                            },
                            session_id,
                            msg_copy["message_id"],
                            user_id,
                        )
            if download_meta:
                msg_copy["download_file"] = download_meta
                td = msg_copy.get("table_data")
                if isinstance(td, dict):
                    td_copy = dict(td)
                    td_copy["download"] = {
                        "url": download_meta["url"],
                        "filename": download_meta["filename"],
                    }
                    if download_meta.get("file_id"):
                        td_copy["file_id"] = download_meta["file_id"]
                    msg_copy["table_data"] = td_copy
            if not msg_copy.get("file_id") and msg_copy.get("download_file"):
                msg_copy["file_id"] = session_id
        normalized_messages.append(msg_copy)
    logger.info(f"History: {len(messages)} messages for session {session_id}")

    return HistoryResponse(
        session_id=session_id,
        messages=normalized_messages,
        success=True
    )

@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}

@router.get("/test")
async def test_endpoint():
    """测试端点 - 验证API可达性"""
    logger.info("Test endpoint called")
    return {
        "status": "ok",
        "timestamp": datetime.now().isoformat()
    }


# ==================== 认证相关路由 ====================

@router.post("/register", response_model=AuthResponse)
async def register(request_data: RegisterRequest):
    """
    用户注册

    - username: 用户名（3-50字符，唯一）
    - password: 密码（至少6字符）
    - email: 邮箱（可选）
    """
    logger.info(f"注册请求: username={request_data.username}")

    # 检查用户名是否已存在
    existing_user = await db.get_user_by_username(request_data.username)
    if existing_user:
        logger.warning(f"注册失败: 用户名已存在 - {request_data.username}")
        raise HTTPException(status_code=400, detail="用户名已存在")

    # 哈希密码
    password_hash = auth_service.hash_password(request_data.password)

    # 生成用户 ID
    user_id = auth_service.generate_user_id()

    # 创建用户
    success = await db.create_user(
        user_id=user_id,
        username=request_data.username,
        password_hash=password_hash,
        email=request_data.email
    )

    if not success:
        raise HTTPException(status_code=500, detail="用户创建失败")

    # 生成 Token
    access_token = auth_service.create_access_token(
        data={"sub": user_id, "username": request_data.username}
    )

    logger.info(f"用户注册成功: {request_data.username} ({user_id})")

    return AuthResponse(
        access_token=access_token,
        user_id=user_id,
        username=request_data.username
    )


@router.post("/login", response_model=AuthResponse)
async def login(request_data: LoginRequest):
    """
    用户登录

    - username: 用户名
    - password: 密码
    """
    logger.info(f"登录请求: username={request_data.username}")

    # 获取用户
    user = await db.get_user_by_username(request_data.username)
    if not user:
        logger.warning(f"登录失败: 用户不存在 - {request_data.username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 验证密码
    if not auth_service.verify_password(request_data.password, user["password_hash"]):
        logger.warning(f"登录失败: 密码错误 - {request_data.username}")
        raise HTTPException(status_code=401, detail="用户名或密码错误")

    # 更新最后登录时间
    await db.update_last_login(user["id"])

    # 生成 Token
    access_token = auth_service.create_access_token(
        data={"sub": user["id"], "username": user["username"]}
    )

    logger.info(f"用户登录成功: {request_data.username} ({user['id']})")

    return AuthResponse(
        access_token=access_token,
        user_id=user["id"],
        username=user["username"]
    )


@router.get("/me", response_model=UserInfo)
async def get_current_user(request: Request):
    """
    获取当前用户信息

    需要在请求头中提供 Authorization: Bearer <token>
    """
    auth_header = request.headers.get("Authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供认证令牌")

    token = auth_header.split(" ")[1]
    payload = auth_service.decode_token(token)

    if not payload:
        raise HTTPException(status_code=401, detail="无效或过期的令牌")

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="令牌格式无效")

    user = await db.get_user_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail="用户不存在")

    return UserInfo(
        id=user["id"],
        username=user["username"],
        email=user.get("email"),
        created_at=user["created_at"],
        last_login=user.get("last_login")
    )
