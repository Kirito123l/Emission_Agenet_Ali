import json
from datetime import datetime
from pathlib import Path
from config import get_config

class DataCollector:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            config = get_config()
            cls._instance.base_dir = config.data_collection_dir
            cls._instance.enabled = config.enable_data_collection
        return cls._instance

    def log(self, task: str, input_value: str, output: dict, method: str,
            model: str = None, latency_ms: float = 0, context: dict = None):
        if not self.enabled:
            return

        entry = {
            "timestamp": datetime.now().isoformat(),
            "task": task,
            "input": input_value,
            "output": {"standard": output.get("standard"), "confidence": output.get("confidence", 0)},
            "method": method,
            "model": model,
            "latency_ms": round(latency_ms, 2),
            "context": context or {},
        }

        log_file = self.base_dir / f"{task}.jsonl"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def get_statistics(self, task: str) -> dict:
        log_file = self.base_dir / f"{task}.jsonl"
        if not log_file.exists():
            return {"total": 0}

        stats = {"total": 0, "by_method": {}, "confidences": []}
        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                stats["total"] += 1
                method = entry.get("method", "unknown")
                stats["by_method"][method] = stats["by_method"].get(method, 0) + 1
                if conf := entry.get("output", {}).get("confidence"):
                    stats["confidences"].append(conf)

        stats["avg_confidence"] = sum(stats["confidences"]) / len(stats["confidences"]) if stats["confidences"] else 0
        return stats

    def export_for_finetune(self, task: str, output_file: str, min_confidence: float = 0.8) -> int:
        log_file = self.base_dir / f"{task}.jsonl"
        if not log_file.exists():
            return 0

        data, seen = [], set()
        instructions = {"vehicle_type": "将车型描述标准化为MOVES标准车型", "pollutant": "将污染物描述标准化"}

        with open(log_file, "r", encoding="utf-8") as f:
            for line in f:
                entry = json.loads(line)
                if entry.get("method") not in ["llm", "rule"]:
                    continue
                if entry.get("output", {}).get("confidence", 0) < min_confidence:
                    continue
                standard = entry.get("output", {}).get("standard")
                if not standard:
                    continue
                key = f"{entry['input']}:{standard}"
                if key in seen:
                    continue
                seen.add(key)
                data.append({"instruction": instructions.get(task, ""), "input": entry["input"], "output": standard})

        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        return len(data)

def get_collector():
    return DataCollector()
