"""Interactive MCP client to query an LLM about the OCEL schema."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import tiktoken

from .mcp_client import MCPClient, MCPClientError, DEFAULT_URL
from .providers import ProviderError, build_provider, ToolCall
from shared.lifecycle import register_shutdown_callback, install_signal_handlers

DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
MAX_TOOL_CALLS = int(os.getenv("MAX_TOOL_CALLS", sys.maxsize))
print(f"Provider: {DEFAULT_PROVIDER} | Model: {DEFAULT_MODEL}")

# Global cache for available tools (fetched once from server)
_cached_tools: Optional[List[Dict[str, Any]]] = None

# Global reference to the MCP client for graceful shutdown
_mcp_client_ref: Optional[MCPClient] = None


def _client_cleanup() -> None:
    """
    Cleanup callback for client shutdown.
    
    Disposes of the MCP client connection if it exists.
    Called when SIGINT, SIGTERM, or other termination signal is received.
    
    Note: Does NOT create new resources (e.g., event loops) during shutdown.
    If the client exists but cannot be disposed (no event loop), best-effort attempt only.
    """
    global _mcp_client_ref
    
    if _mcp_client_ref is not None:
        try:
            try:
                loop = asyncio.get_running_loop()
                # If we're in an async context, schedule the disconnect
                asyncio.run_coroutine_threadsafe(_mcp_client_ref.disconnect(), loop).result(timeout=2)
            except:
                pass
        finally:
            _mcp_client_ref = None


class ThinkingAnimation:
    """Animates thinking dots while waiting for LLM response."""
    
    def __init__(self):
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.dots_frames = [
            ".",
            "..",
            "...",
            " ..",
            "  .",
            "",
        ]
        self.frame_index = 0
    
    def start(self):
        """Start the animation thread."""
        self.running = True
        self.frame_index = 0
        self.thread = threading.Thread(target=self._animate, daemon=True)
        self.thread.start()
    
    def stop(self):
        """Stop the animation thread."""
        self.running = False
        if self.thread:
            self.thread.join(timeout=1)
        # Clear the line by printing backspaces and spaces
        print("\r" + " " * 15 + "\r", end="", flush=True)
    
    def _animate(self):
        """Animation loop running in separate thread."""
        while self.running:
            frame = self.dots_frames[self.frame_index % len(self.dots_frames)]
            print(f"\rAssistant> {frame}", end="", flush=True)
            self.frame_index += 1
            time.sleep(0.5)  # Update every 0.5 seconds for smoother animation


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
You are an OCEL 2.0 process-mining analyst. Discover inefficiencies, interactions, and flow patterns.

DATASET
Object Types: {object_types_list}
Event Types: {event_types_list}
Stats: {total_objects:,} objects, {total_events:,} events | {start_date} to {end_date}
Use ONLY these exact type names in tool calls. Max {max_tool_calls} tool rounds per query.

CURSOR MODEL
All filter/query tools return ONLY a cursor_id. Data never enters the LLM context until
you explicitly request it. Description for the tools will indicate how to inspect or retrieve data from a cursor_id.
Cursors live for the full session — no TTL.

TOOL CHAINING
Tools with an `input_cursor_id` parameter accept a `cursor_id` from a previous result.
The downstream tool then filters within that subset instead of the full OCEL.
Chain any number of steps: each produces its own `cursor_id` for further chaining.
Example — narrowing results in 3 steps, then fetching:
  1. filter_by_object_type("X") → cursor_id C1
  2. filter_by_event_type("Y", input_cursor_id=C1) → cursor_id C2
  3. query_events_by_timerange(start, end, input_cursor_id=C2) → cursor_id C3
  4. get_cursor_results(C3)                                    → all data for user

TIPS
- FETCH LAZILY: Use cursor-related tools to reason about subsets. Get results ONLY for the
  final subset you intend to present to the user.
- `filter_by_event_type` / `filter_by_object_type`: precise type filtering (prefer over `search_ocel`).
- All temporal metrics are in SECONDS; convert for the user.
- STRICT TEMPORAL DELEGATION: NEVER fetch broad datasets to manually inspect, filter, or group
  timestamps in your context window. For ANY semantic temporal condition (e.g., recurring periods,
  specific days, shifts), deduce all exact absolute start/end timestamps from the narrowest known
  boundaries ({start_date}/{end_date} or a cursor's timerange result), then issue
  separate tool calls for EACH distinct time range using tool chaining.

ANALYSIS
- OCEL is multi-object: events are hyperedges linking 1:n or m:n objects.
- Distinguish batching (1 event → many objects) vs singular flows.
- Compute throughput per object type.

OUTPUT
Console text only — no markdown/HTML. Reference the exact Object Type names above.
"""

def format_system_prompt(meta: OcelMetadata) -> str:
    """
    Format the system prompt with real OCEL metadata.
    
    Args:
        meta: OCEL metadata from server.
        
    Returns:
        Complete system prompt.
    """
    return SYSTEM_PROMPT_TEMPLATE.format(
        object_types_list=meta.object_types if meta.object_types else ["(no object types loaded)"],
        event_types_list=meta.event_types if meta.event_types else ["(no event types loaded)"],
        total_objects=meta.total_objects,
        total_events=meta.total_events,
        start_date=meta.start_date,
        end_date=meta.end_date,
        max_tool_calls=MAX_TOOL_CALLS,
    )

def _extract_message_text(m: Dict[str, Any]) -> str:
    """Extract all text from a message regardless of its format.

    Handles all formats present in the message history:
      OpenAI Responses API:
        - function_call_output       → result in 'output'
        - responses_function_calls   → calls[].arguments
      Gemini:
        - tool_result (role)         → result in 'content'
        - assistant with tool calls  → content + gemini_function_calls[].args
      Regular role/content messages  → role + content
    """
    if m.get("type") == "function_call_output":
        return m.get("output", "")
    if m.get("_type") == "responses_function_calls":
        parts = [m.get("content", "")]
        for call in m.get("calls", []):
            parts.append(call.get("arguments", ""))
        return " ".join(filter(None, parts))
    # Gemini assistant message may carry function call args alongside content
    parts = [f"{m.get('role', '')}: {m.get('content', '')}"]
    for fc in m.get("gemini_function_calls", []):
        args = fc.get("args", {})
        if args:
            parts.append(json.dumps(args, ensure_ascii=False))
    return " ".join(filter(None, parts))


def estimate_tokens(messages: List[Dict[str, Any]], model: str) -> int:
    text = "\n".join(_extract_message_text(m) for m in messages)
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

async def execute_tool_calls(
    client: MCPClient, provider: Any, tool_calls: List[ToolCall]
) -> List[Dict[str, Any]]:
    """Execute tool calls via the MCP client.
    
    Args:
        client: Connected MCPClient instance.
        provider: LLM provider instance (for building result messages).
        tool_calls: List of ToolCall objects from the LLM.
        
    Returns:
        List of provider-specific tool result messages.
    """
    results = []
    for tc in tool_calls:
        print(f"→ Calling tool: {tc.name}")
        try:
            result = await client.call_tool(tc.name, tc.arguments)
            result_str = json.dumps(result, indent=2, ensure_ascii=False)
            results.append(provider.build_tool_result_message(tc, result_str))
            print(f"  ✓ Done")
        except MCPClientError as e:
            error_str = json.dumps({"error": str(e)})
            results.append(provider.build_tool_result_message(tc, error_str))
            print(f"  ✗ Error: {e}")
    return results


async def interactive_chat_async(args: argparse.Namespace) -> None:
    """Main interactive chat loop (async version) with native tool calling."""
    global _mcp_client_ref
    
    print(f"Connecting to MCP server at {args.url}...")
    
    async with MCPClient(args.url) as mcp_client:
        # Store global reference for cleanup
        _mcp_client_ref = mcp_client
        
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
        
        # Build system prompt (tools are passed separately to OpenAI)
        system_prompt = format_system_prompt(meta)

        try:
            provider = build_provider(args.provider)
        except ProviderError as exc:
            print(f"Provider error: {exc}")
            sys.exit(1)

        # Initialize message history
        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

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

                # Add user message
                messages.append({"role": "user", "content": user_text})
                
                prompt_tokens = estimate_tokens(
                    [{"role": m["role"], "content": m.get("content", "")} for m in messages],
                    args.model
                )
                print(f"Estimated prompt tokens: {prompt_tokens}")
                
                if not args.force:
                    try:
                        confirm = input("Send? [Y/n]: ").strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        print("\nCancelled.")
                        messages.pop()
                        continue
                    if confirm.lower() in {"n", "no"}:
                        print("Cancelled.")
                        messages.pop()
                        continue

                iteration = 0
                # Continue until no more available tool calls or max iterations reached
                while iteration < MAX_TOOL_CALLS:
                    iteration += 1

                    animation = ThinkingAnimation()
                    animation.start()

                    try:
                        response = provider.chat_with_tools(messages, args.model, available_tools)
                    except Exception as exc:
                        animation.stop()
                        print(f"Error from provider: {exc}")
                        break
                    finally:
                        animation.stop()
                    
                    # Print any content
                    if response.content:
                        print(response.content)

                    # Check if there are tool calls
                    if response.tool_calls:                        
                        # Add assistant message with tool calls to history
                        assistant_msg = provider.build_assistant_tool_call_message(
                            response.content, response.tool_calls
                        )
                        messages.append(assistant_msg)
                        
                        # Execute tools and add results to history
                        tool_results = await execute_tool_calls(
                            mcp_client, provider, response.tool_calls
                        )
                        messages.extend(tool_results)
                        
                        # Continue loop to let LLM process tool results
                        continue
                    else:
                        # No more tool calls, add final response and exit loop
                        if response.content:
                            messages.append({"role": "assistant", "content": response.content})
                        break
                
                if iteration >= MAX_TOOL_CALLS:
                    print(f"\n[Warning: Reached max tool iterations ({MAX_TOOL_CALLS})]")

        except Exception as e:
            print(f"\nError: {e}")


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    
    # Register cleanup callback with the global shutdown manager
    register_shutdown_callback(_client_cleanup)
    
    # Install signal handlers (must be called from main thread)
    install_signal_handlers()
    
    asyncio.run(interactive_chat_async(args))


if __name__ == "__main__":
    main()
