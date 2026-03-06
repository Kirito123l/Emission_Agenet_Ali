"""API路由"""
import os
import json
import tempfile
import pandas as pd
import logging
import sys
import asyncio
import uuid
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Request, Query
from fastapi.responses import FileResponse, StreamingResponse
from typing import Optional, Dict, Any
from urllib.parse import quote

from .models import (
    ChatRequest, ChatResponse, FilePreviewResponse,
    SessionInfo, SessionListResponse, HistoryResponse, UpdateSessionTitleRequest,
    RegisterRequest, LoginRequest, AuthResponse, UserInfo
)
from .database import db
from .auth import auth_service


from .session import SessionRegistry


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

# 临时文件目录
TEMP_DIR = Path(tempfile.gettempdir()) / "emission_agent"
TEMP_DIR.mkdir(exist_ok=True)


def friendly_error_message(error: Exception) -> str:
    """Convert low-level exceptions to user-friendly actionable messages."""
    text = str(error)
    lower = text.lower()

    connection_signals = [
        "connection error",
        "connecterror",
        "unexpected eof",
        "ssl",
        "tls",
        "timed out",
        "api_connection_error",
    ]
    if any(sig in lower for sig in connection_signals):
        return (
            "上游大模型连接失败（网络/代理异常）。请稍后重试。\n"
            "若问题持续：请检查 HTTP(S)_PROXY 配置、代理服务连通性，"
            "或暂时关闭代理后重试。"
        )

    return f"处理出错: {text}"

def clean_reply_text(reply: str) -> str:
    """清理回复文本，移除JSON等技术内容"""
    import re

    # 移除JSON代码块
    reply = re.sub(r'```json[\s\S]*?```', '', reply)
    reply = re.sub(r'```[\s\S]*?```', '', reply)

    # 移除大块JSON（包含curve或pollutants的）
    reply = re.sub(r'\{[^{}]*"curve"[^{}]*\}', '', reply)
    reply = re.sub(r'\{[^{}]*"pollutants"[^{}]*\}', '', reply)

    # 移除多余的空行
    reply = re.sub(r'\n\s*\n\s*\n', '\n\n', reply)

    return reply.strip()


def normalize_download_file(
    download_file: Optional[Any],
    session_id: str,
    message_id: Optional[str] = None,
    user_id: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """Normalize download metadata to a stable frontend-friendly shape."""
    if not download_file:
        return None

    path: Optional[str] = None
    filename: Optional[str] = None

    if isinstance(download_file, dict):
        path = download_file.get("path")
        filename = download_file.get("filename")
    elif isinstance(download_file, str):
        path = download_file
        filename = Path(download_file).name if download_file else None

    if not filename and path:
        filename = Path(path).name
    if not path and not filename:
        return None

    normalized: Dict[str, Any] = {
        "path": str(path) if path else None,
        "filename": filename,
        "file_id": session_id,
    }
    uid_qs = f"?user_id={quote(user_id)}" if user_id else ""
    if message_id:
        normalized["message_id"] = message_id
        normalized["url"] = f"/api/file/download/message/{session_id}/{message_id}{uid_qs}"
    elif filename:
        normalized["url"] = f"/api/download/{quote(filename)}{uid_qs}"
    return normalized


def attach_download_to_table_data(
    table_data: Optional[Dict[str, Any]],
    download_file: Optional[Dict[str, Any]]
) -> Optional[Dict[str, Any]]:
    """Attach download metadata to table payload so history rendering can keep download buttons."""
    if not table_data or not isinstance(table_data, dict):
        return table_data
    if not download_file:
        return table_data

    enriched = dict(table_data)

    if not enriched.get("download"):
        url = download_file.get("url")
        filename = download_file.get("filename")
        if url and filename:
            enriched["download"] = {"url": url, "filename": filename}

    if not enriched.get("file_id") and download_file.get("file_id"):
        enriched["file_id"] = download_file["file_id"]

    return enriched


def build_emission_chart_data(skill_name: Optional[str], data: Dict) -> Optional[Dict]:
    """Normalize emission-factor results for frontend chart rendering. 支持多种格式。"""
    if not skill_name or not isinstance(data, dict):
        return None

    # 格式1: 标准格式 (有 speed_curve + query_summary)
    if "speed_curve" in data and "query_summary" in data:
        query_summary = data.get("query_summary", {})
        vehicle_type = query_summary.get("vehicle_type", "Unknown")
        model_year = query_summary.get("model_year", 2020)
        pollutant = query_summary.get("pollutant", "NOx")
        speed_curve = data.get("speed_curve", [])

        return {
            "type": "emission_factors",
            "vehicle_type": vehicle_type,
            "model_year": model_year,
            "pollutants": {
                pollutant: {
                    "curve": speed_curve,
                    "unit": data.get("unit", "g/mile")
                }
            },
            "metadata": {
                "data_source": data.get("data_source", ""),
                "speed_range": data.get("speed_range", {}),
                "data_points": data.get("data_points", 0)
            },
            "key_points": extract_key_points({"pollutant": pollutant, "curve": speed_curve})
        }

    # 格式2: 多污染物格式 (只有 pollutants)
    if skill_name == "query_emission_factors" and "pollutants" in data:
        pollutants_data = data.get("pollutants", {})
        if isinstance(pollutants_data, dict):
            # 标准化每个污染物的数据格式：将 speed_curve 转换为 curve
            normalized_pollutants = {}
            for pollutant, poll_data in pollutants_data.items():
                if isinstance(poll_data, dict):
                    # 如果有 speed_curve 但没有 curve，进行转换
                    if "speed_curve" in poll_data and "curve" not in poll_data:
                        # 转换 speed_curve 为 curve 格式（g/mile -> g/km）
                        speed_curve = poll_data.get("speed_curve", [])
                        curve = []
                        for point in speed_curve:
                            curve.append({
                                "speed_kph": point.get("speed_kph", 0),
                                "emission_rate": round(point.get("emission_rate", 0) / 1.60934, 4)  # g/mile -> g/km
                            })
                        normalized_pollutants[pollutant] = {
                            "curve": curve,
                            "unit": "g/km"
                        }
                    else:
                        # 已经是正确格式，直接使用
                        normalized_pollutants[pollutant] = poll_data

            return {
                "type": "emission_factors",
                "vehicle_type": data.get("vehicle_type", "Unknown"),
                "model_year": data.get("model_year", 2020),
                "pollutants": normalized_pollutants,
                "metadata": data.get("metadata", {}),
                "key_points": extract_key_points(normalized_pollutants)
            }

    # 格式3: 嵌套在 data 字段中
    if "data" in data and isinstance(data["data"], dict):
        return build_emission_chart_data(skill_name, data["data"])

    # 格式4: 直接是曲线数据
    if "curve" in data or "emission_curve" in data:
        curve = data.get("curve") or data.get("emission_curve", [])
        return {
            "type": "emission_factors",
            "vehicle_type": data.get("vehicle_type", "Unknown"),
            "model_year": data.get("model_year", 2020),
            "pollutants": {
                "default": {"curve": curve, "unit": "g/km"}
            },
            "metadata": {},
            "key_points": extract_key_points({"default": {"curve": curve}})
        }

    logger.warning(f"无法识别的图表数据格式: {list(data.keys())}")
    return None


def extract_key_points(pollutants_data) -> list:
    """Extract key speed points (30/60/90 km/h) for table display."""
    if not pollutants_data:
        return []

    # New format: {"pollutant": name, "curve": [...]}
    if isinstance(pollutants_data, dict) and "curve" in pollutants_data:
        pollutant = pollutants_data.get("pollutant", "Unknown")
        curve = pollutants_data.get("curve", [])
        return _pick_key_points(curve, pollutant)

    # Legacy format: {"NOx": {"curve": [...]}, ...}
    if isinstance(pollutants_data, dict):
        for pollutant, info in pollutants_data.items():
            curve = info.get("curve", []) if isinstance(info, dict) else []
            if curve:
                return _pick_key_points(curve, pollutant)

    return []

def _pick_key_points(curve, pollutant: str) -> list:
    if not curve:
        return []
    targets = [30, 60, 90]
    labels = ["City Congestion", "City Cruise", "Highway"]
    points = []
    for target, label in zip(targets, labels):
        closest = min(curve, key=lambda p: abs(p.get("speed_kph", 0) - target))
        points.append({
            "speed": closest.get("speed_kph"),
            "rate": closest.get("emission_rate"),
            "label": label,
            "pollutant": pollutant
        })
    return points

@router.post("/chat", response_model=ChatResponse)
async def chat(
    request: Request,
    message: str = Form(...),
    session_id: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None)
):
    """
    发送消息并获取回复

    支持：
    - 纯文本消息
    - 带Excel文件的消息（用于轨迹计算或路段计算）
    """
    import sys
    sys.stdout.write(f"\n{'='*60}\n")
    sys.stdout.write("🔵 收到聊天请求\n")
    sys.stdout.write(f"📝 消息: {message[:100]}...\n")
    sys.stdout.write(f"🆔 会话ID: {session_id}\n")
    sys.stdout.write(f"📎 文件: {file.filename if file else 'None'}\n")
    sys.stdout.write(f"{'='*60}\n")
    sys.stdout.flush()

    try:
        # 获取或创建会话
        user_id = get_user_id(request)
        mgr = SessionRegistry.get(user_id)
        session = mgr.get_or_create_session(session_id)

        # 处理上传的文件
        input_file_path = None
        output_file_path = None

        if file:
            # 保存上传的文件
            suffix = Path(file.filename).suffix
            input_file_path = TEMP_DIR / f"{session.session_id}_input{suffix}"
            with open(input_file_path, "wb") as f:
                content = await file.read()
                f.write(content)

            # 准备输出文件路径
            output_file_path = TEMP_DIR / f"{session.session_id}_output.xlsx"

            # 在消息中添加文件信息 - 使用明确的格式让Agent识别
            message = f"{message}\n\n文件已上传，路径: {str(input_file_path)}\n请使用 input_file 参数处理此文件。"

        # 调用Router处理消息
        logger.info(f"调用Router处理消息...")
        result = await session.chat(message, input_file_path)
        logger.info(f"Router回复: {result['text'][:100] if result['text'] else 'None'}...")

        # 更新会话信息
        session.message_count += 1
        session.updated_at = datetime.now().isoformat()
        mgr.update_session_title(session.session_id, message)

        # 从RouterResponse提取数据
        reply_text = result.get("text", "")
        chart_data = result.get("chart_data")
        table_data = result.get("table_data")
        assistant_message_id = uuid.uuid4().hex[:12]
        download_file = normalize_download_file(
            result.get("download_file"),
            session.session_id,
            assistant_message_id,
            user_id
        )

        logger.info(f"[DEBUG API] download_file from router: {download_file}")
        logger.info(f"[DEBUG API] download_file type: {type(download_file)}")
        logger.info(f"[DEBUG API] download_file bool: {bool(download_file)}")

        # 确定数据类型
        data_type = None
        if chart_data:
            data_type = "chart"
        elif table_data:
            data_type = "table"

        # 将下载信息绑定到表格数据，确保历史消息也能渲染下载按钮
        table_data = attach_download_to_table_data(table_data, download_file)

        # 如果有下载文件，更新session
        if download_file:
            session.last_result_file = download_file

        # 构建响应
        response = ChatResponse(
            reply=clean_reply_text(reply_text),
            session_id=session.session_id,
            success=True,
            data_type=data_type,
            chart_data=chart_data,
            table_data=table_data,
            file_id=session.session_id if download_file else None,
            download_file=download_file,
            message_id=assistant_message_id
        )

        # 保存对话历史到Session
        session.save_turn(
            user_input=message,
            assistant_response=reply_text,
            chart_data=chart_data,
            table_data=table_data,
            data_type=data_type,
            file_id=session.session_id if download_file else None,  # 添加 file_id
            download_file=download_file,
            message_id=assistant_message_id
        )

        mgr.save_session()

        logger.info(f"=== 请求处理完成 ===")
        return response

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
    file: Optional[UploadFile] = File(None)
):
    """
    流式聊天接口 - 实时返回响应

    支持：
    - 实时状态更新
    - 逐步文本输出
    - 图表和表格数据
    """
    user_id = get_user_id(request)
    mgr = SessionRegistry.get(user_id)

    async def generate():
        try:
            # 1. 发送"思考中"状态
            yield json.dumps({
                "type": "status",
                "content": "正在理解您的问题..."
            }, ensure_ascii=False) + "\n"
            await asyncio.sleep(0.1)

            # 2. 获取或创建会话
            session = mgr.get_or_create_session(session_id)

            # 3. 处理上传的文件
            input_file_path = None
            output_file_path = None

            if file:
                yield json.dumps({
                    "type": "status",
                    "content": "正在处理上传的文件..."
                }, ensure_ascii=False) + "\n"
                await asyncio.sleep(0.1)

                # 保存上传的文件
                suffix = Path(file.filename).suffix
                input_file_path = TEMP_DIR / f"{session.session_id}_input{suffix}"
                with open(input_file_path, "wb") as f:
                    content = await file.read()
                    f.write(content)

                # 准备输出文件路径
                output_file_path = TEMP_DIR / f"{session.session_id}_output.xlsx"

                # 在消息中添加文件信息
                message_with_file = f"{message}\n\n文件已上传，路径: {str(input_file_path)}\n请使用 input_file 参数处理此文件。"
            else:
                message_with_file = message

            # 4. Planning阶段
            yield json.dumps({
                "type": "status",
                "content": "正在分析任务..."
            }, ensure_ascii=False) + "\n"
            await asyncio.sleep(0.1)

            # 5. 调用Router处理（带心跳保活）
            heartbeat_msg = json.dumps({"type": "heartbeat"}, ensure_ascii=False) + "\n"
            chat_task = asyncio.create_task(session.chat(message_with_file, input_file_path))
            while not chat_task.done():
                try:
                    result = await asyncio.wait_for(asyncio.shield(chat_task), timeout=15)
                    break
                except asyncio.TimeoutError:
                    yield heartbeat_msg
            else:
                result = chat_task.result()

            # 6. 流式输出最终文本
            reply_text = result.get("text", "")
            reply_text_clean = clean_reply_text(reply_text)
            chunk_size = 20  # 每次发送20个字符

            for i in range(0, len(reply_text_clean), chunk_size):
                chunk = reply_text_clean[i:i+chunk_size]
                yield json.dumps({
                    "type": "text",
                    "content": chunk
                }, ensure_ascii=False) + "\n"
                await asyncio.sleep(0.05)  # 模拟打字效果

            # 7. 处理图表/表格数据（从RouterResponse直接获取）
            chart_data = result.get("chart_data")
            table_data = result.get("table_data")
            assistant_message_id = uuid.uuid4().hex[:12]
            download_file = normalize_download_file(
                result.get("download_file"),
                session.session_id,
                assistant_message_id,
                user_id
            )

            logger.info(f"[DEBUG STREAM] download_file from router: {download_file}")
            logger.info(f"[DEBUG STREAM] download_file type: {type(download_file)}")
            logger.info(f"[DEBUG STREAM] download_file bool: {bool(download_file)}")

            # 确定数据类型（优先级：chart > table）
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
                table_data = attach_download_to_table_data(table_data, download_file)
                yield json.dumps({
                    "type": "table",
                    "content": table_data
                }, ensure_ascii=False) + "\n"

            # 如果有下载文件，更新session
            if download_file:
                session.last_result_file = download_file

            # 8. 更新会话信息
            session.message_count += 1
            session.updated_at = datetime.now().isoformat()
            mgr.update_session_title(session.session_id, message)

            # 9. 保存对话历史
            session.save_turn(
                user_input=message,
                assistant_response=reply_text,
                chart_data=chart_data,
                table_data=table_data,
                data_type=data_type,
                file_id=session.session_id if download_file else None,  # 添加 file_id
                download_file=download_file,
                message_id=assistant_message_id
            )
            mgr.save_session()

            # 10. 发送完成信号
            yield json.dumps({
                "type": "done",
                "session_id": session.session_id,
                "file_id": session.session_id if download_file else None,
                "download_file": download_file,
                "message_id": assistant_message_id
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
    预览上传的Excel文件（前5行）

    用于在发送前让用户确认文件内容
    """
    logger.info(f"=== 文件预览请求 ===")
    logger.info(f"文件名: {file.filename}")

    try:
        # 读取文件
        content = await file.read()

        # 根据文件类型读取
        suffix = Path(file.filename).suffix.lower()
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
        if file_path_raw:
            file_path = Path(file_path_raw)
        else:
            from config import get_config
            config = get_config()
            file_path = config.outputs_dir / filename
    else:
        file_path = Path(session.last_result_file)
        filename = f"emission_result_{file_id}.xlsx"

    if not file_path.exists():
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
        if path_raw:
            file_path = Path(path_raw)

    if not file_path:
        td = target.get("table_data")
        if isinstance(td, dict):
            td_download = td.get("download")
            if isinstance(td_download, dict):
                filename = filename or td_download.get("filename")
        if filename:
            from config import get_config
            config = get_config()
            file_path = config.outputs_dir / filename

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
        msg_copy = dict(msg)
        if msg_copy.get("role") == "assistant":
            if not msg_copy.get("message_id"):
                msg_copy["message_id"] = f"legacy-{idx}"
            if not msg_copy.get("download_file"):
                td = msg_copy.get("table_data")
                if isinstance(td, dict):
                    td_download = td.get("download")
                    if isinstance(td_download, dict) and td_download.get("filename"):
                        filename = td_download.get("filename")
                        download_meta = {
                            "filename": filename,
                            "url": f"/api/file/download/message/{session_id}/{msg_copy['message_id']}",
                            "file_id": session_id
                        }
                        from config import get_config
                        config = get_config()
                        download_meta["path"] = str(config.outputs_dir / filename)
                        msg_copy["download_file"] = download_meta
            if not msg_copy.get("file_id") and msg_copy.get("download_file"):
                msg_copy["file_id"] = session_id
        normalized_messages.append(msg_copy)
    logger.info(f"📝 历史消息数量: {len(messages)}")

    # 添加调试日志
    import sys
    for i, msg in enumerate(normalized_messages):
        if msg.get('role') == 'assistant':
            has_chart = msg.get('chart_data') is not None
            has_table = msg.get('table_data') is not None
            sys.stdout.write(f"[DEBUG] 历史消息{i}: role=assistant, chart_data={has_chart}, table_data={has_table}, data_type={msg.get('data_type')}\n")
            sys.stdout.flush()

    logger.info(f"{'='*60}\n")

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
    """测试端点 - 验证日志是否工作"""
    import sys
    sys.stdout.write("\n" + "="*60 + "\n")
    sys.stdout.write("🧪 测试端点被调用\n")
    sys.stdout.write("="*60 + "\n")
    sys.stdout.flush()
    print("🧪 使用print输出", flush=True)
    logger.info("🧪 使用logger输出")
    return {
        "status": "ok",
        "message": "测试成功 - 如果你在终端看到这条消息的日志，说明日志系统正常工作",
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
