import json

success = 0
total = 0

with open('data/learning/cases.jsonl', 'r', encoding='utf-8') as f:
    for line in f:
        if line.strip():
            total += 1
            case = json.loads(line)
            if case.get('success'):
                success += 1

print(f"总案例: {total}")
print(f"成功: {success}")
print(f"失败: {total - success}")
print(f"成功率: {success/total*100:.1f}%")
