"""Interactive MCP client to query an LLM about the OCEL schema."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import tiktoken

from .mcp_client import MCPClient, MCPClientError, OcelInfo, DEFAULT_HOST, DEFAULT_PORT
from .providers import ProviderError, build_provider

DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "GPT-5.2"


@dataclass
class OcelMetadata:
    """OCEL metadata for the system prompt."""
    object_types: List[str] = field(default_factory=list)
    event_types: List[str] = field(default_factory=list)
    total_objects: int = 0
    total_events: int = 0
    start_date: str = "N/A"
    end_date: str = "N/A"


# Available tools the LLM can call
AVAILABLE_TOOLS = [
    {
        "name": "get_schema_section",
        "description": "Retrieve OCEL 2.0 schema sections on demand. Use this when you need details about event structure, object structure, or attribute definitions.",
        "parameters": {
            "section": {
                "type": "string",
                "enum": ["eventTypes", "objectTypes", "events", "objects", "attributes"],
                "description": "The schema section to retrieve",
            }
        },
    },
    {
        "name": "call_mcp_tool",
        "description": "Call an MCP server tool to analyze the OCEL data.",
        "parameters": {
            "tool_name": {"type": "string", "description": "Name of the MCP tool"},
            "arguments": {"type": "object", "description": "Tool arguments"},
        },
    },
]


SYSTEM_PROMPT_TEMPLATE = """
### ROLE & OBJECTIVE
You are an Expert in Object-Centric Process Mining (OCPM) analyzing OCEL 2.0 logs.
Your goal is to discover process inefficiencies, interactions, and flow patterns.

### DYNAMIC CONTEXT (Current Loaded Log)
The following metadata describes the active dataset. USE ONLY these exact names for queries:
- **Object Types**: {object_types_list}
- **Event Types**: {event_types_list}
- **Log Stats**: {total_objects:,} objects, {total_events:,} events.
- **Time Range**: {start_date} to {end_date}.

### AVAILABLE TOOLS
You can request additional information by responding with a tool call in this format:
```tool
{{"tool": "tool_name", "params": {{"param1": "value1"}}}}
```

Available tools:
1. `get_schema_section` - Get OCEL schema details. Params: section (eventTypes|objectTypes|events|objects|attributes)
2. `call_mcp_tool` - Call MCP analysis tools. Params: tool_name, arguments

Example: To get the event structure schema:
```tool
{{"tool": "get_schema_section", "params": {{"section": "events"}}}}
```

### ANALYSIS GUIDELINES
1. **Multiplicity First**: Do not assume a single Case ID. Analyze how events link multiple objects (1:n, m:n relations).
2. **Cardinality**: Identify "Batching" (one event, many objects) vs. "Singular" flows.
3. **Graph Perspective**: Treat the log as a dynamic graph where objects are nodes and events are hyperedges.
4. **Performance**: Calculate throughput times per 'Object Type'.

### OUTPUT FORMAT
- Strict Markdown.
- When citing specific flows, refer to the Object Types defined in the Context above.
- If generating SQL/Python, ensure compatibility with the OCEL 2.0 relational schema (event_map, object_map).
- If you need schema details, request them with a tool call first.
"""


def format_system_prompt(meta: OcelMetadata) -> str:
    """Format the system prompt with real OCEL metadata values."""
    return SYSTEM_PROMPT_TEMPLATE.format(
        object_types_list=meta.object_types if meta.object_types else ["(no object types loaded)"],
        event_types_list=meta.event_types if meta.event_types else ["(no event types loaded)"],
        total_objects=meta.total_objects,
        total_events=meta.total_events,
        start_date=meta.start_date,
        end_date=meta.end_date,
    )


def estimate_tokens(messages: List[Dict[str, str]], model: str) -> int:
    text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
    try:
        encoder = tiktoken.encoding_for_model(model)
    except Exception:
        encoder = tiktoken.get_encoding("cl100k_base")
    return len(encoder.encode(text))


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MCP client for OCEL schema Q&A")
    parser.add_argument("--provider", default=DEFAULT_PROVIDER, choices=["openai", "gemini"], help="LLM provider")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="LLM model name")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"MCP server host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"MCP server port (default: {DEFAULT_PORT})")
    parser.add_argument("-f", "--force", action="store_true", help="Omitir confirmacion de coste antes de enviar")
    return parser


def create_mcp_client(host: str, port: int) -> MCPClient:
    """Create and connect to MCP server."""
    client = MCPClient(host=host, port=port)
    try:
        client.connect()
        client.initialize()
        return client
    except MCPClientError as e:
        print(f"Error connecting to MCP server: {e}")
        print(f"Make sure the server is running: python -m mcp.server --ocel-path <path>")
        sys.exit(1)


def fetch_metadata_from_server(client: MCPClient) -> OcelMetadata:
    """Fetch OCEL metadata from connected MCP server."""
    info = client.get_ocel_info()
    return OcelMetadata(
        object_types=info.object_types,
        event_types=info.event_types,
        total_objects=info.total_objects,
        total_events=info.total_events,
        start_date=info.start_date,
        end_date=info.end_date,
    )


def extract_tool_calls(text: str) -> List[Dict]:
    """Extract tool calls from LLM response."""
    tool_calls = []
    # Match ```tool ... ``` blocks
    pattern = r"```tool\s*\n?(.*?)\n?```"
    matches = re.findall(pattern, text, re.DOTALL)
    for match in matches:
        try:
            call = json.loads(match.strip())
            if "tool" in call:
                tool_calls.append(call)
        except json.JSONDecodeError:
            pass
    return tool_calls


def execute_tool_call(client: MCPClient, tool_call: Dict) -> str:
    """Execute a tool call and return the result."""
    tool_name = tool_call.get("tool", "")
    params = tool_call.get("params", {})

    try:
        if tool_name == "get_schema_section":
            section = params.get("section")
            result = client.get_schema_section(section)
            return f"**Schema Section: {section or 'index'}**\n```json\n{json.dumps(result, indent=2)}\n```"

        elif tool_name == "call_mcp_tool":
            mcp_tool = params.get("tool_name", "")
            mcp_args = params.get("arguments", {})
            result = client.call_tool(mcp_tool, mcp_args)
            return f"**MCP Tool: {mcp_tool}**\n```json\n{json.dumps(result, indent=2)}\n```"

        else:
            return f"Unknown tool: {tool_name}"

    except MCPClientError as e:
        return f"Tool error: {e}"


def interactive_chat(args: argparse.Namespace) -> None:
    print(f"Connecting to MCP server at {args.host}:{args.port}...")
    mcp_client = create_mcp_client(args.host, args.port)

    # Get OCEL metadata from MCP server
    meta = fetch_metadata_from_server(mcp_client)
    print(f"  Object Types: {meta.object_types}")
    print(f"  Event Types: {meta.event_types}")
    print(f"  Objects: {meta.total_objects:,} | Events: {meta.total_events:,}")
    print(f"  Time Range: {meta.start_date} to {meta.end_date}")

    system_prompt = format_system_prompt(meta)

    try:
        provider = build_provider(args.provider)
    except ProviderError as exc:
        print(f"Provider error: {exc}")
        mcp_client.disconnect()
        sys.exit(1)

    # Only system prompt - no full schema (retrieval-based)
    base_messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
    ]
    history: List[Dict[str, str]] = base_messages.copy()

    print(f"\nProvider: {args.provider} | Model: {args.model}")
    print("Type :quit or Ctrl+C to exit.\n")

    try:
        while True:
            try:
                user_text = input("You> ").strip()
            except KeyboardInterrupt:
                print("\nExiting.")
                break

            if not user_text:
                continue
            if user_text.lower() in {":quit", ":exit"}:
                break

            messages = history + [{"role": "user", "content": user_text}]
            prompt_tokens = estimate_tokens(messages, args.model)
            print(f"Estimated prompt tokens: {prompt_tokens}")
            if not args.force:
                confirm = input("Send? [y/N]: ").strip().lower()
                if confirm not in {"y", "yes"}:
                    print("Cancelled.")
                    continue

            print("Assistant> ", end="", flush=True)
            chunks: List[str] = []
            try:
                for chunk in provider.stream_chat(messages, args.model):
                    chunks.append(chunk)
                    print(chunk, end="", flush=True)
                print()
            except KeyboardInterrupt:
                print("\nInterrupted.")
                continue
            except Exception as exc:
                print(f"\nError from provider: {exc}")
                continue

            assistant_reply = "".join(chunks)

            # Check for tool calls in the response
            tool_calls = extract_tool_calls(assistant_reply)
            if tool_calls:
                print("\n[Executing tool calls...]")
                tool_results = []
                for tc in tool_calls:
                    print(f"  → {tc.get('tool', 'unknown')}")
                    result = execute_tool_call(mcp_client, tc)
                    tool_results.append(result)
                    print(f"    ✓ Done")

                # Add tool results to context and continue conversation
                tool_context = "\n\n".join(tool_results)
                history.extend([
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": assistant_reply},
                    {"role": "user", "content": f"Tool results:\n{tool_context}\n\nPlease continue your analysis with this information."},
                ])

                # Auto-continue with tool results
                messages = history.copy()
                print("\nAssistant> ", end="", flush=True)
                chunks = []
                try:
                    for chunk in provider.stream_chat(messages, args.model):
                        chunks.append(chunk)
                        print(chunk, end="", flush=True)
                    print()
                except Exception as exc:
                    print(f"\nError: {exc}")
                    continue

                followup_reply = "".join(chunks)
                history.append({"role": "assistant", "content": followup_reply})
            else:
                history.extend([
                    {"role": "user", "content": user_text},
                    {"role": "assistant", "content": assistant_reply},
                ])

    finally:
        mcp_client.disconnect()


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    interactive_chat(args)


if __name__ == "__main__":
    main()
