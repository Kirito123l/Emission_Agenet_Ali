# 问题排查指南

## 问题1：UI样式不一致（已修复）

### 症状
- 历史记录显示正常（深色背景、浅色文字）
- 实时对话显示异常（浅色背景、深色文字）
- 切换对话后再回来就正常了

### 根本原因
流式消息和历史消息使用了不同的HTML创建方式：
- 流式消息：只有简单的CSS类名 `class="message assistant"`
- 历史消息：完整的Tailwind CSS类名

### 解决方案
已修改 `web/app.js` 中的以下函数：
1. `createAssistantMessageContainer()` - 使用完整的HTML结构
2. `updateMessageContent()` - 添加样式包装

### 验证
重启服务器后，实时对话的样式应该与历史记录一致。

---

## 问题2：Agent回复质量差

### 症状
- 成功率低（0%）
- 延迟高（9-15秒）
- Planning通过但执行失败

### 可能原因

#### 1. 代理配置问题 ⭐ 最可能

**检查方法：**
```bash
python diagnose_agent.py
```

**常见问题：**
- 代理服务未运行（Clash、V2Ray等）
- 代理端口错误（默认7890）
- 代理不稳定导致超时

**解决方案：**

**方案A：修复代理**
1. 确保代理服务正在运行
2. 测试代理连接：
   ```bash
   curl -x http://127.0.0.1:7890 https://www.baidu.com
   ```

**方案B：禁用代理（推荐）**

如果你的网络可以直接访问阿里云API，建议禁用代理：

编辑 `.env` 文件：
```bash
# ============ 代理设置 ============
# HTTP/HTTPS 代理（用于访问 LLM API）
# HTTP_PROXY=http://127.0.0.1:7890
# HTTPS_PROXY=http://127.0.0.1:7890
```

注释掉这两行后重启服务器。

#### 2. 模型配置问题

**当前配置：**
```
AGENT_LLM_MODEL=qwen3-max
SYNTHESIS_LLM_MODEL=qwen3-max
```

**如果原来的电脑使用不同模型：**

可以尝试切换到其他模型：
```bash
# 更快但能力稍弱
AGENT_LLM_MODEL=qwen-plus
SYNTHESIS_LLM_MODEL=qwen-plus

# 或者使用turbo（最快）
AGENT_LLM_MODEL=qwen-turbo-latest
SYNTHESIS_LLM_MODEL=qwen-turbo-latest
```

#### 3. 超时配置

**当前超时：60秒**

如果网络不稳定，可以增加超时时间：

编辑 `llm/client.py` 第23行：
```python
http_client = httpx.Client(
    proxy=proxy,
    timeout=120.0  # 增加到120秒
)
```

#### 4. 知识库加载问题

**检查知识库：**
```bash
python diagnose_agent.py
```

如果知识库文件缺失或损坏，会导致RAG检索失败。

---

## 诊断步骤

### 1. 运行诊断脚本
```bash
python diagnose_agent.py
```

这会检查：
- ✅ 代理连接
- ✅ LLM API连接
- ✅ 知识库
- ✅ 技能注册
- ✅ 数据文件

### 2. 查看日志

**API调用日志：**
```bash
tail -f logs/requests.log
```

**关键指标：**
- HTTP状态码（应该是200）
- 响应时间（应该<3秒）
- 错误信息

### 3. 测试简单查询

启动服务器后，测试一个简单的查询：
```
"小汽车在60km/h的CO2排放因子是多少？"
```

**预期结果：**
- Planning验证通过
- 成功调用knowledge_retrieval技能
- 返回排放因子数据
- 总延迟<5秒

### 4. 对比配置

**检查原来电脑的配置：**
1. `.env` 文件中的模型配置
2. 是否使用代理
3. Python版本和依赖版本

---

## 快速修复建议

### 优先级1：禁用代理（如果不需要）

编辑 `.env`：
```bash
# HTTP_PROXY=http://127.0.0.1:7890
# HTTPS_PROXY=http://127.0.0.1:7890
```

重启服务器：
```bash
.\scripts\restart_server.ps1
```

### 优先级2：切换到更快的模型

编辑 `.env`：
```bash
AGENT_LLM_MODEL=qwen-plus
SYNTHESIS_LLM_MODEL=qwen-plus
```

### 优先级3：增加超时时间

编辑 `llm/client.py`：
```python
timeout=120.0  # 从60秒增加到120秒
```

---

## 性能优化建议

### 1. 缓存优化

确保缓存已启用（`.env`）：
```bash
ENABLE_STANDARDIZATION_CACHE=true
```

### 2. 模型选择

根据需求选择合适的模型：

| 模型 | 速度 | 能力 | 适用场景 |
|------|------|------|----------|
| qwen-turbo-latest | ⚡⚡⚡ | ⭐⭐ | 简单查询、标准化 |
| qwen-plus | ⚡⚡ | ⭐⭐⭐ | 平衡性能和能力 |
| qwen3-max | ⚡ | ⭐⭐⭐⭐ | 复杂推理 |

### 3. 网络优化

- 使用稳定的网络连接
- 如果在国内，直连阿里云API（无需代理）
- 避免使用不稳定的代理

---

## 常见错误及解决方案

### 错误1：`记录学习案例: xxx, success=False`

**原因：** Skill执行失败

**检查：**
1. 查看具体的错误日志
2. 检查数据文件是否完整
3. 检查知识库是否正常加载

### 错误2：`性能异常: ['平均延迟过高: 9925ms']`

**原因：** API调用延迟高

**解决：**
1. 检查代理配置
2. 测试网络连接
3. 切换到更快的模型

### 错误3：`Planning验证失败`

**原因：** LLM返回的计划格式不正确

**解决：**
1. 检查模型配置
2. 查看具体的验证错误
3. 可能需要调整prompt

---

## 联系支持

如果以上方法都无法解决问题，请提供以下信息：

1. 诊断脚本输出：`python diagnose_agent.py > diagnosis.txt`
2. 错误日志：`logs/requests.log` 的最后100行
3. 环境信息：
   - Python版本
   - 操作系统
   - 网络环境（是否使用代理）
4. 具体的错误消息和复现步骤
