"""
训练数据准备脚本
将增强后的数据转换为 Qwen3 聊天格式，并划分训练集/验证集/测试集
"""
import json
import random
from pathlib import Path
from typing import List, Dict

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
DATA_AUG_DIR = PROJECT_ROOT / "data" / "augmented"
DATA_FINAL_DIR = PROJECT_ROOT / "data" / "final"

# 随机种子
random.seed(42)

# ============================================================================
# System Prompts
# ============================================================================

UNIFIED_SYSTEM_PROMPT = """你是标准化助手。根据任务类型，将用户输入标准化为标准值。

任务类型:
- [vehicle]: 标准化为以下13种MOVES车型之一
- [pollutant]: 标准化为以下7种标准污染物之一

MOVES标准车型:
Motorcycle, Passenger Car, Passenger Truck, Light Commercial Truck,
Intercity Bus, Transit Bus, School Bus, Refuse Truck,
Single Unit Short-haul Truck, Single Unit Long-haul Truck,
Motor Home, Combination Short-haul Truck, Combination Long-haul Truck

标准污染物:
CO2, CO, NOx, PM2.5, PM10, THC, SO2

规则:
1. 只返回标准值，不要其他内容
2. 如果无法识别，返回最接近的标准值
3. 忽略修饰词（如"新能源"、"电动"），只关注核心车型"""

COLUMN_MICRO_SYSTEM_PROMPT = """你是列名映射助手。分析Excel表格列名，将其映射到标准字段。

任务类型: micro_emission

微观排放标准字段:
- time_sec: 时间（秒）
- speed_kph: 速度（km/h）
- acceleration_mps2: 加速度（m/s²）
- grade_pct: 坡度（%）

规则:
1. 返回JSON格式: {"原列名": "标准字段名", ...}
2. 只返回能识别的列，忽略无关列
3. 确保JSON格式正确"""

COLUMN_MACRO_SYSTEM_PROMPT = """你是列名映射助手。分析Excel表格列名，将其映射到标准字段。

任务类型: macro_emission

宏观排放标准字段:
- link_id: 路段编号
- link_length_km: 路段长度（km）
- traffic_flow_vph: 交通流量（辆/小时）
- avg_speed_kph: 平均速度（km/h）
- [车型名]: 车队比例（%），如 Passenger Car, Transit Bus 等

规则:
1. 返回JSON格式: {"原列名": "标准字段名", ...}
2. 只返回能识别的列，忽略无关列
3. 如果列名包含车型信息，映射到对应的MOVES车型
4. 确保JSON格式正确"""


# ============================================================================
# 数据转换函数
# ============================================================================

def convert_unified_to_chat_format(data: List[Dict]) -> List[Dict]:
    """将统一模型数据转换为聊天格式"""
    chat_data = []

    for item in data:
        input_text = item["input"]
        output_text = item["output"]
        category = item["category"]

        # 确定任务标签
        task_label = "[vehicle]" if category == "vehicle" else "[pollutant]"

        # 构建聊天格式
        chat_item = {
            "messages": [
                {
                    "role": "system",
                    "content": UNIFIED_SYSTEM_PROMPT
                },
                {
                    "role": "user",
                    "content": f"{task_label} {input_text}"
                },
                {
                    "role": "assistant",
                    "content": output_text
                }
            ]
        }

        chat_data.append(chat_item)

    return chat_data


def convert_column_to_chat_format(data: List[Dict]) -> List[Dict]:
    """将列名映射数据转换为聊天格式"""
    chat_data = []

    for item in data:
        columns = item["columns"]
        mapping = item["mapping"]
        task_type = item["task_type"]

        # 选择对应的 system prompt
        if task_type == "micro_emission":
            system_prompt = COLUMN_MICRO_SYSTEM_PROMPT
        else:
            system_prompt = COLUMN_MACRO_SYSTEM_PROMPT

        # 构建用户输入（列名列表的JSON字符串）
        user_input = json.dumps(columns, ensure_ascii=False)

        # 构建助手输出（映射的JSON字符串）
        assistant_output = json.dumps(mapping, ensure_ascii=False)

        # 构建聊天格式
        chat_item = {
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt
                },
                {
                    "role": "user",
                    "content": user_input
                },
                {
                    "role": "assistant",
                    "content": assistant_output
                }
            ]
        }

        chat_data.append(chat_item)

    return chat_data


def split_dataset(data: List[Dict], train_ratio: float = 0.85, eval_ratio: float = 0.10):
    """
    划分数据集

    Args:
        data: 数据列表
        train_ratio: 训练集比例
        eval_ratio: 验证集比例（剩余为测试集）

    Returns:
        (train_data, eval_data, test_data)
    """
    # 打乱数据
    shuffled = data.copy()
    random.shuffle(shuffled)

    # 计算分割点
    total = len(shuffled)
    train_end = int(total * train_ratio)
    eval_end = int(total * (train_ratio + eval_ratio))

    train_data = shuffled[:train_end]
    eval_data = shuffled[train_end:eval_end]
    test_data = shuffled[eval_end:]

    return train_data, eval_data, test_data


def main():
    """主函数"""
    # 确保输出目录存在
    DATA_FINAL_DIR.mkdir(parents=True, exist_ok=True)

    # ========================================================================
    # 1. 处理统一模型数据
    # ========================================================================
    print("正在处理统一模型数据...")

    # 读取增强后的数据
    with open(DATA_AUG_DIR / "unified_augmented.json", "r", encoding="utf-8") as f:
        unified_data = json.load(f)

    print(f"  - 原始数据: {len(unified_data)} 条")

    # 转换为聊天格式
    unified_chat = convert_unified_to_chat_format(unified_data)
    print(f"  - 转换为聊天格式: {len(unified_chat)} 条")

    # 划分数据集
    unified_train, unified_eval, unified_test = split_dataset(unified_chat)
    print(f"  - 训练集: {len(unified_train)} 条")
    print(f"  - 验证集: {len(unified_eval)} 条")
    print(f"  - 测试集: {len(unified_test)} 条")

    # 保存
    with open(DATA_FINAL_DIR / "unified_train.json", "w", encoding="utf-8") as f:
        json.dump(unified_train, f, ensure_ascii=False, indent=2)

    with open(DATA_FINAL_DIR / "unified_eval.json", "w", encoding="utf-8") as f:
        json.dump(unified_eval, f, ensure_ascii=False, indent=2)

    with open(DATA_FINAL_DIR / "unified_test.json", "w", encoding="utf-8") as f:
        json.dump(unified_test, f, ensure_ascii=False, indent=2)

    # ========================================================================
    # 2. 处理列名映射数据
    # ========================================================================
    print("\n正在处理列名映射数据...")

    # 读取增强后的数据
    with open(DATA_AUG_DIR / "column_augmented.json", "r", encoding="utf-8") as f:
        column_data = json.load(f)

    print(f"  - 原始数据: {len(column_data)} 条")

    # 转换为聊天格式
    column_chat = convert_column_to_chat_format(column_data)
    print(f"  - 转换为聊天格式: {len(column_chat)} 条")

    # 划分数据集
    column_train, column_eval, column_test = split_dataset(column_chat)
    print(f"  - 训练集: {len(column_train)} 条")
    print(f"  - 验证集: {len(column_eval)} 条")
    print(f"  - 测试集: {len(column_test)} 条")

    # 保存
    with open(DATA_FINAL_DIR / "column_train.json", "w", encoding="utf-8") as f:
        json.dump(column_train, f, ensure_ascii=False, indent=2)

    with open(DATA_FINAL_DIR / "column_eval.json", "w", encoding="utf-8") as f:
        json.dump(column_eval, f, ensure_ascii=False, indent=2)

    with open(DATA_FINAL_DIR / "column_test.json", "w", encoding="utf-8") as f:
        json.dump(column_test, f, ensure_ascii=False, indent=2)

    # ========================================================================
    # 3. 统计信息
    # ========================================================================
    print("\n" + "="*60)
    print("训练数据准备完成！")
    print("\n统一模型:")
    print(f"  - 训练集: {len(unified_train)} 条")
    print(f"  - 验证集: {len(unified_eval)} 条")
    print(f"  - 测试集: {len(unified_test)} 条")
    print(f"  - 总计: {len(unified_chat)} 条")
    print("\n列名映射模型:")
    print(f"  - 训练集: {len(column_train)} 条")
    print(f"  - 验证集: {len(column_eval)} 条")
    print(f"  - 测试集: {len(column_test)} 条")
    print(f"  - 总计: {len(column_chat)} 条")
    print("\n总数据量: {} 条".format(len(unified_chat) + len(column_chat)))
    print("="*60)

    # 打印示例
    print("\n示例数据:")
    print("\n[统一模型 - 车型]")
    print(json.dumps(unified_train[0], ensure_ascii=False, indent=2))
    print("\n[列名映射]")
    print(json.dumps(column_train[0], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
