# RAG系统配置指南

## 概述

RAG系统现已支持灵活的embedding和rerank配置，可以在本地模型和在线API之间自由切换。

## 配置项

在 `.env` 文件中配置以下参数：

### Embedding配置

```bash
# Embedding模式: api（在线API）或 local（本地BGE-M3）
EMBEDDING_MODE=api

# API模式下的模型配置
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_DIMENSION=1024
```

**模式说明**：

- `api`: 使用DashScope在线embedding API
  - 优势：无需本地模型，启动快，维护简单
  - 成本：按调用次数计费（约¥0.0007/千tokens）
  - 模型：text-embedding-v3（推荐）或 text-embedding-v2

- `local`: 使用本地BGE-M3模型
  - 优势：无API调用成本，数据不出本地
  - 劣势：需要下载模型（约2GB），首次加载较慢
  - 需要安装：`pip install FlagEmbedding`

### Rerank配置

```bash
# Rerank模式: api（在线API）, local（简单关键词匹配）或 none（不使用rerank）
RERANK_MODE=api

# API模式下的模型配置
RERANK_MODEL=gte-rerank
RERANK_TOP_N=5
```

**模式说明**：

- `api`: 使用DashScope在线rerank API
  - 优势：效果最好，专业的重排序模型
  - 成本：按调用次数计费
  - 模型：gte-rerank（推荐）

- `local`: 使用本地简单算法
  - 基于关键词匹配的简单重排序
  - 无额外成本，但效果一般
  - 适合测试或预算有限场景

- `none`: 不使用rerank
  - 直接使用FAISS检索结果
  - 最快，但可能不够精准

## 推荐配置

### 生产环境（推荐）

```bash
EMBEDDING_MODE=api
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_DIMENSION=1024

RERANK_MODE=api
RERANK_MODEL=gte-rerank
RERANK_TOP_N=5
```

**理由**：
- 维度1024与现有索引兼容，无需重建
- 在线API稳定可靠，成本可控
- Rerank显著提升检索精度

**成本估算**（每月）：
- 假设每天100次查询
- Embedding: 100 × 50 tokens × 30 天 × ¥0.0007/千 ≈ ¥0.1
- Rerank: 100 × 30 天 × ¥0.01/次 ≈ ¥30
- 总计：约¥30/月

### 开发/测试环境

```bash
EMBEDDING_MODE=api
EMBEDDING_MODEL=text-embedding-v3
EMBEDDING_DIMENSION=1024

RERANK_MODE=local  # 或 none
```

**理由**：
- Embedding用API保证效果
- Rerank用本地算法节省成本

### 离线/隐私敏感环境

```bash
EMBEDDING_MODE=local

RERANK_MODE=local  # 或 none
```

**理由**：
- 数据不出本地
- 需要安装FlagEmbedding库

## 依赖安装

### API模式（推荐）

```bash
pip install dashscope>=1.14.0
```

### 本地模式

```bash
pip install FlagEmbedding>=1.2.0
```

### 完整安装

```bash
pip install -r requirements.txt
```

## 切换步骤

### 从本地切换到API

1. 修改 `.env`：
   ```bash
   EMBEDDING_MODE=api
   RERANK_MODE=api
   ```

2. 安装依赖：
   ```bash
   pip install dashscope
   ```

3. 重启服务：
   ```bash
   python main.py
   ```

4. 验证日志：
   ```
   知识检索器初始化 - Embedding模式: api
   知识重排序器初始化 - Rerank模式: api
   ```

### 从API切换到本地

1. 安装本地模型：
   ```bash
   pip install FlagEmbedding
   ```

2. 修改 `.env`：
   ```bash
   EMBEDDING_MODE=local
   RERANK_MODE=local
   ```

3. 重启服务（首次会下载BGE-M3模型，约2GB）

## 注意事项

### 向量维度

- 当前FAISS索引是1024维
- 使用API模式时，必须设置 `EMBEDDING_DIMENSION=1024`
- 如果要使用其他维度，需要重建索引

### API Key

- Embedding和Rerank使用同一个DashScope API key
- 已在 `.env` 中配置：`QWEN_API_KEY`
- 无需额外申请

### 代理设置

- 如果需要代理访问API，已配置：
  ```bash
  HTTP_PROXY=http://127.0.0.1:7890
  HTTPS_PROXY=http://127.0.0.1:7890
  ```

### 降级策略

- API调用失败时，rerank会自动降级到本地算法
- 保证服务可用性

## 性能对比

| 模式 | 启动速度 | 查询速度 | 效果 | 成本 |
|------|---------|---------|------|------|
| API Embedding + API Rerank | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | 低 |
| API Embedding + Local Rerank | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 极低 |
| Local Embedding + Local Rerank | ⭐⭐ | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 无 |

## 故障排查

### 问题1：API调用失败

**症状**：日志显示 "API embedding调用失败"

**解决**：
1. 检查API key是否正确
2. 检查网络连接和代理设置
3. 查看DashScope控制台是否有余额

### 问题2：本地模型加载失败

**症状**：日志显示 "FlagEmbedding 未安装"

**解决**：
```bash
pip install FlagEmbedding
```

### 问题3：维度不匹配

**症状**：FAISS检索报错

**解决**：
- 确保 `EMBEDDING_DIMENSION=1024`
- 如果修改了维度，需要重建索引

## 更多信息

- DashScope文档：https://help.aliyun.com/zh/dashscope/
- BGE-M3模型：https://huggingface.co/BAAI/bge-m3
