# Emission Agent

Intelligent vehicle emission calculation system with modern Tool Use architecture, providing Web interface and API services.

## Project Features

- **AI-First Architecture**: Trust LLM intelligence, minimal rules, natural retry mechanism
- **Tool Use Architecture**: Modern LLM function calling with transparent parameter standardization
- **Smart File Caching**: File modification time detection for accurate cache invalidation
- **Smart Column Mapping**: LLM-powered understanding of arbitrary Excel column names
- **Local Model Support**: Support for locally fine-tuned Qwen3-4B models for cost reduction and data privacy
- **Web Interface**: Modern chat-based web UI with file upload, chart display, and session management
- **Fully Independent**: No dependency on MCP project, all core logic and data included
- **Multi-Model Support**: Support for Qwen/DeepSeek/local models with flexible configuration

## Architecture

### Core Components

```
emission_agent/
├── core/                    # Core architecture layer
│   ├── router.py           # UnifiedRouter - main entry point
│   ├── assembler.py        # Context assembly
│   ├── executor.py         # Tool execution with standardization
│   └── memory.py           # Three-layer memory management
├── tools/                   # Tool implementations
│   ├── emission_factors.py # Emission factor queries
│   ├── micro_emission.py   # Microscale emission calculations
│   ├── macro_emission.py   # Macroscale emission calculations
│   └── file_analyzer.py    # File analysis
├── calculators/            # Calculation engines
│   ├── emission_factors.py # EPA MOVES data queries
│   ├── micro.py           # VSP-based calculations
│   └── macro.py           # Fleet-based calculations
├── services/              # Service layer
│   ├── llm_client.py     # LLM client with tool use
│   └── standardizer.py   # Parameter standardization
├── api/                   # API layer
│   ├── routes.py         # FastAPI endpoints
│   └── session.py        # Session management
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

### Recent Improvements (Latest)

**AI-First Architecture Optimization** (2026-02-21)
- Removed vehicle guardrail (~130 lines): Let LLM handle vehicle grounding naturally
- Simplified synthesis prompt (76→15 lines): Reduce token usage, prevent hallucination
- Streamlined tool definitions: Save ~200 tokens per request
- Centralized fleet mix standardization: Remove duplicate code (~125 lines)
- **File caching fix**: Added mtime detection to prevent using stale cached analysis when files are overwritten
- Vehicle type confirmation: Python rule check before micro emission calculation
- PORT environment variable support: Flexible port configuration

Net result: -165 lines, faster responses, more reliable file handling.

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env` and fill in API keys:

```bash
cp .env.example .env
```

Edit `.env` file with at least:
```
QWEN_API_KEY=your-api-key-here
```

### 3. Start Web Service

```bash
python run_api.py
```

Service will start at http://localhost:8000 (or use PORT environment variable to customize)

```bash
# Use custom port
PORT=8001 python run_api.py
```

### 4. Access Web Interface

Open in browser: http://localhost:8000

Or use command line interface:

```bash
python main.py chat
```

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
   - Output: Link emission summary table + downloadable detailed Excel file

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
# Test new architecture
python test_new_architecture.py

# Test API integration
python test_api_integration.py
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

## Architecture Upgrade

This project uses a modern **Tool Use architecture** optimized for AI-first decision making. See detailed documentation:
- **[ARCHITECTURE.md](docs/ARCHITECTURE.md)** - Complete architecture documentation with workflow details
- **[AI-First Design Philosophy](docs/ARCHITECTURE.md#ai-first-philosophy)** - Why we trust LLM intelligence over rigid rules

Key architectural decisions:
- Removed complex guardrails, let LLM make natural decisions
- Minimal synthesis prompt (15 lines) for faster, more accurate responses
- File caching with mtime detection for reliable multi-file workflows
- Python rule checks only for critical business logic (e.g., vehicle type confirmation)

## License

MIT License

## Contact

For questions or issues, please open an issue on GitHub.
