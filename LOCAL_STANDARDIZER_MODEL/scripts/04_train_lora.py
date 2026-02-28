"""
LoRA 微调训练脚本
支持统一模型和列名映射模型的训练
"""
import os
import sys
import yaml
import json
import torch
from pathlib import Path
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from transformers import (
    AutoModelForCausalLM,
    AutoTokenizer,
    TrainingArguments,
    Trainer,
    DataCollatorForSeq2Seq,
)
from peft import LoraConfig, get_peft_model, TaskType
from datasets import Dataset

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class ModelArguments:
    """模型参数"""
    model_name_or_path: str = field(metadata={"help": "基础模型路径"})
    use_flash_attention: bool = field(default=False, metadata={"help": "是否使用 Flash Attention"})


@dataclass
class DataArguments:
    """数据参数"""
    train_file: str = field(metadata={"help": "训练数据文件"})
    eval_file: str = field(metadata={"help": "验证数据文件"})
    max_length: int = field(default=256, metadata={"help": "最大序列长度"})


@dataclass
class LoraArguments:
    """LoRA 参数"""
    r: int = field(default=16, metadata={"help": "LoRA rank"})
    lora_alpha: int = field(default=32, metadata={"help": "LoRA alpha"})
    lora_dropout: float = field(default=0.05, metadata={"help": "LoRA dropout"})
    target_modules: List[str] = field(default_factory=lambda: ["q_proj", "v_proj"])


def load_config(config_path: str) -> Dict:
    """加载配置文件"""
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return config


def load_dataset_from_json(file_path: str) -> Dataset:
    """从JSON文件加载数据集"""
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return Dataset.from_list(data)


def preprocess_function(examples, tokenizer, max_length):
    """
    预处理函数：将聊天格式转换为模型输入
    """
    model_inputs = {"input_ids": [], "attention_mask": [], "labels": []}

    for messages in examples["messages"]:
        # 使用 tokenizer 的 apply_chat_template 方法
        # 这会自动处理 system, user, assistant 角色
        text = tokenizer.apply_chat_template(
            messages,
            tokenize=False,
            add_generation_prompt=False
        )

        # Tokenize
        tokenized = tokenizer(
            text,
            max_length=max_length,
            truncation=True,
            padding="max_length",
            return_tensors=None
        )

        # 创建 labels（与 input_ids 相同，但 padding 部分设为 -100）
        labels = tokenized["input_ids"].copy()
        labels = [
            -100 if token_id == tokenizer.pad_token_id else token_id
            for token_id in labels
        ]

        model_inputs["input_ids"].append(tokenized["input_ids"])
        model_inputs["attention_mask"].append(tokenized["attention_mask"])
        model_inputs["labels"].append(labels)

    return model_inputs


def main():
    """主函数"""
    import argparse

    parser = argparse.ArgumentParser(description="LoRA 微调训练")
    parser.add_argument("--config", type=str, required=True, help="配置文件路径")
    parser.add_argument("--model_type", type=str, required=True, choices=["unified", "column"], help="模型类型")
    args = parser.parse_args()

    # 加载配置
    config_path = PROJECT_ROOT / args.config
    config = load_config(config_path)

    print("="*60)
    print(f"开始训练 {args.model_type} 模型")
    print("="*60)

    # 1. 加载 tokenizer 和模型
    print("\n[1/6] 加载模型和 tokenizer...")
    model_name = config["base_model"]
    tokenizer = AutoTokenizer.from_pretrained(
        model_name,
        trust_remote_code=True,
        padding_side="right"  # 重要：训练时使用右侧 padding
    )

    # 设置 pad_token
    if tokenizer.pad_token is None:
        tokenizer.pad_token = tokenizer.eos_token

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        trust_remote_code=True,
        torch_dtype=torch.float16 if config["training"].get("fp16", True) else torch.float32,
        device_map="auto"
    )

    print(f"  - 基础模型: {model_name}")
    print(f"  - 模型参数量: {model.num_parameters() / 1e9:.2f}B")

    # 2. 配置 LoRA
    print("\n[2/6] 配置 LoRA...")
    lora_config = LoraConfig(
        r=config["lora"]["r"],
        lora_alpha=config["lora"]["lora_alpha"],
        target_modules=config["lora"]["target_modules"],
        lora_dropout=config["lora"]["lora_dropout"],
        bias=config["lora"]["bias"],
        task_type=TaskType.CAUSAL_LM,
    )

    model = get_peft_model(model, lora_config)
    model.print_trainable_parameters()

    # 3. 加载数据集
    print("\n[3/6] 加载数据集...")
    train_file = PROJECT_ROOT / config["data"]["train_file"]
    eval_file = PROJECT_ROOT / config["data"]["eval_file"]

    train_dataset = load_dataset_from_json(train_file)
    eval_dataset = load_dataset_from_json(eval_file)

    print(f"  - 训练集: {len(train_dataset)} 条")
    print(f"  - 验证集: {len(eval_dataset)} 条")

    # 4. 预处理数据
    print("\n[4/6] 预处理数据...")
    max_length = config["data"]["max_length"]

    train_dataset = train_dataset.map(
        lambda x: preprocess_function(x, tokenizer, max_length),
        batched=True,
        remove_columns=train_dataset.column_names,
        desc="预处理训练集"
    )

    eval_dataset = eval_dataset.map(
        lambda x: preprocess_function(x, tokenizer, max_length),
        batched=True,
        remove_columns=eval_dataset.column_names,
        desc="预处理验证集"
    )

    # 5. 配置训练参数
    print("\n[5/6] 配置训练参数...")
    output_dir = PROJECT_ROOT / config["training"]["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    training_args = TrainingArguments(
        output_dir=str(output_dir),
        num_train_epochs=config["training"]["num_train_epochs"],
        per_device_train_batch_size=config["training"]["per_device_train_batch_size"],
        per_device_eval_batch_size=config["training"]["per_device_train_batch_size"],
        gradient_accumulation_steps=config["training"]["gradient_accumulation_steps"],
        learning_rate=config["training"]["learning_rate"],
        warmup_ratio=config["training"]["warmup_ratio"],
        fp16=config["training"].get("fp16", True),
        gradient_checkpointing=config["training"].get("gradient_checkpointing", True),
        logging_steps=config["training"]["logging_steps"],
        save_steps=config["training"]["save_steps"],
        eval_steps=config["training"]["eval_steps"],
        save_total_limit=config["training"].get("save_total_limit", 3),
        load_best_model_at_end=config["training"].get("load_best_model_at_end", True),
        metric_for_best_model=config["training"].get("metric_for_best_model", "eval_loss"),
        greater_is_better=config["training"].get("greater_is_better", False),
        evaluation_strategy="steps",
        save_strategy="steps",
        report_to="none",  # 不使用 wandb 等
    )

    # 6. 开始训练
    print("\n[6/6] 开始训练...")
    trainer = Trainer(
        model=model,
        args=training_args,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        data_collator=DataCollatorForSeq2Seq(tokenizer=tokenizer, padding=True),
    )

    # 训练
    trainer.train()

    # 保存最终模型
    final_model_path = output_dir / "final"
    trainer.save_model(str(final_model_path))
    tokenizer.save_pretrained(str(final_model_path))

    print("\n" + "="*60)
    print("训练完成！")
    print(f"模型已保存至: {final_model_path}")
    print("="*60)


if __name__ == "__main__":
    main()
