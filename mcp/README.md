# MCP: OCEL Server & Client

This folder contains the MCP (Model Context Protocol) server for OCEL 2.0 analysis and an interactive LLM client for querying the OCEL schema.

## Setup

Install dependencies:
```bash
pip install -r ../requirements.txt
```

The client estimates tokens using `tiktoken` before each query and shows the cost. Confirm or edit the message before sending (`-f` to auto-approve).

## Server

### Run
```bash
# From repo root
python -m mcp.server --ocel-path ./storage/github.ocel_v1.json

# From mcp/server directory
cd server && python main.py --ocel-path ../storage/github.ocel_v1.json
```

**Environment variables:**
- `OCEL_FILE`: Path to OCEL JSON file (optional if `--ocel-path` provided)
- `LOG_LEVEL`: DEBUG, INFO, WARNING, ERROR, CRITICAL (default: INFO)
- `LOG_FILE`: Path to log file (default: logs/mcp_server.log)

See [server/.env.example](server/.env.example) for full configuration.

## Client

Interactive terminal CLI for asking questions about the OCEL schema using OpenAI or Gemini.

### Run
```bash
# From repo root (defaults: provider=openai, model=GPT-5.2)
python -m mcp.client --provider openai --model GPT-5.2

# From mcp/client directory
cd client && python main.py --provider gemini --model gemini-2.0-flash

# Skip cost confirmation prompt
python -m mcp.client -f
```

**Arguments:**
- `--provider {openai, gemini}`: LLM provider (default: openai)
- `--model MODEL`: Model name (default: GPT-5.2)
- `--schema-path PATH`: Path to OCEL schema JSON
- `-f, --force`: Skip cost confirmation before sending messages

**Environment variables:**
- `OPENAI_API_KEY`: Required for OpenAI provider
- `GEMINI_API_KEY`: Required for Gemini provider

See [client/.env.example](client/.env.example) for setup.
