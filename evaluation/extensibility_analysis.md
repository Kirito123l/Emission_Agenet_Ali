# Tool Extensibility Analysis

## Before Declarative ToolContract

Adding a new tool required coordinated edits in multiple runtime surfaces:

1. Create `tools/xxx.py` for the tool implementation.
2. Modify `tools/definitions.py` to add the OpenAI function-calling JSON schema.
3. Modify `tools/registry.py` `init_tools()` to register the tool instance.
4. Modify `core/tool_dependencies.py` `TOOL_GRAPH` to declare prerequisites and provided result tokens.
5. Modify `core/readiness.py` action-catalog construction to add readiness metadata.
6. Modify `core/router.py` continuation-keyword mapping to expose follow-up tool hints.

Observed change surface: 6 files.

## After Declarative ToolContract

Adding a new tool now requires:

1. Create `tools/xxx.py` for the tool implementation.
2. Add one contract entry under `config/tool_contracts.yaml`.
3. Modify `tools/registry.py` `init_tools()` to register the tool instance.

Observed change surface: 1 Python file plus 1 YAML edit.

## Current Runtime Generation Path

- `config/tool_contracts.yaml` is the single metadata source for:
  - OpenAI tool definitions
  - tool dependency graph
  - readiness action catalog entries
  - continuation keywords
- `tools/contract_loader.py` materializes these runtime artifacts.
- `tools/definitions.py`, `core/tool_dependencies.py`, `core/readiness.py`, and `core/router.py` now consume generated metadata instead of maintaining separate hand-synchronized copies.

## Remaining Manual Step

Tool instance registration remains in `tools/registry.py`. Tool implementation plus registry wiring are still required even though metadata synchronization has been consolidated into the YAML contract.
