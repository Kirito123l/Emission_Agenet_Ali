"""
清理学习案例 - 只保留成功案例
"""
import json
from pathlib import Path
import shutil
from datetime import datetime

def clean_learning_cases():
    """清理学习案例，只保留成功案例"""
    cases_file = Path("data/learning/cases.jsonl")

    if not cases_file.exists():
        print("❌ 学习案例文件不存在")
        return

    # 备份原文件
    backup_file = cases_file.with_suffix(f'.jsonl.backup.{datetime.now().strftime("%Y%m%d_%H%M%S")}')
    shutil.copy(cases_file, backup_file)
    print(f"✅ 已备份到: {backup_file}")

    # 读取并过滤
    success_cases = []
    failed_cases = []

    with open(cases_file, 'r', encoding='utf-8') as f:
        for line in f:
            if line.strip():
                case = json.loads(line)
                if case.get('success'):
                    success_cases.append(case)
                else:
                    failed_cases.append(case)

    print(f"\n统计:")
    print(f"  成功案例: {len(success_cases)}")
    print(f"  失败案例: {len(failed_cases)}")

    # 写入只包含成功案例的文件
    with open(cases_file, 'w', encoding='utf-8') as f:
        for case in success_cases:
            f.write(json.dumps(case, ensure_ascii=False) + '\n')

    print(f"\n✅ 已清理完成，保留 {len(success_cases)} 个成功案例")
    print(f"⚠️ 如需恢复，请使用备份文件: {backup_file}")

if __name__ == "__main__":
    print("="*60)
    print("清理学习案例")
    print("="*60)

    response = input("\n是否清理学习案例，只保留成功案例？(y/n): ")
    if response.lower() == 'y':
        clean_learning_cases()
    else:
        print("已取消")
