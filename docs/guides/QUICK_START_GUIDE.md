# Quick Start Guide - Testing RAG and Download Features

## 1. Restart the Application

After the fixes, restart the emission agent application:

```bash
cd E:\Agent_MCP\Agent_MCP\emission_agent
python main.py
```

You should see in the logs:
```
Initialized 5 tools: ['query_emission_factors', 'calculate_micro_emission', 'calculate_macro_emission', 'analyze_file', 'query_knowledge']
```

## 2. Test RAG Knowledge Retrieval

Open the web interface and try these knowledge queries:

### Example 1: Emission Standards
```
什么是国六排放标准？
```

Expected behavior:
- System calls `query_knowledge` tool
- Returns answer with source references
- Shows citations from knowledge base

### Example 2: Regulations
```
国五和国六有什么区别？
```

### Example 3: Technical Concepts
```
机动车排放标准有哪些？
```

## 3. Test Download Button in History

### Step 1: Create a New Calculation
Upload a trajectory or road link file and perform a calculation.

### Step 2: Download the Result
Click the download button to verify it works.

### Step 3: View History
1. Reload the page (hard refresh: Ctrl+Shift+R)
2. Click on the session in the history list
3. Verify the download button appears in the historical message

## 4. Browser Cache

If you don't see the changes:
- **Windows**: Press `Ctrl + Shift + R`
- **Mac**: Press `Cmd + Shift + R`
- Or clear browser cache manually

## 5. Verify Tool Registration

Check the application logs for:
```
INFO: Registered tool: query_knowledge
INFO: Initialized 5 tools: [...]
```

## 6. Known Limitations

### Old Historical Sessions
Sessions created before 2026-02-05 won't have download buttons because they don't have the `file_id` field in their saved data. This is expected and cannot be fixed retroactively.

### New Sessions
All new sessions created after the fix will properly save `file_id` and show download buttons in history.

## 7. Troubleshooting

### RAG Not Working
If knowledge queries don't work:
1. Check logs for "Failed to register knowledge tool"
2. Verify dependencies are installed:
   ```bash
   pip list | grep -E "pyarrow|datasets|transformers"
   ```
3. Run the test script:
   ```bash
   python test_rag_integration.py
   ```

### Download Button Missing
If download button doesn't appear:
1. Hard refresh browser (Ctrl+Shift+R)
2. Check if it's an old session (created before fix)
3. Create a new calculation to test

### Dependencies Issues
If you see import errors:
```bash
pip install --upgrade pyarrow datasets transformers
```

## 8. Success Indicators

✅ **RAG Working**:
- Knowledge queries return answers with sources
- Logs show "query_knowledge" tool being called
- Citations appear in responses

✅ **Download Buttons Working**:
- Download button appears after calculations
- Download button persists in history (for new sessions)
- Files download successfully

✅ **System Healthy**:
- 5 tools registered (including query_knowledge)
- No import errors in logs
- All test cases pass

## 9. Example Session Flow

1. **Ask a knowledge question**:
   ```
   User: 什么是国六排放标准？
   Agent: [Calls query_knowledge tool]
   Agent: [Returns answer with sources]
   ```

2. **Upload and calculate**:
   ```
   User: [Uploads trajectory file]
   Agent: [Analyzes file]
   User: 计算排放
   Agent: [Calculates emissions]
   Agent: [Shows results with download button]
   ```

3. **View history**:
   ```
   User: [Reloads page]
   User: [Clicks on session in history]
   Result: Download button appears in historical message
   ```

## 10. Contact

If you encounter issues not covered here, check:
- `RAG_AND_HISTORY_FIXES.md` - Detailed technical documentation
- `test_rag_integration.py` - Automated test script
- Application logs - For error messages and debugging info
