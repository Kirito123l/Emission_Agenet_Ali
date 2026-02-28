"""
模型评估脚本
评估微调后的模型在测试集上的表现
"""
import json
import torch
from pathlib import Path
from typing import Dict, List
from transformers import AutoModelForCausalLM, AutoTokenizer
from peft import PeftModel
from tqdm import tqdm

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


def load_model_and_tokenizer(base_model_path: str, lora_path: str):
    """加载模型和 tokenizer"""
    print(f"加载基础模型: {base_model_path}")
    tokenizer = AutoTokenizer.from_pretrained(base_model_path, trust_remote_code=True)

    model = AutoModelForCausalLM.from_pretrained(
        base_model_path,
        trust_remote_code=True,
        torch_dtype=torch.float16,
        device_map="auto"
    )

    print(f"加载 LoRA 权重: {lora_path}")
    model = PeftModel.from_pretrained(model, lora_path)
    model.eval()

    return model, tokenizer


def generate_response(model, tokenizer, messages: List[Dict], max_new_tokens: int = 128):
    """生成响应"""
    # 构建输入
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )

    inputs = tokenizer(text, return_tensors="pt").to(model.device)

    # 生成
    with torch.no_grad():
        outputs = model.generate(
            **inputs,
            max_new_tokens=max_new_tokens,
            temperature=0.1,
            do_sample=False,
            pad_token_id=tokenizer.pad_token_id,
            eos_token_id=tokenizer.eos_token_id,
        )

    # 解码
    response = tokenizer.decode(outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
    return response.strip()


def evaluate_unified_model(model, tokenizer, test_file: str):
    """评估统一模型"""
    print("\n" + "="*60)
    print("评估统一模型（车型 + 污染物标准化）")
    print("="*60)

    # 加载测试数据
    with open(test_file, "r", encoding="utf-8") as f:
        test_data = json.load(f)

    # 统计
    correct = {"vehicle": 0, "pollutant": 0}
    total = {"vehicle": 0, "pollutant": 0}
    errors = {"vehicle": [], "pollutant": []}

    for item in tqdm(test_data, desc="评估中"):
        messages = item["messages"]
        expected = messages[-1]["content"]  # assistant 的回复

        # 判断任务类型
        user_input = messages[1]["content"]
        if "[vehicle]" in user_input:
            task_type = "vehicle"
        else:
            task_type = "pollutant"

        # 生成预测
        predicted = generate_response(model, tokenizer, messages[:-1])

        # 比较
        total[task_type] += 1
        if predicted == expected:
            correct[task_type] += 1
        else:
            errors[task_type].append({
                "input": user_input,
                "expected": expected,
                "predicted": predicted
            })

    # 打印结果
    print("\n结果:")
    print(f"  车型标准化:")
    print(f"    - 准确率: {correct['vehicle'] / total['vehicle'] * 100:.2f}% ({correct['vehicle']}/{total['vehicle']})")
    print(f"  污染物标准化:")
    print(f"    - 准确率: {correct['pollutant'] / total['pollutant'] * 100:.2f}% ({correct['pollutant']}/{total['pollutant']})")
    print(f"  总体准确率: {sum(correct.values()) / sum(total.values()) * 100:.2f}%")

    # 打印错误示例
    if errors["vehicle"]:
        print(f"\n车型错误示例（前5个）:")
        for err in errors["vehicle"][:5]:
            print(f"  输入: {err['input']}")
            print(f"  期望: {err['expected']}")
            print(f"  预测: {err['predicted']}")
            print()

    if errors["pollutant"]:
        print(f"\n污染物错误示例（前5个）:")
        for err in errors["pollutant"][:5]:
            print(f"  输入: {err['input']}")
            print(f"  期望: {err['expected']}")
            print(f"  预测: {err['predicted']}")
            print()

    return {
        "vehicle_accuracy": correct["vehicle"] / total["vehicle"],
        "pollutant_accuracy": correct["pollutant"] / total["pollutant"],
        "overall_accuracy": sum(correct.values()) / sum(total.values())
    }


def evaluate_column_model(model, tokenizer, test_file: str):
    """评估列名映射模型"""
    print("\n" + "="*60)
    print("评估列名映射模型")
    print("="*60)

    # 加载测试数据
    with open(test_file, "r", encoding="utf-8") as f:
        test_data = json.load(f)

    # 统计
    exact_match = 0
    partial_match = 0
    total = len(test_data)
    errors = []

    for item in tqdm(test_data, desc="评估中"):
        messages = item["messages"]
        expected_str = messages[-1]["content"]  # assistant 的回复

        try:
            expected = json.loads(expected_str)
        except:
            continue

        # 生成预测
        predicted_str = generate_response(model, tokenizer, messages[:-1], max_new_tokens=256)

        try:
            predicted = json.loads(predicted_str)
        except:
            errors.append({
                "input": messages[1]["content"],
                "expected": expected_str,
                "predicted": predicted_str,
                "error": "JSON解析失败"
            })
            continue

        # 比较
        if predicted == expected:
            exact_match += 1
        elif all(k in predicted and predicted[k] == v for k, v in expected.items()):
            partial_match += 1
        else:
            errors.append({
                "input": messages[1]["content"],
                "expected": expected,
                "predicted": predicted,
                "error": "映射不匹配"
            })

    # 打印结果
    print("\n结果:")
    print(f"  完全匹配: {exact_match / total * 100:.2f}% ({exact_match}/{total})")
    print(f"  部分匹配: {(exact_match + partial_match) / total * 100:.2f}% ({exact_match + partial_match}/{total})")

    # 打印错误示例
    if errors:
        print(f"\n错误示例（前5个）:")
        for err in errors[:5]:
            print(f"  输入: {err['input']}")
            print(f"  期望: {err['expected']}")
            print(f"  预测: {err['predicted']}")
            print(f"  错误: {err['error']}")
            print()

    return {
        "exact_match": exact_match / total,
        "partial_match": (exact_match + partial_match) / total
    }


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="模型评估")
    parser.add_argument("--model_type", type=str, required=True, choices=["unified", "column"], help="模型类型")
    parser.add_argument("--base_model", type=str, default="Qwen/Qwen2.5-3B-Instruct", help="基础模型路径")
    parser.add_argument("--lora_path", type=str, required=True, help="LoRA 权重路径")
    args = parser.parse_args()

    # 加载模型
    model, tokenizer = load_model_and_tokenizer(args.base_model, args.lora_path)

    # 评估
    if args.model_type == "unified":
        test_file = PROJECT_ROOT / "data" / "final" / "unified_test.json"
        results = evaluate_unified_model(model, tokenizer, test_file)
    else:
        test_file = PROJECT_ROOT / "data" / "final" / "column_test.json"
        results = evaluate_column_model(model, tokenizer, test_file)

    # 保存结果
    results_file = PROJECT_ROOT / "models" / f"{args.model_type}_eval_results.json"
    with open(results_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2)

    print(f"\n评估结果已保存至: {results_file}")


if __name__ == "__main__":
    main()
