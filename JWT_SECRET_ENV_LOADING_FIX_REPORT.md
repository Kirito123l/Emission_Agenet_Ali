# JWT Secret Env Loading Fix Report

## Root Cause

- `api/auth.py` 在模块导入时立即执行：
  - `SECRET_KEY = os.getenv("JWT_SECRET_KEY", _DEFAULT_SECRET)`
- 但它自己没有加载 `.env`。
- `config.py` 虽然调用了 `load_dotenv()`，但只有在某些导入路径里才会先被导入。
- 如果运行时导入顺序是先进入 `api/auth.py`、后进入 `config.py`，那么：
  - `JWT_SECRET_KEY` 还没有从项目根目录 `.env` 注入到进程环境
  - `api/auth.py` 就会提前拿到 `_DEFAULT_SECRET`
  - 并打印：
    - `JWT_SECRET_KEY is not set -- using insecure default`

本质上，这是一个 `.env` 加载时机依赖导入顺序的问题。

## Files Changed

- `api/auth.py`
- `tests/test_config.py`

## Exact Fix

### `api/auth.py`

- 在读取 `JWT_SECRET_KEY` 之前，显式加载项目根目录 `.env`：
  - `load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)`
- 这样 `api/auth.py` 不再依赖 `config.py` 是否已先被导入。
- `override=False` 保持现有优先级不变：
  - 显式环境变量仍然优先于 `.env`
  - 只是在环境尚未注入时，确保 `.env` 能被读到

### `tests/test_config.py`

- 新增一个小测试，验证：
  - 即使没有先导入 `config.py`
  - `api.auth` 也会在读取 secret 前调用 `.env` 加载逻辑

## How To Verify On The Server After Deploy

在服务器上执行：

```bash
ssh root@139.196.235.238
cd /opt/emission_agent
git log -1 --oneline
source venv/bin/activate
sudo systemctl restart emission-agent
sudo journalctl -u emission-agent -n 50 --no-pager
```

你要重点看：

- 重启后的日志里**不应再出现**：
  - `JWT_SECRET_KEY is not set -- using insecure default`

如果你还想直接验证服务进程确实能读到当前 `.env` 里的 key，可以在服务器上执行：

```bash
cd /opt/emission_agent
source venv/bin/activate
python - <<'PY'
import api.auth as auth_mod
print("using_default", auth_mod.SECRET_KEY == auth_mod._DEFAULT_SECRET)
print("secret_length", len(auth_mod.SECRET_KEY))
PY
```

预期：

- `using_default` 应为 `False`
- `secret_length` 应反映你服务器 `.env` 中真实 JWT secret 的长度

## What Was Intentionally Not Changed

- 没有重构整个配置系统
- 没有改动 `config.py` 的整体行为
- 没有改 JWT token 的编码/解码语义
- 没有改认证接口或会话逻辑
- 没有引入新的配置抽象层

这轮修复只解决一个确定的生产配置问题：
让 `api/auth.py` 在任何导入顺序下都能稳定读取项目根目录 `.env` 中的 `JWT_SECRET_KEY`
