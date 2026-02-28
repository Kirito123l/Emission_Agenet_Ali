# Developer Documentation

## Architecture Overview

The Emission Agent uses a modern Tool Use architecture based on OpenAI's function calling standard. This document provides detailed information for developers working on the codebase.

## Core Architecture

### 1. UnifiedRouter (`core/router.py`)

The main entry point for all user interactions.

**Responsibilities**:
- Receives user messages
- Manages conversation flow
- Coordinates between assembler, LLM, and executor
- Returns structured responses

**Key Methods**:
```python
async def chat(
    user_message: str,
    file_path: Optional[str] = None
) -> RouterResponse:
    """
    Main chat method

    Flow:
    1. Analyze file (if provided)
    2. Assemble context (system prompt, tools, messages)
    3. Call LLM with tools
    4. Execute tool calls (if any)
    5. Synthesize results
    6. Update memory
    7. Return RouterResponse
    """
```

**RouterResponse Structure**:
```python
@dataclass
class RouterResponse:
    text: str                      # Natural language response
    chart_data: Optional[Dict]     # Chart data for frontend
    table_data: Optional[Dict]     # Table data for frontend
    download_file: Optional[str]   # Path to downloadable file
```

### 2. ContextAssembler (`core/assembler.py`)

Assembles context for LLM calls.

**Responsibilities**:
- Loads system prompts from YAML
- Retrieves tool definitions
- Formats conversation history
- Adds file context if needed

**Key Methods**:
```python
def assemble(
    user_message: str,
    memory: MemoryManager,
    file_context: Optional[Dict] = None
) -> AssembledContext:
    """
    Assembles complete context for LLM

    Returns:
    - system_prompt: System instructions
    - tools: Tool definitions (OpenAI format)
    - messages: Conversation history
    """
```

### 3. ToolExecutor (`core/executor.py`)

Executes tool calls with transparent standardization.

**Responsibilities**:
- Retrieves tools from registry
- Standardizes parameters (transparent to LLM)
- Executes tools
- Formats results

**Key Methods**:
```python
async def execute(
    tool_name: str,
    arguments: Dict[str, Any],
    file_path: str = None
) -> Dict:
    """
    Execute a tool call

    Flow:
    1. Get tool from registry
    2. Standardize parameters (vehicle_type, pollutant)
    3. Validate parameters
    4. Execute tool
    5. Format result
    """
```

**Standardization Process**:
```python
# LLM says: "小汽车"
# Executor standardizes to: "Passenger Car"
# Tool receives: "Passenger Car"
# LLM never sees the standardization
```

### 4. MemoryManager (`core/memory.py`)

Manages three-layer memory system.

**Memory Layers**:
1. **Working Memory**: Recent conversation turns (last 5-10 turns)
2. **Fact Memory**: Extracted facts (vehicle type, model year, etc.)
3. **Compressed Memory**: Summarized older conversations

**Key Methods**:
```python
def update(
    user_message: str,
    assistant_response: str,
    tool_calls: Optional[List[Dict]] = None,
    file_path: Optional[str] = None
):
    """
    Update memory after each turn

    - Adds to working memory
    - Extracts facts
    - Compresses if needed
    """

def get_context_messages(self) -> List[Dict]:
    """
    Get messages for LLM context

    Returns:
    - Compressed summary (if exists)
    - Fact memory
    - Working memory
    """
```

## Tool System

### Tool Structure

All tools inherit from `BaseTool` and return `ToolResult`:

```python
from tools.base import BaseTool, ToolResult

class MyTool(BaseTool):
    async def execute(self, **kwargs) -> ToolResult:
        try:
            # Tool logic here
            result_data = do_calculation(**kwargs)

            return ToolResult(
                success=True,
                data=result_data,
                summary="Natural language summary of what was done",
                error=None
            )
        except Exception as e:
            return ToolResult(
                success=False,
                data=None,
                summary=None,
                error=str(e)
            )
```

### Tool Registration

Tools are registered in `tools/registry.py`:

```python
def init_tools():
    """Initialize and register all tools"""
    from tools.emission_factors import EmissionFactorsTool
    register_tool("query_emission_factors", EmissionFactorsTool())

    from tools.micro_emission import MicroEmissionTool
    register_tool("calculate_micro_emission", MicroEmissionTool())

    # ... more tools
```

### Tool Definitions

Tool definitions follow OpenAI function calling format in `tools/definitions.py`:

```python
TOOL_DEFINITIONS = [
    {
        "type": "function",
        "function": {
            "name": "query_emission_factors",
            "description": "Query emission factor speed curves from EPA MOVES database",
            "parameters": {
                "type": "object",
                "properties": {
                    "vehicle_type": {
                        "type": "string",
                        "description": "Vehicle type (e.g., Passenger Car, Light Truck)"
                    },
                    "pollutant": {
                        "type": "string",
                        "description": "Pollutant name (e.g., CO2, NOx, PM2.5)"
                    },
                    "model_year": {
                        "type": "integer",
                        "description": "Model year (1995-2025)"
                    }
                },
                "required": ["vehicle_type", "pollutant", "model_year"]
            }
        }
    }
]
```

## Service Layer

### LLM Client (`services/llm_client.py`)

Handles LLM API calls with tool use support.

**Key Features**:
- Multi-provider support (Qwen, DeepSeek, local models)
- Tool use (function calling)
- Streaming support
- Error handling and retries

**Usage**:
```python
from services.llm_client import LLMClient

client = LLMClient(assignment=config.agent_llm)

response = await client.chat_with_tools(
    messages=[...],
    tools=[...],
    system="System prompt"
)

# Response includes:
# - content: Text response
# - tool_calls: List of tool calls (if any)
```

### Standardizer (`services/standardizer.py`)

Standardizes vehicle types and pollutants.

**Modes**:
1. **API Mode**: Uses cloud LLM for standardization
2. **Local Mode**: Uses locally deployed fine-tuned model

**Usage**:
```python
from services.standardizer import get_standardizer

standardizer = get_standardizer()

# Standardize vehicle type
result = standardizer.standardize_vehicle("小汽车")
# Returns: "Passenger Car"

# Standardize pollutant
result = standardizer.standardize_pollutant("二氧化碳")
# Returns: "CO2"
```

## API Layer

### Session Management (`api/session.py`)

Manages user sessions with JSON persistence.

**Session Structure**:
```python
class Session:
    session_id: str
    title: str
    created_at: str
    updated_at: str
    message_count: int
    last_result_file: Optional[str]
    _router: Optional[UnifiedRouter]
    _history: List[Dict]
```

**Key Methods**:
```python
async def chat(
    message: str,
    file_path: Optional[str] = None
) -> Dict:
    """
    Chat with router and return structured response

    Returns:
    {
        "text": "...",
        "chart_data": {...},
        "table_data": {...},
        "download_file": "..."
    }
    """

def save_turn(
    user_input: str,
    assistant_response: str,
    chart_data: Optional[Dict] = None,
    table_data: Optional[Dict] = None,
    data_type: Optional[str] = None
):
    """Save conversation turn to history"""
```

### API Routes (`api/routes.py`)

FastAPI endpoints for web interface.

**Main Endpoints**:

1. **POST /api/chat** - Main chat endpoint
   ```python
   @router.post("/chat", response_model=ChatResponse)
   async def chat(
       message: str = Form(...),
       session_id: Optional[str] = Form(None),
       file: Optional[UploadFile] = File(None)
   ):
       # Get or create session
       session = session_manager.get_or_create_session(session_id)

       # Call router
       result = await session.chat(message, input_file_path)

       # Format response
       return ChatResponse(
           reply=result["text"],
           chart_data=result["chart_data"],
           table_data=result["table_data"],
           ...
       )
   ```

2. **GET /api/sessions** - List sessions
3. **GET /api/sessions/{id}/history** - Get session history
4. **POST /api/file/preview** - Preview uploaded file
5. **GET /api/download/{filename}** - Download result file

## Calculator Layer

### Emission Factor Calculator (`calculators/emission_factors.py`)

Queries EPA MOVES emission factor database.

**Data Structure**:
```
skills/emission_factors/data/emission_matrix/
├── Passenger_Car/
│   ├── 2020/
│   │   ├── CO2_summer_freeway.json
│   │   ├── NOx_summer_freeway.json
│   │   └── ...
│   └── ...
└── ...
```

**Query Method**:
```python
def query(
    vehicle_type: str,
    pollutant: str,
    model_year: int,
    season: str = "summer",
    road_type: str = "freeway",
    return_curve: bool = True
) -> Dict:
    """
    Query emission factors

    Returns:
    {
        "status": "success",
        "data": {
            "speed_curve": [...],
            "unit": "g/mile",
            "data_source": "EPA MOVES",
            ...
        }
    }
    """
```

### Micro Emission Calculator (`calculators/micro.py`)

Calculates emissions using VSP (Vehicle Specific Power) methodology.

**Input**: Second-by-second trajectory data
**Output**: Detailed emission results

**Key Method**:
```python
async def calculate(
    trajectory_data: List[Dict],
    vehicle_type: str,
    model_year: int,
    pollutants: List[str],
    ...
) -> Dict:
    """
    Calculate microscale emissions

    Flow:
    1. Calculate VSP for each second
    2. Query emission factors for each VSP bin
    3. Calculate emissions
    4. Aggregate results
    """
```

### Macro Emission Calculator (`calculators/macro.py`)

Calculates emissions for road networks using fleet composition.

**Input**: Road link data with traffic flow and fleet composition
**Output**: Link-level emission summary

**Key Method**:
```python
async def calculate(
    links_data: List[Dict],
    model_year: int,
    pollutants: List[str],
    ...
) -> Dict:
    """
    Calculate macroscale emissions

    Flow:
    1. For each link:
       a. For each vehicle type in fleet:
          - Query emission factors
          - Calculate emissions
       b. Aggregate by pollutant
    2. Sum across all links
    """
```

## Configuration

### Config Structure (`config.py`)

```python
@dataclass
class Config:
    # LLM assignments
    agent_llm: LLMAssignment
    synthesis_llm: LLMAssignment

    # Providers
    providers: Dict[str, ProviderConfig]

    # Standardizer
    standardizer_mode: str  # "api" or "local"
    local_standardizer_url: Optional[str]

    # Paths
    data_dir: Path
    outputs_dir: Path

    # Memory settings
    max_working_memory_turns: int
    compression_threshold: int
```

### Prompt Configuration (`config/prompts/core.yaml`)

```yaml
system:
  base: |
    You are an intelligent emission calculation assistant...

  tool_use_instructions: |
    When you need to perform calculations or query data, use the available tools...

synthesis:
  base: |
    Synthesize the tool results into a natural language response...
```

## Testing

### Unit Tests

Test individual components:

```python
# Test tool execution
async def test_emission_factors_tool():
    tool = EmissionFactorsTool()
    result = await tool.execute(
        vehicle_type="Passenger Car",
        pollutant="CO2",
        model_year=2020
    )
    assert result.success
    assert result.data is not None
```

### Integration Tests

Test complete flows:

```python
# Test router flow
async def test_router_chat():
    router = UnifiedRouter(session_id="test")
    response = await router.chat(
        user_message="Query CO2 emission factors for 2020 passenger cars"
    )
    assert response.text
    assert response.chart_data
```

### API Tests

Test API endpoints:

```python
# Test chat endpoint
async def test_chat_endpoint():
    session = Session(session_id="test")
    result = await session.chat(
        message="Query emission factors",
        file_path=None
    )
    assert result["text"]
```

## Common Development Tasks

### Adding a New Tool

1. **Create tool class** (`tools/my_tool.py`):
   ```python
   from tools.base import BaseTool, ToolResult

   class MyTool(BaseTool):
       async def execute(self, **kwargs) -> ToolResult:
           # Implementation
           return ToolResult(success=True, data=result)
   ```

2. **Add tool definition** (`tools/definitions.py`):
   ```python
   {
       "type": "function",
       "function": {
           "name": "my_tool",
           "description": "...",
           "parameters": {...}
       }
   }
   ```

3. **Register tool** (`tools/registry.py`):
   ```python
   from tools.my_tool import MyTool
   register_tool("my_tool", MyTool())
   ```

### Adding a New Calculator

1. **Create calculator** (`calculators/my_calculator.py`):
   ```python
   class MyCalculator:
       def calculate(self, **kwargs):
           # Implementation
           return result
   ```

2. **Use in tool**:
   ```python
   from calculators.my_calculator import MyCalculator

   class MyTool(BaseTool):
       def __init__(self):
           self.calculator = MyCalculator()

       async def execute(self, **kwargs):
           result = self.calculator.calculate(**kwargs)
           return ToolResult(success=True, data=result)
   ```

### Modifying Prompts

Edit `config/prompts/core.yaml`:

```yaml
system:
  base: |
    Your updated system prompt...

  tool_use_instructions: |
    Updated tool use instructions...
```

Prompts are loaded at runtime, so no code changes needed.

### Adding Memory Features

Extend `MemoryManager` in `core/memory.py`:

```python
class MemoryManager:
    def extract_custom_fact(self, message: str):
        # Custom fact extraction logic
        pass

    def get_custom_context(self):
        # Custom context retrieval
        pass
```

## Debugging

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Common Issues

1. **Tool not found**
   - Check tool is registered in `tools/registry.py`
   - Verify `init_tools()` is called

2. **Standardization fails**
   - Check standardizer mode in config
   - Verify local model is running (if using local mode)
   - Check mapping tables in `config/unified_mappings.yaml`

3. **LLM doesn't call tools**
   - Check tool definitions are correct
   - Verify system prompt includes tool use instructions
   - Check LLM model supports function calling

4. **Memory issues**
   - Check memory limits in config
   - Verify compression is working
   - Monitor memory usage

## Performance Optimization

### Caching

- Tool results can be cached for repeated queries
- Standardization results are cached per session
- LLM responses can be cached for identical inputs

### Async Operations

- All I/O operations use async/await
- Multiple tool calls can run in parallel
- File operations are non-blocking

### Memory Management

- Working memory is limited to recent turns
- Old conversations are compressed
- Facts are extracted to reduce context size

## Security Considerations

### Input Validation

- All file uploads are validated
- Excel files are scanned for malicious content
- User inputs are sanitized

### API Security

- Session IDs are randomly generated
- File downloads are restricted to outputs directory
- Path traversal attacks are prevented

### Data Privacy

- Local model option for sensitive data
- Session data is stored locally
- No data sent to external services (except LLM APIs)

## Deployment

### Production Checklist

- [ ] Set production API keys in `.env`
- [ ] Configure appropriate LLM models
- [ ] Set up logging and monitoring
- [ ] Configure file upload limits
- [ ] Set up backup for session data
- [ ] Configure CORS for web interface
- [ ] Set up SSL/TLS for API
- [ ] Configure rate limiting

### Docker Deployment

```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

CMD ["python", "run_api.py"]
```

### Environment Variables

```bash
# Required
QWEN_API_KEY=your-key

# Optional
DEEPSEEK_API_KEY=your-key
HTTP_PROXY=http://proxy:port
STANDARDIZER_MODE=api
LOCAL_STANDARDIZER_URL=http://localhost:8000/v1
```

## Contributing

### Code Style

- Follow PEP 8
- Use type hints
- Write docstrings for public methods
- Keep functions focused and small

### Testing

- Write tests for new features
- Maintain test coverage above 80%
- Run tests before committing

### Documentation

- Update README for user-facing changes
- Update this doc for architecture changes
- Add inline comments for complex logic

## Resources

- [OpenAI Function Calling](https://platform.openai.com/docs/guides/function-calling)
- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [EPA MOVES Model](https://www.epa.gov/moves)
- [VSP Methodology](https://www.epa.gov/moves/vsp-vehicle-specific-power)
