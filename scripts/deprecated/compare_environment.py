"""
环境对比诊断脚本
"""
import sys
import platform
from pathlib import Path

def check_environment():
    """检查环境信息"""
    print("\n" + "="*60)
    print("环境信息对比")
    print("="*60)

    # Python版本
    print(f"\nPython版本: {sys.version}")
    print(f"Python路径: {sys.executable}")

    # 操作系统
    print(f"\n操作系统: {platform.system()} {platform.release()}")
    print(f"架构: {platform.machine()}")

    # 依赖版本
    print("\n关键依赖版本:")
    try:
        import openai
        print(f"  openai: {openai.__version__}")
    except ImportError:
        print(f"  openai: 未安装")

    try:
        import httpx
        print(f"  httpx: {httpx.__version__}")
    except ImportError:
        print(f"  httpx: 未安装")

    try:
        import pandas
        print(f"  pandas: {pandas.__version__}")
    except ImportError:
        print(f"  pandas: 未安装")

    try:
        import fastapi
        print(f"  fastapi: {fastapi.__version__}")
    except ImportError:
        print(f"  fastapi: 未安装")

    # 环境变量
    print("\n环境配置:")
    from dotenv import load_dotenv
    import os
    load_dotenv()

    print(f"  AGENT_LLM_MODEL: {os.getenv('AGENT_LLM_MODEL', 'N/A')}")
    print(f"  SYNTHESIS_LLM_MODEL: {os.getenv('SYNTHESIS_LLM_MODEL', 'N/A')}")
    print(f"  HTTP_PROXY: {os.getenv('HTTP_PROXY', 'N/A')}")

    # 学习案例统计
    print("\n学习案例统计:")
    cases_file = Path("data/learning/cases.jsonl")
    if cases_file.exists():
        import json
        total = 0
        success = 0
        failed = 0
        with open(cases_file, 'r', encoding='utf-8') as f:
            for line in f:
                if line.strip():
                    total += 1
                    try:
                        case = json.loads(line)
                        if case.get('success'):
                            success += 1
                        else:
                            failed += 1
                    except:
                        pass
        print(f"  总案例数: {total}")
        print(f"  成功案例: {success}")
        print(f"  失败案例: {failed}")
        print(f"  成功率: {success/total*100:.1f}%" if total > 0 else "  成功率: N/A")
    else:
        print(f"  学习案例文件不存在")

    # 缓存统计
    print("\n缓存状态:")
    cache_dir = Path("data/cache")
    if cache_dir.exists():
        cache_files = list(cache_dir.glob("*"))
        print(f"  缓存文件数: {len(cache_files)}")
    else:
        print(f"  缓存目录不存在")

def compare_with_reference():
    """与参考环境对比"""
    print("\n" + "="*60)
    print("可能的环境差异原因")
    print("="*60)

    print("""
1. **LLM模型行为差异**
   - 同一个模型在不同时间可能有不同的输出格式
   - 建议：检查两台电脑使用的模型是否完全相同

2. **学习案例积累差异**
   - 原电脑可能积累了更多成功案例
   - Few-shot学习会影响LLM的输出格式
   - 建议：复制原电脑的 data/learning/cases.jsonl

3. **依赖版本差异**
   - OpenAI SDK版本可能不同
   - 建议：确保两台电脑使用相同版本的依赖

4. **网络环境差异**
   - 代理设置可能影响API响应
   - 网络延迟可能导致超时
   - 建议：对比代理配置

5. **Python版本差异**
   - 不同Python版本的行为可能略有不同
   - 建议：使用相同的Python版本

6. **随机性因素**
   - LLM输出本身有随机性
   - temperature参数的影响
   - 建议：降低temperature（已设置为0.0）
    """)

def main():
    print("\n" + "="*60)
    print("环境对比诊断")
    print("="*60)

    check_environment()
    compare_with_reference()

    print("\n" + "="*60)
    print("建议的对比步骤")
    print("="*60)
    print("""
1. 在原电脑上运行此脚本，对比输出
2. 检查学习案例数量差异
3. 对比依赖版本
4. 如果原电脑成功率高，考虑复制学习案例文件
5. 确保使用相同的模型和配置
    """)

if __name__ == "__main__":
    main()
