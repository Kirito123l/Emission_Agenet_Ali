"""
数据验证脚本
验证生成的训练数据质量
"""
import json
from pathlib import Path
from collections import Counter

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
DATA_FINAL_DIR = PROJECT_ROOT / "data" / "final"


def validate_unified_data():
    """验证统一模型数据"""
    print("="*60)
    print("验证统一模型数据")
    print("="*60)

    # 加载数据
    with open(DATA_FINAL_DIR / "unified_train.json", "r", encoding="utf-8") as f:
        train_data = json.load(f)

    with open(DATA_FINAL_DIR / "unified_eval.json", "r", encoding="utf-8") as f:
        eval_data = json.load(f)

    with open(DATA_FINAL_DIR / "unified_test.json", "r", encoding="utf-8") as f:
        test_data = json.load(f)

    all_data = train_data + eval_data + test_data

    print(f"\n数据量:")
    print(f"  - 训练集: {len(train_data)}")
    print(f"  - 验证集: {len(eval_data)}")
    print(f"  - 测试集: {len(test_data)}")
    print(f"  - 总计: {len(all_data)}")

    # 统计车型和污染物分布
    vehicle_outputs = []
    pollutant_outputs = []

    for item in all_data:
        messages = item["messages"]
        user_input = messages[1]["content"]
        output = messages[2]["content"]

        if "[vehicle]" in user_input:
            vehicle_outputs.append(output)
        else:
            pollutant_outputs.append(output)

    # 车型分布
    print(f"\n车型分布:")
    vehicle_counter = Counter(vehicle_outputs)
    for vehicle, count in sorted(vehicle_counter.items()):
        print(f"  - {vehicle}: {count} 条")

    # 污染物分布
    print(f"\n污染物分布:")
    pollutant_counter = Counter(pollutant_outputs)
    for pollutant, count in sorted(pollutant_counter.items()):
        print(f"  - {pollutant}: {count} 条")

    # 检查是否所有标准值都有数据
    expected_vehicles = [
        "Motorcycle", "Passenger Car", "Passenger Truck", "Light Commercial Truck",
        "Intercity Bus", "Transit Bus", "School Bus", "Refuse Truck",
        "Single Unit Short-haul Truck", "Single Unit Long-haul Truck",
        "Motor Home", "Combination Short-haul Truck", "Combination Long-haul Truck"
    ]

    expected_pollutants = ["CO2", "CO", "NOx", "PM2.5", "PM10", "THC", "SO2"]

    missing_vehicles = set(expected_vehicles) - set(vehicle_counter.keys())
    missing_pollutants = set(expected_pollutants) - set(pollutant_counter.keys())

    if missing_vehicles:
        print(f"\n[警告] 缺失的车型: {missing_vehicles}")
    else:
        print(f"\n[OK] 所有13种车型都有数据")

    if missing_pollutants:
        print(f"[警告] 缺失的污染物: {missing_pollutants}")
    else:
        print(f"[OK] 所有7种污染物都有数据")

    # 检查数据格式
    print(f"\n数据格式检查:")
    format_errors = 0
    for i, item in enumerate(all_data[:100]):  # 检查前100条
        if "messages" not in item:
            format_errors += 1
            continue

        messages = item["messages"]
        if len(messages) != 3:
            format_errors += 1
            continue

        if messages[0]["role"] != "system":
            format_errors += 1
        if messages[1]["role"] != "user":
            format_errors += 1
        if messages[2]["role"] != "assistant":
            format_errors += 1

    if format_errors > 0:
        print(f"  [警告] 发现 {format_errors} 个格式错误")
    else:
        print(f"  [OK] 格式正确")

    # 打印示例
    print(f"\n示例数据:")
    print(json.dumps(train_data[0], ensure_ascii=False, indent=2))


def validate_column_data():
    """验证列名映射数据"""
    print("\n" + "="*60)
    print("验证列名映射数据")
    print("="*60)

    # 加载数据
    with open(DATA_FINAL_DIR / "column_train.json", "r", encoding="utf-8") as f:
        train_data = json.load(f)

    with open(DATA_FINAL_DIR / "column_eval.json", "r", encoding="utf-8") as f:
        eval_data = json.load(f)

    with open(DATA_FINAL_DIR / "column_test.json", "r", encoding="utf-8") as f:
        test_data = json.load(f)

    all_data = train_data + eval_data + test_data

    print(f"\n数据量:")
    print(f"  - 训练集: {len(train_data)}")
    print(f"  - 验证集: {len(eval_data)}")
    print(f"  - 测试集: {len(test_data)}")
    print(f"  - 总计: {len(all_data)}")

    # 统计任务类型分布
    task_types = []
    for item in all_data:
        messages = item["messages"]
        system_content = messages[0]["content"]
        if "micro_emission" in system_content:
            task_types.append("micro_emission")
        else:
            task_types.append("macro_emission")

    task_counter = Counter(task_types)
    print(f"\n任务类型分布:")
    for task, count in task_counter.items():
        print(f"  - {task}: {count} 条")

    # 检查 JSON 格式
    print(f"\nJSON 格式检查:")
    json_errors = 0
    for item in all_data[:100]:  # 检查前100条
        messages = item["messages"]
        user_input = messages[1]["content"]
        assistant_output = messages[2]["content"]

        try:
            json.loads(user_input)
            json.loads(assistant_output)
        except:
            json_errors += 1

    if json_errors > 0:
        print(f"  [警告] 发现 {json_errors} 个 JSON 格式错误")
    else:
        print(f"  [OK] JSON 格式正确")

    # 打印示例
    print(f"\n示例数据:")
    print(json.dumps(train_data[0], ensure_ascii=False, indent=2))


def main():
    """主函数"""
    validate_unified_data()
    validate_column_data()

    print("\n" + "="*60)
    print("数据验证完成！")
    print("="*60)


if __name__ == "__main__":
    main()
