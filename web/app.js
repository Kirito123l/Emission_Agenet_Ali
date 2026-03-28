// ==================== API配置 ====================
const API_BASE = '/api';
let currentSessionId = null;
let currentFile = null;
const USE_STREAMING = true;  // 是否使用流式输出

// ==================== 用户认证与标识 ====================
// 游客模式状态
let isGuest = true;
let authToken = null;
let username = null;

function generateUUID() {
    return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
        const r = Math.random() * 16 | 0;
        const v = c === 'x' ? r : (r & 0x3 | 0x8);
        return v.toString(16);
    });
}

function getUserId() {
    // 如果已登录且有 Token，从 Token 中解析 user_id
    if (authToken) {
        try {
            const payload = parseJWT(authToken);
            return payload.sub;
        } catch (e) {
            console.error('解析 Token 失败:', e);
        }
    }

    // 游客模式：使用 sessionStorage 存储临时 ID（刷新页面会重置）
    let uid = sessionStorage.getItem('guest_user_id');
    if (!uid) {
        uid = generateUUID();
        sessionStorage.setItem('guest_user_id', uid);
    }
    return uid;
}

function parseJWT(token) {
    // 简单的 JWT 解析（仅解码 payload，不验证签名）
    const parts = token.split('.');
    if (parts.length !== 3) {
        throw new Error('Invalid token format');
    }
    const payload = parts[1];
    const decoded = atob(payload.replace(/-/g, '+').replace(/_/g, '/'));
    return JSON.parse(decoded);
}

function fetchWithUser(url, options = {}) {
    const headers = options.headers instanceof Headers
        ? options.headers
        : new Headers(options.headers || {});

    // 添加 X-User-ID 头
    headers.set('X-User-ID', getUserId());

    // 如果有 Token，添加 Authorization 头
    if (authToken) {
        headers.set('Authorization', `Bearer ${authToken}`);
    }

    return fetch(url, { ...options, headers });
}

// 初始化认证状态
function initAuthState() {
    authToken = localStorage.getItem('auth_token');
    username = localStorage.getItem('username');

    if (authToken && username) {
        // 已登录
        isGuest = false;
        console.log('✅ 已登录用户:', username);
    } else {
        // 游客模式
        isGuest = true;
        console.log('🔵 游客模式');
    }

    // 更新用户界面
    updateUserDisplay();
}

// 更新用户信息显示
function updateUserDisplay() {
    const userDisplayName = document.getElementById('user-display-name');
    if (!userDisplayName) return;

    if (isGuest) {
        // 游客模式
        userDisplayName.innerHTML = `
            <span class="text-slate-500">Guest</span>
            <span class="mx-2 text-slate-300">|</span>
            <a href="/login" class="text-primary hover:underline font-medium">登录 / 注册</a>
        `;
    } else {
        // 已登录
        userDisplayName.innerHTML = `
            <span class="font-medium">${escapeHtml(username)}</span>
            <span class="mx-2 text-slate-300">|</span>
            <button onclick="logout()" class="text-slate-400 hover:text-red-500 transition-colors text-sm">退出</button>
        `;
    }
}

// 退出登录
function logout() {
    if (confirm('确定要退出登录吗？')) {
        localStorage.removeItem('auth_token');
        localStorage.removeItem('user_id');
        localStorage.removeItem('username');
        // 刷新页面进入游客模式
        window.location.reload();
    }
}

// 页面加载时初始化
document.addEventListener('DOMContentLoaded', () => {
    initAuthState();
    ensureLeafletStackingStyles();
});

// ==================== DOM元素 ====================
const messagesContainer = document.getElementById('messages-container');
const messageInput = document.querySelector('#input-area textarea');
const sendButton = document.querySelector('#input-area button[class*="bg-primary"]');
const attachButton = document.querySelector('#input-area button[title="Attach file"]');
const newChatButton = document.querySelector('aside button[class*="bg-primary"]');
const sessionListContainer = document.querySelector('aside .flex.flex-col.gap-1');

// 创建隐藏的文件输入
const fileInput = document.createElement('input');
fileInput.type = 'file';
fileInput.accept = '.xlsx,.xls,.csv,.zip';
fileInput.style.display = 'none';
document.body.appendChild(fileInput);

const LEAFLET_STACK_FIX_STYLE_ID = 'leaflet-stacking-fix';

function ensureLeafletStackingStyles() {
    if (document.getElementById(LEAFLET_STACK_FIX_STYLE_ID)) {
        return;
    }

    const style = document.createElement('style');
    style.id = LEAFLET_STACK_FIX_STYLE_ID;
    style.textContent = `
        .assistant-message-row {
            position: relative;
            z-index: 0;
        }

        .assistant-message-card {
            position: relative;
            z-index: 1;
            isolation: isolate;
        }

        .message-map-wrapper {
            position: relative;
            z-index: 0;
            isolation: isolate;
            overflow: hidden;
        }

        .message-map-surface {
            position: relative;
            z-index: 1;
            isolation: isolate;
        }

        .message-map-container {
            position: relative !important;
            z-index: 1 !important;
            overflow: hidden !important;
            isolation: isolate;
        }

        .message-map-container.leaflet-container,
        .message-map-container .leaflet-container {
            position: relative !important;
            z-index: 1 !important;
        }

        .message-map-container .leaflet-pane,
        .message-map-container .leaflet-tile-pane {
            z-index: 1 !important;
        }

        .message-map-container .leaflet-overlay-pane,
        .message-map-container .leaflet-shadow-pane {
            z-index: 2 !important;
        }

        .message-map-container .leaflet-marker-pane,
        .message-map-container .leaflet-tooltip-pane {
            z-index: 3 !important;
        }

        .message-map-container .leaflet-popup-pane {
            z-index: 4 !important;
        }

        .message-map-container .leaflet-top,
        .message-map-container .leaflet-bottom,
        .message-map-container .leaflet-control {
            z-index: 5 !important;
        }
    `;
    document.head.appendChild(style);
}

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

// ==================== 核心函数 ====================

async function sendMessage() {
    console.log('🚀 sendMessage 函数被调用');
    const message = messageInput.value.trim();
    console.log('📝 消息内容:', message);
    console.log('📎 当前文件:', currentFile);

    if (!message && !currentFile) {
        console.log('⚠️ 消息和文件都为空，返回');
        return;
    }

    // 根据配置选择流式或非流式
    if (USE_STREAMING) {
        return sendMessageStream(message, currentFile);
    }

    // 原有的非流式逻辑
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

        console.log('🌐 准备发送请求到:', `${API_BASE}/chat`);
        console.log('📦 FormData 内容:', {
            message: message,
            session_id: currentSessionId,
            file: fileToSend?.name
        });

        // 发送请求
        console.log('⏳ 开始 fetch...');
        const response = await fetchWithUser(`${API_BASE}/chat`, {
            method: 'POST',
            body: formData
        });
        console.log('✅ fetch 完成，状态码:', response.status);

        const data = await response.json();
        console.log('📥 收到响应数据:', data);
        console.log('  - data_type:', data.data_type);
        console.log('  - chart_data:', data.chart_data);
        console.log('  - reply length:', data.reply?.length);

        // 移除加载状态
        if (loadingEl) {
            loadingEl.remove();
        }

        // 保存session_id
        currentSessionId = data.session_id;

        // 显示助手回复
        addAssistantMessage(data);

        // 重新加载会话列表（更新标题）
        loadSessionList();

    } catch (error) {
        console.error('❌ 请求失败:', error);
        console.error('错误堆栈:', error.stack);
        if (loadingEl) {
            loadingEl.remove();
        }
        addAssistantMessage({
            reply: `抱歉，请求失败: ${error.message}`,
            success: false
        });
    }
}

async function sendMessageStream(message, file) {
    console.log('🚀 sendMessageStream 函数被调用 (流式模式)');

    // 显示用户消息
    addUserMessage(message, file?.name);

    // 清空输入
    messageInput.value = '';
    currentFile = null;
    hideFilePreview();

    // 创建助手消息容器（用于流式填充）
    const assistantMsgId = 'msg-' + Date.now();
    const msgContainer = createAssistantMessageContainer(assistantMsgId);

    // 显示typing indicator
    showTypingIndicator('正在思考...');

    try {
        // 构建FormData
        const formData = new FormData();
        formData.append('message', message);
        if (currentSessionId) {
            formData.append('session_id', currentSessionId);
        }
        if (file) {
            formData.append('file', file);
        }

        console.log('🌐 发送流式请求到:', `${API_BASE}/chat/stream`);

        // 发送流式请求
        const response = await fetchWithUser(`${API_BASE}/chat/stream`, {
            method: 'POST',
            body: formData
        });

        if (!response.ok) {
            throw new Error(`HTTP error! status: ${response.status}`);
        }

        const reader = response.body.getReader();
        const decoder = new TextDecoder();

        let fullText = '';
        let buffer = '';

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;

            // 解码数据
            buffer += decoder.decode(value, { stream: true });

            // 按行分割
            const lines = buffer.split('\n');
            buffer = lines.pop() || '';  // 保留最后一个不完整的行

            for (const line of lines) {
                if (!line.trim()) continue;

                try {
                    const data = JSON.parse(line);

                    switch (data.type) {
                        case 'heartbeat':
                            // 心跳包，忽略
                            break;

                        case 'status':
                            // 更新状态提示
                            showTypingIndicator(data.content);
                            break;

                        case 'text':
                            // 追加文本内容
                            fullText += data.content;
                            updateMessageContent(assistantMsgId, fullText);
                            hideTypingIndicator();
                            break;

                        case 'chart':
                            // 渲染图表
                            hideTypingIndicator();
                            renderChart(data.content, assistantMsgId);
                            break;

                        case 'table':
                            // 渲染表格
                            hideTypingIndicator();
                            console.log('[DEBUG] Table event received:', {
                                content: data.content,
                                assistantMsgId,
                                download_file: data.download_file,
                                file_id: data.file_id
                            });
                            renderTable(
                                data.content,
                                assistantMsgId,
                                data.download_file || null,
                                data.file_id || null
                            );
                            break;

                        case 'map':
                            // 渲染地图
                            hideTypingIndicator();
                            const container = document.getElementById(assistantMsgId);
                            if (container) {
                                renderMapData(data.content, container);
                            }
                            break;

                        case 'done':
                            // 完成，更新session_id
                            hideTypingIndicator();
                            if (data.session_id) {
                                currentSessionId = data.session_id;
                            }
                            // 兼容旧格式：done事件回补下载按钮（新格式通常已在table内渲染）
                            if (data.file_id && !hasAnyDownloadControl(assistantMsgId)) {
                                addDownloadButton(assistantMsgId, data.file_id);
                            }
                            if (Array.isArray(data.trace_friendly) && data.trace_friendly.length > 0) {
                                attachTracePanelToMessage(assistantMsgId, data.trace_friendly);
                            }
                            // 重新加载会话列表
                            loadSessionList();
                            break;

                        case 'error':
                            // 显示错误
                            hideTypingIndicator();
                            updateMessageContent(assistantMsgId, `❌ ${data.content}`);
                            break;
                    }
                } catch (e) {
                    console.error('解析流式数据失败:', e, 'line:', line);
                }
            }
        }

    } catch (error) {
        console.error('❌ 流式请求失败:', error);
        hideTypingIndicator();
        updateMessageContent(assistantMsgId, `抱歉，请求失败: ${error.message}`);
    }
}

function createAssistantMessageContainer(msgId) {
    ensureLeafletStackingStyles();
    const container = document.createElement('div');
    container.id = msgId;
    // 使用与历史消息相同的完整HTML结构
    container.className = 'assistant-message-row flex justify-start gap-4';
    container.innerHTML = `
        <div class="size-10 rounded-full bg-surface border border-slate-100 shadow-sm flex items-center justify-center shrink-0">
            <span class="text-xl">🌿</span>
        </div>
        <div class="flex flex-col gap-4 flex-1 min-w-0">
            <div class="assistant-message-card bg-white dark:bg-slate-800 p-4 rounded-xl shadow-sm border border-slate-100 dark:border-slate-700">
                <div class="message-content"></div>
            </div>
        </div>
    `;
    messagesContainer.appendChild(container);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return container;
}

function updateMessageContent(msgId, content) {
    const container = document.getElementById(msgId);
    if (container) {
        const contentDiv = container.querySelector('.message-content');
        if (contentDiv) {
            const cleanedReply = formatReplyText(content);
            // 使用与历史消息相同的文本清洗和 Markdown 渲染逻辑
            contentDiv.innerHTML = cleanedReply
                ? `<div class="prose prose-slate dark:prose-invert max-w-none text-base text-slate-800 dark:text-slate-200 leading-relaxed">${formatMarkdown(cleanedReply)}</div>`
                : '';
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    }
}

function getAssistantMessageContainer(target) {
    if (!target) return null;
    if (typeof target === 'string') {
        return document.getElementById(target);
    }
    return target;
}

function getAssistantMessageCard(target) {
    const container = getAssistantMessageContainer(target);
    const messageContent = container?.querySelector('.message-content');
    return messageContent ? messageContent.parentElement : null;
}

function renderTracePanel(traceFriendly) {
    if (!Array.isArray(traceFriendly) || traceFriendly.length === 0) {
        return null;
    }

    const wrapper = document.createElement('div');
    wrapper.className = 'trace-panel-container';

    // Toggle button with step count
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'trace-toggle';
    toggle.innerHTML = `<span class="toggle-chevron">\u25B6</span> 查看分析步骤 / View Analysis Steps <span class="step-count">(${traceFriendly.length})</span>`;

    // Panel
    const panel = document.createElement('div');
    panel.className = 'trace-panel';

    // Timeline container
    const timeline = document.createElement('div');
    timeline.className = 'trace-timeline';

    traceFriendly.forEach(step => {
        const status = step.status || 'success';
        const stepEl = document.createElement('div');
        stepEl.className = `trace-step ${status}`;

        // Dot
        const dot = document.createElement('div');
        dot.className = 'trace-step-dot';
        stepEl.appendChild(dot);

        // Header line (title + badges)
        const header = document.createElement('div');
        header.className = 'trace-step-header';

        const titleEl = document.createElement('span');
        titleEl.className = 'trace-step-title';
        titleEl.textContent = step.title || 'Step';
        header.appendChild(titleEl);

        // Duration badge
        const durationMatch = step.description ? step.description.match(/\((\d+(?:\.\d+)?ms)\)/) : null;
        if (durationMatch) {
            const badge = document.createElement('span');
            badge.className = 'trace-step-badge duration';
            badge.textContent = durationMatch[1];
            header.appendChild(badge);
        }

        // Confidence badge for file grounding
        if (step.step_type === 'file_grounding' && step.description) {
            const confMatch = step.description.match(/confidence\s+(\d+%)/);
            if (confMatch) {
                const badge = document.createElement('span');
                badge.className = 'trace-step-badge confidence';
                badge.textContent = confMatch[1];
                header.appendChild(badge);
            }
        }

        stepEl.appendChild(header);

        // Description
        if (step.description) {
            const desc = document.createElement('div');
            desc.className = 'trace-step-desc';

            if (step.step_type === 'parameter_standardization') {
                const lines = step.description.split('\n');
                desc.innerHTML = lines.map(line => {
                    const arrowMatch = line.match(/^(.+?):\s*(.+?)\s*\u2192\s*(.+?)\s{2}\((.+)\)$/);
                    if (arrowMatch) {
                        return `<span class="param-mapping">${escapeHtml(arrowMatch[1])}: ${escapeHtml(arrowMatch[2])}</span>`
                            + `<span class="param-arrow">\u2192</span>`
                            + `<span class="param-mapping" style="font-weight:600">${escapeHtml(arrowMatch[3])}</span>`
                            + ` <span class="param-meta">(${escapeHtml(arrowMatch[4])})</span>`;
                    }
                    const checkMatch = line.match(/^(.+?):\s*(.+?)\s*\u2713\s{2}\((.+)\)$/);
                    if (checkMatch) {
                        return `<span class="param-mapping">${escapeHtml(checkMatch[1])}: ${escapeHtml(checkMatch[2])}</span>`
                            + ` <span style="color:#10b981">\u2713</span>`
                            + ` <span class="param-meta">(${escapeHtml(checkMatch[3])})</span>`;
                    }
                    return escapeHtml(line);
                }).join('<br>');
            } else {
                desc.textContent = step.description;
            }
            stepEl.appendChild(desc);
        }

        timeline.appendChild(stepEl);
    });

    panel.appendChild(timeline);

    // Toggle behavior
    toggle.addEventListener('click', () => {
        panel.classList.toggle('visible');
        toggle.classList.toggle('expanded');
    });

    wrapper.appendChild(toggle);
    wrapper.appendChild(panel);
    return wrapper;
}

function attachTracePanelToMessage(target, traceFriendly) {
    const card = getAssistantMessageCard(target);
    if (!card) return;

    const existingPanel = card.querySelector('.trace-panel-container');
    if (existingPanel) {
        existingPanel.remove();
    }

    const tracePanel = renderTracePanel(traceFriendly);
    if (!tracePanel) return;

    card.appendChild(tracePanel);
}

function showTypingIndicator(text) {
    let indicator = document.getElementById('typing-indicator');
    if (!indicator) {
        indicator = document.createElement('div');
        indicator.id = 'typing-indicator';
        indicator.className = 'typing-indicator';
        messagesContainer.appendChild(indicator);
    }
    indicator.textContent = text;
    indicator.style.display = 'flex';
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function hideTypingIndicator() {
    const indicator = document.getElementById('typing-indicator');
    if (indicator) {
        indicator.style.display = 'none';
    }
}

function addDownloadButton(msgId, fileId) {
    const container = document.getElementById(msgId);
    if (!container) {
        console.error('找不到消息容器:', msgId);
        return;
    }

    // 查找表格的header（包含标题和下载按钮的区域）
    const tableHeaders = container.querySelectorAll('.flex.justify-between.items-center');
    if (tableHeaders.length === 0) {
        console.error('找不到表格header');
        return;
    }

    // 为每个表格header添加下载按钮（可能有汇总表和详情表）
    tableHeaders.forEach(header => {
        // 检查是否已经有下载按钮
        if (header.querySelector('button[data-download-btn="1"], button[onclick*="downloadFile"], a[download], a[href*="/api/download/"], a[href*="/api/file/download/"]')) {
            return;
        }

        // 创建下载按钮
        const downloadBtn = document.createElement('button');
        downloadBtn.setAttribute('data-download-btn', '1');
        downloadBtn.onclick = () => downloadFile(fileId);
        downloadBtn.className = 'inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg transition-colors';
        downloadBtn.innerHTML = `
            <span class="material-symbols-outlined" style="font-size: 18px;">download</span>
            下载结果文件
        `;

        // 添加到header
        header.appendChild(downloadBtn);
    });

    console.log('✅ 下载按钮已添加到消息:', msgId);
}

function hasAnyDownloadControl(msgId) {
    const container = document.getElementById(msgId);
    if (!container) return false;
    return !!container.querySelector(
        'a[download], a[href*="/api/download/"], a[href*="/api/file/download/"], button[data-download-btn="1"], button[onclick*="downloadFile"]'
    );
}

function renderChart(chartData, msgId) {
    const container = document.getElementById(msgId);
    if (!container) return;

    // 添加key points表格
    if (chartData.key_points?.length) {
        const tableHtml = renderKeyPointsTable(chartData.key_points);
        container.querySelector('.message-content').insertAdjacentHTML('beforeend', tableHtml);
    }

    // 添加图表
    const chartId = `emission-chart-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const chartHtml = renderChartCard(chartData, chartId);
    container.querySelector('.message-content').insertAdjacentHTML('beforeend', chartHtml);

    // 初始化图表
    setTimeout(() => {
        initChartPayload(chartData, chartId);
    }, 100);
}

function renderTable(tableData, msgId, downloadFile = null, fileId = null) {
    console.log('[DEBUG] renderTable called:', {
        msgId,
        tableData,
        downloadFile,
        fileId
    });

    const container = document.getElementById(msgId);
    if (!container) {
        console.error('[DEBUG] Container not found for msgId:', msgId);
        return;
    }

    const tableHtml = renderResultTable(tableData, fileId || tableData.file_id, downloadFile);
    console.log('[DEBUG] Table HTML generated, length:', tableHtml.length);

    const messageContent = container.querySelector('.message-content');
    if (!messageContent) {
        console.error('[DEBUG] .message-content not found in container');
        return;
    }

    messageContent.insertAdjacentHTML('beforeend', tableHtml);
    console.log('[DEBUG] Table inserted successfully');
}

async function handleFileSelect(e) {
    const file = e.target.files[0];
    if (!file) return;

    currentFile = file;

    // 预览文件
    try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetchWithUser(`${API_BASE}/file/preview`, {
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

async function startNewChat() {
    try {
        const response = await fetchWithUser(`${API_BASE}/sessions/new`, { method: 'POST' });
        const data = await response.json();
        currentSessionId = data.session_id;
        currentFile = null;

        // 清空消息区域
        renderHistory([]);

        // 重新加载会话列表
        loadSessionList();

    } catch (error) {
        console.error('新建会话失败:', error);
    }
}

// ==================== 会话历史管理 ====================

async function loadSessionList() {
    console.log('📋 loadSessionList 被调用');

    // 游客模式：显示提示信息
    if (isGuest) {
        renderGuestModeBanner();
        return;
    }

    console.log('🌐 API_BASE:', API_BASE);
    try {
        console.log('⏳ 开始获取会话列表...');
        const response = await fetchWithUser(`${API_BASE}/sessions`);
        console.log('✅ 会话列表请求完成，状态码:', response.status);

        // 游客模式下 API 返回 401，不显示错误
        if (response.status === 401) {
            renderGuestModeBanner();
            return;
        }

        const data = await response.json();
        console.log('📥 会话列表数据:', data);

        if (data.sessions && data.sessions.length > 0) {
            renderSessionList(data.sessions);
        } else {
            renderEmptySessionList();
        }
    } catch (error) {
        console.error('❌ 加载会话列表失败:', error);
    }
}

// 渲染游客模式提示
function renderGuestModeBanner() {
    if (!sessionListContainer) return;

    sessionListContainer.innerHTML = `
        <div class="px-4 py-6 mx-3 mt-2 bg-gradient-to-br from-slate-50 to-slate-100 dark:from-slate-800/50 dark:to-slate-900/50 rounded-xl border border-slate-200 dark:border-slate-700">
            <div class="flex flex-col items-center text-center space-y-4">
                <!-- 图标 -->
                <div class="flex items-center justify-center w-12 h-12 rounded-full bg-amber-100 dark:bg-amber-900/30 text-amber-600 dark:text-amber-400">
                    <span class="material-symbols-outlined" style="font-size: 28px;">person_outline</span>
                </div>

                <!-- 标题 -->
                <div>
                    <h3 class="text-sm font-semibold text-slate-700 dark:text-slate-200">游客模式</h3>
                    <p class="text-xs text-slate-500 dark:text-slate-400 mt-1">当前会话数据不会被持久化保存</p>
                </div>

                <!-- 描述 -->
                <p class="text-xs text-slate-600 dark:text-slate-400 leading-relaxed max-w-[200px]">
                    刷新页面后，当前的分析轨迹将会丢失。<br/>
                    登录后可启用历史追溯与数据持久化功能。
                </p>

                <!-- 登录按钮 -->
                <a href="/login" class="inline-flex items-center gap-2 px-4 py-2 bg-primary hover:bg-primary-dark text-white text-sm font-medium rounded-lg transition-all shadow-sm hover:shadow">
                    <span class="material-symbols-outlined" style="font-size: 18px;">login</span>
                    <span>登录 / 注册</span>
                </a>
            </div>
        </div>
    `;
}

// 渲染空会话列表
function renderEmptySessionList() {
    if (!sessionListContainer) return;

    sessionListContainer.innerHTML = `
        <div class="px-4 py-6 mx-3 mt-2 text-center">
            <p class="text-sm text-slate-500 dark:text-slate-400">暂无历史对话</p>
            <p class="text-xs text-slate-400 dark:text-slate-500 mt-1">开始新的对话来创建记录</p>
        </div>
    `;
}

function renderSessionList(sessions) {
    if (!sessionListContainer) return;

    // 清空现有列表（保留标题）
    const title = sessionListContainer.querySelector('h3');
    sessionListContainer.innerHTML = '';
    if (title) {
        sessionListContainer.appendChild(title);
    } else {
        sessionListContainer.innerHTML = '<h3 class="px-3 text-xs font-semibold text-slate-400 uppercase tracking-wider mb-1">Recent</h3>';
    }

    // 渲染会话列表
    sessions.forEach((session, index) => {
        const isCurrent = currentSessionId === session.session_id;
        const sessionEl = document.createElement('div');
        sessionEl.dataset.sessionId = session.session_id;
        sessionEl.className = isCurrent
            ? 'group flex items-center justify-between px-3 py-2 rounded-lg bg-white dark:bg-slate-800 shadow-sm border border-slate-100 dark:border-slate-700 cursor-pointer'
            : 'group flex items-center justify-between px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400 transition-colors cursor-pointer';

        sessionEl.innerHTML = `
            <div class="session-main flex items-center gap-3 overflow-hidden flex-1 min-w-0">
                <span class="material-symbols-outlined ${isCurrent ? 'text-primary' : ''} shrink-0" style="font-size: 20px;">${isCurrent ? 'chat_bubble' : 'history'}</span>
                <p class="session-title text-sm font-medium truncate">${escapeHtml(session.title)}</p>
            </div>
            <div class="session-actions flex items-center gap-1">
                <button class="edit-btn opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-blue-500 hover:bg-blue-50 dark:hover:bg-blue-900/20 rounded transition-all" title="重命名会话">
                    <span class="material-symbols-outlined" style="font-size: 18px;">edit</span>
                </button>
                <button class="delete-btn opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-all" title="删除会话">
                    <span class="material-symbols-outlined" style="font-size: 18px;">delete</span>
                </button>
            </div>
        `;

        // 点击切换会话
        sessionEl.addEventListener('click', (e) => {
            // 如果正在编辑或点击了操作按钮，不切换
            if (sessionEl.dataset.editing === '1') return;
            if (e.target.closest('.delete-btn') || e.target.closest('.edit-btn') || e.target.closest('.session-rename')) return;
            e.preventDefault();
            loadSession(session.session_id);
        });

        // 点击重命名
        const editBtn = sessionEl.querySelector('.edit-btn');
        editBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            startInlineRename(sessionEl, session);
        });

        // 点击删除
        const deleteBtn = sessionEl.querySelector('.delete-btn');
        deleteBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            if (confirm('确定要删除这个会话吗？')) {
                deleteSession(session.session_id);
            }
        });

        sessionListContainer.appendChild(sessionEl);
    });
}

async function deleteSession(sessionId) {
    try {
        const response = await fetchWithUser(`${API_BASE}/sessions/${sessionId}`, { method: 'DELETE' });
        if (response.ok) {
            // 如果删除的是当前会话，新建一个
            if (currentSessionId === sessionId) {
                startNewChat();
            } else {
                loadSessionList();
            }
        }
    } catch (error) {
        console.error('删除会话失败:', error);
    }
}

async function updateSessionTitle(sessionId, title) {
    try {
        const response = await fetchWithUser(`${API_BASE}/sessions/${sessionId}/title`, {
            method: 'PATCH',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({ title })
        });
        if (!response.ok) {
            const err = await response.json().catch(() => ({}));
            throw new Error(err.detail || `HTTP ${response.status}`);
        }
        await loadSessionList();
    } catch (error) {
        console.error('更新会话标题失败:', error);
        alert(`更新会话标题失败: ${error.message}`);
    }
}

function startInlineRename(sessionEl, session) {
    if (!sessionEl || sessionEl.dataset.editing === '1') return;
    sessionEl.dataset.editing = '1';

    const main = sessionEl.querySelector('.session-main');
    const titleEl = sessionEl.querySelector('.session-title');
    const actions = sessionEl.querySelector('.session-actions');
    if (!main || !titleEl || !actions) return;

    const oldTitle = (session.title || '新对话').trim();

    const wrapper = document.createElement('div');
    wrapper.className = 'session-rename flex items-center gap-1 flex-1 min-w-0';

    const input = document.createElement('input');
    input.type = 'text';
    input.value = oldTitle;
    input.maxLength = 80;
    input.className = 'w-full text-sm px-2 py-1 rounded-md border border-slate-300 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-200 outline-none focus:ring-2 focus:ring-primary/40';

    const saveBtn = document.createElement('button');
    saveBtn.className = 'p-1 text-emerald-600 hover:bg-emerald-50 dark:hover:bg-emerald-900/20 rounded';
    saveBtn.title = '保存';
    saveBtn.innerHTML = '<span class="material-symbols-outlined" style="font-size: 18px;">check</span>';

    const cancelBtn = document.createElement('button');
    cancelBtn.className = 'p-1 text-slate-500 hover:bg-slate-100 dark:hover:bg-slate-700 rounded';
    cancelBtn.title = '取消';
    cancelBtn.innerHTML = '<span class="material-symbols-outlined" style="font-size: 18px;">close</span>';

    wrapper.appendChild(input);
    wrapper.appendChild(saveBtn);
    wrapper.appendChild(cancelBtn);

    titleEl.replaceWith(wrapper);
    actions.classList.add('opacity-100');

    const cleanup = () => {
        sessionEl.dataset.editing = '0';
        actions.classList.remove('opacity-100');
    };

    const commit = async () => {
        const nextTitle = input.value.trim();
        if (!nextTitle) {
            input.focus();
            return;
        }
        if (nextTitle === oldTitle) {
            await loadSessionList();
            cleanup();
            return;
        }
        await updateSessionTitle(session.session_id, nextTitle);
        cleanup();
    };

    const cancel = async () => {
        await loadSessionList();
        cleanup();
    };

    saveBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await commit();
    });

    cancelBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        await cancel();
    });

    input.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            await commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            await cancel();
        }
    });

    input.addEventListener('click', (e) => e.stopPropagation());
    setTimeout(() => {
        input.focus();
        input.select();
    }, 0);
}

async function loadSession(sessionId) {
    console.log('加载会话:', sessionId);
    currentSessionId = sessionId;

    try {
        const response = await fetchWithUser(`${API_BASE}/sessions/${sessionId}/history`);
        const data = await response.json();

        if (data.success) {
            renderHistory(data.messages);
        } else {
            console.error('加载历史失败');
        }
    } catch (error) {
        console.error('加载历史出错:', error);
    }

    // 重新渲染列表以更新选中态
    loadSessionList();
}

function getMessageAttachmentFilename(message) {
    if (!message || typeof message !== 'object') return null;
    if (typeof message.file_name === 'string' && message.file_name.trim()) {
        return message.file_name.trim();
    }
    if (typeof message.file_path === 'string' && message.file_path.trim()) {
        const segments = message.file_path.trim().split(/[\\/]/);
        return segments[segments.length - 1] || null;
    }
    return null;
}

function renderHistory(messages) {
    if (!messagesContainer) return;

    // 清空并添加日期标签
    messagesContainer.innerHTML = '<div class="flex justify-center pb-4"><span class="px-3 py-1 bg-slate-100 dark:bg-slate-800 text-slate-500 text-xs rounded-full font-medium">Today</span></div>';

    messages.forEach(msg => {
        if (msg.role === 'user') {
            addUserMessage(msg.content, getMessageAttachmentFilename(msg));
        } else {
            // 传递完整的图表数据和 file_id
            console.log('[DEBUG] 渲染历史消息:', {
                has_chart_data: !!msg.chart_data,
                has_table_data: !!msg.table_data,
                has_map_data: !!msg.map_data,
                data_type: msg.data_type,
                file_id: msg.file_id,  // 添加调试日志
                has_download_file: !!msg.download_file
            });
            addAssistantMessage({
                reply: msg.content,
                success: true,
                data_type: msg.data_type,
                chart_data: msg.chart_data,
                table_data: msg.table_data,
                map_data: msg.map_data,
                has_data: msg.has_data,
                file_id: msg.file_id,  // 添加 file_id
                download_file: msg.download_file,
                trace_friendly: msg.trace_friendly
            });
        }
    });

    scrollToBottom();
}

// ==================== UI渲染函数 ====================

function addUserMessage(text, filename = null) {
    if (!messagesContainer) return;

    const html = `
        <div class="flex justify-end gap-4 ml-auto">
            <div class="flex flex-col gap-2 items-end">
                ${filename ? `
                <div class="inline-flex items-center gap-2 max-w-md bg-white/90 dark:bg-slate-700/90 border border-slate-200 dark:border-slate-600 px-3 py-1.5 rounded-full shadow-sm">
                    <div class="w-6 h-6 rounded-full bg-emerald-100 dark:bg-emerald-900/40 flex items-center justify-center shrink-0">
                        <span class="material-symbols-outlined text-emerald-600 dark:text-emerald-400" style="font-size: 14px;">description</span>
                    </div>
                    <div class="min-w-0">
                        <p class="text-xs font-medium text-slate-700 dark:text-slate-200 truncate">${escapeHtml(filename)}</p>
                        <p class="text-[11px] leading-none text-slate-400">附件已上传</p>
                    </div>
                </div>
                ` : ''}
                <div class="bg-primary text-white p-4 rounded-2xl rounded-tr-sm max-w-lg">
                    <div class="text-base leading-relaxed whitespace-pre-wrap">${escapeHtml(text)}</div>
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
    if (!messagesContainer) return;
    ensureLeafletStackingStyles();

    // Clean and format the reply text
    const cleanedReply = formatReplyText(data.reply);
    let contentHtml = cleanedReply ? `<div class="prose prose-slate dark:prose-invert max-w-none text-base text-slate-800 dark:text-slate-200 leading-relaxed">${formatMarkdown(cleanedReply)}</div>` : '';

    // 与实时流式路径保持一致：只要存在有效富媒体负载，就应在历史中渲染
    const hasValidChartData =
                               data.chart_data &&
                               typeof data.chart_data === 'object' &&
                               Object.keys(data.chart_data).length > 0;

    const hasValidTableData =
                               data.table_data &&
                               typeof data.table_data === 'object' &&
                               Object.keys(data.table_data).length > 0;

    const mapItems = getMapPayloadItems(data.map_data);
    const hasValidMapData = hasRenderableMapData(data.map_data);

    // 调试日志
    console.log('[DEBUG] addAssistantMessage:', {
        data_type: data.data_type,
        hasValidChartData,
        hasValidTableData,
        hasValidMapData,
        chart_data_keys: data.chart_data ? Object.keys(data.chart_data) : null,
        table_data_keys: data.table_data ? Object.keys(data.table_data) : null,
        map_data_type: data.map_data ? data.map_data.type : null,
        map_payload_count: mapItems.length,
        map_data_links: mapItems[0] ? mapItems[0].links?.length || 0 : 0,
        map_data_features: mapItems[0]?.layers?.[0]?.data?.features?.length || mapItems[0]?.concentration_grid?.receptors?.length || 0
    });

    // 添加图表（排放因子曲线）
    // Key points table (if available)
    if (hasValidChartData && data.chart_data.key_points?.length) {
        console.log('[DEBUG] 显示Key Points表格');
        contentHtml += renderKeyPointsTable(data.chart_data.key_points);
    }

    let chartId = null;
    if (hasValidChartData) {
        console.log('[DEBUG] 显示图表负载:', data.chart_data.type || 'emission_factors');
        chartId = `emission-chart-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        contentHtml += renderChartCard(data.chart_data, chartId);
    }

    // 添加表格（计算结果）
    if (hasValidTableData) {
        console.log('[DEBUG] 显示计算结果表格');
        contentHtml += renderResultTable(data.table_data, data.file_id, data.download_file);
    }

    // 历史消息提示
    if (data.has_data && !data.data_type) {
        contentHtml += `
            <div class="mt-2 p-2 bg-slate-50 dark:bg-slate-700/50 rounded text-xs text-slate-500">
                ⚠️ 此为历史消息，详细图表/表格数据未加载。请下载历史文件查看。
            </div>
         `;
    }

    const html = `
        <div class="assistant-message-row flex justify-start gap-4">
            <div class="size-10 rounded-full bg-surface border border-slate-100 shadow-sm flex items-center justify-center shrink-0">
                <span class="text-xl">🌿</span>
            </div>
            <div class="flex flex-col gap-4 flex-1 min-w-0">
                <div class="assistant-message-card bg-white dark:bg-slate-800 p-4 rounded-xl shadow-sm border border-slate-100 dark:border-slate-700">
                    <div class="message-content">${contentHtml}</div>
                </div>
            </div>
        </div>
    `;
    messagesContainer.insertAdjacentHTML('beforeend', html);

    // Get message container for map/chart rendering
    const msgContainers = messagesContainer.querySelectorAll('.assistant-message-row');
    const msgContainer = msgContainers[msgContainers.length - 1];

    // 初始化图表（如果有）
    if (data.data_type === 'chart' && data.chart_data && chartId) {
        initChartPayload(data.chart_data, chartId);
    }

    // 初始化地图（如果有）
    if (hasValidMapData) {
        console.log('[DEBUG] 显示地图:', mapItems.map(item => item.type || 'emission'));
        renderMapData(data.map_data, msgContainer);
    }

    if (Array.isArray(data.trace_friendly) && data.trace_friendly.length > 0) {
        attachTracePanelToMessage(msgContainer, data.trace_friendly);
    }

    scrollToBottom();
}

function addLoadingMessage() {
    if (!messagesContainer) return null;

    const html = `
        <div class="flex justify-start gap-4 loading-message">
            <div class="size-10 rounded-full bg-surface border border-slate-100 shadow-sm flex items-center justify-center shrink-0">
                <span class="text-xl">🌿</span>
            </div>
            <div class="bg-white dark:bg-slate-800 p-4 rounded-xl shadow-sm border border-slate-100 dark:border-slate-700">
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

function renderEmissionChart(chartData, chartId) {
    const chartElementId = chartId || `emission-chart-${Date.now()}`;
    const pollutants = Object.keys(chartData.pollutants || {});
    const tabs = pollutants.map((p, i) =>
        `<button class="chart-tab px-3 py-1 ${i === 0 ? 'bg-white dark:bg-slate-600 shadow-sm font-bold' : ''} rounded-md text-xs text-slate-800 dark:text-slate-200" data-pollutant="${p}" data-chart-id="${chartElementId}">${p}</button>`
    ).join('');

    return `
        <div class="w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm p-6 mt-4" data-chart-id="${chartElementId}">
            <div class="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                    <h3 class="text-slate-900 dark:text-white font-bold text-lg">排放因子曲线</h3>
                    <p class="text-slate-500 text-sm">${chartData.vehicle_type} · ${chartData.model_year}年</p>
                </div>
                <div class="flex bg-slate-100 dark:bg-slate-700 rounded-lg p-1">
                    ${tabs}
                </div>
            </div>
            <div id="${chartElementId}" class="emission-chart" style="height: 300px;"></div>
            <div class="chart-error hidden mt-3 text-xs text-red-600 bg-red-50 dark:bg-red-900/20 dark:text-red-200 border border-red-100 dark:border-red-800 rounded-lg px-3 py-2" data-chart-id="${chartElementId}"></div>
            <p class="text-xs text-slate-400 mt-2 text-center">鼠标移到曲线上查看具体数值</p>
        </div>
    `;
}

function renderRankedBarChart(chartData, chartId) {
    const chartElementId = chartId || `ranked-chart-${Date.now()}`;
    const title = chartData.title || '结果排名图';
    const subtitle = chartData.subtitle || '';

    return `
        <div class="w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm p-6 mt-4" data-chart-id="${chartElementId}">
            <div class="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                    <h3 class="text-slate-900 dark:text-white font-bold text-lg">${title}</h3>
                    <p class="text-slate-500 text-sm">${subtitle}</p>
                </div>
                <div class="px-3 py-1 rounded-full bg-emerald-50 dark:bg-emerald-900/20 text-emerald-700 dark:text-emerald-300 text-xs font-medium">
                    Top ${chartData.topk || (chartData.categories?.length || 0)}
                </div>
            </div>
            <div id="${chartElementId}" class="emission-chart" style="height: 320px;"></div>
            <div class="chart-error hidden mt-3 text-xs text-red-600 bg-red-50 dark:bg-red-900/20 dark:text-red-200 border border-red-100 dark:border-red-800 rounded-lg px-3 py-2" data-chart-id="${chartElementId}"></div>
            <p class="text-xs text-slate-400 mt-2 text-center">鼠标移到柱形上查看具体数值</p>
        </div>
    `;
}

function renderChartCard(chartData, chartId) {
    if (chartData?.type === 'ranked_bar_chart') {
        return renderRankedBarChart(chartData, chartId);
    }
    return renderEmissionChart(chartData, chartId);
}

function renderKeyPointsTable(keyPoints) {
    if (!Array.isArray(keyPoints) || keyPoints.length === 0) return '';

    const rowsHtml = keyPoints.map(point => `
        <tr class="hover:bg-slate-50 dark:hover:bg-slate-700/50">
            <td class="px-4 py-2 text-slate-600 dark:text-slate-400">${point.speed ?? ''}</td>
            <td class="px-4 py-2 text-slate-600 dark:text-slate-400">${typeof point.rate === 'number' ? point.rate.toFixed(4) : point.rate ?? ''}</td>
            <td class="px-4 py-2 text-slate-600 dark:text-slate-400">${point.label ?? ''}</td>
            <td class="px-4 py-2 text-slate-600 dark:text-slate-400">${point.pollutant ?? ''}</td>
        </tr>
    `).join('');

    return `
        <div class="w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm overflow-hidden mt-4">
            <div class="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50">
                <h3 class="font-bold text-slate-800 dark:text-white text-sm">Key Speed Points</h3>
                <p class="text-xs text-slate-500">Low / Mid / High speed reference points</p>
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-sm">
                    <thead class="text-xs text-slate-500 bg-slate-50 dark:bg-slate-700/50 uppercase">
                        <tr>
                            <th class="px-4 py-2 font-medium text-left">Speed (km/h)</th>
                            <th class="px-4 py-2 font-medium text-left">Pollutant</th>
                            <th class="px-4 py-2 font-medium text-left">Scenario</th>
                            <th class="px-4 py-2 font-medium text-left">Pollutant</th>
                        </tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100 dark:divide-slate-700">
                        ${rowsHtml}
                    </tbody>
                </table>
            </div>
        </div>
    `;
}

function renderResultTable(tableData, fileId, downloadFile = null) {
    if (!tableData) return '';

    const columns = tableData.columns || [];
    const allRows = tableData.preview_rows || tableData.rows || [];
    const totalRows = tableData.total_rows || allRows.length;
    const totalColumns = tableData.total_columns || columns.length;
    const summary = tableData.summary || {};

    // 限制预览行数（最多显示10行）
    const MAX_PREVIEW_ROWS = 10;
    const previewRows = allRows.slice(0, MAX_PREVIEW_ROWS);
    const hasMoreRows = totalRows > MAX_PREVIEW_ROWS;

    if (!previewRows || previewRows.length === 0) {
        return '<div class="text-slate-500 text-sm mt-4">暂无数据</div>';
    }

    // 1. 渲染汇总表格（如果有）
    let summaryHtml = '';
    if (summary.total_emissions_g || summary.total_emissions || tableData.total_emissions) {
        const emissions = summary.total_emissions_g || summary.total_emissions || tableData.total_emissions;
        const summaryRows = [];

        // 添加总距离和总时间
        if (summary.total_distance_km) {
            summaryRows.push(`<tr><td class="px-4 py-2 text-slate-700 dark:text-slate-300">总行驶距离</td><td class="px-4 py-2 text-slate-600 dark:text-slate-400">${summary.total_distance_km.toFixed(3)} km</td></tr>`);
        }
        if (summary.total_time_s) {
            summaryRows.push(`<tr><td class="px-4 py-2 text-slate-700 dark:text-slate-300">总运行时间</td><td class="px-4 py-2 text-slate-600 dark:text-slate-400">${summary.total_time_s} s</td></tr>`);
        }

        // 添加排放量
        Object.entries(emissions).forEach(([key, value]) => {
            const displayValue = typeof value === 'number' ? value.toFixed(2) : value;
            summaryRows.push(`<tr><td class="px-4 py-2 text-slate-700 dark:text-slate-300">${key}总排放量</td><td class="px-4 py-2 text-slate-600 dark:text-slate-400">${displayValue} g</td></tr>`);
        });

        if (summaryRows.length > 0) {
            summaryHtml = `
                <div class="w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm overflow-hidden mt-4">
                    <div class="px-4 py-3 border-b border-slate-100 dark:border-slate-700 bg-slate-50/50 dark:bg-slate-700/30">
                        <h3 class="font-bold text-slate-800 dark:text-white text-sm">计算结果汇总</h3>
                    </div>
                    <div class="overflow-x-auto">
                        <table class="w-full text-sm">
                            <thead class="text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-700/50">
                                <tr>
                                    <th class="px-4 py-2 text-left font-medium">指标</th>
                                    <th class="px-4 py-2 text-left font-medium">数值</th>
                                </tr>
                            </thead>
                            <tbody class="divide-y divide-slate-100 dark:divide-slate-700">
                                ${summaryRows.join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }
    }

    // 2. 渲染详细数据预览
    const headerHtml = columns.map(c => `<th class="px-4 py-3 font-medium text-left">${c}</th>`).join('');
    const rowsHtml = previewRows.map(row =>
        `<tr class="hover:bg-slate-50 dark:hover:bg-slate-700/50">
            ${columns.map(c => `<td class="px-4 py-3 text-slate-600 dark:text-slate-400">${formatCellValue(row[c])}</td>`).join('')}
        </tr>`
    ).join('');

    // 3. 下载按钮
    let downloadBtn = '';
    const effectiveDownload = tableData.download || downloadFile;
    if (effectiveDownload && effectiveDownload.url && effectiveDownload.filename) {
        downloadBtn = `
            <a href="${effectiveDownload.url}"
               download="${effectiveDownload.filename}"
               class="inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg transition-colors">
                <span class="material-symbols-outlined" style="font-size: 18px;">download</span>
                下载结果文件
            </a>`;
    } else if (fileId) {
        downloadBtn = `
            <button onclick="downloadFile('${fileId}')"
                    class="inline-flex items-center gap-2 px-4 py-2 bg-emerald-600 hover:bg-emerald-700 text-white text-sm font-medium rounded-lg transition-colors">
                <span class="material-symbols-outlined" style="font-size: 18px;">download</span>
                下载结果文件
            </button>`;
    }

    // 4. 组合完整HTML
    const columnInfo = totalColumns > columns.length
        ? `显示前${columns.length}列（共${totalColumns}列）`
        : `共${columns.length}列`;

    const detailTableHtml = `
        <div class="w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm overflow-hidden mt-4">
            <div class="px-4 py-3 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center bg-slate-50/50 dark:bg-slate-700/30">
                <div>
                    <h3 class="font-bold text-slate-800 dark:text-white text-sm">计算结果详情</h3>
                    <p class="text-xs text-slate-500 dark:text-slate-400">显示前${previewRows.length}行（共${totalRows}行），${columnInfo}</p>
                </div>
                ${downloadBtn}
            </div>
            <div class="overflow-x-auto">
                <table class="w-full text-sm">
                    <thead class="text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-700/50 uppercase">
                        <tr>${headerHtml}</tr>
                    </thead>
                    <tbody class="divide-y divide-slate-100 dark:divide-slate-700">
                        ${rowsHtml}
                    </tbody>
                </table>
            </div>
            ${hasMoreRows ? `
                <div class="px-4 py-3 bg-slate-50/50 dark:bg-slate-700/30 border-t border-slate-100 dark:border-slate-700">
                    <p class="text-xs text-slate-500 dark:text-slate-400 text-center">
                        还有 ${totalRows - MAX_PREVIEW_ROWS} 行数据，请下载完整文件查看
                    </p>
                </div>
            ` : ''}
        </div>
    `;

    return summaryHtml + detailTableHtml;
}

function formatCellValue(value) {
    if (value === null || value === undefined) return '-';
    if (typeof value === 'number') {
        // Keep reasonable decimal places
        if (Number.isInteger(value)) return value.toString();
        return value.toFixed(4).replace(/\.?0+$/, '');
    }
    return String(value);
}

function showFilePreview(preview) {
    const inputArea = document.querySelector('.absolute.bottom-0');
    let previewEl = document.getElementById('file-preview');
    if (!previewEl) {
        previewEl = document.createElement('div');
        previewEl.id = 'file-preview';
        previewEl.className = 'mb-2';
        inputArea?.insertBefore(previewEl, inputArea.firstChild);
    }

    const safeFilename = escapeHtml(preview.filename || 'unnamed_file');
    const fileSize = formatFileSize((preview.size_kb || 0) * 1024);
    const fileType = (safeFilename.split('.').pop() || '').toUpperCase();

    // Compact composer attachment chip (ChatGPT-like)
    previewEl.innerHTML = `
        <div class="max-w-4xl mx-auto w-full">
            <div class="flex items-center gap-3 px-3 py-2 bg-white/95 dark:bg-slate-800/95 rounded-2xl border border-slate-200 dark:border-slate-700 shadow-sm">
                <div class="w-8 h-8 bg-emerald-100 dark:bg-emerald-900/30 rounded-lg flex items-center justify-center shrink-0">
                    <span class="material-symbols-outlined text-emerald-600 dark:text-emerald-400" style="font-size: 18px;">description</span>
                </div>
                <div class="flex-1 min-w-0">
                    <p class="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">${safeFilename}</p>
                    <div class="flex items-center gap-2 text-xs text-slate-500 dark:text-slate-400">
                        <span>${fileSize}</span>
                        <span class="inline-block w-1 h-1 rounded-full bg-slate-300 dark:bg-slate-600"></span>
                        <span>${fileType || 'FILE'}</span>
                    </div>
                </div>
                <button onclick="removeFile()" class="p-1.5 hover:bg-slate-100 dark:hover:bg-slate-700 rounded-full transition-colors shrink-0" aria-label="移除附件">
                    <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                    </svg>
                </button>
            </div>
        </div>
    `;
    previewEl.style.display = 'block';
}

function formatFileSize(bytes) {
    if (bytes < 1024) return bytes + ' B';
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(1) + ' KB';
    return (bytes / (1024 * 1024)).toFixed(1) + ' MB';
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

let echartsLoadPromise = null;

function ensureEchartsLoaded() {
    if (typeof echarts !== 'undefined') {
        return Promise.resolve(true);
    }

    if (echartsLoadPromise) {
        return echartsLoadPromise;
    }

    echartsLoadPromise = new Promise((resolve, reject) => {
        const script = document.createElement('script');
        script.src = 'https://cdn.jsdelivr.net/npm/echarts@5.4.3/dist/echarts.min.js';
        script.onload = () => resolve(true);
        script.onerror = () => reject(new Error('ECharts load failed'));
        document.head.appendChild(script);
    });

    return echartsLoadPromise;
}

function showChartInitError(chartEl, message) {
    if (!chartEl) return;
    const errorEl = document.querySelector(`.chart-error[data-chart-id="${chartEl.id}"]`);
    if (!errorEl) return;
    errorEl.textContent = message;
    errorEl.classList.remove('hidden');
}

function clearChartInitError(chartEl) {
    if (!chartEl) return;
    const errorEl = document.querySelector(`.chart-error[data-chart-id="${chartEl.id}"]`);
    if (!errorEl) return;
    errorEl.classList.add('hidden');
    errorEl.textContent = '';
}

function initEmissionChart(chartData, chartId) {
    const chartEl = chartId ? document.getElementById(chartId) : null;
    const fallbackCharts = !chartEl ? document.querySelectorAll('.emission-chart') : null;
    const resolvedChartEl = chartEl || (fallbackCharts?.length ? fallbackCharts[fallbackCharts.length - 1] : null);
    if (!resolvedChartEl) {
        console.error('Chart container not found');
        return;
    }

    clearChartInitError(resolvedChartEl);

    if (typeof echarts === 'undefined') {
        showChartInitError(resolvedChartEl, 'Chart init failed: ECharts not loaded, retrying...');
        if (!resolvedChartEl.dataset.echartsRetry) {
            resolvedChartEl.dataset.echartsRetry = '1';
            ensureEchartsLoaded()
                .then(() => initEmissionChart(chartData, chartId))
                .catch(() => showChartInitError(resolvedChartEl, 'Chart init failed: ECharts load failed'));
        }
        return;
    }

    console.log('Chart init:', chartData);

    let chart;
    try {
        chart = echarts.init(resolvedChartEl);
    } catch (err) {
        showChartInitError(resolvedChartEl, 'Chart init failed: ECharts render error');
        console.error(err);
        return;
    }
    const pollutants = chartData.pollutants || {};
    const firstPollutant = Object.keys(pollutants)[0];

    if (!firstPollutant) {
        console.error('Chart container not found');
        showChartInitError(resolvedChartEl, 'Chart init failed: missing pollutant data');
        return;
    }



    const curveData = pollutants[firstPollutant]?.curve || [];
    if (!curveData.length) {
        showChartInitError(resolvedChartEl, 'Chart init failed: empty curve data');
        return;
    }

    console.log(`📈 ${firstPollutant} 曲线数据点数:`, curveData.length);

    const option = {
        color: ['#10b77f'],
        tooltip: {
            trigger: 'axis',
            backgroundColor: 'rgba(0,0,0,0.8)',
            borderColor: 'transparent',
            textStyle: { color: '#fff' },
            formatter: (params) => {
                const p = params[0];
                return `<div style="padding: 4px 8px;">
                    <div style="font-weight: bold;">速度: ${p.data[0].toFixed(1)} km/h</div>
                    <div>${firstPollutant}: ${p.data[1].toFixed(4)} g/km</div>
                </div>`;
            }
        },
        grid: {
            left: '10%',
            right: '5%',
            bottom: '15%',
            top: '10%'
        },
        xAxis: {
            type: 'value',
            name: '速度 (km/h)',
            nameLocation: 'middle',
            nameGap: 30,
            nameTextStyle: { color: '#666', fontSize: 12 },
            min: 0,
            max: 130,
            axisLine: { lineStyle: { color: '#ddd' } },
            splitLine: { lineStyle: { color: '#f0f0f0' } }
        },
        yAxis: {
            type: 'value',
            name: '排放因子 (g/km)',
            nameLocation: 'middle',
            nameGap: 50,
            nameTextStyle: { color: '#666', fontSize: 12 },
            axisLine: { lineStyle: { color: '#ddd' } },
            splitLine: { lineStyle: { color: '#f0f0f0' } }
        },
        series: [{
            type: 'line',
            smooth: true,
            data: curveData.map(p => [p.speed_kph, p.emission_rate]),
            lineStyle: { width: 3 },
            areaStyle: {
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: 'rgba(16, 183, 127, 0.3)' },
                    { offset: 1, color: 'rgba(16, 183, 127, 0)' }
                ])
            },
            showSymbol: true,  // 强制显示数据点
            symbol: 'circle',
            symbolSize: 6
        }]
    };

    chart.setOption(option);
    console.log('✅ 图表初始化完成');

    window.addEventListener('resize', () => chart.resize());

    // Tab切换
    document.querySelectorAll(`.chart-tab[data-chart-id="${resolvedChartEl.id}"]`).forEach(tab => {
        tab.addEventListener('click', () => {
            const pollutant = tab.dataset.pollutant;
            const newCurve = pollutants[pollutant]?.curve || [];
            console.log(`🔄 切换到 ${pollutant}, 数据点数:`, newCurve.length);

            document.querySelectorAll(`.chart-tab[data-chart-id="${resolvedChartEl.id}"]`).forEach(t => {
                t.classList.remove('bg-white', 'dark:bg-slate-600', 'shadow-sm', 'font-bold');
            });
            tab.classList.add('bg-white', 'dark:bg-slate-600', 'shadow-sm', 'font-bold');

            chart.setOption({
                tooltip: {
                    formatter: (params) => {
                        const p = params[0];
                        return `<div style="padding: 4px 8px;">
                            <div style="font-weight: bold;">速度: ${p.data[0].toFixed(1)} km/h</div>
                            <div>${pollutant}: ${p.data[1].toFixed(4)} g/km</div>
                        </div>`;
                    }
                },
                yAxis: {
                    name: `${pollutant} (g/km)`
                },
                series: [{
                    showSymbol: true,  // 强制显示数据点
                    data: newCurve.map(p => [p.speed_kph, p.emission_rate])
                }]
            });
        });
    });
}

// ==================== 地图渲染函数 ====================

function getMapPayloadItems(mapData) {
    if (!mapData) {
        return [];
    }

    if (Array.isArray(mapData)) {
        return mapData.flatMap(item => getMapPayloadItems(item));
    }

    if (typeof mapData !== 'object') {
        return [];
    }

    if (mapData.type === 'map_collection' && Array.isArray(mapData.items)) {
        return mapData.items.flatMap(item => getMapPayloadItems(item));
    }

    return [mapData];
}

function hasRenderableSingleMapData(mapData) {
    if (!mapData || typeof mapData !== 'object') {
        return false;
    }

    if (Array.isArray(mapData.links) && mapData.links.length > 0) {
        return true;
    }

    if (mapData.type === 'hotspot' || Array.isArray(mapData.hotspots) || Array.isArray(mapData.hotspots_detail)) {
        const normalizedHotspot = normalizeHotspotMapData(mapData);
        return !!(normalizedHotspot && normalizedHotspot.layers?.length);
    }

    if (mapData.type === 'raster' || mapData.raster_grid) {
        const normalizedRaster = normalizeRasterMapData(mapData);
        return !!(normalizedRaster && normalizedRaster.layers?.[0]?.data?.features?.length);
    }

    if (mapData.type === 'concentration' || mapData.concentration_grid || Array.isArray(mapData.layers)) {
        const normalized = normalizeConcentrationMapData(mapData);
        return !!(normalized && normalized.layers?.[0]?.data?.features?.length);
    }

    return false;
}

function hasRenderableMapData(mapData) {
    return getMapPayloadItems(mapData).some(item => hasRenderableSingleMapData(item));
}

function renderSingleMapData(mapData, msgContainer) {
    if (mapData.type === 'hotspot' || Array.isArray(mapData.hotspots) || Array.isArray(mapData.hotspots_detail)) {
        renderHotspotMap(mapData, msgContainer);
        return;
    }

    if (mapData.type === 'raster' || mapData.raster_grid) {
        renderRasterMap(mapData, msgContainer);
        return;
    }

    if (mapData.type === 'concentration' || mapData.concentration_grid || Array.isArray(mapData.layers)) {
        if (mapData.raster_grid) {
            renderRasterMap({ ...mapData, type: 'raster' }, msgContainer);
            return;
        }
        renderConcentrationMap(mapData, msgContainer);
        return;
    }

    renderEmissionMap(mapData, msgContainer);
}

function renderMapData(mapData, msgContainer) {
    const mapItems = getMapPayloadItems(mapData);
    if (!mapItems.length) {
        console.warn('[Map] Invalid map data payload');
        return;
    }

    ensureLeafletStackingStyles();

    mapItems.forEach((item, index) => {
        if (!hasRenderableSingleMapData(item)) {
            console.warn(`[Map] Skipping non-renderable map payload at index ${index}`);
            return;
        }
        renderSingleMapData(item, msgContainer);
    });
}

function initRankedBarChart(chartData, chartId) {
    const chartEl = chartId ? document.getElementById(chartId) : null;
    const fallbackCharts = !chartEl ? document.querySelectorAll('.emission-chart') : null;
    const resolvedChartEl = chartEl || (fallbackCharts?.length ? fallbackCharts[fallbackCharts.length - 1] : null);
    if (!resolvedChartEl) {
        console.error('Chart container not found');
        return;
    }

    clearChartInitError(resolvedChartEl);

    if (typeof echarts === 'undefined') {
        showChartInitError(resolvedChartEl, 'Chart init failed: ECharts not loaded, retrying...');
        if (!resolvedChartEl.dataset.echartsRetry) {
            resolvedChartEl.dataset.echartsRetry = '1';
            ensureEchartsLoaded()
                .then(() => initRankedBarChart(chartData, chartId))
                .catch(() => showChartInitError(resolvedChartEl, 'Chart init failed: ECharts load failed'));
        }
        return;
    }

    const categories = Array.isArray(chartData.categories) ? chartData.categories : [];
    const values = Array.isArray(chartData.values) ? chartData.values : [];
    if (!categories.length || !values.length || categories.length !== values.length) {
        showChartInitError(resolvedChartEl, 'Chart init failed: missing ranked bar chart data');
        return;
    }

    let chart;
    try {
        chart = echarts.init(resolvedChartEl);
    } catch (err) {
        showChartInitError(resolvedChartEl, 'Chart init failed: ECharts render error');
        console.error(err);
        return;
    }

    const metricLabel = chartData.metric_label || chartData.ranking_metric || 'metric';
    const option = {
        color: ['#0f8f66'],
        tooltip: {
            trigger: 'axis',
            axisPointer: {
                type: 'shadow'
            },
            backgroundColor: 'rgba(0,0,0,0.8)',
            borderColor: 'transparent',
            textStyle: { color: '#fff' },
            formatter: (params) => {
                const p = params[0];
                return `<div style="padding: 4px 8px;">
                    <div style="font-weight: bold;">${p.name}</div>
                    <div>${metricLabel}: ${typeof p.value === 'number' ? p.value.toFixed(4) : p.value}</div>
                </div>`;
            }
        },
        grid: {
            left: '8%',
            right: '5%',
            bottom: '22%',
            top: '10%'
        },
        xAxis: {
            type: 'category',
            data: categories,
            axisLabel: {
                interval: 0,
                rotate: categories.length > 4 ? 28 : 0,
                color: '#666'
            },
            axisLine: { lineStyle: { color: '#ddd' } }
        },
        yAxis: {
            type: 'value',
            name: metricLabel,
            nameTextStyle: { color: '#666', fontSize: 12 },
            axisLine: { lineStyle: { color: '#ddd' } },
            splitLine: { lineStyle: { color: '#f0f0f0' } }
        },
        series: [{
            type: 'bar',
            data: values,
            barMaxWidth: 42,
            itemStyle: {
                borderRadius: [8, 8, 0, 0],
                color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                    { offset: 0, color: '#16c47f' },
                    { offset: 1, color: '#0f8f66' }
                ])
            }
        }]
    };

    chart.setOption(option);
    window.addEventListener('resize', () => chart.resize());
}

function initChartPayload(chartData, chartId) {
    if (chartData?.type === 'ranked_bar_chart') {
        initRankedBarChart(chartData, chartId);
        return;
    }
    initEmissionChart(chartData, chartId);
}

function renderEmissionMap(mapData, msgContainer) {
    if (!mapData || !mapData.links || mapData.links.length === 0) {
        console.warn('[Map] No valid map data provided');
        return;
    }

    console.log(`[Map] renderEmissionMap called with ${mapData.links.length} links`);

    const mapId = `emission-map-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const pollutants = Object.keys(mapData.links[0].emissions || {});
    const defaultPollutant = mapData.pollutant || (pollutants[0] || 'CO2');

    // Create pollutant selector options
    const pollutantOptions = pollutants.map(p =>
        `<option value="${p}" ${p === defaultPollutant ? 'selected' : ''}>${p}</option>`
    ).join('');

    // Create color scale legend
    const colorScale = mapData.color_scale || {};
    const minVal = colorScale.min || 0;
    const maxVal = colorScale.max || 100;
    const legendGradient = 'linear-gradient(to right, #3B82F6, #10B981, #F5D046, #F97316, #DC2626)';

    // Build map HTML
    const mapHtml = `
        <div class="message-map-wrapper message-map-surface w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm p-6 mt-4" data-map-id="${mapId}">
            <div class="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                    <h3 class="text-slate-900 dark:text-white font-bold text-lg">路段排放地图</h3>
                    <p class="text-slate-500 text-sm">显示 ${mapData.links.length} 个路段的 ${defaultPollutant} 排放</p>
                </div>
                <div class="flex items-center gap-3">
                    <select id="${mapId}-pollutant" class="px-3 py-1.5 rounded-md text-sm border border-slate-200 dark:border-slate-600 bg-white dark:bg-slate-700 text-slate-800 dark:text-slate-200 min-w-[80px] focus:outline-none focus:ring-2 focus:ring-primary">
                        ${pollutantOptions}
                    </select>
                </div>
            </div>
            <div id="${mapId}" style="height: 480px;" class="message-map-container rounded-lg overflow-hidden border border-slate-200 dark:border-slate-600"></div>
            <div class="mt-4 flex items-center gap-4 text-sm">
                <div class="flex items-center gap-3">
                    <span class="text-slate-600 dark:text-slate-400">低排放</span>
                    <div class="w-40 h-3 rounded" style="background: ${legendGradient}"></div>
                    <span class="text-slate-600 dark:text-slate-400">高排放</span>
                </div>
                <div class="ml-auto text-slate-500 dark:text-slate-400">
                    <span>${minVal.toFixed(2)} - ${maxVal.toFixed(2)} kg/(h·km)</span>
                </div>
            </div>
        </div>
    `;

    // Insert map into message content
    const contentDiv = msgContainer.querySelector('.message-content');
    console.log('[Map] msgContainer:', msgContainer);
    console.log('[Map] contentDiv found:', !!contentDiv);

    if (contentDiv) {
        contentDiv.insertAdjacentHTML('beforeend', mapHtml);
        scrollToBottom();

        // Initialize map after a delay to ensure DOM is ready
        setTimeout(() => {
            console.log(`[Map] Initializing map ${mapId}`);
            const mapContainer = document.getElementById(mapId);
            if (!mapContainer) {
                console.error(`[Map] Map container ${mapId} not found in DOM`);
                return;
            }

            initLeafletMap(mapData, mapId, defaultPollutant);

            // Add pollutant change listener
            const select = document.getElementById(`${mapId}-pollutant`);
            if (select) {
                select.addEventListener('change', (e) => {
                    const newPollutant = e.target.value;
                    console.log(`[Map] Switching to pollutant: ${newPollutant}`);
                    initLeafletMap(mapData, mapId, newPollutant);
                });
            }
        }, 150);  // Increased delay to 150ms for better reliability
    } else {
        console.error('[Map] Message content div not found');
    }
}

function formatMapValue(value) {
    const numeric = Number(value || 0);
    if (!Number.isFinite(numeric)) {
        return '0.000';
    }
    const absVal = Math.abs(numeric);
    if (absVal >= 100) {
        return numeric.toFixed(1);
    }
    if (absVal >= 10) {
        return numeric.toFixed(2);
    }
    if (absVal >= 1) {
        return numeric.toFixed(3);
    }
    return numeric.toFixed(4);
}

function computeMapZoom(span) {
    if (span > 10) return 6;
    if (span > 5) return 7;
    if (span > 2) return 8;
    if (span > 1) return 9;
    if (span > 0.5) return 10;
    if (span > 0.2) return 11;
    if (span > 0.1) return 12;
    if (span > 0.05) return 13;
    return 14;
}

function normalizeRasterMapData(mapData) {
    if (!mapData || typeof mapData !== 'object') {
        return null;
    }

    if (
        mapData.type === 'raster' &&
        Array.isArray(mapData.layers) &&
        mapData.layers[0]?.data?.features?.length
    ) {
        return mapData;
    }

    const raster = mapData.raster_grid;
    if (!raster || typeof raster !== 'object') {
        return null;
    }

    const cellCenters = Array.isArray(raster.cell_centers_wgs84) ? raster.cell_centers_wgs84 : [];
    if (cellCenters.length === 0) {
        return null;
    }

    const resolution = Number(raster.resolution_m || 50);
    const pollutant = mapData.pollutant || mapData.query_info?.pollutant || 'NOx';
    const values = [];
    const features = [];
    const lons = [];
    const lats = [];

    cellCenters.forEach((cell) => {
        const meanConc = Number(cell.mean_conc ?? 0);
        const maxConc = Number(cell.max_conc ?? meanConc);
        const lon = Number(cell.lon);
        const lat = Number(cell.lat);

        if (!Number.isFinite(meanConc) || !Number.isFinite(maxConc) || !Number.isFinite(lon) || !Number.isFinite(lat)) {
            return;
        }
        if (meanConc <= 0) {
            return;
        }

        const cosLat = Math.max(Math.abs(Math.cos((lat * Math.PI) / 180)), 1e-6);
        const dLat = (resolution / 2) / 111320;
        const dLon = (resolution / 2) / (111320 * cosLat);

        values.push(meanConc);
        lons.push(lon);
        lats.push(lat);

        features.push({
            type: 'Feature',
            geometry: {
                type: 'Polygon',
                coordinates: [[
                    [lon - dLon, lat - dLat],
                    [lon + dLon, lat - dLat],
                    [lon + dLon, lat + dLat],
                    [lon - dLon, lat + dLat],
                    [lon - dLon, lat - dLat],
                ]]
            },
            properties: {
                row: cell.row,
                col: cell.col,
                mean_conc: Number(meanConc.toFixed(4)),
                max_conc: Number(maxConc.toFixed(4)),
                value: Number(meanConc.toFixed(4)),
            }
        });
    });

    if (features.length === 0 || values.length === 0) {
        return null;
    }

    const minLon = Math.min(...lons);
    const maxLon = Math.max(...lons);
    const minLat = Math.min(...lats);
    const maxLat = Math.max(...lats);
    const span = Math.max(maxLon - minLon, maxLat - minLat);
    const stats = raster.stats || {};

    return {
        type: 'raster',
        title: mapData.title || `${pollutant} Concentration Field (${Math.round(resolution)}m grid)`,
        pollutant,
        center: [(minLat + maxLat) / 2, (minLon + maxLon) / 2],
        zoom: computeMapZoom(span),
        layers: [{
            id: 'concentration_raster',
            type: 'polygon',
            data: {
                type: 'FeatureCollection',
                features
            },
            style: {
                color_field: 'value',
                color_scale: 'YlOrRd',
                value_range: [Math.min(...values), Math.max(...values)],
                opacity: 0.7,
                stroke: false,
                legend_title: `${pollutant} Concentration`,
                legend_unit: 'μg/m³',
                resolution_m: resolution,
            }
        }],
        coverage_assessment: mapData.coverage_assessment || {},
        summary: {
            total_cells: Number(stats.total_cells || 0),
            nonzero_cells: Number(stats.nonzero_cells || features.length),
            resolution_m: resolution,
            mean_concentration: Number((values.reduce((sum, value) => sum + value, 0) / values.length).toFixed(4)),
            max_concentration: Number(Math.max(...values).toFixed(4)),
            unit: 'μg/m³',
        }
    };
}

function normalizeHotspotMapData(mapData) {
    if (!mapData || typeof mapData !== 'object') {
        return null;
    }

    if (
        mapData.type === 'hotspot' &&
        Array.isArray(mapData.layers) &&
        mapData.layers.length > 0 &&
        Array.isArray(mapData.hotspots_detail)
    ) {
        return mapData;
    }

    const hotspots = Array.isArray(mapData.hotspots_detail)
        ? mapData.hotspots_detail
        : (Array.isArray(mapData.hotspots) ? mapData.hotspots : []);
    if (hotspots.length === 0) {
        return null;
    }

    const hotspotFeatures = [];
    const centerLons = [];
    const centerLats = [];
    const contributingRoadIds = new Set();

    hotspots.forEach((hotspot) => {
        const center = hotspot.center || {};
        const centerLon = Number(center.lon);
        const centerLat = Number(center.lat);
        if (Number.isFinite(centerLon) && Number.isFinite(centerLat)) {
            centerLons.push(centerLon);
            centerLats.push(centerLat);
        }

        let bbox = Array.isArray(hotspot.bbox) ? hotspot.bbox : [];
        if (bbox.length < 4) {
            if (!Number.isFinite(centerLon) || !Number.isFinite(centerLat)) {
                return;
            }
            bbox = [centerLon - 0.001, centerLat - 0.001, centerLon + 0.001, centerLat + 0.001];
        }

        hotspotFeatures.push({
            type: 'Feature',
            geometry: {
                type: 'Polygon',
                coordinates: [[
                    [Number(bbox[0]), Number(bbox[1])],
                    [Number(bbox[2]), Number(bbox[1])],
                    [Number(bbox[2]), Number(bbox[3])],
                    [Number(bbox[0]), Number(bbox[3])],
                    [Number(bbox[0]), Number(bbox[1])],
                ]]
            },
            properties: {
                hotspot_id: hotspot.hotspot_id,
                rank: hotspot.rank,
                max_conc: Number(hotspot.max_conc || 0),
                mean_conc: Number(hotspot.mean_conc || 0),
                area_m2: Number(hotspot.area_m2 || 0),
                grid_cells: Number(hotspot.grid_cells || 0),
            }
        });

        (hotspot.contributing_roads || []).forEach((road) => {
            const roadId = String(road.link_id || '').trim();
            if (roadId) {
                contributingRoadIds.add(roadId);
            }
        });
    });

    if (hotspotFeatures.length === 0) {
        return null;
    }

    const rasterMap = normalizeRasterMapData({
        type: 'raster',
        title: mapData.title,
        pollutant: mapData.pollutant || mapData.query_info?.pollutant || 'NOx',
        raster_grid: mapData.raster_grid,
        coverage_assessment: mapData.coverage_assessment,
    });

    const layers = [];
    if (rasterMap?.layers?.[0]) {
        layers.push(rasterMap.layers[0]);
    }
    layers.push({
        id: 'hotspot_areas',
        type: 'hotspot_polygon',
        data: {
            type: 'FeatureCollection',
            features: hotspotFeatures,
        },
        style: {
            color: '#FF0000',
            weight: 3,
            dashArray: '8, 4',
            fillColor: '#FF0000',
            fillOpacity: 0.1,
            opacity: 0.9,
        }
    });

    const minLon = centerLons.length ? Math.min(...centerLons) : 121.47;
    const maxLon = centerLons.length ? Math.max(...centerLons) : 121.47;
    const minLat = centerLats.length ? Math.min(...centerLats) : 31.23;
    const maxLat = centerLats.length ? Math.max(...centerLats) : 31.23;
    const span = Math.max(maxLon - minLon, maxLat - minLat);

    return {
        type: 'hotspot',
        title: mapData.title || 'Pollution Hotspot Analysis',
        center: [(minLat + maxLat) / 2, (minLon + maxLon) / 2],
        zoom: computeMapZoom(span || 0.05),
        interpretation: mapData.interpretation || '',
        layers,
        hotspots_detail: hotspots,
        contributing_road_ids: Array.from(contributingRoadIds),
        coverage_assessment: mapData.coverage_assessment || {},
        summary: mapData.summary || {},
    };
}

function interpolateYlOrRd(ratio) {
    const colors = [
        [255, 255, 204],
        [255, 237, 160],
        [254, 217, 118],
        [254, 178, 76],
        [253, 141, 60],
        [252, 78, 42],
        [227, 26, 28],
        [189, 0, 38],
        [128, 0, 38],
    ];

    const clamped = Math.max(0, Math.min(1, Number(ratio) || 0));
    const index = Math.min(Math.floor(clamped * colors.length), colors.length - 1);
    const [r, g, b] = colors[index];
    return `rgb(${r},${g},${b})`;
}

function getRasterColor(value, minVal, maxVal) {
    const numericValue = Number(value || 0);
    const numericMin = Number(minVal || 0);
    const numericMax = Number(maxVal || 0);

    if (!Number.isFinite(numericValue) || numericMax <= numericMin) {
        return interpolateYlOrRd(0);
    }

    if (numericValue <= 0 || numericMin <= 0) {
        const linearRatio = Math.max(0, Math.min(1, (numericValue - numericMin) / (numericMax - numericMin || 1)));
        return interpolateYlOrRd(linearRatio);
    }

    const logMin = Math.log10(Math.max(numericMin, 1e-6));
    const logMax = Math.log10(Math.max(numericMax, 1e-6));
    const logVal = Math.log10(Math.max(numericValue, 1e-6));
    const logRatio = Math.max(0, Math.min(1, (logVal - logMin) / (logMax - logMin || 1)));
    return interpolateYlOrRd(logRatio);
}

function renderCoverageWarning(coverage) {
    if (!coverage || typeof coverage !== 'object') {
        return '';
    }

    const level = coverage.level;
    if (level === 'complete_regional') {
        return '';
    }

    const warnings = Array.isArray(coverage.warnings) ? coverage.warnings.filter(Boolean) : [];
    const message = warnings.length > 0
        ? warnings.join(' | ')
        : String(coverage.result_semantics || '').trim();
    if (!message) {
        return '';
    }

    const sparse = level === 'sparse_local';
    const bgColor = sparse ? '#FFF3CD' : '#D4EDDA';
    const borderColor = sparse ? '#F59E0B' : '#10B981';
    const textColor = sparse ? '#92400E' : '#166534';
    const icon = sparse ? '⚠️' : 'ℹ️';

    return `
        <div class="mb-4 rounded-xl px-4 py-3 text-sm" style="background:${bgColor}; border:1px solid ${borderColor}; color:${textColor};">
            <strong>${icon} Coverage:</strong> ${escapeHtml(message)}
        </div>
    `;
}

function renderInterpretationBanner(interpretation) {
    const text = String(interpretation || '').trim();
    if (!text) {
        return '';
    }

    return `
        <div class="mb-4 rounded-xl px-4 py-3 text-sm border border-sky-200 bg-sky-50 text-sky-900">
            <strong>Interpretation:</strong> ${escapeHtml(text)}
        </div>
    `;
}

function renderRasterLegend(style, minVal, maxVal) {
    const resolution = Number(style?.resolution_m || 0);
    const legendTitle = escapeHtml(style?.legend_title || 'Concentration');
    const legendUnit = escapeHtml(style?.legend_unit || 'μg/m³');
    const gradient = 'linear-gradient(to right, #FFFFCC, #FFEDA0, #FED976, #FEB24C, #FD8D3C, #FC4E2A, #E31A1C, #BD0026, #800026)';

    return `
        <div class="mt-4 flex flex-wrap items-center gap-4 text-sm">
            <div class="flex flex-col gap-1">
                <div class="font-semibold text-slate-700 dark:text-slate-200">${legendTitle}</div>
                <div class="flex items-center gap-3">
                    <span class="text-slate-600 dark:text-slate-400">低浓度</span>
                    <div class="w-48 h-3 rounded" style="background: ${gradient}"></div>
                    <span class="text-slate-600 dark:text-slate-400">高浓度</span>
                </div>
                <div class="flex items-center justify-between text-slate-500 dark:text-slate-400">
                    <span>${formatMapValue(minVal)} ${legendUnit}</span>
                    <span>${formatMapValue(maxVal)} ${legendUnit}</span>
                </div>
            </div>
            <div class="ml-auto text-slate-500 dark:text-slate-400">
                ${resolution > 0 ? `${Math.round(resolution)}m grid` : ''}
            </div>
        </div>
    `;
}

function renderHotspotLegend(rasterStyle, minVal, maxVal, roadCount) {
    const rasterLegend = rasterStyle
        ? renderRasterLegend(rasterStyle, minVal, maxVal)
        : '';
    const roadLabel = Number(roadCount || 0) > 0
        ? `<div class="text-slate-500 dark:text-slate-400">候选贡献路段: ${Number(roadCount)}</div>`
        : '';

    return `
        ${rasterLegend}
        <div class="mt-3 flex flex-wrap items-center gap-4 text-sm">
            <div class="flex items-center gap-2 text-slate-700 dark:text-slate-200">
                <span class="inline-block w-6 h-3 rounded-sm" style="border: 3px dashed #FF0000; background: rgba(255,0,0,0.1);"></span>
                <span>热点区域 / Hotspot Areas</span>
            </div>
            <div class="flex items-center gap-2 text-slate-700 dark:text-slate-200">
                <span class="inline-flex items-center justify-center w-6 h-6 rounded-full text-white text-xs font-bold" style="background:#FF0000;">#</span>
                <span>热点编号 / Rank Label</span>
            </div>
            ${roadLabel}
        </div>
    `;
}

function initAnalysisLeafletMap(mapId) {
    if (typeof L === 'undefined') {
        console.error('[Map] Leaflet not loaded');
        return null;
    }

    const mapContainer = document.getElementById(mapId);
    if (!mapContainer) {
        console.error(`[Map] Map container not found: ${mapId}`);
        return null;
    }

    mapContainer.style.backgroundColor = '#ffffff';

    const map = L.map(mapId, {
        attributionControl: true,
        zoomControl: true,
        preferCanvas: true,
        renderer: L.canvas({ padding: 0.5 })
    });
    mapContainer._leaflet_map = map;

    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(map);

    const layerControl = L.control.layers(null, {}, {
        position: 'topright',
        collapsed: true
    }).addTo(map);

    const labelsLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        subdomains: 'abcd',
        pane: 'overlayPane'
    });
    layerControl.addOverlay(labelsLayer, '地名标注 / Labels');

    try {
        loadGISBasemap().then((basemapData) => {
            if (basemapData && !basemapData.error) {
                const basemapLayer = L.geoJSON(basemapData, {
                    style: { color: '#94a3b8', weight: 1, fill: false, opacity: 0.5 }
                });
                layerControl.addOverlay(basemapLayer, '行政边界');
            }
        }).catch(() => {});

        loadGISRoadNetwork().then((roadData) => {
            if (roadData && !roadData.error) {
                const roadLayer = L.geoJSON(roadData, {
                    style: { color: '#cbd5e1', weight: 0.5, opacity: 0.25 }
                });
                layerControl.addOverlay(roadLayer, '路网底图');
            }
        }).catch(() => {});
    } catch (e) {}

    map.attributionControl.setPrefix('© Emission Agent');
    return { map, mapContainer, layerControl };
}

function getRoadFeatureIdentifiers(feature) {
    const props = feature?.properties || {};
    const keys = ['link_id', 'LINK_ID', 'road_id', 'ROAD_ID', 'id', 'ID', 'name', 'NAME', 'NAME_1', 'segment_id'];
    return keys
        .map((key) => {
            const value = props[key];
            return value === null || value === undefined ? '' : String(value).trim();
        })
        .filter(Boolean);
}

function tryAddHighlightedRoadLayer(map, layerControl, contributingRoadIds) {
    const ids = (contributingRoadIds || [])
        .map((value) => String(value || '').trim())
        .filter(Boolean);
    if (!map || ids.length === 0) {
        return;
    }

    const roadIdSet = new Set(ids);
    loadGISRoadNetwork().then((roadData) => {
        if (!roadData || roadData.error || !Array.isArray(roadData.features)) {
            return;
        }

        const matchedFeatures = roadData.features.filter((feature) =>
            getRoadFeatureIdentifiers(feature).some((identifier) => roadIdSet.has(identifier))
        );
        if (matchedFeatures.length === 0) {
            console.info('[Map] No GIS road features matched contributing road IDs');
            return;
        }

        const highlightLayer = L.geoJSON(
            {
                type: 'FeatureCollection',
                features: matchedFeatures
            },
            {
                style: {
                    color: '#B91C1C',
                    weight: 4,
                    opacity: 0.95
                },
                onEachFeature: (feature, layer) => {
                    const props = feature.properties || {};
                    const displayName =
                        props.link_id ||
                        props.LINK_ID ||
                        props.road_id ||
                        props.id ||
                        props.name ||
                        'Contributing Road';
                    layer.bindPopup(`
                        <div style="min-width: 180px;">
                            <h3 style="font-weight: bold; margin: 0 0 8px 0;">${escapeHtml(String(displayName))}</h3>
                            <div style="font-size: 13px; line-height: 1.6;">热点贡献候选路段</div>
                        </div>
                    `);
                }
            }
        );

        highlightLayer.addTo(map);
        layerControl.addOverlay(highlightLayer, '贡献路段 / Contributing Roads');
    }).catch((error) => {
        console.warn('[Map] Failed to build contributing road highlight layer:', error);
    });
}

function initRasterLeafletMap(mapData, mapId) {
    const initialized = initAnalysisLeafletMap(mapId);
    if (!initialized) {
        return;
    }

    const { map, mapContainer, layerControl } = initialized;
    const layer = mapData.layers?.[0];
    const features = layer?.data?.features || [];
    if (features.length === 0) {
        console.warn('[Map] No raster features to render');
        return;
    }

    const style = layer.style || {};
    const [minVal, maxVal] = style.value_range || [0, 1];
    const unit = style.legend_unit || mapData.summary?.unit || 'μg/m³';

    const rasterLayer = L.geoJSON(layer.data, {
        style: (feature) => {
            const value = Number(feature.properties?.value || 0);
            return {
                fillColor: getRasterColor(value, minVal, maxVal),
                fillOpacity: Number(style.opacity || 0.7),
                stroke: false,
                fill: true,
            };
        },
        onEachFeature: (feature, rasterCell) => {
            const props = feature.properties || {};
            rasterCell.bindPopup(
                `<div style="min-width: 170px;">
                    <h3 style="font-weight: bold; margin: 0 0 8px 0;">Grid Cell</h3>
                    <div style="font-size: 13px; line-height: 1.6;">
                        <div><strong>Mean:</strong> ${formatMapValue(props.mean_conc || 0)} ${unit}</div>
                        <div><strong>Max:</strong> ${formatMapValue(props.max_conc || 0)} ${unit}</div>
                    </div>
                </div>`
            );
        }
    });

    rasterLayer.addTo(map);
    layerControl.addOverlay(rasterLayer, '浓度栅格 / Concentration Raster');
    mapContainer._raster_layer = rasterLayer;
    mapContainer._map_data = mapData;

    const bounds = rasterLayer.getBounds();
    if (bounds.isValid()) {
        map.fitBounds(bounds, { padding: [20, 20], maxZoom: 16 });
    } else if (Array.isArray(mapData.center) && mapData.center.length === 2) {
        map.setView(mapData.center, mapData.zoom || 12);
    } else {
        map.setView([31.23, 121.47], 12);
    }

    setTimeout(() => {
        map.invalidateSize();
    }, 100);
}

function initHotspotLeafletMap(mapData, mapId) {
    const initialized = initAnalysisLeafletMap(mapId);
    if (!initialized) {
        return;
    }

    const { map, mapContainer, layerControl } = initialized;
    const layers = Array.isArray(mapData.layers) ? mapData.layers : [];
    const rasterLayerData = layers.find((layer) => layer.id === 'concentration_raster');
    const hotspotLayerData = layers.find((layer) => layer.id === 'hotspot_areas');

    let rasterLayer = null;
    if (rasterLayerData?.data?.features?.length) {
        const [minVal, maxVal] = rasterLayerData.style?.value_range || [0, 1];
        rasterLayer = L.geoJSON(rasterLayerData.data, {
            style: (feature) => ({
                fillColor: getRasterColor(Number(feature.properties?.value || 0), minVal, maxVal),
                fillOpacity: 0.5,
                stroke: false,
                fill: true,
            })
        });
        rasterLayer.addTo(map);
        layerControl.addOverlay(rasterLayer, '浓度背景 / Concentration Background');
    }

    let hotspotLayer = null;
    if (hotspotLayerData?.data?.features?.length) {
        hotspotLayer = L.geoJSON(hotspotLayerData.data, {
            style: () => ({
                color: '#FF0000',
                weight: 3,
                dashArray: '8, 4',
                fillColor: '#FF0000',
                fillOpacity: 0.1,
                opacity: 0.9,
            }),
            onEachFeature: (feature, layer) => {
                const props = feature.properties || {};
                const hotspotDetail = (mapData.hotspots_detail || []).find(
                    (hotspot) => Number(hotspot.hotspot_id) === Number(props.hotspot_id)
                );

                let popupContent =
                    `<div style="min-width: 220px;">` +
                    `<h3 style="font-weight: bold; margin: 0 0 8px 0;">Hotspot #${escapeHtml(String(props.rank ?? '-'))}</h3>` +
                    `<div style="font-size: 13px; line-height: 1.6;">` +
                    `<div><strong>Max:</strong> ${formatMapValue(props.max_conc || 0)} μg/m³</div>` +
                    `<div><strong>Mean:</strong> ${formatMapValue(props.mean_conc || 0)} μg/m³</div>` +
                    `<div><strong>Area:</strong> ${formatMapValue(props.area_m2 || 0)} m²</div>` +
                    `</div>`;

                if (hotspotDetail && Array.isArray(hotspotDetail.contributing_roads) && hotspotDetail.contributing_roads.length > 0) {
                    popupContent += '<div style="margin-top: 8px; font-size: 13px; line-height: 1.6;"><strong>Top Contributing Roads:</strong>';
                    hotspotDetail.contributing_roads.slice(0, 5).forEach((road) => {
                        popupContent += `<div>${escapeHtml(String(road.link_id || '-'))}: ${formatMapValue(road.contribution_pct || 0)}%</div>`;
                    });
                    popupContent += '</div>';
                }

                popupContent += '</div>';
                layer.bindPopup(popupContent);
            }
        });
        hotspotLayer.addTo(map);
        layerControl.addOverlay(hotspotLayer, '热点区域 / Hotspot Areas');
    }

    const hotspotLabels = L.layerGroup();
    (mapData.hotspots_detail || []).forEach((hotspot) => {
        const center = hotspot.center || {};
        const lon = Number(center.lon);
        const lat = Number(center.lat);
        if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
            return;
        }

        const icon = L.divIcon({
            className: 'hotspot-label',
            html: `<div style="
                background: #FF0000;
                color: white;
                border-radius: 50%;
                width: 24px;
                height: 24px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: bold;
                font-size: 12px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.3);
            ">#${escapeHtml(String(hotspot.rank || '?'))}</div>`,
            iconSize: [24, 24],
            iconAnchor: [12, 12],
        });
        hotspotLabels.addLayer(L.marker([lat, lon], { icon }));
    });
    if (hotspotLabels.getLayers().length > 0) {
        hotspotLabels.addTo(map);
        layerControl.addOverlay(hotspotLabels, '热点编号 / Labels');
    }

    tryAddHighlightedRoadLayer(map, layerControl, mapData.contributing_road_ids || []);

    mapContainer._map_data = mapData;
    mapContainer._hotspot_layer = hotspotLayer;

    if (hotspotLayer && hotspotLayer.getBounds().isValid()) {
        map.fitBounds(hotspotLayer.getBounds(), { padding: [20, 20], maxZoom: 16 });
    } else if (rasterLayer && rasterLayer.getBounds().isValid()) {
        map.fitBounds(rasterLayer.getBounds(), { padding: [20, 20], maxZoom: 16 });
    } else if (Array.isArray(mapData.center) && mapData.center.length === 2) {
        map.setView(mapData.center, mapData.zoom || 12);
    } else {
        map.setView([31.23, 121.47], 12);
    }

    setTimeout(() => {
        map.invalidateSize();
    }, 100);
}

function renderRasterMap(mapData, msgContainer) {
    const normalizedMapData = normalizeRasterMapData(mapData);
    const layer = normalizedMapData?.layers?.[0];
    const features = layer?.data?.features || [];
    if (!normalizedMapData || features.length === 0) {
        console.warn('[Map] No valid raster map data provided');
        return;
    }

    const style = layer.style || {};
    const [minVal, maxVal] = style.value_range || [0, 1];
    const pollutant = normalizedMapData.pollutant || 'NOx';
    const unit = style.legend_unit || normalizedMapData.summary?.unit || 'μg/m³';
    const coverageHtml = renderCoverageWarning(normalizedMapData.coverage_assessment);
    const mapId = `raster-map-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;

    const mapHtml = `
        <div class="message-map-wrapper message-map-surface w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm p-6 mt-4" data-map-id="${mapId}">
            <div class="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                    <h3 class="text-slate-900 dark:text-white font-bold text-lg">${escapeHtml(normalizedMapData.title || `${pollutant} Concentration Field`)}</h3>
                    <p class="text-slate-500 text-sm">显示 ${features.length} 个非零栅格单元的 ${pollutant} 浓度场</p>
                </div>
                <div class="text-sm text-slate-500 dark:text-slate-400 text-right">
                    <div>平均浓度 ${formatMapValue(normalizedMapData.summary?.mean_concentration || 0)} ${unit}</div>
                    <div>最大浓度 ${formatMapValue(normalizedMapData.summary?.max_concentration || 0)} ${unit}</div>
                    <div>分辨率 ${Math.round(Number(normalizedMapData.summary?.resolution_m || style.resolution_m || 50))} m</div>
                </div>
            </div>
            ${coverageHtml}
            <div id="${mapId}" style="height: 520px;" class="message-map-container rounded-lg overflow-hidden border border-slate-200 dark:border-slate-600"></div>
            ${renderRasterLegend(style, minVal, maxVal)}
        </div>
    `;

    const contentDiv = msgContainer.querySelector('.message-content');
    if (!contentDiv) {
        console.error('[Map] Message content div not found for raster map');
        return;
    }

    contentDiv.insertAdjacentHTML('beforeend', mapHtml);
    scrollToBottom();

    setTimeout(() => {
        const mapContainer = document.getElementById(mapId);
        if (!mapContainer) {
            console.error(`[Map] Raster map container ${mapId} not found in DOM`);
            return;
        }
        initRasterLeafletMap(normalizedMapData, mapId);
    }, 150);
}

function renderHotspotMap(mapData, msgContainer) {
    const normalizedMapData = normalizeHotspotMapData(mapData);
    const hotspotCount = normalizedMapData?.hotspots_detail?.length || 0;
    if (!normalizedMapData || hotspotCount === 0) {
        console.warn('[Map] No valid hotspot map data provided');
        return;
    }

    const rasterLayer = normalizedMapData.layers.find((layer) => layer.id === 'concentration_raster');
    const rasterStyle = rasterLayer?.style || null;
    const [minVal, maxVal] = rasterStyle?.value_range || [0, 1];
    const interpretationHtml = renderInterpretationBanner(normalizedMapData.interpretation);
    const coverageHtml = renderCoverageWarning(normalizedMapData.coverage_assessment);
    const mapId = `hotspot-map-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const summary = normalizedMapData.summary || {};

    const mapHtml = `
        <div class="message-map-wrapper message-map-surface w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm p-6 mt-4" data-map-id="${mapId}">
            <div class="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                    <h3 class="text-slate-900 dark:text-white font-bold text-lg">${escapeHtml(normalizedMapData.title || 'Pollution Hotspot Analysis')}</h3>
                    <p class="text-slate-500 text-sm">识别出 ${hotspotCount} 个热点区域，并展示热点源归因结果</p>
                </div>
                <div class="text-sm text-slate-500 dark:text-slate-400 text-right">
                    <div>热点面积 ${formatMapValue(summary.total_hotspot_area_m2 || 0)} m²</div>
                    <div>区域占比 ${formatMapValue(summary.area_fraction_pct || 0)}%</div>
                    <div>最高浓度 ${formatMapValue(summary.max_concentration || 0)} μg/m³</div>
                </div>
            </div>
            ${interpretationHtml}
            ${coverageHtml}
            <div id="${mapId}" style="height: 540px;" class="message-map-container rounded-lg overflow-hidden border border-slate-200 dark:border-slate-600"></div>
            ${renderHotspotLegend(rasterStyle, minVal, maxVal, normalizedMapData.contributing_road_ids?.length || 0)}
        </div>
    `;

    const contentDiv = msgContainer.querySelector('.message-content');
    if (!contentDiv) {
        console.error('[Map] Message content div not found for hotspot map');
        return;
    }

    contentDiv.insertAdjacentHTML('beforeend', mapHtml);
    scrollToBottom();

    setTimeout(() => {
        const mapContainer = document.getElementById(mapId);
        if (!mapContainer) {
            console.error(`[Map] Hotspot map container ${mapId} not found in DOM`);
            return;
        }
        initHotspotLeafletMap(normalizedMapData, mapId);
    }, 150);
}

function normalizeConcentrationMapData(mapData) {
    if (!mapData || typeof mapData !== 'object') {
        return null;
    }

    if (Array.isArray(mapData.layers) && mapData.layers.length > 0) {
        return mapData;
    }

    const concentrationGrid = mapData.concentration_grid || {};
    const receptors = Array.isArray(concentrationGrid.receptors) ? concentrationGrid.receptors : [];
    if (receptors.length === 0) {
        return null;
    }

    const pollutant = mapData.pollutant || mapData.query_info?.pollutant || 'NOx';
    const validReceptors = receptors
        .map((receptor, index) => {
            const lon = Number(receptor.lon);
            const lat = Number(receptor.lat);
            const meanConc = Number(receptor.mean_conc ?? receptor.value ?? 0);
            const maxConc = Number(receptor.max_conc ?? meanConc);
            if (!Number.isFinite(lon) || !Number.isFinite(lat) || !Number.isFinite(meanConc) || !Number.isFinite(maxConc)) {
                return null;
            }
            return {
                type: 'Feature',
                geometry: { type: 'Point', coordinates: [lon, lat] },
                properties: {
                    receptor_id: receptor.receptor_id ?? index,
                    mean_conc: meanConc,
                    max_conc: maxConc,
                    value: meanConc,
                }
            };
        })
        .filter(Boolean);

    if (validReceptors.length === 0) {
        return null;
    }

    const nonZeroFeatures = validReceptors.filter(feature => feature.properties.value > 0);
    const features = nonZeroFeatures.length > 0 ? nonZeroFeatures : validReceptors;
    const values = features.map(feature => feature.properties.value);
    const bounds = concentrationGrid.bounds || {};
    const minLon = Number.isFinite(Number(bounds.min_lon))
        ? Number(bounds.min_lon)
        : Math.min(...features.map(feature => feature.geometry.coordinates[0]));
    const maxLon = Number.isFinite(Number(bounds.max_lon))
        ? Number(bounds.max_lon)
        : Math.max(...features.map(feature => feature.geometry.coordinates[0]));
    const minLat = Number.isFinite(Number(bounds.min_lat))
        ? Number(bounds.min_lat)
        : Math.min(...features.map(feature => feature.geometry.coordinates[1]));
    const maxLat = Number.isFinite(Number(bounds.max_lat))
        ? Number(bounds.max_lat)
        : Math.max(...features.map(feature => feature.geometry.coordinates[1]));
    const span = Math.max(maxLon - minLon, maxLat - minLat);
    let zoom = 14;
    if (span > 10) zoom = 6;
    else if (span > 5) zoom = 7;
    else if (span > 2) zoom = 8;
    else if (span > 1) zoom = 9;
    else if (span > 0.5) zoom = 10;
    else if (span > 0.2) zoom = 11;
    else if (span > 0.1) zoom = 12;
    else if (span > 0.05) zoom = 13;

    return {
        type: 'concentration',
        title: mapData.title || `${pollutant} Concentration Distribution`,
        pollutant,
        center: [(minLat + maxLat) / 2, (minLon + maxLon) / 2],
        zoom,
        layers: [{
            id: 'concentration_points',
            type: 'circle',
            data: {
                type: 'FeatureCollection',
                features
            },
            style: {
                radius: 6,
                color_field: 'value',
                color_scale: 'YlOrRd',
                value_range: [Math.min(...values), Math.max(...values)],
                opacity: 0.85,
                legend_title: `${pollutant} Concentration`,
                legend_unit: mapData.summary?.unit || 'μg/m³'
            }
        }],
        summary: {
            receptor_count: mapData.summary?.receptor_count ?? receptors.length,
            mean_concentration: mapData.summary?.mean_concentration ?? (values.reduce((sum, value) => sum + value, 0) / values.length),
            max_concentration: mapData.summary?.max_concentration ?? Math.max(...values),
            unit: mapData.summary?.unit || 'μg/m³'
        }
    };
}

function renderConcentrationMap(mapData, msgContainer) {
    const normalizedMapData = normalizeConcentrationMapData(mapData);
    const layer = normalizedMapData?.layers?.[0];
    const features = layer?.data?.features || [];
    if (!normalizedMapData || features.length === 0) {
        console.warn('[Map] No valid concentration map data provided');
        return;
    }

    console.log(`[Map] renderConcentrationMap called with ${features.length} receptors`);

    const mapId = `concentration-map-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
    const style = layer.style || {};
    const valueRange = style.value_range || [0, 1];
    const minVal = Number(valueRange[0] || 0);
    const maxVal = Number(valueRange[1] || minVal);
    const unit = style.legend_unit || normalizedMapData.summary?.unit || 'μg/m³';
    const legendGradient = 'linear-gradient(to right, #ffffb2, #fecc5c, #fd8d3c, #f03b20, #bd0026)';
    const pollutant = normalizedMapData.pollutant || 'NOx';

    const mapHtml = `
        <div class="message-map-wrapper message-map-surface w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm p-6 mt-4" data-map-id="${mapId}">
            <div class="flex flex-wrap items-center justify-between gap-4 mb-4">
                <div>
                    <h3 class="text-slate-900 dark:text-white font-bold text-lg">${escapeHtml(normalizedMapData.title || `${pollutant} Concentration Distribution`)}</h3>
                    <p class="text-slate-500 text-sm">显示 ${features.length} 个受体点的 ${pollutant} 浓度分布</p>
                </div>
                <div class="text-sm text-slate-500 dark:text-slate-400 text-right">
                    <div>平均浓度 ${Number(normalizedMapData.summary?.mean_concentration || 0).toFixed(3)} ${unit}</div>
                    <div>最大浓度 ${Number(normalizedMapData.summary?.max_concentration || 0).toFixed(3)} ${unit}</div>
                </div>
            </div>
            <div id="${mapId}" style="height: 480px;" class="message-map-container rounded-lg overflow-hidden border border-slate-200 dark:border-slate-600"></div>
            <div class="mt-4 flex items-center gap-4 text-sm">
                <div class="flex items-center gap-3">
                    <span class="text-slate-600 dark:text-slate-400">低浓度</span>
                    <div class="w-40 h-3 rounded" style="background: ${legendGradient}"></div>
                    <span class="text-slate-600 dark:text-slate-400">高浓度</span>
                </div>
                <div class="ml-auto text-slate-500 dark:text-slate-400">
                    <span>${minVal.toFixed(3)} - ${maxVal.toFixed(3)} ${unit}</span>
                </div>
            </div>
        </div>
    `;

    const contentDiv = msgContainer.querySelector('.message-content');
    if (contentDiv) {
        contentDiv.insertAdjacentHTML('beforeend', mapHtml);
        scrollToBottom();

        setTimeout(() => {
            const mapContainer = document.getElementById(mapId);
            if (!mapContainer) {
                console.error(`[Map] Concentration map container ${mapId} not found in DOM`);
                return;
            }

            initConcentrationLeafletMap(normalizedMapData, mapId);
        }, 150);
    } else {
        console.error('[Map] Message content div not found for concentration map');
    }
}

function getConcentrationColor(value, minVal, maxVal) {
    const colors = ['#ffffb2', '#fecc5c', '#fd8d3c', '#f03b20', '#bd0026'];
    if (!Number.isFinite(value) || maxVal <= minVal) {
        return colors[0];
    }

    const ratio = Math.max(0, Math.min(1, (value - minVal) / (maxVal - minVal || 1)));
    const index = Math.min(Math.floor(ratio * colors.length), colors.length - 1);
    return colors[index];
}

function initConcentrationLeafletMap(mapData, mapId) {
    if (typeof L === 'undefined') {
        console.error('[Map] Leaflet not loaded');
        return;
    }

    const mapContainer = document.getElementById(mapId);
    if (!mapContainer) {
        console.error(`[Map] Map container not found: ${mapId}`);
        return;
    }

    const layer = mapData.layers?.[0];
    const features = layer?.data?.features || [];
    if (features.length === 0) {
        console.warn('[Map] No concentration features to render');
        return;
    }

    mapContainer.style.backgroundColor = '#ffffff';

    const map = L.map(mapId, {
        attributionControl: true,
        zoomControl: true,
        preferCanvas: true,
        renderer: L.canvas({ padding: 0.5 })
    });

    mapContainer._leaflet_map = map;

    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(map);

    const layerControl = L.control.layers(null, {}, {
        position: 'topright',
        collapsed: true
    }).addTo(map);

    const labelsLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        subdomains: 'abcd',
        pane: 'overlayPane'
    });
    layerControl.addOverlay(labelsLayer, '地名标注 / Labels');

    try {
        loadGISBasemap().then(basemapData => {
            if (basemapData && !basemapData.error) {
                const basemapLayer = L.geoJSON(basemapData, {
                    style: { color: '#94a3b8', weight: 1, fill: false, opacity: 0.5 }
                });
                layerControl.addOverlay(basemapLayer, '行政边界');
            }
        }).catch(() => {});

        loadGISRoadNetwork().then(roadData => {
            if (roadData && !roadData.error) {
                const roadLayer = L.geoJSON(roadData, {
                    style: { color: '#cbd5e1', weight: 0.5, opacity: 0.3 }
                });
                layerControl.addOverlay(roadLayer, '路网底图');
            }
        }).catch(() => {});
    } catch (e) {}

    map.attributionControl.setPrefix('© Emission Agent');

    const style = layer.style || {};
    const colorField = style.color_field || 'value';
    const valueRange = style.value_range || [0, 1];
    const minVal = Number(valueRange[0] || 0);
    const maxVal = Number(valueRange[1] || minVal);
    const unit = style.legend_unit || mapData.summary?.unit || 'μg/m³';
    const radius = Number(style.radius || 6);
    const opacity = Number(style.opacity || 0.85);

    const concentrationLayer = L.layerGroup();
    const bounds = [];

    features.forEach(feature => {
        const coordinates = feature.geometry?.coordinates || [];
        if (coordinates.length < 2) {
            return;
        }

        const lon = Number(coordinates[0]);
        const lat = Number(coordinates[1]);
        if (!Number.isFinite(lon) || !Number.isFinite(lat)) {
            return;
        }

        const props = feature.properties || {};
        const value = Number(props[colorField] || 0);
        const marker = L.circleMarker([lat, lon], {
            radius,
            fillColor: getConcentrationColor(value, minVal, maxVal),
            fillOpacity: opacity,
            stroke: true,
            weight: 1,
            color: '#334155',
            opacity: 0.6
        });

        marker.bindPopup(`
            <div style="min-width: 180px;">
                <h3 style="font-weight: bold; margin: 0 0 8px 0;">受体 ${escapeHtml(String(props.receptor_id ?? '-'))}</h3>
                <div style="font-size: 13px; line-height: 1.6;">
                    <div><strong>平均浓度:</strong> ${Number(props.mean_conc || 0).toFixed(3)} ${unit}</div>
                    <div><strong>最大浓度:</strong> ${Number(props.max_conc || 0).toFixed(3)} ${unit}</div>
                </div>
            </div>
        `);

        concentrationLayer.addLayer(marker);
        bounds.push([lat, lon]);
    });

    concentrationLayer.addTo(map);
    layerControl.addOverlay(concentrationLayer, '浓度受体 / Concentration');

    mapContainer._concentration_layer = concentrationLayer;
    mapContainer._map_data = mapData;

    if (bounds.length > 0) {
        map.fitBounds(L.latLngBounds(bounds), {
            padding: [10, 10],
            maxZoom: 16
        });
        setTimeout(() => {
            map.invalidateSize();
        }, 100);
    } else if (Array.isArray(mapData.center) && mapData.center.length === 2) {
        map.setView(mapData.center, mapData.zoom || 12);
    } else {
        map.setView([31.23, 121.47], 12);
    }
}

// ==================== GIS 底图加载 ====================

let GIS_BASEMAP_DATA = null;
let GIS_ROADNETWORK_DATA = null;

async function loadGISBasemap() {
    if (GIS_BASEMAP_DATA !== null) return GIS_BASEMAP_DATA;

    try {
        const response = await fetch(`${API_BASE}/gis/basemap`);
        if (response.ok) {
            GIS_BASEMAP_DATA = await response.json();
            return GIS_BASEMAP_DATA;
        }
    } catch (e) {
        console.warn('[GIS] Failed to load basemap:', e);
    }
    return null;
}

async function loadGISRoadNetwork() {
    if (GIS_ROADNETWORK_DATA !== null) return GIS_ROADNETWORK_DATA;

    try {
        const response = await fetch(`${API_BASE}/gis/roadnetwork`);
        if (response.ok) {
            GIS_ROADNETWORK_DATA = await response.json();
            return GIS_ROADNETWORK_DATA;
        }
    } catch (e) {
        console.warn('[GIS] Failed to load road network:', e);
    }
    return null;
}

// Helper function to update map polylines when switching pollutants (without recreating map)
function updateMapPollutant(map, emissionLayer, mapData, pollutant) {
    console.log(`[Map] Updating to pollutant: ${pollutant}`);

    // Get color scale
    const colorScale = mapData.color_scale || {};
    const minVal = colorScale.min || 0;
    const maxVal = colorScale.max || 100;

    // Update each polyline's color and popup
    emissionLayer.eachLayer(polyline => {
        const link = polyline._linkData;
        if (!link) return;

        // Get emission value for new pollutant
        const emission = link.emissions?.[pollutant] || 0;
        const color = getEmissionColor(emission, minVal, maxVal);

        // Update polyline color
        polyline.setStyle({ color: color });

        // Update popup content
        const popupContent = `
            <div style="min-width: 200px;">
                <h3 style="font-weight: bold; margin: 0 0 8px 0;">${escapeHtml(link.link_id)}</h3>
                <div style="font-size: 13px; line-height: 1.6;">
                    <div><strong>${pollutant}:</strong> ${emission.toFixed(2)} kg/(h·km)</div>
                    <div><strong>单位排放率:</strong> ${(link.emission_rate?.[pollutant] || 0).toFixed(2)} g/(veh·km)</div>
                    <div><strong>速度:</strong> ${link.avg_speed_kph || 0} km/h</div>
                    <div><strong>流量:</strong> ${link.traffic_flow_vph || 0} veh/h</div>
                    <div><strong>长度:</strong> ${link.link_length_km || 0} km</div>
                </div>
            </div>
        `;
        polyline.setPopupContent(popupContent);
    });

    console.log(`[Map] Updated ${emissionLayer.getLayers().length} polylines`);
}

function initLeafletMap(mapData, mapId, pollutant) {
    if (typeof L === 'undefined') {
        console.error('[Map] Leaflet not loaded');
        return;
    }

    const mapContainer = document.getElementById(mapId);
    if (!mapContainer) {
        console.error(`[Map] Map container not found: ${mapId}`);
        return;
    }

    // Check if map already exists - if so, just update polylines
    if (mapContainer._leaflet_map && mapContainer._emission_layer) {
        console.log('[Map] Updating existing map with new pollutant');
        updateMapPollutant(mapContainer._leaflet_map, mapContainer._emission_layer, mapData, pollutant);
        return;
    }

    // Set white background for clean academic style
    mapContainer.style.backgroundColor = '#ffffff';

    // Initialize map WITHOUT setting initial view
    // The view will be set later based on emission data bounds
    // Use Canvas renderer for better performance with many polylines
    const map = L.map(mapId, {
        attributionControl: true,
        zoomControl: true,
        preferCanvas: true,  // Use Canvas renderer for better performance
        renderer: L.canvas({ padding: 0.5 })
    });

    // Store map reference for cleanup
    mapContainer._leaflet_map = map;

    // PRIMARY: CartoDB Positron No Labels — clean base for emission overlays
    L.tileLayer('https://{s}.basemaps.cartocdn.com/light_nolabels/{z}/{x}/{y}{r}.png', {
        attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OSM</a> &copy; <a href="https://carto.com/">CARTO</a>',
        subdomains: 'abcd',
        maxZoom: 19
    }).addTo(map);

    // Layer control for optional overlays
    const layerControl = L.control.layers(null, {}, {
        position: 'topright',
        collapsed: true
    }).addTo(map);

    // OPTIONAL: Labels layer (toggle on/off)
    const labelsLayer = L.tileLayer('https://{s}.basemaps.cartocdn.com/light_only_labels/{z}/{x}/{y}{r}.png', {
        maxZoom: 19,
        subdomains: 'abcd',
        pane: 'overlayPane'
    });
    layerControl.addOverlay(labelsLayer, '地名标注 / Labels');

    // OPTIONAL: GIS basemap/roadnetwork as overlay layers (not shown by default)
    try {
        loadGISBasemap().then(basemapData => {
            if (basemapData && !basemapData.error) {
                const basemapLayer = L.geoJSON(basemapData, {
                    style: { color: '#94a3b8', weight: 1, fill: false, opacity: 0.5 }
                });
                layerControl.addOverlay(basemapLayer, '行政边界');
            }
        }).catch(() => {});

        loadGISRoadNetwork().then(roadData => {
            if (roadData && !roadData.error) {
                const roadLayer = L.geoJSON(roadData, {
                    style: { color: '#cbd5e1', weight: 0.5, opacity: 0.3 }
                });
                layerControl.addOverlay(roadLayer, '路网底图');
            }
        }).catch(() => {});
    } catch(e) {}

    // Custom attribution
    map.attributionControl.setPrefix('© Emission Agent');

    // Get color scale
    const colorScale = mapData.color_scale || {};
    const minVal = colorScale.min || 0;
    const maxVal = colorScale.max || 100;

    // Determine line weight based on number of links (adaptive scaling)
    const linkCount = mapData.links ? mapData.links.length : 0;
    let lineWeight;
    if (linkCount > 10000) {
        lineWeight = 2;      // Very large scale
    } else if (linkCount > 5000) {
        lineWeight = 2.5;    // Large scale
    } else if (linkCount > 1000) {
        lineWeight = 3;      // Medium-large scale
    } else if (linkCount > 100) {
        lineWeight = 3.5;    // Medium scale
    } else {
        lineWeight = 4;      // Small scale: thick lines
    }
    const baseOpacity = linkCount > 5000 ? 0.6 : linkCount > 1000 ? 0.7 : 0.85;
    console.log(`[Map] Adaptive line weight: ${lineWeight}, opacity: ${baseOpacity} for ${linkCount} links`);

    // Draw links
    const bounds = [];
    const emissionLayer = L.layerGroup();  // Create layer group for emission polylines

    mapData.links.forEach(link => {
        const coords = link.geometry || link.coordinates || [];
        if (!coords || coords.length < 2) return;

        // Get emission value for current pollutant
        const emission = link.emissions?.[pollutant] || 0;
        const color = getEmissionColor(emission, minVal, maxVal);

        // Convert [lon, lat] to [lat, lon] for Leaflet
        const latLngs = coords.map(c => [c[1], c[0]]);

        // Create polyline with adaptive weight and opacity
        const polyline = L.polyline(latLngs, {
            color: color,
            weight: lineWeight,
            opacity: baseOpacity,
            smoothFactor: 1.0
        });

        // Store link data for later updates
        polyline._linkData = link;

        // Build popup content
        const popupContent = `
            <div style="min-width: 200px;">
                <h3 style="font-weight: bold; margin: 0 0 8px 0;">${escapeHtml(link.link_id)}</h3>
                <div style="font-size: 13px; line-height: 1.6;">
                    <div><strong>${pollutant}:</strong> ${emission.toFixed(2)} kg/(h·km)</div>
                    <div><strong>单位排放率:</strong> ${(link.emission_rate?.[pollutant] || 0).toFixed(2)} g/(veh·km)</div>
                    <div><strong>速度:</strong> ${link.avg_speed_kph || 0} km/h</div>
                    <div><strong>流量:</strong> ${link.traffic_flow_vph || 0} veh/h</div>
                    <div><strong>长度:</strong> ${link.link_length_km || 0} km</div>
                </div>
            </div>
        `;

        // Add popup to polyline
        polyline.bindPopup(popupContent);
        emissionLayer.addLayer(polyline);

        // Extend bounds with converted coordinates
        latLngs.forEach(latlng => bounds.push(latlng));
    });

    // Add emission layer to map
    emissionLayer.addTo(map);

    // Store emission layer and map data for later updates
    mapContainer._emission_layer = emissionLayer;
    mapContainer._map_data = mapData;
    mapContainer._line_weight = lineWeight;

    // Fit map to show all emission links (ONLY based on emission data, not GIS basemap)
    if (bounds.length > 0) {
        // Use fitBounds immediately to set the initial view based on emission data
        // This ensures the map focuses on the emission data area, not the entire city
        const boundsObj = L.latLngBounds(bounds);
        map.fitBounds(boundsObj, {
            padding: [5, 5],
            maxZoom: 16  // Allow closer zoom for better detail
        });

        // Invalidate size after a short delay to ensure proper rendering
        setTimeout(() => {
            map.invalidateSize();
        }, 100);
    } else {
        // Fallback: if no emission data, use generic China center (overridden by fitBounds)
        map.setView([35.0, 105.0], 4);
    }

    console.log(`[Map] Initialized with ${emissionLayer.getLayers().length} links`);
}

function getEmissionColor(value, minVal, maxVal) {
    // Handle edge cases
    if (value <= 0 || maxVal <= minVal) return '#3B82F6';

    // Logarithmic normalization for wide value ranges (e.g. NOx 0.001-0.04)
    const safeMin = Math.max(minVal, 0.001);
    const safeVal = Math.max(value, 0.001);
    const safeMax = Math.max(maxVal, safeMin * 1.001);
    const logMin = Math.log(safeMin);
    const logMax = Math.log(safeMax);
    const logVal = Math.log(safeVal);
    const ratio = Math.max(0, Math.min(1, (logVal - logMin) / (logMax - logMin)));

    // 5-stop saturated color ramp: blue → emerald → yellow → orange → red
    const stops = [
        [0.0,  [59, 130, 246]],   // #3B82F6 blue (low)
        [0.25, [16, 185, 129]],   // #10B981 emerald
        [0.5,  [245, 208, 70]],   // #F5D046 yellow
        [0.75, [249, 115, 22]],   // #F97316 orange
        [1.0,  [220, 38, 38]],    // #DC2626 red (high)
    ];

    let lower = stops[0], upper = stops[stops.length - 1];
    for (let i = 0; i < stops.length - 1; i++) {
        if (ratio >= stops[i][0] && ratio <= stops[i + 1][0]) {
            lower = stops[i];
            upper = stops[i + 1];
            break;
        }
    }

    const t = (ratio - lower[0]) / (upper[0] - lower[0] || 1);
    const r = Math.round(lower[1][0] + t * (upper[1][0] - lower[1][0]));
    const g = Math.round(lower[1][1] + t * (upper[1][1] - lower[1][1]));
    const b = Math.round(lower[1][2] + t * (upper[1][2] - lower[1][2]));

    return `rgb(${r},${g},${b})`;
}

// ==================== 工具函数 ====================

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function formatMarkdown(text) {
    if (!text) return '';

    // Use marked.js for Markdown rendering
    if (typeof marked !== 'undefined') {
        // Configure marked
        marked.setOptions({
            breaks: true,      // Support line breaks
            gfm: true,         // GitHub Flavored Markdown
            headerIds: false,  // Don't add IDs to headers
            mangle: false      // Don't escape email addresses
        });

        return marked.parse(text);
    }

    // Fallback: simple Markdown processing
    return text
        // Headers
        .replace(/^### (.*$)/gm, '<h3 class="text-lg font-semibold text-slate-800 dark:text-slate-200 mt-4 mb-2">$1</h3>')
        .replace(/^## (.*$)/gm, '<h2 class="text-xl font-semibold text-slate-800 dark:text-slate-200 mt-4 mb-2">$1</h2>')
        .replace(/^# (.*$)/gm, '<h1 class="text-2xl font-bold text-slate-800 dark:text-slate-200 mt-4 mb-2">$1</h1>')
        // Bold
        .replace(/\*\*(.*?)\*\*/g, '<strong class="font-semibold text-slate-800 dark:text-slate-200">$1</strong>')
        // Italic
        .replace(/\*(.*?)\*/g, '<em>$1</em>')
        // Code
        .replace(/`(.*?)`/g, '<code class="px-1.5 py-0.5 bg-slate-100 dark:bg-slate-700 rounded text-sm font-mono text-slate-700 dark:text-slate-300">$1</code>')
        // Lists
        .replace(/^- (.*$)/gm, '<li class="ml-4">$1</li>')
        // Line breaks
        .replace(/\n/g, '<br>');
}

function formatReplyText(reply) {
    if (!reply) return '';

    // Remove JSON code blocks
    let text = reply
        .replace(/```json[\s\S]*?```/g, '')  // Remove ```json ... ```
        .replace(/```[\s\S]*?```/g, '')      // Remove other code blocks
        .replace(/\{[\s\S]*?"curve"[\s\S]*?\}/g, '')  // Remove inline JSON with curve data
        .replace(/\{[\s\S]*?"pollutants"[\s\S]*?\}/g, '')  // Remove inline JSON with pollutants
        .trim();

    // If the entire content looks like JSON, try to parse and hide it
    if (text.startsWith('{') || text.startsWith('[')) {
        try {
            JSON.parse(text);
            // If it's valid JSON, don't display it (frontend will handle data separately)
            return '';
        } catch (e) {
            // Not valid JSON, continue processing
        }
    }

    return text;
}

function scrollToBottom() {
    if (messagesContainer) {
        // Use setTimeout to ensure DOM is updated before scrolling
        setTimeout(() => {
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }, 100);
    }
}

function downloadFile(fileId) {
    fetchWithUser(`${API_BASE}/file/download/${fileId}`)
        .then(res => {
            if (!res.ok) throw new Error(`HTTP ${res.status}`);
            const disposition = res.headers.get('Content-Disposition') || '';
            const match = disposition.match(/filename="?([^"]+)"?/);
            const filename = match ? match[1] : `emission_result_${fileId}.xlsx`;
            return res.blob().then(blob => ({ blob, filename }));
        })
        .then(({ blob, filename }) => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = filename;
            document.body.appendChild(a);
            a.click();
            a.remove();
            URL.revokeObjectURL(url);
        })
        .catch(err => {
            console.error('下载失败:', err);
            alert('下载失败: ' + err.message);
        });
}

// ==================== 页面加载完成 ====================
document.addEventListener('DOMContentLoaded', () => {
    console.log('Emission Agent 前端已加载');
    console.log('ECharts 状态:', typeof echarts !== 'undefined' ? '已加载' : '未加载');

    // Ensure ECharts is available
    ensureEchartsLoaded().catch(() => console.error('ECharts load failed'));

    // 加载会话列表
    loadSessionList();
});
