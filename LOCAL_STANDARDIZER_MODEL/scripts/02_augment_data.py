"""
数据增强脚本
对种子数据进行多种增强，生成多样化的训练数据
"""
import json
import random
from pathlib import Path
from typing import List, Dict, Set

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent
DATA_RAW_DIR = PROJECT_ROOT / "data" / "raw"
DATA_AUG_DIR = PROJECT_ROOT / "data" / "augmented"

# 随机种子
random.seed(42)


class DataAugmenter:
    """数据增强器"""

    def __init__(self):
        # 修饰词（用于车型）
        self.vehicle_modifiers = [
            "新能源", "电动", "燃油", "混动", "柴油", "汽油",
            "国六", "国五", "国四", "纯电动", "插电混动",
        ]

        # 上下文模板
        self.context_templates = [
            "查询{}",
            "我想查{}",
            "{}类型",
            "帮我查{}的数据",
            "{}的排放",
            "计算{}排放",
            "分析{}",
            "{}是什么",
            "关于{}",
            "{}的信息",
        ]

    def augment_text(self, text: str, is_vehicle: bool = False) -> List[str]:
        """
        生成文本变体

        Args:
            text: 原始文本
            is_vehicle: 是否为车型（车型可以添加修饰词）

        Returns:
            文本变体列表
        """
        variants = set()
        variants.add(text)  # 原始文本

        # 1. 空格变体
        if " " in text:
            variants.add(text.replace(" ", ""))  # 去空格
        if len(text) > 1 and " " not in text:
            # 添加空格（仅对较短的文本）
            if len(text) <= 10:
                variants.add(" ".join(list(text)))

        # 2. 大小写变体（英文）
        if any(c.isalpha() and ord(c) < 128 for c in text):
            variants.add(text.lower())
            variants.add(text.upper())
            variants.add(text.title())

        # 3. 标点变体
        variants.add(text + "。")
        variants.add(text + "的")
        variants.add(text + "?")
        variants.add(text + "？")

        # 4. 上下文变体（随机选择3-5个模板）
        num_contexts = min(5, len(self.context_templates))
        selected_templates = random.sample(self.context_templates, num_contexts)
        for template in selected_templates:
            variants.add(template.format(text))

        # 5. 修饰词变体（仅车型）
        if is_vehicle and any(c >= '\u4e00' and c <= '\u9fff' for c in text):
            # 随机选择3-5个修饰词
            num_modifiers = min(5, len(self.vehicle_modifiers))
            selected_modifiers = random.sample(self.vehicle_modifiers, num_modifiers)
            for mod in selected_modifiers:
                variants.add(mod + text)
                variants.add(text + "（" + mod + "）")

        return list(variants)

    def augment_vehicle_data(self, seed_data: List[Dict]) -> List[Dict]:
        """增强车型数据"""
        augmented = []

        for item in seed_data:
            input_text = item["input"]
            output_text = item["output"]

            # 生成变体
            variants = self.augment_text(input_text, is_vehicle=True)

            for variant in variants:
                augmented.append({
                    "input": variant,
                    "output": output_text,
                    "category": "vehicle",
                    "source": "augmented"
                })

        return augmented

    def augment_pollutant_data(self, seed_data: List[Dict]) -> List[Dict]:
        """增强污染物数据"""
        augmented = []

        for item in seed_data:
            input_text = item["input"]
            output_text = item["output"]

            # 生成变体
            variants = self.augment_text(input_text, is_vehicle=False)

            for variant in variants:
                augmented.append({
                    "input": variant,
                    "output": output_text,
                    "category": "pollutant",
                    "source": "augmented"
                })

        return augmented

    def augment_column_data(self, seed_data: List[Dict]) -> List[Dict]:
        """增强列名映射数据"""
        augmented = []

        # 按任务类型分组
        micro_data = [d for d in seed_data if d.get("task_type") == "micro_emission"]
        macro_data = [d for d in seed_data if d.get("task_type") == "macro_emission"]

        # 增强微观排放列名
        augmented.extend(self._augment_column_group(micro_data, "micro_emission"))

        # 增强宏观排放列名
        augmented.extend(self._augment_column_group(macro_data, "macro_emission"))

        return augmented

    def _augment_column_group(self, data: List[Dict], task_type: str) -> List[Dict]:
        """增强列名组"""
        augmented = []

        # 按标准字段分组
        by_standard = {}
        for item in data:
            std = item["output"]
            if std not in by_standard:
                by_standard[std] = []
            by_standard[std].append(item["input"])

        # 生成列名组合（模拟真实Excel表格）
        num_combinations = 1500  # 每种任务类型生成1500个组合（总共3000条）

        for _ in range(num_combinations):
            # 随机选择2-4个标准字段
            num_fields = random.randint(2, min(4, len(by_standard)))
            selected_standards = random.sample(list(by_standard.keys()), num_fields)

            # 为每个标准字段随机选择一个别名
            columns = []
            mapping = {}
            for std in selected_standards:
                alias = random.choice(by_standard[std])
                columns.append(alias)
                mapping[alias] = std

            # 可能添加干扰列
            if random.random() < 0.3:
                noise_cols = ["备注", "说明", "序号", "index", "Unnamed: 0", "id"]
                columns.append(random.choice(noise_cols))

            # 打乱列顺序
            random.shuffle(columns)

            augmented.append({
                "columns": columns,
                "mapping": mapping,
                "task_type": task_type,
                "category": "column_mapping",
                "source": "augmented"
            })

        return augmented


def main():
    """主函数"""
    # 确保输出目录存在
    DATA_AUG_DIR.mkdir(parents=True, exist_ok=True)

    augmenter = DataAugmenter()

    # 1. 增强车型数据
    print("正在增强车型数据...")
    with open(DATA_RAW_DIR / "vehicle_type_seed.json", "r", encoding="utf-8") as f:
        vehicle_seed = json.load(f)

    vehicle_augmented = augmenter.augment_vehicle_data(vehicle_seed)

    # 去重
    seen = set()
    vehicle_unique = []
    for item in vehicle_augmented:
        key = (item["input"], item["output"])
        if key not in seen:
            seen.add(key)
            vehicle_unique.append(item)

    print(f"  - 种子数据: {len(vehicle_seed)} 条")
    print(f"  - 增强后: {len(vehicle_augmented)} 条")
    print(f"  - 去重后: {len(vehicle_unique)} 条")

    # 2. 增强污染物数据
    print("\n正在增强污染物数据...")
    with open(DATA_RAW_DIR / "pollutant_seed.json", "r", encoding="utf-8") as f:
        pollutant_seed = json.load(f)

    pollutant_augmented = augmenter.augment_pollutant_data(pollutant_seed)

    # 去重
    seen = set()
    pollutant_unique = []
    for item in pollutant_augmented:
        key = (item["input"], item["output"])
        if key not in seen:
            seen.add(key)
            pollutant_unique.append(item)

    print(f"  - 种子数据: {len(pollutant_seed)} 条")
    print(f"  - 增强后: {len(pollutant_augmented)} 条")
    print(f"  - 去重后: {len(pollutant_unique)} 条")

    # 3. 合并车型和污染物数据（统一模型）
    print("\n正在合并统一模型数据...")
    unified_data = vehicle_unique + pollutant_unique
    unified_file = DATA_AUG_DIR / "unified_augmented.json"
    with open(unified_file, "w", encoding="utf-8") as f:
        json.dump(unified_data, f, ensure_ascii=False, indent=2)
    print(f"  - 统一模型数据: {len(unified_data)} 条")
    print(f"  - 保存至: {unified_file}")

    # 4. 增强列名映射数据
    print("\n正在增强列名映射数据...")
    with open(DATA_RAW_DIR / "column_mapping_seed.json", "r", encoding="utf-8") as f:
        column_seed = json.load(f)

    column_augmented = augmenter.augment_column_data(column_seed)

    print(f"  - 种子数据: {len(column_seed)} 条")
    print(f"  - 增强后: {len(column_augmented)} 条")

    column_file = DATA_AUG_DIR / "column_augmented.json"
    with open(column_file, "w", encoding="utf-8") as f:
        json.dump(column_augmented, f, ensure_ascii=False, indent=2)
    print(f"  - 保存至: {column_file}")

    # 5. 统计信息
    print("\n" + "="*60)
    print("数据增强完成！")
    print(f"统一模型数据: {len(unified_data)} 条")
    print(f"列名映射数据: {len(column_augmented)} 条")
    print(f"总数据量: {len(unified_data) + len(column_augmented)} 条")
    print("="*60)


if __name__ == "__main__":
    main()
