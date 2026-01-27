# MCP: OCEL Server & Client

This folder contains the MCP (Model Context Protocol) server for OCEL 2.0 analysis and an interactive LLM client for querying the OCEL schema.

## Communication Protocol

The server supports **JSON-RPC 2.0** with two transport modes:

| Mode | Use Case | How it works |
|------|----------|--------------|
| **TCP** | Standalone client/server | Server listens on a port, clients connect via socket |
| **STDIO** | MCP host integration (VS Code, etc.) | Host spawns server as subprocess, communicates via stdin/stdout |

## Setup

Install dependencies:
```bash
pip install -r ../requirements.txt
```

The client estimates tokens using `tiktoken` before each query and shows the cost. Confirm or edit the message before sending (`-f` to auto-approve).

---

## Server

The server loads an OCEL file and exposes analysis tools via JSON-RPC 2.0.

### Mode 1: TCP (for standalone client)

The server listens on a TCP port and accepts connections from any client.

```bash
# Start TCP server on 127.0.0.1:9820 (default)
python -m mcp.server --ocel-path ./storage/github.ocel_v1.json

# Custom host/port
python -m mcp.server --ocel-path ./storage/my_log.json --host 0.0.0.0 --port 8000
```

Then connect with the client:
```bash
python -m mcp.client --host 127.0.0.1 --port 9820
```

### Mode 2: STDIO (for MCP host integration)

In STDIO mode, the server reads JSON-RPC requests from **stdin** and writes responses to **stdout**. This is used when an MCP host (like VSCode) spawns the server as a subprocess.

```bash
python -m mcp.server --mode stdio --ocel-path ./storage/github.ocel_v1.json
```

**Manual testing with STDIO** (for debugging):
```bash
# Start server in STDIO mode
python -m mcp.server --mode stdio --ocel-path ./storage/ocel.json

# Then type JSON-RPC requests directly (one per line):
{"jsonrpc": "2.0", "id": 1, "method": "initialize"}
{"jsonrpc": "2.0", "id": 2, "method": "ocel/info"}
{"jsonrpc": "2.0", "id": 3, "method": "tools/list"}
```

### Server Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--ocel-path PATH` | Path to OCEL JSON file | (required or `OCEL_FILE` env) |
| `--mode {tcp, stdio}` | Transport mode | `tcp` |
| `--host HOST` | TCP host to bind | `127.0.0.1` |
| `--port PORT` | TCP port to listen on | `9820` |
| `--debug` | Enable DEBUG logging | `false` |

**Environment variables:**
- `OCEL_FILE`: Path to OCEL JSON file (optional if `--ocel-path` provided)
- `LOG_LEVEL`: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
- `LOG_FILE`: Path to log file (default: logs/mcp_server.log)

See [server/.env.example](server/.env.example) for full configuration.

---

## Client

Interactive terminal CLI for asking questions about the OCEL schema using OpenAI or Gemini. The client connects to the MCP server **via TCP** to fetch OCEL metadata (object types, event types, counts, time range).

> **Note:** The client only works with TCP mode. For STDIO mode, use an MCP host like VSCode.

### Run
```bash
# Start server first (in one terminal)
python -m mcp.server --ocel-path ./storage/github.ocel_v1.json

# Run client (in another terminal)
python -m mcp.client --provider openai --model GPT-5.2

# Connect to custom server
python -m mcp.client --host 192.168.1.100 --port 8000

# Skip cost confirmation prompt
python -m mcp.client -f
```

### Client Arguments

| Argument | Description | Default |
|----------|-------------|---------|
| `--provider {openai, gemini}` | LLM provider | `openai` |
| `--model MODEL` | Model name | `GPT-5.2` |
| `--schema-path PATH` | Path to OCEL schema JSON | `shared/schemas/ocel_2_0.json` |
| `--host HOST` | MCP server host | `127.0.0.1` |
| `--port PORT` | MCP server port | `9820` |
| `-f, --force` | Skip cost confirmation | `false` |

**Environment variables:**
- `OPENAI_API_KEY`: Required for OpenAI provider
- `GEMINI_API_KEY`: Required for Gemini provider

See [client/.env.example](client/.env.example) for setup.
