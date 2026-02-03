"""Interactive MCP client to query an LLM about the OCEL schema."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import tiktoken

from .mcp_client import MCPClient, MCPClientError, DEFAULT_URL
from .providers import ProviderError, build_provider

DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
print(f"Provider: {DEFAULT_PROVIDER}, Model: {DEFAULT_MODEL}")

# Global cache for available tools (fetched once from server)
_cached_tools: Optional[List[Dict[str, Any]]] = None


@dataclass
class OcelMetadata:
    """OCEL metadata for the system prompt."""
    object_types: List[str] = field(default_factory=list)
    event_types: List[str] = field(default_factory=list)
    total_objects: int = 0
    total_events: int = 0
    start_date: str = "N/A"
    end_date: str = "N/A"


async def fetch_available_tools(client: MCPClient) -> List[Dict[str, Any]]:
    """
    Fetch available MCP tools from the server and cache them.
    
    Args:
        client: Connected MCPClient instance.
        
    Returns:
        List of tool definitions in MCP standard format.
    """
    global _cached_tools
    
    if _cached_tools is not None:
        return _cached_tools
    
    try:
        # Call the list_available_tools MCP tool
        result = await client.call_tool("list_available_tools", {})
        
        if "error" in result:
            # Fallback to MCP native tools/list
            tools = await client.list_tools()
            _cached_tools = tools
            return tools
        
        _cached_tools = result.get("tools", [])
        return _cached_tools
    
    except Exception as e:
        # Fallback to empty list
        print(f"  Warning: Could not fetch tools: {e}")
        _cached_tools = []
        return []


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

### AVAILABLE MCP TOOLS
You can request additional information by responding with a tool call in this format:
```tool
{{"tool": "tool_name", "params": {{"param1": "value1"}}}}
```

**IMPORTANT: All temporal metrics (performance, bottlenecks) are returned in SECONDS (SI unit).**

Available tools:
{available_tools_section}

### ANALYSIS GUIDELINES
1. **Multiplicity First**: Do not assume a single Case ID. Analyze how events link multiple objects (1:n, m:n relations).
2. **Cardinality**: Identify "Batching" (one event, many objects) vs. "Singular" flows.
3. **Graph Perspective**: Treat the log as a dynamic graph where objects are nodes and events are hyperedges.
4. **Performance**: Calculate throughput times per 'Object Type'. All times are in SECONDS.

### OUTPUT FORMAT
- Strict Markdown.
- When citing specific flows, refer to the Object Types defined in the Context above.
- If generating SQL/Python, ensure compatibility with the OCEL 2.0 relational schema (event_map, object_map).
- If you need more context, use search_ocel or get_schema_section first.
"""

def format_system_prompt(meta: OcelMetadata, tools: List[Dict[str, Any]]) -> str:
    """
    Format the system prompt with real OCEL metadata and available tools.
    
    Args:
        meta: OCEL metadata from server.
        tools: List of tool definitions in MCP standard format.
        
    Returns:
        Complete system prompt.
    """
    tools_json = json.dumps(tools, indent=2) if tools else "No tools available."
    
    return SYSTEM_PROMPT_TEMPLATE.format(
        object_types_list=meta.object_types if meta.object_types else ["(no object types loaded)"],
        event_types_list=meta.event_types if meta.event_types else ["(no event types loaded)"],
        total_objects=meta.total_objects,
        total_events=meta.total_events,
        start_date=meta.start_date,
        end_date=meta.end_date,
        available_tools_section=tools_json,
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
    parser.add_argument("--url", default=DEFAULT_URL, help=f"MCP server URL (default: {DEFAULT_URL})")
    parser.add_argument("-f", "--force", action="store_true", help="Skip cost confirmation before sending")
    return parser


async def create_mcp_client(url: str) -> MCPClient:
    """Create and connect to MCP server."""
    client = MCPClient(server_url=url)
    try:
        await client.connect()
        return client
    except MCPClientError as e:
        print(f"Error connecting to MCP server: {e}")
        print(f"Make sure the server is running: python -m mcp_ocel.server --ocel-path <path>")
        sys.exit(1)


async def fetch_metadata_from_server(client: MCPClient) -> OcelMetadata:
    """Fetch OCEL metadata from connected MCP server."""
    info = await client.get_ocel_info()
    return OcelMetadata(
        object_types=info.object_types,
        event_types=info.event_types,
        total_objects=info.total_objects,
        total_events=info.total_events,
        start_date=info.start_date,
        end_date=info.end_date,
    )


def extract_tool_calls(text: str) -> List[Dict[str, Any]]:
    """Extract tool calls from LLM response.
    
    Args:
        text: LLM response text.
        
    Returns:
        List of parsed tool call dictionaries.
    """
    tool_calls: List[Dict[str, Any]] = []
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


async def execute_tool_call(client: MCPClient, tool_call: Dict[str, Any]) -> str:
    """Execute a tool call and return the result.
    
    Args:
        client: Connected MCPClient instance.
        tool_call: Tool call dictionary with 'tool' and 'params' keys.
        
    Returns:
        Formatted result string.
    """
    tool_name = tool_call.get("tool", "")
    params = tool_call.get("params", {})

    try:
        # Call any MCP tool directly
        result = await client.call_tool(tool_name, params)
        return f"**Tool: {tool_name}**\n```json\n{json.dumps(result, indent=2)}\n```"

    except MCPClientError as e:
        return f"Tool error: {e}"


async def enrich_context_with_search(client: MCPClient, user_query: str) -> Optional[str]:
    """
    Use hybrid search to find relevant OCEL context for the user's query.
    
    Returns formatted context string or None if search fails/unavailable.
    """
    try:
        result = await client.search_ocel(query=user_query, top_k=3)
        
        if "error" in result:
            return None
        
        results = result.get("results", [])
        if not results:
            return None
        
        context_parts = []
        for r in results:
            chunk_type = r.get("chunk_type", "unknown")
            content = r.get("content", "")
            score = r.get("score", 0)
            context_parts.append(f"[{chunk_type} | relevance: {score:.3f}]\n{content}")
        
        return "### Relevant OCEL Context (from hybrid search)\n" + "\n\n".join(context_parts)
    
    except Exception:
        return None


async def interactive_chat_async(args: argparse.Namespace) -> None:
    """Main interactive chat loop (async version)."""
    print(f"Connecting to MCP server at {args.url}...")
    
    async with MCPClient(args.url) as mcp_client:
        # Get OCEL metadata from MCP server
        meta = await fetch_metadata_from_server(mcp_client)
        print(f"  Object Types: {meta.object_types}")
        print(f"  Event Types: {meta.event_types}")
        print(f"  Objects: {meta.total_objects:,} | Events: {meta.total_events:,}")
        print(f"  Time Range: {meta.start_date} to {meta.end_date}")
        
        # Fetch available tools from server (cached globally)
        print("  Loading available tools...")
        available_tools = await fetch_available_tools(mcp_client)
        print(f"  Tools available: {len(available_tools)}")
        
        # Build system prompt with tools in MCP format
        system_prompt = format_system_prompt(meta, available_tools)
        print(system_prompt)

        try:
            provider = build_provider(args.provider)
        except ProviderError as exc:
            print(f"Provider error: {exc}")
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
                except (KeyboardInterrupt, EOFError):
                    print("\nExiting.")
                    break

                if not user_text:
                    continue
                if user_text.lower() in {":quit", ":exit"}:
                    break

                # Enrich context with hybrid search before sending to LLM
                search_context = await enrich_context_with_search(mcp_client, user_text)
                if search_context:
                    enriched_query = f"{user_text}\n\n{search_context}"
                    print("  [Hybrid search context added]")
                else:
                    enriched_query = user_text

                messages = history + [{"role": "user", "content": enriched_query}]
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
                        result = await execute_tool_call(mcp_client, tc)
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

        except Exception as e:
            print(f"\nError: {e}")


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    asyncio.run(interactive_chat_async(args))


if __name__ == "__main__":
    main()
