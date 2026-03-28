# Emission Agent

Emission Agent is a research-oriented LLM + tool-use system for vehicle emission analysis. It combines a FastAPI backend, chat-style web UI, domain calculation tools, file-grounded workflows, knowledge/RAG retrieval, GIS result visualization, and an engineering evaluation harness in one repository.

## What This Repo Actually Does

In practical terms, this repository lets a user:

- ask emission-analysis questions in natural language through a web UI, CLI, or API
- retrieve MOVES-based emission-factor curves for specific vehicles, pollutants, and model years
- upload trajectory or road-link files and run micro/macro emission calculations
- query a knowledge base for emission-related methods, standards, and regulations
- view results as text, charts, tables, downloadable files, and GIS map payloads
- validate the current system with a regression suite and a small evaluation/smoke harness

## Project Status

- Current maturity: active research/engineering prototype with a working app surface, regression baseline, and usable evaluation harness
- Current stage: deployment-validated baseline stabilization for easier maintenance, collaboration, future experiments, and later open-source release
- Stable day-to-day surfaces: `python run_api.py`, `python main.py health`, `pytest`, and `python evaluation/run_smoke_suite.py`
- Intentionally deferred: deeper `core/router.py` extraction and broad historical-report cleanup

## Start Here

Read these first:

1. [ENGINEERING_STATUS.md](ENGINEERING_STATUS.md) for the current engineering state, docs map, and deferred areas
2. [CURRENT_BASELINE.md](CURRENT_BASELINE.md) for the current frozen milestone summary and recommended next workstreams
3. [RELEASE_READINESS.md](RELEASE_READINESS.md) for the current shareability/open-source sanity checklist
4. [RUNNING.md](RUNNING.md) for the current supported run paths and minimum validation commands
5. [evaluation/README.md](evaluation/README.md) for the minimal benchmark and reproducibility path
6. [examples/README.md](examples/README.md) for the smallest realistic workflows
7. [CONTRIBUTING.md](CONTRIBUTING.md) for practical contributor and maintainer guidance
8. [DEVELOPMENT.md](DEVELOPMENT.md) for maintainer navigation and safe checks
9. [ROUTER_REFACTOR_PREP.md](ROUTER_REFACTOR_PREP.md) only if you are planning future `core/router.py` or `api/routes.py` work

Historical phase reports now live under [docs/reports/phases/](docs/reports/phases/) and GIS optimization records under [docs/reports/gis/](docs/reports/gis/). They remain decision records, but they are background context rather than the current source of truth.

## Main Capabilities

- **AI-First Architecture**: Trust LLM intelligence, minimal rules, natural retry mechanism
- **Tool Use Architecture**: Modern LLM function calling with transparent parameter standardization
- **Emission-Factor Queries**: EPA MOVES speed-emission curves and key-point outputs
- **Micro and Macro Emission Calculation**: file-grounded workflows for trajectory and link-level data
- **Knowledge / RAG Retrieval**: emission-related standards, methods, and regulations through the active `query_knowledge` tool path
- **GIS Result Visualization**: macro-emission map payloads for link-level road-network exploration
- **Smart File Caching**: File modification-time detection for accurate cache invalidation
- **Web + API Surface**: chat-based web UI, session management, charts, tables, and downloads
- **Evaluation Harness**: normalization, file-grounding, end-to-end, and ablation runners
- **Multi-Model Support**: Qwen, DeepSeek, and local/OpenAI-compatible deployments

## Quickstart

### Choose Your Goal

| Goal | Command | Expected result |
|---|---|---|
| Try the app | `python run_api.py` | Web UI at `http://localhost:8000` and API docs at `http://localhost:8000/docs` |
| Validate local setup | `python main.py health` then `pytest` | Basic runtime health plus current regression baseline |
| Run minimal evaluation | `python evaluation/run_smoke_suite.py` | Fresh run under `evaluation/logs/` with `smoke_summary.json` |

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

For normal chat usage, set at least one provider key in `.env`, for example:

```bash
QWEN_API_KEY=your-api-key-here
```

### 3. Start The Canonical App Path

```bash
python run_api.py
```

Optional custom port:

```bash
PORT=8001 python run_api.py
```

### 4. Validate Or Reproduce

Smallest local validation:

```bash
python main.py health
pytest
```

Smallest evaluation path:

```bash
python evaluation/run_smoke_suite.py
```

Use [RUNNING.md](RUNNING.md) for run/smoke details and [evaluation/README.md](evaluation/README.md) for benchmark details.

### Minimum Successful Workflow

If you want the shortest realistic path from clone to confidence:

1. Copy `.env.example` to `.env`.
2. Run `python main.py health`.
3. Run `pytest`.
4. If you have a real provider key configured, run `python run_api.py` and open `http://localhost:8000`.
5. If you want benchmark-style validation, run `python evaluation/run_smoke_suite.py`.

Use [RELEASE_READINESS.md](RELEASE_READINESS.md) for the current stable-vs-evolving boundary before sharing the repo externally.

## Examples And Contribution

- [examples/README.md](examples/README.md) shows the two smallest realistic workflows:
  - boot the app and try a real query
  - run the smallest meaningful evaluation
- [CONTRIBUTING.md](CONTRIBUTING.md) explains how to work safely in the current consolidation stage

## Architecture At A Glance

### Core Components

```
emission_agent/
├── core/                    # Core architecture layer
│   ├── router.py           # UnifiedRouter - main entry point
│   ├── assembler.py        # Context assembly
│   ├── executor.py         # Tool execution with standardization
│   ├── memory.py           # Three-layer memory management
│   ├── router_memory_utils.py
│   ├── router_payload_utils.py
│   ├── router_render_utils.py
│   └── router_synthesis_utils.py
├── tools/                   # Tool implementations
│   ├── emission_factors.py # Emission factor queries
│   ├── micro_emission.py   # Microscale emission calculations
│   ├── macro_emission.py   # Macroscale emission calculations
│   ├── file_analyzer.py    # File analysis / task detection
│   └── knowledge.py        # Knowledge / RAG retrieval
├── calculators/            # Calculation engines
│   ├── emission_factors.py # EPA MOVES data queries
│   ├── micro_emission.py   # VSP-based calculations
│   ├── macro_emission.py   # Fleet/link-based calculations
│   └── vsp.py             # VSP / opMode support logic
├── services/              # Service layer
│   ├── llm_client.py     # LLM client with tool use
│   └── standardizer.py   # Parameter standardization
├── api/                   # API layer
│   ├── main.py           # FastAPI app entrypoint
│   ├── routes.py         # Chat/file/download/auth/session endpoints
│   ├── session.py        # Session management
│   ├── auth.py           # JWT auth service
│   └── database.py       # User/session persistence
└── web/                   # Frontend
    ├── index.html        # Web UI
    └── app.js            # Frontend logic
```

### Design Principles

1. **AI-First Philosophy**: Trust LLM to make intelligent decisions with good information, avoid rigid rules
2. **Tool Use Mode**: Uses OpenAI function calling standard for tool execution
3. **Transparent Standardization**: Parameters are standardized in executor layer, invisible to LLM
4. **Three-Layer Memory**: Working memory (5 turns) + Fact memory (structured) + Compressed memory
5. **Smart File Caching**: File mtime detection prevents stale cache when files are overwritten
6. **Clean Separation**: Router → Assembler → LLM → Executor → Tools

### Recent Repository Progress

Recent consolidation work already completed in the repository:

- route/helper extraction and contract protection for `api/routes.py`
- four conservative helper extractions from `core/router.py`
- mocked async boundary protection around `_synthesize_results(...)`
- clearer run/eval/developer navigation at the repository root
- cleaner smoke/evaluation output from the micro Excel path

## Usage Examples

### Web Interface

1. **Emission Factor Query**
   - Input: "Query CO2 emission factors for 2020 passenger cars"
   - Output: Speed-emission factor curve chart + key speed point table

2. **Microscale Emission Calculation**
   - Upload trajectory data Excel file (with time, speed, acceleration, grade columns)
   - Input: "Calculate emissions for this vehicle"
   - System will ask for vehicle type, then auto-calculate
   - Output: Emission calculation results table + downloadable detailed Excel file

3. **Macroscale Emission Calculation**
   - Upload road link data Excel file (with link length, traffic flow, average speed, fleet composition)
   - Input: "Calculate emissions for these road links"
   - Output: Link emission summary table + downloadable detailed Excel file + optional GIS map payload

4. **Knowledge / RAG Query**
   - Input: "What does MOVES mean by opMode 300?" or "What are the main pollutants in this workflow?"
   - Output: knowledge-grounded answer with source-backed retrieval content when available

### Representative End-to-End Workflow

One realistic workflow that exercises the current RAG + calculation + GIS surface looks like this:

1. Start the app with `python run_api.py` and open `http://localhost:8000`
2. Ask a knowledge question such as:
   - `"What does MOVES opMode 300 represent, and why is it used in macro emission calculations?"`
3. Upload a road-link Excel file and ask:
   - `"Calculate CO2 and NOx emissions for these road links with model year 2025"`
4. The system can then:
   - use `query_knowledge` to ground the method explanation
   - use `analyze_file` to infer the uploaded file structure
   - use `calculate_macro_emission` to compute link-level emissions
5. The response surface can include:
   - a natural-language explanation
   - link-level table previews
   - downloadable result files
   - GIS map payloads for road-network visualization when map-capable macro results are produced

### Command Line

```bash
# Interactive chat
python main.py chat

# Health check
python main.py health

# List available tools
python main.py tools-list
```

## Core Tools

### 1. query_emission_factors - Emission Factor Query
Query emission factor speed curves from EPA MOVES database

**Required Parameters**:
- `vehicle_type`: Vehicle type (13 MOVES standard types supported)
- `pollutant`: Pollutant (CO2, NOx, PM2.5, etc.)
- `model_year`: Year (1995-2025)

**Optional Parameters**:
- `season`: Season (default: summer)
- `road_type`: Road type (default: freeway)

**Output**: Speed-emission factor curve chart + key speed point data table

### 2. calculate_micro_emission - Microscale Emission Calculation
Calculate emissions based on second-by-second trajectory data using VSP methodology

**Required Parameters**:
- `vehicle_type`: Vehicle type
- `model_year`: Model year
- `pollutants`: List of pollutants to calculate
- `file_path` or trajectory data

**Output**: Detailed emission results + downloadable Excel file

### 3. calculate_macro_emission - Macroscale Emission Calculation
Calculate emissions for road network using fleet composition and traffic data

**Required Parameters**:
- `model_year`: Model year
- `pollutants`: List of pollutants to calculate
- `file_path` or road link data

**Output**: Link-level emission summary + downloadable Excel file

### 4. analyze_file - File Analysis
Detect uploaded file structure and infer likely task type before tool execution.

**Typical output**:
- inferred task type such as `micro_emission` or `macro_emission`
- column mapping hints
- file preview metadata used by the API/web layer

### 5. query_knowledge - Knowledge / RAG Retrieval
Query the project knowledge base for emission-related methods, standards, and regulations.

**Typical parameters**:
- `query`
- `top_k` (optional)
- `expectation` (optional)

**Output**: knowledge-grounded answer text plus retrieval/source metadata when available

## API Endpoints

### POST /api/chat
Main chat endpoint for conversational interaction

**Request**:
```json
{
  "message": "Query CO2 emission factors for 2020 passenger cars",
  "session_id": "optional-session-id",
  "file": "optional-file-upload"
}
```

**Response**:
```json
{
  "reply": "text response",
  "session_id": "session-id",
  "success": true,
  "data_type": "chart",
  "chart_data": {...},
  "table_data": null,
  "file_id": null
}
```

### GET /api/sessions
List all chat sessions

### GET /api/sessions/{session_id}/history
Get chat history for a session

### POST /api/file/preview
Preview uploaded Excel file

### GET /api/download/{filename}
Download calculation result file

## Configuration

### Model Configuration (config.py)

```python
# Agent LLM (main reasoning)
agent_llm = LLMAssignment(
    provider="qwen",
    model="qwen-plus"
)

# Synthesis LLM (result formatting)
synthesis_llm = LLMAssignment(
    provider="qwen",
    model="qwen-turbo"
)
```

### Standardizer Configuration

Choose between cloud API or local model:

```python
# Cloud API (default)
standardizer_mode = "api"

# Local model (requires vLLM server)
standardizer_mode = "local"
local_standardizer_url = "http://localhost:8000/v1"
```

## Local Model Deployment

See `LOCAL_STANDARDIZER_MODEL/` directory for:
- Training data preparation
- LoRA fine-tuning scripts
- vLLM deployment guide
- Integration instructions

## Development

For the current maintainer-facing status and document map, start with [ENGINEERING_STATUS.md](ENGINEERING_STATUS.md) and [DEVELOPMENT.md](DEVELOPMENT.md).

### Project Structure

- `core/` - Core architecture (router, executor, assembler, memory)
- `tools/` - Tool implementations
- `calculators/` - Calculation engines
- `services/` - Service layer (LLM, standardizer)
- `api/` - API layer (routes, session management)
- `web/` - Frontend (HTML, JavaScript)
- `config/` - Configuration files
- `data/` - Data storage (sessions, learning cases)

### Testing

```bash
# Unit / regression suite
pytest

# Lightweight local runtime validation
python main.py health

# Knowledge asset / registration smoke
python scripts/utils/test_rag_integration.py

# Specialized integration scripts (require configured runtime / live LLM)
python scripts/utils/test_new_architecture.py
python scripts/utils/test_api_integration.py

# Evaluation smoke suite
python evaluation/run_smoke_suite.py
```

### Adding New Tools

1. Create tool class in `tools/` inheriting from `BaseTool`
2. Implement `execute()` method returning `ToolResult`
3. Add tool definition to `tools/definitions.py`
4. Register tool in `tools/registry.py`

Example:
```python
from tools.base import BaseTool, ToolResult

class MyTool(BaseTool):
    async def execute(self, **kwargs) -> ToolResult:
        # Tool logic here
        return ToolResult(
            success=True,
            data=result_data,
            summary="Natural language summary"
        )
```

## Architecture Reference

For the current high-level design, see:

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the end-to-end architecture and workflow
- [ENGINEERING_STATUS.md](ENGINEERING_STATUS.md) for the current cleanup status, extracted seams, and deferred areas

## License

MIT License

## Contact

For questions or issues, please open an issue on GitHub.
