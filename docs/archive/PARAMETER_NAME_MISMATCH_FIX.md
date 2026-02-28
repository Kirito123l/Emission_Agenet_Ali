# Parameter Name Mismatch Fix

## Problem

LLM was calling `calculate_micro_emission` but the tool was failing with:
```
Missing required parameter: trajectory_data or input_file
```

## Root Cause

Parameter name mismatch across the system:

1. **Tool Definition** (`tools/definitions.py`): Uses `file_path` parameter
2. **Executor** (`core/executor.py`): Auto-injects `file_path` parameter
3. **Skill Implementation** (`skills/micro_emission/skill.py`): Expects `input_file` parameter

When the executor injected `file_path`, the skill didn't recognize it and reported missing `input_file`.

## Solution

Added parameter mapping in both emission skills to accept `file_path` and map it to `input_file`:

### 1. Micro Emission Skill (`skills/micro_emission/skill.py`)

```python
def execute(self, **params) -> SkillResult:
    context = {"skill": self.name}

    # Map file_path to input_file if provided (parameter name compatibility)
    if "file_path" in params and "input_file" not in params:
        params["input_file"] = params["file_path"]
        logger.info(f"Mapped file_path to input_file: {params['file_path']}")

    logger.info(f"[MicroEmission] Received parameters: {list(params.keys())}")
    logger.debug(f"[MicroEmission] Full parameters: {params}")
```

### 2. Macro Emission Skill (`skills/macro_emission/skill.py`)

```python
def execute(self, **params) -> SkillResult:
    context = {"skill": self.name}

    # Map file_path to input_file if provided (parameter name compatibility)
    if "file_path" in params and "input_file" not in params:
        params["input_file"] = params["file_path"]
        logger.info(f"Mapped file_path to input_file: {params['file_path']}")

    logger.info(f"[MacroEmission] Received parameters: {list(params.keys())}")
    logger.debug(f"[MacroEmission] Full parameters: {params}")
```

### 3. Enhanced Executor Logging (`core/executor.py`)

Added detailed logging to track parameter flow:

```python
# Show original arguments from LLM
logger.info(f"[Executor] Original arguments from LLM for {tool_name}: {arguments}")

# Show standardized arguments
logger.info(f"[Executor] Standardized arguments: {standardized_args}")

# Show auto-injection
if file_path and "file_path" not in standardized_args:
    standardized_args["file_path"] = file_path
    logger.info(f"[Executor] Auto-injected file_path: {file_path}")
```

## Testing

Restart the server and test with:
```
1. Upload micro_05_minimal.csv
2. Say: "帮我计算这个大货车的排放"
3. When asked for parameters, say: "默认吧"
```

Expected behavior:
- Executor logs will show: `[Executor] Auto-injected file_path: ...`
- Skill logs will show: `Mapped file_path to input_file: ...`
- Calculation should complete successfully

## Files Modified

1. `skills/micro_emission/skill.py` - Added file_path → input_file mapping
2. `skills/macro_emission/skill.py` - Added file_path → input_file mapping
3. `core/executor.py` - Enhanced logging for debugging
