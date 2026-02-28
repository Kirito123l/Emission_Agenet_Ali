# Complete Diagnostic Report - Tool Execution Failure

## Executive Summary

**Problem**: LLM calls `calculate_micro_emission` but tool fails with "Missing required parameter: trajectory_data or input_file"

**Root Cause**: Parameter name mismatch between tool definition and tool implementation
- Tool definition advertises: `file_path`
- Tool implementation expects: `input_file`

## Current Symptoms

1. User uploads file and requests calculation
2. LLM says "正在计算" (calculating)
3. Tool execution fails silently with "Error: None"
4. LLM starts hallucinating (mentions CMEM model that doesn't exist)
5. Calculation never completes

## Architecture Analysis

### 1. Tool Call Chain

```
User Request
    ↓
router.py (UnifiedRouter)
    ↓
executor.py (ToolExecutor)
    ↓
tools/micro_emission.py (MicroEmissionTool)
    ↓
calculators/micro_emission.py (MicroEmissionCalculator)
```

### 2. Tool Registration

**File**: `tools/registry.py`

```python
# Line 90-91
from tools.micro_emission import MicroEmissionTool
register_tool("calculate_micro_emission", MicroEmissionTool())
```

**Key Finding**: The system uses `tools/micro_emission.py`, NOT `skills/micro_emission/skill.py`

### 3. Parameter Flow

#### Step 1: Tool Definition (tools/definitions.py)

```python
# Line 74-76
"file_path": {
    "type": "string",
    "description": "Path to trajectory data file. REQUIRED when user uploaded a file."
}
```

**Advertised to LLM**: `file_path`

#### Step 2: Executor Auto-Injection (core/executor.py)

```python
# Line 81-83
if file_path and "file_path" not in standardized_args:
    standardized_args["file_path"] = file_path
```

**Injected parameter**: `file_path`

#### Step 3: Tool Implementation (tools/micro_emission.py)

```python
# Line 59
input_file = kwargs.get("input_file")

# Line 72
if input_file:
    # Read from Excel file

# Line 81-86
elif not trajectory_data:
    return ToolResult(
        success=False,
        error="Missing required parameter: trajectory_data or input_file",
        data=None
    )
```

**Expected parameter**: `input_file`

### 4. The Mismatch

| Component | Parameter Name |
|-----------|---------------|
| Tool Definition (LLM sees) | `file_path` |
| Executor (injects) | `file_path` |
| Tool Implementation (expects) | `input_file` |

**Result**: Tool receives `file_path` but only checks for `input_file`, so it reports missing parameter.

## New vs Old Architecture

### Old Architecture (NOT USED)
- Location: `skills/` directory
- Files: `skills/micro_emission/skill.py`
- Status: **LEGACY - Not registered in tool registry**

### New Architecture (CURRENTLY USED)
- Location: `tools/` directory
- Files: `tools/micro_emission.py`
- Status: **ACTIVE - Registered and used**

**Critical Error**: Previous fixes modified `skills/micro_emission/skill.py` which is NOT being used!

## Parameter Comparison

### calculate_micro_emission

**Tool Definition** (tools/definitions.py:74-99):
- `file_path` (string)
- `trajectory_data` (array)
- `vehicle_type` (string) - REQUIRED
- `pollutants` (array)
- `model_year` (integer)
- `season` (string)

**Tool Implementation** (tools/micro_emission.py:54-61):
- `vehicle_type` (expects standardized)
- `pollutants` (default: ["CO2", "NOx"])
- `model_year` (default: 2020)
- `season` (default: "夏季")
- `input_file` ← **MISMATCH**
- `output_file`
- `trajectory_data`

### calculate_macro_emission

**Tool Definition** (tools/definitions.py:121-146):
- `file_path` (string)
- `links_data` (array)
- `pollutants` (array)
- `fleet_mix` (object)
- `model_year` (integer)
- `season` (string)

**Tool Implementation** (tools/macro_emission.py:102-109):
- `links_data`
- `pollutants` (default: ["CO2", "NOx"])
- `model_year` (default: 2020)
- `season` (default: "夏季")
- `default_fleet_mix`
- `input_file` ← **MISMATCH**
- `output_file`

## Why LLM Doesn't Call the Tool Correctly

Looking at the logs, the LLM IS calling the tool, but:

1. LLM might not be passing `file_path` in arguments (needs verification)
2. Even if LLM passes `file_path`, tool expects `input_file`
3. Executor injects `file_path`, but tool doesn't recognize it

## Required Fixes

### Fix 1: Map file_path to input_file in Tool Implementation

**File**: `tools/micro_emission.py`

```python
async def execute(self, **kwargs) -> ToolResult:
    # Map file_path to input_file (parameter compatibility)
    if "file_path" in kwargs and "input_file" not in kwargs:
        kwargs["input_file"] = kwargs["file_path"]
        logger.info(f"Mapped file_path to input_file: {kwargs['file_path']}")

    # Continue with existing logic...
```

**File**: `tools/macro_emission.py` (same fix)

### Fix 2: Update Tool Definitions (Alternative)

Change `file_path` to `input_file` in `tools/definitions.py` to match implementation.

**Recommendation**: Use Fix 1 (mapping) because:
- Less disruptive
- Maintains backward compatibility
- Executor already injects `file_path`

## Diagnostic Logging Added

### File: tools/micro_emission.py (line 53)

```python
# DIAGNOSTIC LOGGING
logger.info("=" * 50)
logger.info("[MicroEmission] FULL PARAMS DUMP:")
for k, v in kwargs.items():
    logger.info(f"  {k}: {v} (type: {type(v).__name__})")
logger.info("=" * 50)
```

### File: core/executor.py (lines 68-70, 83)

```python
logger.info(f"[Executor] Original arguments from LLM for {tool_name}: {arguments}")
logger.info(f"[Executor] Standardized arguments: {standardized_args}")
logger.info(f"[Executor] Auto-injected file_path: {file_path}")
```

## Testing Plan

1. Restart server: `.\scripts\restart_server.ps1`
2. Upload `micro_05_minimal.csv`
3. Say: "帮我计算这个大货车的排放"
4. Check logs for:
   - `[Executor] Original arguments from LLM`: What LLM passed
   - `[Executor] Auto-injected file_path`: Executor injection
   - `[MicroEmission] FULL PARAMS DUMP`: What tool received

## Next Steps

1. **Immediate**: Apply Fix 1 to both micro and macro emission tools
2. **Verify**: Run test and check diagnostic logs
3. **Clean up**: Remove old `skills/` directory or mark as deprecated
4. **Document**: Update architecture docs to clarify tool vs skill distinction
