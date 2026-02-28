// ==================== API配置 ====================
const API_BASE = 'http://localhost:8000/api';
let currentSessionId = null;
let currentFile = null;
const USE_STREAMING = true;  // 是否使用流式输出

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
        const response = await fetch(`${API_BASE}/chat`, {
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
        const response = await fetch(`${API_BASE}/chat/stream`, {
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
                            renderTable(data.content, assistantMsgId);
                            break;

                        case 'done':
                            // 完成，更新session_id
                            hideTypingIndicator();
                            if (data.session_id) {
                                currentSessionId = data.session_id;
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
    const container = document.createElement('div');
    container.id = msgId;
    container.className = 'message assistant';
    container.innerHTML = '<div class="message-content"></div>';
    messagesContainer.appendChild(container);
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
    return container;
}

function updateMessageContent(msgId, content) {
    const container = document.getElementById(msgId);
    if (container) {
        const contentDiv = container.querySelector('.message-content');
        if (contentDiv) {
            contentDiv.innerHTML = marked.parse(content);
            messagesContainer.scrollTop = messagesContainer.scrollHeight;
        }
    }
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
    const chartHtml = renderEmissionChart(chartData, chartId);
    container.querySelector('.message-content').insertAdjacentHTML('beforeend', chartHtml);

    // 初始化图表
    setTimeout(() => {
        initEmissionChart(chartData, chartId);
    }, 100);
}

function renderTable(tableData, msgId) {
    const container = document.getElementById(msgId);
    if (!container) return;

    const tableHtml = renderResultTable(tableData, tableData.file_id);
    container.querySelector('.message-content').insertAdjacentHTML('beforeend', tableHtml);
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

async function startNewChat() {
    try {
        const response = await fetch(`${API_BASE}/sessions/new`, { method: 'POST' });
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
    console.log('🌐 API_BASE:', API_BASE);
    try {
        console.log('⏳ 开始获取会话列表...');
        const response = await fetch(`${API_BASE}/sessions`);
        console.log('✅ 会话列表请求完成，状态码:', response.status);
        const data = await response.json();
        console.log('📥 会话列表数据:', data);

        if (data.sessions && data.sessions.length > 0) {
            renderSessionList(data.sessions);
        }
    } catch (error) {
        console.error('❌ 加载会话列表失败:', error);
    }
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
        sessionEl.className = isCurrent
            ? 'group flex items-center justify-between px-3 py-2 rounded-lg bg-white dark:bg-slate-800 shadow-sm border border-slate-100 dark:border-slate-700 cursor-pointer'
            : 'group flex items-center justify-between px-3 py-2 rounded-lg hover:bg-slate-100 dark:hover:bg-slate-800 text-slate-600 dark:text-slate-400 transition-colors cursor-pointer';

        sessionEl.innerHTML = `
            <div class="flex items-center gap-3 overflow-hidden">
                <span class="material-symbols-outlined ${isCurrent ? 'text-primary' : ''} shrink-0" style="font-size: 20px;">${isCurrent ? 'chat_bubble' : 'history'}</span>
                <p class="text-sm font-medium truncate">${escapeHtml(session.title)}</p>
            </div>
            <button class="delete-btn opacity-0 group-hover:opacity-100 p-1 text-slate-400 hover:text-red-500 hover:bg-red-50 dark:hover:bg-red-900/20 rounded transition-all" title="删除会话">
                <span class="material-symbols-outlined" style="font-size: 18px;">delete</span>
            </button>
        `;

        // 点击切换会话
        sessionEl.addEventListener('click', (e) => {
            // 如果点击的是删除按钮，不切换
            if (e.target.closest('.delete-btn')) return;
            e.preventDefault();
            loadSession(session.session_id);
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
        const response = await fetch(`${API_BASE}/sessions/${sessionId}`, { method: 'DELETE' });
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

async function loadSession(sessionId) {
    console.log('加载会话:', sessionId);
    currentSessionId = sessionId;

    try {
        const response = await fetch(`${API_BASE}/sessions/${sessionId}/history`);
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

function renderHistory(messages) {
    if (!messagesContainer) return;

    // 清空并添加日期标签
    messagesContainer.innerHTML = '<div class="flex justify-center pb-4"><span class="px-3 py-1 bg-slate-100 dark:bg-slate-800 text-slate-500 text-xs rounded-full font-medium">Today</span></div>';

    messages.forEach(msg => {
        if (msg.role === 'user') {
            addUserMessage(msg.content);
        } else {
            // 传递完整的图表数据
            console.log('[DEBUG] 渲染历史消息:', {
                has_chart_data: !!msg.chart_data,
                has_table_data: !!msg.table_data,
                data_type: msg.data_type
            });
            addAssistantMessage({
                reply: msg.content,
                success: true,
                data_type: msg.data_type,      // 新增
                chart_data: msg.chart_data,    // 新增
                table_data: msg.table_data,    // 新增
                has_data: msg.has_data
            });
        }
    });

    scrollToBottom();
}

// ==================== UI渲染函数 ====================

function addUserMessage(text, filename = null) {
    if (!messagesContainer) return;

    const html = `
        <div class="flex justify-end gap-4 max-w-4xl ml-auto">
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

    // Clean and format the reply text
    const cleanedReply = formatReplyText(data.reply);
    let contentHtml = cleanedReply ? `<div class="prose prose-slate dark:prose-invert max-w-none text-base text-slate-800 dark:text-slate-200 leading-relaxed">${formatMarkdown(cleanedReply)}</div>` : '';

    // ✅ 增强验证：只有在明确有图表数据且data_type正确时才显示
    const hasValidChartData = data.data_type === 'chart' &&
                               data.chart_data &&
                               typeof data.chart_data === 'object' &&
                               Object.keys(data.chart_data).length > 0;

    const hasValidTableData = data.data_type === 'table' &&
                               data.table_data &&
                               typeof data.table_data === 'object' &&
                               Object.keys(data.table_data).length > 0;

    // 调试日志
    console.log('[DEBUG] addAssistantMessage:', {
        data_type: data.data_type,
        hasValidChartData,
        hasValidTableData,
        chart_data_keys: data.chart_data ? Object.keys(data.chart_data) : null,
        table_data_keys: data.table_data ? Object.keys(data.table_data) : null
    });

    // 添加图表（排放因子曲线）
    // Key points table (if available)
    if (hasValidChartData && data.chart_data.key_points?.length) {
        console.log('[DEBUG] 显示Key Points表格');
        contentHtml += renderKeyPointsTable(data.chart_data.key_points);
    }

    let chartId = null;
    if (hasValidChartData) {
        console.log('[DEBUG] 显示排放因子曲线图');
        chartId = `emission-chart-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`;
        contentHtml += renderEmissionChart(data.chart_data, chartId);
    }

    // 添加表格（计算结果）
    if (hasValidTableData) {
        console.log('[DEBUG] 显示计算结果表格');
        contentHtml += renderResultTable(data.table_data, data.file_id);
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
        <div class="flex justify-start gap-4 max-w-4xl">
            <div class="size-10 rounded-full bg-surface border border-slate-100 shadow-sm flex items-center justify-center shrink-0">
                <span class="text-xl">🌿</span>
            </div>
            <div class="flex flex-col gap-4 flex-1 min-w-0">
                <div class="bg-white dark:bg-slate-800 p-4 rounded-xl shadow-sm border border-slate-100 dark:border-slate-700">
                    ${contentHtml}
                </div>
            </div>
        </div>
    `;
    messagesContainer.insertAdjacentHTML('beforeend', html);
    scrollToBottom();

    // 初始化图表（如果有）
    if (data.data_type === 'chart' && data.chart_data && chartId) {
        initEmissionChart(data.chart_data, chartId);
    }
}

function addLoadingMessage() {
    if (!messagesContainer) return null;

    const html = `
        <div class="flex justify-start gap-4 max-w-4xl loading-message">
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

function renderResultTable(tableData, fileId) {
    if (!tableData) return '';

    const columns = tableData.columns || [];
    const rows = tableData.preview_rows || tableData.rows || [];
    const totalRows = tableData.total_rows || rows.length;

    if (!rows || rows.length === 0) {
        return '<div class="text-slate-500 text-sm mt-4">暂无数据</div>';
    }

    const headerHtml = columns.map(c => `<th class="px-4 py-3 font-medium text-left">${c}</th>`).join('');
    const rowsHtml = rows.map(row =>
        `<tr class="hover:bg-slate-50 dark:hover:bg-slate-700/50">
            ${columns.map(c => `<td class="px-4 py-3 text-slate-600 dark:text-slate-400">${formatCellValue(row[c])}</td>`).join('')}
        </tr>`
    ).join('');

    const downloadBtn = fileId ?
        `<button onclick="downloadFile('${fileId}')" class="text-primary hover:text-primary-dark text-xs font-bold flex items-center gap-1">
            <span class="material-symbols-outlined" style="font-size: 16px;">download</span>
            下载Excel
        </button>` : '';

    // Summary information
    let summaryHtml = '';
    const summary = tableData.summary || tableData.total_emissions;
    if (summary && Object.keys(summary).length > 0) {
        const items = Object.entries(summary)
            .map(([k, v]) => `
                <div>
                    <p class="text-xs text-emerald-600 dark:text-emerald-400">${k}</p>
                    <p class="text-sm font-semibold text-emerald-800 dark:text-emerald-300">${formatCellValue(v)}</p>
                </div>
            `)
            .join('');
        summaryHtml = `
            <div class="px-4 py-3 bg-emerald-50 dark:bg-emerald-900/20 border-t border-slate-200 dark:border-slate-700">
                <h5 class="font-medium text-emerald-800 dark:text-emerald-300 mb-2">汇总</h5>
                <div class="grid grid-cols-2 md:grid-cols-4 gap-4">
                    ${items}
                </div>
            </div>
        `;
    }

    return `
        <div class="w-full bg-white dark:bg-slate-800 rounded-2xl border border-slate-100 dark:border-slate-700 shadow-sm overflow-hidden mt-4">
            <div class="px-4 py-3 border-b border-slate-100 dark:border-slate-700 flex justify-between items-center bg-slate-50/50 dark:bg-slate-700/30">
                <div>
                    <h3 class="font-bold text-slate-800 dark:text-white text-sm">计算结果</h3>
                    <p class="text-xs text-slate-500 dark:text-slate-400">显示前${rows.length}行，共${totalRows}行</p>
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
            ${summaryHtml}
        </div>
    `;
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
        previewEl.className = 'mb-3';
        inputArea?.insertBefore(previewEl, inputArea.firstChild);
    }

    // Simplified file preview (ChatGPT style)
    previewEl.innerHTML = `
        <div class="flex items-center gap-3 px-4 py-3 bg-slate-50 dark:bg-slate-800 rounded-xl border border-slate-200 dark:border-slate-700">
            <div class="w-10 h-10 bg-emerald-100 dark:bg-emerald-900/30 rounded-lg flex items-center justify-center shrink-0">
                <svg class="w-5 h-5 text-emerald-600 dark:text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                          d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"/>
                </svg>
            </div>
            <div class="flex-1 min-w-0">
                <p class="text-sm font-medium text-slate-700 dark:text-slate-200 truncate">${preview.filename}</p>
                <p class="text-xs text-slate-500 dark:text-slate-400">${formatFileSize(preview.size_kb * 1024)}</p>
            </div>
            <button onclick="removeFile()" class="p-1.5 hover:bg-slate-200 dark:hover:bg-slate-700 rounded-full transition-colors shrink-0">
                <svg class="w-4 h-4 text-slate-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M6 18L18 6M6 6l12 12"/>
                </svg>
            </button>
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
    window.open(`${API_BASE}/file/download/${fileId}`, '_blank');
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
