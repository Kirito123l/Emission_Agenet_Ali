# Response Truncation Issue - Diagnosis and Fix

## Issue Summary

User reported that agent responses were being cut off mid-sentence during emission calculations. The conversation log showed:

```
👉 我来快速检查前5行数据，确认数值合理性：


```

The response ended abruptly with empty lines, leaving the user without a complete answer.

## Root Cause Analysis

### Problem 1: Token Limit Too Low (PRIMARY ISSUE)

**Location**: `config.py:14`

```python
max_tokens: int = 2000  # Too restrictive
```

**Impact**:
- The LLM synthesis phase requires significant tokens to:
  1. Process tool execution results
  2. Format data into natural language
  3. Provide helpful explanations and next steps
- With only 2000 tokens, complex responses get truncated
- The `finish_reason` would be "length" instead of "stop"

**Evidence from logs**:
```
Processing message: 大货车，2021年的...
Assembled context: ~1528 tokens, 6 messages
Executing tool: calculate_micro_emission
Executing tool: analyze_file
```

Two tools were executed, but the synthesis response was incomplete.

### Problem 2: Insufficient Logging

**Location**: `core/router.py:273-278`

The synthesis method didn't log:
- Whether truncation occurred (`finish_reason`)
- Response length
- Tool results summary

This made debugging difficult.

## Fixes Applied

### Fix 1: Increased Token Limit

**File**: `config.py`

```python
# Before
max_tokens: int = 2000

# After
max_tokens: int = 4000  # Increased from 2000 to allow longer synthesis responses
```

**Rationale**:
- 4000 tokens provides enough headroom for:
  - Multi-tool execution results
  - Detailed explanations
  - Error messages and suggestions
  - Natural language formatting
- Still reasonable for API costs
- Can be further increased if needed

### Fix 2: Enhanced Logging

**File**: `core/router.py`

Added logging to track:
```python
logger.info(f"Synthesizing results from {len(tool_results)} tool calls")
logger.debug(f"Tool results summary: {results_summary[:200]}...")
logger.info(f"Synthesis complete. Response length: {len(synthesis_response.content)} chars, finish_reason: {synthesis_response.finish_reason}")

if synthesis_response.finish_reason == "length":
    logger.warning("⚠️ Synthesis response was truncated due to max_tokens limit!")
```

**Benefits**:
- Immediate visibility when truncation occurs
- Helps diagnose future issues
- Tracks response quality metrics

## Testing Recommendations

1. **Restart the server** to apply config changes:
   ```powershell
   .\scripts\restart_server.ps1
   ```

2. **Re-test the same scenario**:
   - Upload the same CSV file
   - Specify "大货车，2021年的"
   - Verify complete response

3. **Monitor logs** for:
   - "Synthesis complete" messages
   - Response length
   - Any "truncated" warnings

4. **Check for**:
   - Complete explanations
   - No mid-sentence cutoffs
   - Proper data presentation

## Additional Observations

### Tool Execution Status

The logs show both tools were executed:
```
Executing tool: calculate_micro_emission
Executing tool: analyze_file
```

However, the agent mentioned "之前调用 calculate_micro_emission 失败" (previous call failed). This suggests:
- The micro emission calculation may have encountered a data validation error
- The error was properly caught and reported
- But the synthesis was cut off before explaining the issue fully

### Potential Follow-up Issues

If truncation persists after this fix, investigate:
1. **Data validation errors** in `calculate_micro_emission`
2. **File format issues** with the uploaded CSV
3. **Column mapping failures** in the intelligent mapper
4. **Whether 4000 tokens is still insufficient** for very complex scenarios

## Configuration Options

If 4000 tokens is still not enough, you can:

1. **Increase further** in `config.py`:
   ```python
   max_tokens: int = 6000  # or 8000
   ```

2. **Set per-assignment** for synthesis specifically:
   ```python
   self.synthesis_llm = LLMAssignment(
       provider=os.getenv("SYNTHESIS_LLM_PROVIDER", "qwen"),
       model=os.getenv("SYNTHESIS_LLM_MODEL", "qwen-plus"),
       max_tokens=6000  # Higher limit for synthesis
   )
   ```

3. **Use environment variable**:
   ```env
   AGENT_LLM_MAX_TOKENS=4000
   ```

## Summary

- **Root cause**: 2000 token limit was too restrictive for multi-tool synthesis
- **Fix**: Increased to 4000 tokens + added logging
- **Impact**: Should resolve response truncation issues
- **Next steps**: Restart server and re-test

---

**Date**: 2026-02-04
**Fixed by**: Claude Code
**Status**: ✅ Fixed, pending verification
