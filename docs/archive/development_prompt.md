# Emission Agent 前后端开发任务

## 项目概述

这是一个**机动车排放计算助手**的Web应用。后端Agent已开发完成（Phase 1-6），现在需要：
1. 开发FastAPI后端API层
2. 将前端HTML与后端API对接

## 项目位置

```
D:\Agent_MCP\emission_agent\
```

## 当前项目结构

```
emission_agent/
├── agent/                      # Agent核心（已完成）
│   ├── core.py                 # EmissionAgent主类
│   ├── context.py              # 对话上下文管理
│   ├── validator.py            # 计划验证器
│   ├── reflector.py            # 反思修复器
│   ├── learner.py              # 学习器
│   ├── monitor.py              # 性能监控
│   ├── cache.py                # Planning缓存
│   └── prompts/                # 提示词
│
├── skills/                     # 4个核心Skill（已完成）
│   ├── emission_factors/       # 排放因子查询
│   │   ├── skill.py
│   │   ├── calculator.py
│   │   └── excel_handler.py
│   ├── micro_emission/         # 微观排放计算（逐秒轨迹）
│   │   ├── skill.py
│   │   ├── calculator.py
│   │   └── excel_handler.py
│   ├── macro_emission/         # 宏观排放计算（路段级）
│   │   ├── skill.py
│   │   ├── calculator.py
│   │   └── excel_handler.py
│   └── knowledge/              # 知识问答
│       ├── skill.py
│       └── retriever.py
│
├── shared/                     # 共享模块
│   └── standardizer/           # 车型/污染物标准化
│
├── llm/                        # LLM客户端
│   └── client.py
│
├── config.py                   # 配置管理
├── main.py                     # CLI入口
│
├── web/                        # 前端文件（新增）
│   └── index.html              # Stitch生成的HTML（即将放入）
│
└── api/                        # API层（待开发）
    ├── __init__.py
    ├── main.py                 # FastAPI入口
    ├── routes.py               # 路由
    ├── models.py               # Pydantic模型
    └── session.py              # 会话管理
```

---

## 任务一：创建API层

### 1.1 创建 `api/models.py`

```python
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

class SessionListResponse(BaseModel):
    """会话列表响应"""
    sessions: List[SessionInfo]
```

### 1.2 创建 `api/session.py`

```python
"""会话管理"""
import uuid
from typing import Dict, Optional
from datetime import datetime
from agent.core import EmissionAgent

class Session:
    """单个会话"""
    def __init__(self, session_id: str):
        self.session_id = session_id
        self.agent = EmissionAgent()
        self.title = "新对话"
        self.created_at = datetime.now()
        self.updated_at = datetime.now()
        self.message_count = 0
        self.last_result_file: Optional[str] = None  # 最近生成的结果文件路径

class SessionManager:
    """会话管理器"""
    
    def __init__(self):
        self._sessions: Dict[str, Session] = {}
    
    def create_session(self) -> str:
        """创建新会话"""
        session_id = str(uuid.uuid4())[:8]
        self._sessions[session_id] = Session(session_id)
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """获取会话"""
        return self._sessions.get(session_id)
    
    def get_or_create_session(self, session_id: Optional[str]) -> Session:
        """获取或创建会话"""
        if session_id and session_id in self._sessions:
            return self._sessions[session_id]
        
        new_id = session_id or str(uuid.uuid4())[:8]
        self._sessions[new_id] = Session(new_id)
        return self._sessions[new_id]
    
    def update_session_title(self, session_id: str, first_message: str):
        """根据第一条消息更新会话标题"""
        session = self._sessions.get(session_id)
        if session and session.message_count == 1:
            # 取前20个字符作为标题
            session.title = first_message[:20] + ("..." if len(first_message) > 20 else "")
    
    def list_sessions(self) -> list:
        """列出所有会话"""
        return sorted(
            self._sessions.values(),
            key=lambda s: s.updated_at,
            reverse=True
        )
    
    def delete_session(self, session_id: str):
        """删除会话"""
        if session_id in self._sessions:
            del self._sessions[session_id]

# 全局实例
session_manager = SessionManager()
```

### 1.3 创建 `api/routes.py`

```python
"""API路由"""
import os
import tempfile
import pandas as pd
from pathlib import Path
from datetime import datetime
from fastapi import APIRouter, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse
from typing import Optional

from .models import (
    ChatRequest, ChatResponse, FilePreviewResponse,
    SessionInfo, SessionListResponse
)
from .session import session_manager

router = APIRouter()

# 临时文件目录
TEMP_DIR = Path(tempfile.gettempdir()) / "emission_agent"
TEMP_DIR.mkdir(exist_ok=True)

@router.post("/chat", response_model=ChatResponse)
async def chat(
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
    try:
        # 获取或创建会话
        session = session_manager.get_or_create_session(session_id)
        
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
            
            # 在消息中添加文件信息
            message = f"{message}\n[附件: {file.filename}, 输入文件: {input_file_path}, 输出文件: {output_file_path}]"
        
        # 调用Agent
        reply = session.agent.chat(message)
        
        # 更新会话信息
        session.message_count += 1
        session.updated_at = datetime.now()
        session_manager.update_session_title(session.session_id, message)
        
        # 解析返回数据类型
        response = ChatResponse(
            reply=reply,
            session_id=session.session_id,
            success=True
        )
        
        # 检查是否有图表数据（排放因子查询）
        last_result = session.agent._context.last_successful_result
        if last_result:
            skill_name = last_result.get("skill")
            data = last_result.get("data", {})
            
            if skill_name == "query_emission_factors" and "pollutants" in data:
                # 排放因子曲线数据
                response.data_type = "chart"
                response.chart_data = {
                    "type": "emission_factors",
                    "vehicle_type": data.get("vehicle_type"),
                    "model_year": data.get("model_year"),
                    "pollutants": data.get("pollutants"),
                    "metadata": data.get("metadata", {})
                }
            
            elif skill_name in ["calculate_micro_emission", "calculate_macro_emission"]:
                # 计算结果表格
                response.data_type = "table"
                response.table_data = {
                    "type": skill_name,
                    "summary": data.get("summary", {}),
                    "total_emissions": data.get("total_emissions", {}),
                }
                
                # 如果生成了输出文件
                if output_file_path and output_file_path.exists():
                    session.last_result_file = str(output_file_path)
                    response.file_id = session.session_id
                    
                    # 读取前5行作为预览
                    df = pd.read_excel(output_file_path)
                    response.table_data["columns"] = list(df.columns)
                    response.table_data["preview_rows"] = df.head(5).to_dict(orient="records")
                    response.table_data["total_rows"] = len(df)
        
        return response
        
    except Exception as e:
        return ChatResponse(
            reply=f"抱歉，处理出错: {str(e)}",
            session_id=session_id or "",
            success=False,
            error=str(e)
        )

@router.post("/file/preview", response_model=FilePreviewResponse)
async def preview_file(file: UploadFile = File(...)):
    """
    预览上传的Excel文件（前5行）
    
    用于在发送前让用户确认文件内容
    """
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
async def download_file(file_id: str):
    """下载结果文件"""
    session = session_manager.get_session(file_id)
    if not session or not session.last_result_file:
        raise HTTPException(status_code=404, detail="文件不存在")
    
    file_path = Path(session.last_result_file)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    
    return FileResponse(
        path=file_path,
        filename=f"emission_result_{file_id}.xlsx",
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
async def list_sessions():
    """获取会话列表"""
    sessions = session_manager.list_sessions()
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
async def create_session():
    """创建新会话"""
    session_id = session_manager.create_session()
    return {"session_id": session_id}

@router.delete("/sessions/{session_id}")
async def delete_session(session_id: str):
    """删除会话"""
    session_manager.delete_session(session_id)
    return {"status": "ok"}

@router.get("/health")
async def health_check():
    """健康检查"""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}
```

### 1.4 创建 `api/main.py`

```python
"""FastAPI应用入口"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from .routes import router

app = FastAPI(
    title="Emission Agent API",
    description="机动车排放计算助手 API",
    version="2.1.0"
)

# CORS配置
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 开发环境允许所有来源
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API路由
app.include_router(router, prefix="/api")

# 静态文件（前端）
web_dir = Path(__file__).parent.parent / "web"
if web_dir.exists():
    app.mount("/", StaticFiles(directory=web_dir, html=True), name="web")
```

### 1.5 创建 `api/__init__.py`

```python
"""API模块"""
from .main import app
```

### 1.6 创建 `run_api.py`（项目根目录）

```python
"""启动API服务"""
import uvicorn

if __name__ == "__main__":
    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
```

### 1.7 更新 `requirements.txt`

添加以下依赖：
```
fastapi>=0.100.0
uvicorn>=0.22.0
python-multipart>=0.0.6
```

---

## 任务二：前端对接

### 2.1 将HTML文件放入web目录

将 `web.html` 重命名为 `index.html`，放入 `web/` 目录

### 2.2 修改HTML，添加API交互

在HTML的 `<script>` 部分添加以下JavaScript代码：

```javascript
// ==================== API配置 ====================
const API_BASE = 'http://localhost:8000/api';
let currentSessionId = null;
let currentFile = null;

// ==================== DOM元素 ====================
const messagesContainer = document.querySelector('.messages-container') || document.querySelector('[class*="overflow-y-auto"]');
const messageInput = document.querySelector('textarea');
const sendButton = document.querySelector('[class*="bg-primary"][class*="rounded-xl"]');
const attachButton = document.querySelector('[title="Attach file"]') || document.querySelector('[class*="attach"]');
const newChatButton = document.querySelector('.new-calculation-btn') || document.querySelector('button:has(.material-symbols-outlined:contains("add"))');

// 创建隐藏的文件输入
const fileInput = document.createElement('input');
fileInput.type = 'file';
fileInput.accept = '.xlsx,.xls,.csv';
fileInput.style.display = 'none';
document.body.appendChild(fileInput);

// ==================== 事件绑定 ====================

// 发送按钮点击
sendButton?.addEventListener('click', sendMessage);

// Enter发送（Shift+Enter换行）
messageInput?.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        sendMessage();
    }
});

// 附件按钮点击
attachButton?.addEventListener('click', () => fileInput.click());

// 文件选择
fileInput.addEventListener('change', handleFileSelect);

// 新建对话
newChatButton?.addEventListener('click', startNewChat);

// Quick Tools点击
document.querySelectorAll('[class*="Quick Tools"] button, .quick-tools button').forEach(btn => {
    btn.addEventListener('click', () => {
        const toolName = btn.textContent.trim();
        const prompts = {
            'Emission Factors': '查询2020年小汽车的CO2排放因子',
            'Trajectory Calc': '帮我计算车辆轨迹的逐秒排放',
            'Report Templates': '批量计算道路的排放量',
            '查询排放因子': '查询2020年小汽车的CO2排放因子',
            '轨迹排放计算': '帮我计算车辆轨迹的逐秒排放',
            '路段排放计算': '批量计算道路的排放量',
        };
        if (prompts[toolName]) {
            messageInput.value = prompts[toolName];
            messageInput.focus();
        }
    });
});

// ==================== 核心函数 ====================

async function sendMessage() {
    const message = messageInput.value.trim();
    if (!message && !currentFile) return;
    
    // 显示用户消息
    addUserMessage(message, currentFile?.name);
    
    // 清空输入
    messageInput.value = '';
    const fileToSend = currentFile;
    currentFile = null;
    hideFilePreview();
    
    // 显示加载状态
    const loadingEl = addLoadingMessage();
    
    try {
        // 构建FormData
        const formData = new FormData();
        formData.append('message', message);
        if (currentSessionId) {
            formData.append('session_id', currentSessionId);
        }
        if (fileToSend) {
            formData.append('file', fileToSend);
        }
        
        // 发送请求
        const response = await fetch(`${API_BASE}/chat`, {
            method: 'POST',
            body: formData
        });
        
        const data = await response.json();
        
        // 移除加载状态
        loadingEl.remove();
        
        // 保存session_id
        currentSessionId = data.session_id;
        
        // 显示助手回复
        addAssistantMessage(data);
        
    } catch (error) {
        loadingEl.remove();
        addAssistantMessage({
            reply: `抱歉，请求失败: ${error.message}`,
            success: false
        });
    }
}

async function handleFileSelect(e) {
    const file = e.target.files[0];
    if (!file) return;
    
    currentFile = file;
    
    // 预览文件
    try {
        const formData = new FormData();
        formData.append('file', file);
        
        const response = await fetch(`${API_BASE}/file/preview`, {
            method: 'POST',
            body: formData
        });
        
        const preview = await response.json();
        showFilePreview(preview);
        
    } catch (error) {
        showFilePreview({
            filename: file.name,
            size_kb: file.size / 1024,
            rows_total: 0,
            columns: [],
            preview_rows: [],
            detected_type: 'unknown',
            warnings: ['预览加载失败']
        });
    }
    
    // 清空input以便重复选择同一文件
    fileInput.value = '';
}

function startNewChat() {
    currentSessionId = null;
    currentFile = null;
    
    // 清空消息区域（保留时间戳）
    const messages = messagesContainer.querySelectorAll('.message, [class*="flex justify-start"], [class*="flex justify-end"]');
    messages.forEach(m => m.remove());
    
    // 显示欢迎消息
    addWelcomeMessage();
}

// ==================== UI渲染函数 ====================

function addUserMessage(text, filename = null) {
    const html = `
        <div class="flex justify-end gap-4 max-w-4xl ml-auto animate-fade-in-up">
            <div class="flex flex-col gap-2 items-end">
                ${filename ? `
                <div class="flex items-center gap-2 bg-slate-100 dark:bg-slate-700 px-3 py-2 rounded-lg">
                    <span class="material-symbols-outlined text-primary" style="font-size: 20px;">description</span>
                    <div>
                        <p class="text-sm font-medium text-slate-800 dark:text-slate-200">${filename}</p>
                        <p class="text-xs text-slate-500">已解析</p>
                    </div>
                </div>
                ` : ''}
                <div class="bg-primary text-white p-4 rounded-2xl rounded-tr-sm max-w-lg">
                    <p class="text-base leading-relaxed">${escapeHtml(text)}</p>
                </div>
            </div>
            <div class="size-10 rounded-full bg-slate-200 flex items-center justify-center shrink-0">
                <span class="material-symbols-outlined text-slate-600" style="font-size: 20px;">person</span>
            </div>
        </div>
    `;
    messagesContainer.insertAdjacentHTML('beforeend', html);
    scrollToBottom();
}

function addAssistantMessage(data) {
    let contentHtml = `<p class="text-base text-slate-800 dark:text-slate-200 leading-relaxed">${formatMarkdown(data.reply)}</p>`;
    
    // 添加图表（排放因子曲线）
    if (data.data_type === 'chart' && data.chart_data) {
        contentHtml += renderEmissionChart(data.chart_data);
    }
    
    // 添加表格（计算结果）
    if (data.data_type === 'table' && data.table_data) {
        contentHtml += renderResultTable(data.table_data, data.file_id);
    }
    
    const html = `
        <div class="flex justify-start gap-4 max-w-4xl animate-fade-in-up">
            <div class="size-10 rounded-full bg-surface border border-slate-100 shadow-sm flex items-center justify-center shrink-0">
                <span class="text-xl">🌿</span>
            </div>
            <div class="flex flex-col gap-4 flex-1 min-w-0">
                <div class="bg-white dark:bg-slate-800 p-4 rounded-xl">
                    ${contentHtml}
                </div>
            </div>
        </div>
    `;
    messagesContainer.insertAdjacentHTML('beforeend', html);
    scrollToBottom();
    
    // 初始化图表（如果有）
    if (data.data_type === 'chart' && data.chart_data) {
        initEmissionChart(data.chart_data);
    }
}

function addLoadingMessage() {
    const html = `
        <div class="flex justify-start gap-4 max-w-4xl loading-message">
            <div class="size-10 rounded-full bg-surface border border-slate-100 shadow-sm flex items-center justify-center shrink-0">
                <span class="text-xl">🌿</span>
            </div>
            <div class="bg-white dark:bg-slate-800 p-4 rounded-xl">
                <div class="flex items-center gap-2">
                    <div class="flex gap-1">
                        <span class="w-2 h-2 bg-primary rounded-full animate-bounce" style="animation-delay: 0ms;"></span>
                        <span class="w-2 h-2 bg-primary rounded-full animate-bounce" style="animation-delay: 150ms;"></span>
                        <span class="w-2 h-2 bg-primary rounded-full animate-bounce" style="animation-delay: 300ms;"></span>
                    </div>
                    <span class="text-slate-500 text-sm">正在分析...</span>
                </div>
            </div>
        </div>
    `;
    messagesContainer.insertAdjacentHTML('beforeend', html);
    scrollToBottom();
    return messagesContainer.querySelector('.loading-message');
}

function renderEmissionChart(chartData) {
    const pollutants = Object.keys(chartData.pollutants || {});
    const tabs = pollutants.map((p, i) => 
        `<button class="chart-tab px-3 py-1 ${i === 0 ? 'bg-white dark:bg-slate-600 shadow-sm font-bold' : ''} rounded-md text-xs text-slate-800 dark:text-slate-200" data-pollutant="${p}">${p}</button>`
    ).join('');
    
    return `
        <div class="w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm p-6 mt-4">
            <div class="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                    <h3 class="text-slate-900 dark:text-white font-bold text-lg">排放因子曲线</h3>
                    <p class="text-slate-500 text-sm">${chartData.vehicle_type} · ${chartData.model_year}年</p>
                </div>
                <div class="flex bg-slate-100 dark:bg-slate-700 rounded-lg p-1">
                    ${tabs}
                </div>
            </div>
            <div id="emission-chart-${Date.now()}" class="emission-chart" style="height: 300px;"></div>
            <p class="text-xs text-slate-400 mt-2 text-center">鼠标移到曲线上查看具体数值</p>
        </div>
    `;
}

function renderResultTable(tableData, fileId) {
    const columns = tableData.columns || [];
    const rows = tableData.preview_rows || [];
    const totalRows = tableData.total_rows || rows.length;
    
    const headerHtml = columns.map(c => `<th class="px-4 py-3 font-medium text-left">${c}</th>`).join('');
    const rowsHtml = rows.map(row => 
        `<tr class="hover:bg-slate-50 dark:hover:bg-slate-700/50">
            ${columns.map(c => `<td class="px-4 py-3 text-slate-600 dark:text-slate-400">${row[c] ?? ''}</td>`).join('')}
        </tr>`
    ).join('');
    
    const downloadBtn = fileId ? 
        `<button onclick="downloadFile('${fileId}')" class="text-primary hover:text-primary-dark text-xs font-bold flex items-center gap-1">
            <span class="material-symbols-outlined" style="font-size: 16px;">download</span>
            下载Excel
        </button>` : '';
    
    // 汇总信息
    let summaryHtml = '';
    if (tableData.total_emissions) {
        const items = Object.entries(tableData.total_emissions)
            .map(([k, v]) => `${k}: ${typeof v === 'number' ? v.toFixed(2) : v}`)
            .join(' | ');
        summaryHtml = `
            <div class="px-4 py-3 bg-primary/5 text-primary font-medium text-sm">
                汇总: ${items}
            </div>
        `;
    }
    
    return `
        <div class="w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm overflow-hidden mt-4">
            <div class="px-4 py-3 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center bg-slate-50/50">
                <div>
                    <h3 class="font-bold text-slate-800 dark:text-white text-sm">计算结果</h3>
                    <p class="text-xs text-slate-500">显示前5行，共${totalRows}行</p>
                </div>
                ${downloadBtn}
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-sm">
                    <thead class="text-xs text-slate-500 bg-slate-50 dark:bg-slate-700/50 uppercase">
                        <tr>${headerHtml}</tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100 dark:divide-slate-700">
                        ${rowsHtml}
                    </tbody>
                </table>
            </div>
            ${summaryHtml}
        </div>
    `;
}

function showFilePreview(preview) {
    // 创建预览元素（在输入框上方）
    const inputArea = document.querySelector('.input-area') || messageInput.parentElement.parentElement;
    
    let previewEl = document.getElementById('file-preview');
    if (!previewEl) {
        previewEl = document.createElement('div');
        previewEl.id = 'file-preview';
        previewEl.className = 'mb-3 p-4 bg-slate-50 dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700';
        inputArea.insertBefore(previewEl, inputArea.firstChild);
    }
    
    const warningsHtml = preview.warnings?.length ? 
        `<div class="mt-2 text-xs text-orange-500">${preview.warnings.map(w => `⚠️ ${w}`).join('<br>')}</div>` : '';
    
    const columnsHtml = preview.columns?.slice(0, 5).join(', ') + (preview.columns?.length > 5 ? '...' : '');
    
    previewEl.innerHTML = `
        <div class="flex items-center justify-between mb-2">
            <div class="flex items-center gap-2">
                <span class="material-symbols-outlined text-primary">description</span>
                <span class="font-medium text-sm">${preview.filename}</span>
                <span class="text-xs text-slate-500">${preview.size_kb.toFixed(1)} KB · ${preview.rows_total} 行</span>
            </div>
            <button onclick="removeFile()" class="text-slate-400 hover:text-slate-600">
                <span class="material-symbols-outlined" style="font-size: 18px;">close</span>
            </button>
        </div>
        <div class="text-xs text-slate-500">
            <span class="text-primary font-medium">${preview.detected_type === 'trajectory' ? '轨迹文件' : preview.detected_type === 'links' ? '路段文件' : '未知类型'}</span>
            · 列: ${columnsHtml}
        </div>
        ${warningsHtml}
    `;
    previewEl.style.display = 'block';
}

function hideFilePreview() {
    const previewEl = document.getElementById('file-preview');
    if (previewEl) {
        previewEl.style.display = 'none';
    }
}

function removeFile() {
    currentFile = null;
    hideFilePreview();
}

// ==================== 图表初始化 ====================

function initEmissionChart(chartData) {
    // 需要引入ECharts
    const chartEl = document.querySelector('.emission-chart:last-of-type');
    if (!chartEl || typeof echarts === 'undefined') return;
    
    const chart = echarts.init(chartEl);
    const pollutants = chartData.pollutants || {};
    const firstPollutant = Object.keys(pollutants)[0];
    
    if (!firstPollutant) return;
    
    const curveData = pollutants[firstPollutant]?.curve || [];
    
    const option = {
        tooltip: {
            trigger: 'axis',
            formatter: (params) => {
                const p = params[0];
                return `速度: ${p.data[0]} km/h<br/>排放: ${p.data[1].toFixed(2)} g/km`;
            }
        },
        grid: {
            left: '3%',
            right: '4%',
            bottom: '3%',
            containLabel: true
        },
        xAxis: {
            type: 'value',
            name: '速度 (km/h)',
            nameLocation: 'middle',
            nameGap: 30,
            min: 0,
            max: 130
        },
        yAxis: {
            type: 'value',
            name: '排放因子 (g/km)',
            nameLocation: 'middle',
            nameGap: 50
        },
        series: [{
            type: 'line',
            smooth: true,
            data: curveData.map(p => [p.speed_kph, p.emission_rate]),
            lineStyle: { color: '#10b77f', width: 3 },
            areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: 'rgba(16, 183, 127, 0.3)' },
                    { offset: 1, color: 'rgba(16, 183, 127, 0)' }
                ])
            },
            symbol: 'circle',
            symbolSize: 6
        }]
    };
    
    chart.setOption(option);
    
    // 响应式
    window.addEventListener('resize', () => chart.resize());
    
    // Tab切换
    chartEl.parentElement.querySelectorAll('.chart-tab').forEach(tab => {
        tab.addEventListener('click', () => {
            const pollutant = tab.dataset.pollutant;
            const newCurve = pollutants[pollutant]?.curve || [];
            
            // 更新选中状态
            chartEl.parentElement.querySelectorAll('.chart-tab').forEach(t => {
                t.classList.remove('bg-white', 'dark:bg-slate-600', 'shadow-sm', 'font-bold');
            });
            tab.classList.add('bg-white', 'dark:bg-slate-600', 'shadow-sm', 'font-bold');
            
            // 更新图表
            chart.setOption({
                series: [{
                    data: newCurve.map(p => [p.speed_kph, p.emission_rate])
                }]
            });
        });
    });
}

// ==================== 工具函数 ====================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatMarkdown(text) {
    // 简单的Markdown转换
    return text
        .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        .replace(/`(.*?)`/g, '<code class="bg-slate-100 dark:bg-slate-700 px-1 py-0.5 rounded text-sm">$1</code>')
        .replace(/\n/g, '<br>');
}

function scrollToBottom() {
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

async function downloadFile(fileId) {
    window.open(`${API_BASE}/file/download/${fileId}`, '_blank');
}

function addWelcomeMessage() {
    // 可选：添加欢迎消息
}

// ==================== 页面加载完成 ====================
document.addEventListener('DOMContentLoaded', () => {
    console.log('Emission Agent 前端已加载');
    
    // 加载ECharts（如果还没有）
    if (typeof echarts === 'undefined') {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js';
        document.head.appendChild(script);
    }
});
```

---

## 任务三：测试验证

### 3.1 启动服务

```bash
cd D:\Agent_MCP\emission_agent

# 安装新依赖
pip install fastapi uvicorn python-multipart

# 启动API服务
python run_api.py
```

### 3.2 测试API

```bash
# 健康检查
curl http://localhost:8000/api/health

# 发送消息
curl -X POST http://localhost:8000/api/chat \
  -F "message=查询2020年小汽车的CO2排放因子"

# 打开前端
# 浏览器访问 http://localhost:8000
```

### 3.3 测试场景

1. **排放因子查询**
   - 输入："查询2020年小汽车的CO2和NOx排放因子"
   - 预期：返回折线图，可切换污染物

2. **文件上传（轨迹）**
   - 上传trajectory.xlsx
   - 输入："计算这个轨迹的排放"
   - 预期：返回表格预览 + 下载按钮

3. **文件上传（路段）**
   - 上传links.xlsx
   - 输入："计算这些道路的排放"
   - 预期：返回表格预览 + 下载按钮

4. **增量对话**
   - 输入："查询小汽车CO2排放因子"
   - 输入："NOx呢？"
   - 预期：记住车型，只改污染物

---

## 任务四：更新文档

更新 `PROGRESS.md`，添加Phase 7:

```markdown
## Phase 7: Web前端和API ✅

### 7.1 API层开发
- api/main.py - FastAPI入口
- api/routes.py - 路由定义
- api/models.py - 数据模型
- api/session.py - 会话管理

### 7.2 前端对接
- web/index.html - 主页面
- 消息发送和显示
- 文件上传和预览
- 图表渲染（ECharts）
- 表格展示和下载

### 7.3 API端点
- POST /api/chat - 发送消息
- POST /api/file/preview - 文件预览
- GET /api/file/download/{id} - 下载结果
- GET /api/file/template/{type} - 下载模板
- GET /api/sessions - 会话列表
- POST /api/sessions/new - 新建会话
- DELETE /api/sessions/{id} - 删除会话
```

---

## 目录结构（完成后）

```
emission_agent/
├── agent/                      # 已有
├── skills/                     # 已有
├── shared/                     # 已有
├── llm/                        # 已有
├── api/                        # 新增
│   ├── __init__.py
│   ├── main.py
│   ├── routes.py
│   ├── models.py
│   └── session.py
├── web/                        # 新增
│   └── index.html
├── config.py
├── main.py                     # CLI入口
├── run_api.py                  # API启动脚本（新增）
└── requirements.txt            # 更新
```

---

## 注意事项

1. **CORS**: 开发环境允许所有来源，生产环境需要限制
2. **文件清理**: 临时文件需要定期清理
3. **错误处理**: 确保所有API都有适当的错误处理
4. **Session持久化**: 当前是内存存储，重启会丢失，后续可改用数据库

---

## 成功标准

- [ ] API服务正常启动（`python run_api.py`）
- [ ] 健康检查返回正常
- [ ] 前端页面可以访问（http://localhost:8000）
- [ ] 可以发送消息并收到回复
- [ ] 可以上传文件并看到预览
- [ ] 排放因子查询显示折线图
- [ ] 计算结果显示表格并可下载
- [ ] 新建对话正常工作
