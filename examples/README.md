# Examples

This directory contains the smallest realistic workflows for trying the repository without reading the full report trail.

Before starting, read:

1. [../README.md](../README.md)
2. [../RELEASE_READINESS.md](../RELEASE_READINESS.md)
3. [../RUNNING.md](../RUNNING.md)
4. [../evaluation/README.md](../evaluation/README.md) if you want the benchmark path

## Workflow 1: Boot The App And Try A Real Query

Use this when you want to prove the integrated app starts and the main chat surface is reachable.

### Commands

```bash
pip install -r requirements.txt
cp .env.example .env
python run_api.py
```

If you want to use live chat/tool calls, set at least one real model key in `.env` first, for example:

```bash
QWEN_API_KEY=your-api-key-here
```

### What To Open

- `http://localhost:8000` for the web UI
- `http://localhost:8000/docs` for the API docs
- `http://localhost:8000/api/health` for a quick server-side sanity check

### Example Prompts

- `Query CO2 emission factors for 2020 passenger cars`
- `Calculate emissions for these road links`

### What To Expect

- the emission-factor query should return a chart plus key-point table
- file-driven flows should return a summary plus table/download outputs after upload and tool execution

### If You Only Want A Local Validation

If you are not ready to configure live LLM access yet, use:

```bash
python main.py health
pytest
```

## Workflow 2: Run The Smallest Meaningful Evaluation

Use this when you want a reproducible benchmark-style sanity check rather than interactive app usage.

### Command

```bash
python evaluation/run_smoke_suite.py
```

### What It Runs

- normalization evaluation
- file-grounding evaluation
- end-to-end evaluation in `tool` mode

### What To Expect

A fresh run directory under `evaluation/logs/` containing:

- `normalization/`
- `file_grounding/`
- `end2end/`
- `smoke_summary.json`

### When To Use Something Else

- Use [../RUNNING.md](../RUNNING.md) if you only want runtime validation.
- Use [../evaluation/README.md](../evaluation/README.md) if you want individual benchmark runners or ablation runs.
