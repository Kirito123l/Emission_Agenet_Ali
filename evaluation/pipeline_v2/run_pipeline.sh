#!/bin/bash
set -e

echo "=== Stage 1: Coverage Audit ==="
python evaluation/pipeline_v2/coverage_audit.py \
    --benchmark evaluation/benchmarks/end2end_tasks.jsonl \
    --mappings config/unified_mappings.yaml \
    --constraints config/cross_constraints.yaml \
    --output evaluation/pipeline_v2/gap_report.json \
    --print-summary

echo "=== Stage 2: Targeted Generation ==="
python evaluation/pipeline_v2/targeted_generator.py \
    --gaps evaluation/pipeline_v2/gap_report.json \
    --existing evaluation/benchmarks/end2end_tasks.jsonl \
    --output evaluation/pipeline_v2/candidates.jsonl \
    --count-per-gap 2 \
    --model qwen3-max \
    --temperature 0.8

echo "=== Stage 3: Auto Validation ==="
python evaluation/pipeline_v2/auto_validator.py \
    --candidates evaluation/pipeline_v2/candidates.jsonl \
    --benchmark evaluation/benchmarks/end2end_tasks.jsonl \
    --mappings config/unified_mappings.yaml \
    --constraints config/cross_constraints.yaml \
    --output evaluation/pipeline_v2/validated_candidates.jsonl \
    --model qwen3-max \
    --llm-temperature 0.1

echo "=== Stage 4: Human Review ==="
NEEDS_REVIEW=$(python3 -c "
import json
from pathlib import Path
path = Path('evaluation/pipeline_v2/validated_candidates.jsonl')
tasks = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines() if line.strip()]
print(sum(1 for task in tasks if (task.get('validation') or {}).get('status') == 'needs_review'))
")

if [ "$NEEDS_REVIEW" -gt 0 ]; then
    echo "$NEEDS_REVIEW 条任务需要人工审阅"
    python evaluation/pipeline_v2/review_cli.py \
        --input evaluation/pipeline_v2/validated_candidates.jsonl \
        --output evaluation/pipeline_v2/reviewed_candidates.jsonl
else
    echo "所有任务自动通过，无需人工审阅"
    cp evaluation/pipeline_v2/validated_candidates.jsonl evaluation/pipeline_v2/reviewed_candidates.jsonl
fi

echo "=== Stage 5: Regression Check ==="
python evaluation/pipeline_v2/regression_check.py \
    --input evaluation/pipeline_v2/reviewed_candidates.jsonl \
    --output-dir evaluation/pipeline_v2/regression_results \
    --mode router

echo "=== Stage 6: Merge to Benchmark ==="
python evaluation/pipeline_v2/merge_to_benchmark.py \
    --reviewed evaluation/pipeline_v2/reviewed_candidates.jsonl \
    --benchmark evaluation/benchmarks/end2end_tasks.jsonl \
    --output evaluation/benchmarks/end2end_tasks.jsonl

echo "=== Final Coverage Report ==="
python evaluation/pipeline_v2/coverage_audit.py \
    --benchmark evaluation/benchmarks/end2end_tasks.jsonl \
    --mappings config/unified_mappings.yaml \
    --constraints config/cross_constraints.yaml \
    --output evaluation/pipeline_v2/final_coverage_report.json \
    --print-summary
