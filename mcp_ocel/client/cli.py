"""Interactive MCP client to query an LLM about the OCEL schema."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import threading
import time
from math import isinf
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from tzlocal import get_localzone_name

import tiktoken

from shared.config.env import Env

from .mcp_client import MCPClient, MCPClientError, DEFAULT_URL
from .providers import ProviderError, build_provider, ToolCall
from shared.lifecycle import register_shutdown_callback, install_signal_handlers

DEFAULT_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
DEFAULT_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
MAX_TOOL_CALLS = float(os.getenv("MAX_TOOL_CALLS", "inf"))
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
ROLE: OCEL 2.0 Process Mining Analyst. Focus: control-flow, bottlenecks, m:n object-event relations.
CONTEXT: User timezone={timezone} | Objects={object_types_list} | Events={event_types_list}
STATS: {total_objects:,} objects | {total_events:,} events | Global Range: {start_date} to {end_date}

TOOL SUFFICIENCY AXIOM
The provided toolset is COMPLETE for all OCEL 2.0 inquiries.
1. NO MISSING TOOLS: If a specific operation seems unavailable, you are failing to decompose the problem. A composite solution chaining filters, search, and time-windowing ALWAYS exists.
2. NO EXCUSES: It is strictly forbidden to claim a calculation cannot be done or to fallback to raw data fetching due to perceived tool limitations. You must derive the answer by combining primitive operations.

COMPUTE-ON-TOOL PROTOCOL NON-NEGOTIABLE
1. NO RAW FETCHING: IT IS FORBIDDEN to fetch raw records to count, group, or filter in your context window. You MUST use aggregation tools.
2. RAW DATA EXCEPTION: Fetch raw records ONLY as the final step to display specific examples to the user. INTERNAL INSPECTION FOR REASONING IS FORBIDDEN. 
3. CURSOR CHAINING: Filter then Aggregate then Narrow down. Pass cursor_id sequentially.
4. ABSTRACT WORKFLOW: Do not rely on specific tool names to deduce conclusions. Follow the logical flow: narrow scope -> get exact bounds -> decompose into windows -> aggregate per window -> combine.
5. INDIRECT LOOKUP & DECOMPOSITION: If a direct filter for a specific condition (e.g., text pattern, specific weekday, complex attribute) is missing, DO NOT fallback to raw data inspection. You MUST use available search utilities to find IDs or mathematically generate precise query parameters (e.g., time-windows) to target the data via tools.
{max_tool_calls_instruction}
MANDATORY EXHAUSTIVE COVERAGE
For any temporal or periodic analysis:
1. BOUNDARIES: First, deduce the EXACT start and end of the active cursor or dataset.
2. NO LAZINESS: You MUST process 100% of the deduced timeframe. NEVER sample or truncate.
3. PARALLELISM: If possible in the environment, you can emit up parallel tool calls to cover the full range efficiently.
4. SILENT LOOPING: Do not generate text or ask permission between batches. Loop until coverage is 100%.

OUTPUT RULES
FORMAT: Plain text only. NO Markdown or HTML.
UNITS: Convert tool seconds to human-readable minutes, hours, or days.

EXECUTION STRATEGY
Before calling tools, you must internally verify:
Am I fetching raw rows to count them? -> STOP -> Use Aggregation Tool.
Am I checking only 1 month of a 2-year range? -> STOP -> Schedule calls for full range.
"""

def format_system_prompt(meta: OcelMetadata) -> str:
    """
    Format the system prompt with real OCEL metadata.
    
    Args:
        meta: OCEL metadata from server.
        
    Returns:
        Complete system prompt.
    """

    if not isinf(MAX_TOOL_CALLS):
        tool_calls_str = f"7. MAX TOOL CALLS: Limit to {MAX_TOOL_CALLS} tool rounds per query.\n"
    else:
        tool_calls_str = ""

    return SYSTEM_PROMPT_TEMPLATE.format(
        object_types_list=meta.object_types if meta.object_types else ["(no object types loaded)"],
        event_types_list=meta.event_types if meta.event_types else ["(no event types loaded)"],
        total_objects=meta.total_objects,
        total_events=meta.total_events,
        start_date=meta.start_date,
        end_date=meta.end_date,
        max_tool_calls_instruction=tool_calls_str,
        timezone=Env.str("TZ", get_localzone_name())
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
                
                prompt_tokens = estimate_tokens(messages, args.model)
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
