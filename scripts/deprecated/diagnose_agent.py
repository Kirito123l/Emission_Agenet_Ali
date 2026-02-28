"""
Agent诊断脚本 - 检查环境配置和连接问题
"""
import os
import sys
import time
import httpx
from pathlib import Path
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

def check_proxy():
    """检查代理连接"""
    print("\n" + "="*60)
    print("1. 检查代理配置")
    print("="*60)

    http_proxy = os.getenv("HTTP_PROXY", "")
    https_proxy = os.getenv("HTTPS_PROXY", "")

    print(f"HTTP_PROXY: {http_proxy}")
    print(f"HTTPS_PROXY: {https_proxy}")

    if not http_proxy and not https_proxy:
        print("✅ 未配置代理")
        return True

    # 测试代理连接
    proxy = https_proxy or http_proxy
    print(f"\n测试代理连接: {proxy}")

    try:
        client = httpx.Client(proxy=proxy, timeout=5.0)
        response = client.get("https://www.baidu.com")
        if response.status_code == 200:
            print(f"✅ 代理连接正常 (状态码: {response.status_code})")
            return True
        else:
            print(f"⚠️ 代理连接异常 (状态码: {response.status_code})")
            return False
    except Exception as e:
        print(f"❌ 代理连接失败: {e}")
        print("\n建议：")
        print("1. 检查代理服务是否运行（如Clash、V2Ray等）")
        print("2. 确认代理端口是否正确（默认7890）")
        print("3. 如果不需要代理，请在.env中注释掉HTTP_PROXY和HTTPS_PROXY")
        return False

def check_llm_api():
    """检查LLM API连接"""
    print("\n" + "="*60)
    print("2. 检查LLM API连接")
    print("="*60)

    qwen_api_key = os.getenv("QWEN_API_KEY", "")
    qwen_base_url = os.getenv("QWEN_BASE_URL", "")
    agent_model = os.getenv("AGENT_LLM_MODEL", "qwen-plus")

    print(f"API Key: {qwen_api_key[:20]}..." if qwen_api_key else "未配置")
    print(f"Base URL: {qwen_base_url}")
    print(f"Agent Model: {agent_model}")

    if not qwen_api_key:
        print("❌ 未配置QWEN_API_KEY")
        return False

    # 测试API调用
    print(f"\n测试API调用...")

    try:
        from openai import OpenAI

        # 配置代理
        http_client = None
        proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
        if proxy:
            http_client = httpx.Client(proxy=proxy, timeout=30.0)

        client = OpenAI(
            api_key=qwen_api_key,
            base_url=qwen_base_url,
            http_client=http_client
        )

        start_time = time.time()
        response = client.chat.completions.create(
            model=agent_model,
            messages=[{"role": "user", "content": "你好"}],
            temperature=0.0,
            max_tokens=50
        )
        latency = (time.time() - start_time) * 1000

        content = response.choices[0].message.content
        print(f"✅ API调用成功")
        print(f"   响应: {content[:50]}...")
        print(f"   延迟: {latency:.0f}ms")

        if latency > 5000:
            print(f"⚠️ 延迟过高 ({latency:.0f}ms)，可能影响用户体验")
            print("   建议：检查网络连接或代理配置")

        return True

    except Exception as e:
        print(f"❌ API调用失败: {e}")
        print("\n可能的原因：")
        print("1. API Key无效或过期")
        print("2. 网络连接问题")
        print("3. 代理配置错误")
        print("4. 模型名称错误")
        return False

def check_knowledge_base():
    """检查知识库"""
    print("\n" + "="*60)
    print("3. 检查知识库")
    print("="*60)

    kb_path = Path("skills/knowledge/index")

    if not kb_path.exists():
        print(f"❌ 知识库目录不存在: {kb_path}")
        return False

    # 检查索引文件
    required_files = [
        "chunks.jsonl",
        "dense_index.faiss",
        "sparse_embeddings.pkl",
        "chunk_ids.pkl"
    ]

    all_exist = True
    for file_name in required_files:
        file_path = kb_path / file_name
        if file_path.exists():
            size_kb = file_path.stat().st_size / 1024
            print(f"✅ {file_name} ({size_kb:.1f} KB)")
        else:
            print(f"❌ {file_name} 不存在")
            all_exist = False

    return all_exist

def check_skills():
    """检查技能注册"""
    print("\n" + "="*60)
    print("4. 检查技能注册")
    print("="*60)

    try:
        from skills.registry import init_skills, get_registry

        init_skills()
        registry = get_registry()
        skills = [skill.name for skill in registry.all()]

        print(f"✅ 成功注册 {len(skills)} 个技能:")
        for skill in skills:
            print(f"   - {skill}")

        return True

    except Exception as e:
        print(f"❌ 技能注册失败: {e}")
        return False

def check_data_files():
    """检查数据文件"""
    print("\n" + "="*60)
    print("5. 检查数据文件")
    print("="*60)

    # 检查各个skill的数据文件
    data_locations = [
        ("skills/emission_factors/data/emission_matrix", "*.csv"),
        ("skills/micro_emission/data", "*.csv"),
        ("skills/macro_emission/data", "*.csv"),
    ]

    all_exist = True
    for location, pattern in data_locations:
        path = Path(location)
        if path.exists():
            files = list(path.glob(pattern))
            if files:
                print(f"✅ {location}: {len(files)} 个文件")
            else:
                print(f"⚠️ {location}: 目录存在但无数据文件")
                all_exist = False
        else:
            print(f"❌ {location}: 目录不存在")
            all_exist = False

    return all_exist

def main():
    print("\n" + "="*60)
    print("Emission Agent 环境诊断")
    print("="*60)

    results = {
        "代理连接": check_proxy(),
        "LLM API": check_llm_api(),
        "知识库": check_knowledge_base(),
        "技能注册": check_skills(),
        "数据文件": check_data_files(),
    }

    print("\n" + "="*60)
    print("诊断结果汇总")
    print("="*60)

    for name, status in results.items():
        icon = "✅" if status else "❌"
        print(f"{icon} {name}")

    all_passed = all(results.values())

    if all_passed:
        print("\n✅ 所有检查通过！")
    else:
        print("\n⚠️ 部分检查未通过，请根据上述建议进行修复")

    return 0 if all_passed else 1

if __name__ == "__main__":
    sys.exit(main())
