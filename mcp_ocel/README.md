# MCP OCEL Server & Client

Server and client for OCEL 2.0 process mining analysis via MCP (Model Context Protocol).

## Quick Start

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment variables

Create `.env` files or export these variables:

**Server:**
```bash
export OCEL_FILE=./storage/your_log.json  # Path to OCEL 2.0 JSON file
export OCEL_DEBUG=false                    # Enable debug logging (optional)
```

**Client:**
```bash
export OPENAI_API_KEY=sk-...   # For OpenAI provider
# or
export GEMINI_API_KEY=...      # For Gemini provider
```

### 3. Start the server (Terminal 1)

```bash
python -m mcp_ocel.server --ocel-path ./storage/your_log.json
```

The server will start on `http://127.0.0.1:8000/mcp`.

**Server options:**

| Argument | Description | Default |
|----------|-------------|---------|
| `--ocel-path PATH` | Path to OCEL JSON file | `OCEL_FILE` env var |
| `--host HOST` | Host to bind | `127.0.0.1` |
| `--port PORT` | Port to listen on | `8000` |
| `--transport {streamable-http,sse,stdio}` | Transport mode | `streamable-http` |
| `--debug` | Enable debug logging | `false` |

### 4. Start the client (Terminal 2)

```bash
python -m mcp_ocel.client --url http://127.0.0.1:8000/mcp
```

**Client options:**

| Argument | Description | Default |
|----------|-------------|---------|
| `--url URL` | MCP server URL | `http://127.0.0.1:8000/mcp` |
| `--provider {openai,gemini}` | LLM provider | `openai` |
| `--model MODEL` | Model name | `gpt-4o` |
| `-f, --force` | Skip cost confirmation | `false` |

## Configuration Priorities

### Server Configuration
The server follows this priority order for configuration (highest to lowest):

1. **Command-line arguments** (highest priority)
2. **Environment variables**
3. **Default values**

**OCEL File Path:**
- CLI: `--ocel-path PATH`
- Env: `OCEL_FILE`
- Default: `./log.json`

**Debug Logging:**
- CLI: `--debug` (sets `OCEL_DEBUG=true`)
- Env: `OCEL_DEBUG` (values: `true`/`false`)
- Default: `false`

**Host, Port, Transport:** Only configurable via CLI arguments.

### Client Configuration
The client has different priority handling:

**LLM Provider API Keys:**
- Only from environment variables (no CLI override)
- `OPENAI_API_KEY` for OpenAI provider
- `GEMINI_API_KEY` for Gemini provider

**Other Settings (Provider, Model, URL, Force):**
- Only from command-line arguments (no environment variable fallbacks)
- Use defaults if not specified

## Available Tools

The server exposes these MCP tools for process mining analysis:

| Tool | Description |
|------|-------------|
| `trace_object_lifecycle` | Trace all events for a specific object |
| `query_events_by_timerange` | Query events within a time range |
| `get_statistics_by_object_type` | Get object type statistics |
| `detect_anomalies` | Detect orphaned objects and broken references |
| `find_orphaned_objects` | Find objects without events |
| `search_ocel` | Hybrid semantic search over OCEL data |

## Resources

| URI | Description |
|-----|-------------|
| `ocel://info` | OCEL file metadata (types, counts, time range) |
| `ocel://schema/{section}` | Schema sections (eventTypes, objectTypes, etc.) |
