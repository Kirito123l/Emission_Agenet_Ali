"""API数据模型"""
from pydantic import BaseModel, EmailStr, Field
from typing import Optional, List, Dict, Any
from datetime import datetime


# ==================== 认证相关模型 ====================

class RegisterRequest(BaseModel):
    """用户注册请求"""
    username: str = Field(..., min_length=3, max_length=50, description="用户名")
    password: str = Field(..., min_length=6, max_length=100, description="密码")
    email: Optional[EmailStr] = Field(None, description="邮箱（可选）")


class LoginRequest(BaseModel):
    """用户登录请求"""
    username: str = Field(..., description="用户名")
    password: str = Field(..., description="密码")


class AuthResponse(BaseModel):
    """认证响应"""
    access_token: str
    token_type: str = "bearer"
    user_id: str
    username: str


class UserInfo(BaseModel):
    """用户信息"""
    id: str
    username: str
    email: Optional[str] = None
    created_at: str
    last_login: Optional[str] = None


# ==================== 聊天相关模型 ====================

class ChatRequest(BaseModel):
    """聊天请求"""
    message: str
    session_id: Optional[str] = None
    # 文件通过multipart/form-data单独上传

class ChatResponse(BaseModel):
    """聊天响应"""
    reply: str
    session_id: str
    data_type: Optional[str] = None  # "text" | "chart" | "table" | "map" | "table_and_map"
    chart_data: Optional[Dict[str, Any]] = None  # 图表数据
    table_data: Optional[Dict[str, Any]] = None  # 表格数据
    map_data: Optional[Dict[str, Any]] = None  # 地图数据
    file_id: Optional[str] = None  # 结果文件ID（用于下载）
    download_file: Optional[Dict[str, Any]] = None  # 下载文件元数据
    message_id: Optional[str] = None  # 助手消息ID（用于消息级下载）
    success: bool = True
    error: Optional[str] = None

class FilePreviewResponse(BaseModel):
    """文件预览响应"""
    filename: str
    size_kb: float
    rows_total: Optional[int] = None
    columns: List[str] = []
    preview_rows: List[Dict[str, Any]] = []  # 前5行数据
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
    map_data: Optional[Dict[str, Any]] = None
    data_type: Optional[str] = None  # "chart" | "table" | "map" | "table_and_map" | None
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
