"""API数据模型"""
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
from datetime import datetime

class ChatRequest(BaseModel):
    """聊天请求"""
    message: str
    session_id: Optional[str] = None
    # 文件通过multipart/form-data单独上传

class ChatResponse(BaseModel):
    """聊天响应"""
    reply: str
    session_id: str
    data_type: Optional[str] = None  # "text" | "chart" | "table" | "chart_and_table"
    chart_data: Optional[Dict[str, Any]] = None  # 图表数据
    table_data: Optional[Dict[str, Any]] = None  # 表格数据
    file_id: Optional[str] = None  # 结果文件ID（用于下载）
    download_file: Optional[Dict[str, Any]] = None  # 下载文件元数据
    message_id: Optional[str] = None  # 助手消息ID（用于消息级下载）
    success: bool = True
    error: Optional[str] = None

class FilePreviewResponse(BaseModel):
    """文件预览响应"""
    filename: str
    size_kb: float
    rows_total: int
    columns: List[str]
    preview_rows: List[Dict[str, Any]]  # 前5行数据
    detected_type: str  # "trajectory" | "links" | "unknown"
    warnings: List[str] = []

class SessionInfo(BaseModel):
    """会话信息"""
    session_id: str
    title: str
    created_at: datetime
    updated_at: datetime
    message_count: int

class Message(BaseModel):
    """单条消息"""
    role: str  # "user" | "assistant"
    content: str
    timestamp: str
    has_data: bool = False
    # 新增字段 - 支持历史消息中的图表和表格数据
    chart_data: Optional[Dict[str, Any]] = None
    table_data: Optional[Dict[str, Any]] = None
    data_type: Optional[str] = None  # "chart" | "table" | None
    message_id: Optional[str] = None  # 消息ID（助手消息）
    file_id: Optional[str] = None  # 历史消息下载ID
    download_file: Optional[Dict[str, Any]] = None  # 历史消息下载元数据


class UpdateSessionTitleRequest(BaseModel):
    """更新会话标题请求"""
    title: str

class HistoryResponse(BaseModel):
    """历史记录响应"""
    session_id: str
    messages: List[Message]
    success: bool = True

class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: List[SessionInfo]
