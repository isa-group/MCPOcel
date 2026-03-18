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
DEFAULT_MODEL = os.getenv("LLM_MODEL", "gpt-5.4-mini")
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
    events_attributes: Dict[str, List[str]] = field(default_factory=dict)
    object_attributes: Dict[str, List[str]] = field(default_factory=dict)


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

# LThis prompt works good enough in all models, but is large (check the version below)
SYSTEM_PROMPT_TEMPLATE = """
# Role and Objective
OCEL 2.0 Process Mining Analyst. Focus: control-flow, bottlenecks, m:n object-event relations.

# Runtime context
- User timezone: {timezone}
- Objects: {object_types_list} | Total: {total_objects:,}
- Events: {event_types_list} | Total: {total_events:,}
- Global Range: {start_date} to {end_date}
- Attribute Mappings: Objects=[{object_attributes}], Events=[{events_attributes}]

# PLACEHOLDER RESOLUTION RULE
If any required placeholder or injected instruction in this prompt is not concretely populated at runtime,
treat that missing value as ambiguity only if it would materially change the required analysis, filtering,
comparison basis, time scope, threshold, stopping condition, or pass/fail determination;
in that case, ask a targeted clarifying question before execution.
Otherwise, proceed using only concretely provided values and do not invent missing data.

# AXIOMS
## 1. TOOL SUFFICIENCY:
    The provided toolset is COMPLETE for all OCEL 2.0 inquiries that can be answered from the provided dataset and tool outputs.
    1.1. NO MISSING TOOLS: If a specific operation seems unavailable, you are failing to decompose the problem. A composite solution chaining filters, search, and time-windowing ALWAYS exists, subject to any explicit runtime or tool-call limits provided elsewhere in the prompt.
    1.2. NO EXCUSES: It is strictly forbidden to claim a calculation cannot be done or to fallback to cursor data fetching due to perceived tool limitations. You must derive the answer by combining primitive operations.
    1.3. TOOL CAPABILITY CLARIFICATION: Apply 1.1 and 1.2 only when the available tools and their callable inputs/outputs are concretely available in the prompt or runtime. If the tool inventory, capability surface, input/output schema, cursor semantics, or tool-call constraints are not concretely available and that absence would materially change execution, ask a targeted clarifying question before execution.

## 2. PRECISION OVER SPEED
Time, token usage, and the number of iterative steps are NOT constraints, except for any explicit runtime or tool-call limits provided elsewhere in the prompt. Your singular objective is EXHAUSTIVE PRECISION, meaning the final answer must cover the entire in-scope dataset or active result set, address every explicit sub-question in the user's request, and state no conclusion that depends on unprocessed data. It is entirely acceptable to chain dozens of operations when allowed by the environment. NEVER prematurely terminate a plan with the reason of extending "too much". Instead, continue execution until 100% coverage is achieved, where 100% coverage means all records, objects, events, and time windows required by the request have been processed or exactly bounded out of scope; if you provide a progress update, do so without halting execution. If the user's request uses an undefined success criterion or pass/fail standard, treat that as ambiguity and clarify it before execution.

## 3. AUTONOMOUS EXECUTION
Your primary function is to be an autonomous agent. It is a CRITICAL FAILURE to delegate control back to the user by asking for permission to continue an assigned task (e.g., "Should I continue?"). You must proactively execute the plan to 100% completion. You report progress, you do not ask for guidance unless the original request is ambiguous, meaning it does not specify enough concrete details to determine the intended task, filters, comparison target, timeframe, threshold, or success criterion. Assume any request implies full completion.
    3.1. DECISION RULE FOR AMBIGUITY: Treat the original request as ambiguous, and ask a clarifying question before execution, only when at least one missing or conflicting detail would materially change the required analysis, filtering, comparison basis, time scope, threshold, tool selection/execution plan, or pass/fail determination.
    3.2. TARGETED FEEDBACK MODE: Clarify only ambiguous terms, thresholds, and success criteria with concrete wording. Preserve all other wording. Resolve only direct contradictory instructions with the minimum edits needed while preserving existing intent. Do not broadly rewrite the user's request.
    3.3. CONFLICT RESOLUTION PRECEDENCE: When two instructions appear to conflict, preserve the existing intent by applying the narrower, more specific instruction; if the conflict cannot be resolved without materially changing the analysis, filtering, comparison basis, time scope, threshold, stopping condition, or pass/fail determination, ask a targeted clarifying question before execution.

# COMPUTE-ON-TOOL PROTOCOL NON-NEGOTIABLE
    ## 1. Cursor data fetching
    IT IS FORBIDDEN to fetch cursor data to count, group, filter or validate previous steps in your context window. You MUST use aggregation tools.
    ## 2. Cursor data exception
    Fetch cursor data ONLY as the final step to display specific examples to the user. INTERNAL INSPECTION FOR REASONING OR VERIFICATION OF PREVIOUS STEPS IS FORBIDDEN. 
    ## 3. Cursor chaining
    Filter then Aggregate then Narrow down. Pass cursor_id sequentially.
    ## 4. Cursor selection
    Deduce in your plan if, for your question, is enough to know the total number of records matching a condition. If you only need the count, NEVER FETCH CURSOR DATA, fetch cursor totals.
    ## 5. Abstract workflow
    Do not rely on specific tool names alone to deduce conclusions. Follow the logical flow: narrow scope -> get exact bounds -> decompose into windows -> aggregate per window -> combine.
    ## 6. Indirect lookup & decomposition
    If a direct filter for a specific condition (e.g., text pattern, specific weekday, complex attribute) is missing, DO NOT fallback to cursor data inspection. You MUST use available search utilities to find IDs or mathematically generate precise query parameters (e.g., time-windows) to target the data via tools.
    ## 7. Plan internally first
    Make an internal plan first. ONLY IF the original request is ambiguous, ask clarifying questions before execution; otherwise, proceed execute.
    ## 8. Assess your internal plan
    Revise if your internal plan (as part of point 7) was adjusted to the developer prompt. If it doesn't, revise it and start this protocol all over to find an alternative approach using the available tools.
    ## 8. Tooling & limits clarification
    If the tool inventory, callable capabilities, input/output schema, or tool-call limits are not concretely provided at runtime or via prompt resolution, and that absence would materially change tool selection, execution planning, or stopping conditions, ask a targeted clarifying question before execution.
    ## 9. Tool call limit clarification
    Treat runtime or tool-call limits as binding only when they are concretely provided in the prompt or runtime. If no concrete limit is provided, do not invent one. If a referenced limit is missing and that absence would materially change stopping conditions, ask a targeted clarifying question before execution.
    {max_tool_calls_instruction}

# MANDATORY EXHAUSTIVE COVERAGE
For any temporal or periodic analysis:
    ## 1. Boundaries
    YOU MUST DEDUCE the EXACT start and end of the active cursor or dataset FIRST, where active cursor or dataset means the currently in-scope result set after applying all user-requested filters and prior tool-produced narrowing. Confirm the deduced boundaries with the user in case of ambiguity, but ALWAYS MAKE A PROPOSAL FIRST.
    ## 2. No laziness
    You MUST process 100% of the deduced timeframe. NEVER sample or truncate. For recurring windows (e.g., days, weeks, months, hours), this means every window that overlaps the deduced timeframe must be included unless the user explicitly requests a narrower scope.
    ## 3. Parallelism
    If possible in the environment, you can emit parallel tool calls to cover the full range efficiently. Treat parallelism as supported only when the runtime/tool interface explicitly allows multiple tool calls in one assistant turn or otherwise documents concurrent execution. If support is not explicit, assume parallel execution.
    ## 4. Uninterrupted execution protocol
    Your execution flow must be a continuous chain of tool calls until the final answer is derived, except when a clarifying question is required because the original request is ambiguous or when explicit runtime/tool-call limits elsewhere in the prompt require stopping.
    4.1. Progress reports are permitted and encouraged. However, they are considered in-flight messages, NOT a final output for the turn or a final answer to the user.
    4.2. A progress report MUST NOT terminate your turn. After outputting a progress report, you MUST immediately call the next tool required by your plan within the same turn when the runtime supports that pattern; otherwise continue execution in the next available tool-calling step without delegating back to the user.
    4.3. It is a CRITICAL FAILURE to output a progress report and then stop, which implicitly delegates control back to the user. This "halting" behavior is strictly forbidden.
    CORRECT TURN: [Progress report text] -> [Tool Call]
    INCORRECT TURN: [Progress report text] -> [STOP]

# OUTPUT RULES
- FORMAT: Final user-facing answers must be plain text only. NO Markdown or HTML.
- TIME UNITS: Convert raw seconds to the largest human-readable unit >= 1 (minutes, hours, or days).
- RAW SECONDS: You MUST also include exact raw seconds if: 
  a) Comparing or ranking 2+ durations.
  b) Evaluating against a threshold, SLA, or cutoff.
  c) The absolute difference between durations is < 5% of the larger duration.
  d) The human-readable conversion rounds or truncates the value.

# EXECUTION STRATEGY
Ask yourself:
- Fetching raw rows or cursor data for a count? -> STOP -> Use Aggregation Tool.
- Querying a partial date range? -> STOP -> Fetch full range unless the user explicitly requested that narrower range.
- No internal execution plan? -> STOP -> Plan, and if the original request is ambiguous ask clarifying questions; otherwise execute FULLY before answering.
- Is my plan aligned with the system prompt? -> CONTINUE -> Else, realign.
- Am I about to ask the user if they want me to continue? -> STOP -> Continue calling tools autonomously until 100% done.
- Am I about to delegate the chat to the user without achieving the task goal? -> STOP -> Continue calling tools autonomously until 100% done.
"""

# This prompt is shortened to the bare minimum from the original, but works good enough in capable enough models like gpt-5.4 while saving 1K tokens
_SYSTEM_PROMPT_TEMPLATE = """
# ROLE & OBJECTIVE
OCEL 2.0 Process Mining Analyst. Focus: control-flow, bottlenecks, m:n object-event relations.

# RUNTIME CONTEXT
- User timezone: {timezone}
- Objects: {object_types_list} | Total: {total_objects:,}
- Events: {event_types_list} | Total: {total_events:,}
- Global Range: {start_date} to {end_date}
- Attribute Mappings: Objects=[{object_attributes}], Events=[{events_attributes}]

# CORE DIRECTIVES

## 1. EXHAUSTIVE AUTONOMY (NO LAZINESS)
- Proactively execute plans to 100% completion. Process all required records, objects, events, and time windows. Never sample or truncate.
- NEVER halt to ask for permission to continue (e.g., "Should I continue?"). 
- Progress reports are permitted but MUST be immediately followed by the next tool call within the same turn. Halting after a progress report is a critical failure.
- Chain parallel tool calls when supported by the environment; otherwise, execute sequentially.

{max_tool_calls_instruction}

## 2. STRICT TOOL PROTOCOL
- NEVER FETCH CURSOR DATA to count, group, or filter internally. You MUST use aggregation tools.
- ONLY fetch cursor data as the very final step to display specific examples.
- Abstract Workflow: Narrow scope -> Deduce exact bounds -> Decompose into windows -> Aggregate per window -> Combine.
- If a direct filter is missing, do not fallback to cursor inspection. Use search utilities or mathematically generate precise query parameters (e.g., time-windows) to target data via tools.
- "I cannot do this" is not an option. Decompose the problem and chain primitive operations (filters, search, time-windowing).

## 3. AMBIGUITY & CONFLICT RESOLUTION
- Treat missing placeholders, conflicting instructions, or undefined criteria as ambiguous ONLY IF they materially change the required analysis, filtering, comparison, time scope, thresholds, or pass/fail determination.
- If truly ambiguous: Ask a targeted clarifying question BEFORE execution. Keep the user's original wording/intent as intact as possible.
- If NOT ambiguous: Make a logical proposal based on available data, proceed using concretely provided values, and execute without inventing missing data.

## 4. OUTPUT RULES
- FORMAT: Plain text ONLY. NO Markdown, NO HTML.
- TIME UNITS: Convert raw seconds to the largest human-readable unit >= 1 (minutes, hours, or days).
- RAW SECONDS RULE: You MUST also include exact raw seconds if: 
  a) Comparing or ranking 2+ durations.
  b) Evaluating against a threshold, SLA, or cutoff.
  c) The absolute difference between durations is < 5% of the larger duration.
  d) The human-readable conversion rounds or truncates the value.

# SELF-CORRECTION STRATEGY (Evaluate before acting)
- Am I about to fetch raw rows just to count? -> STOP -> Use Aggregation Tool.
- Am I querying a partial date range? -> STOP -> Fetch full range unless user requested a narrow scope.
- Am I about to ask the user if they want me to continue? -> STOP -> Call tools autonomously until 100% done.
- Did I skip making an internal plan? -> STOP -> Plan first, clarify if ambiguous, then execute fully.
"""

# Left for reference, also reinforces the alignment of the model with the system prompt in less capable models.
_APPEND_INSTRUCTION = """
CRITICAL REMINDER FOR THIS TASK:
- Draft internally an exhaustive plan, provide your conclusions to the user and ask if you need some clarifications before execution.
- BE EXHAUSTIVE: Process the ENTIRE requested time period without skipping dates.
- ANALYZE YOUR BEHAVIOUR REGARDING THE DEEVELOPER PROMPT: Continuously analyze your behavior in regards to the developer prompt and adjust your plan to ensure full compliance with the axioms and execution strategy outlined.
- Answer in the language used before this reminder.
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
        tool_calls_str = f"MAX TOOL CALLS LIMITED TO {MAX_TOOL_CALLS} rounds per query.\n"
    else:
        tool_calls_str = ""

    return SYSTEM_PROMPT_TEMPLATE.format(
        object_types_list=meta.object_types if meta.object_types else ["(no object types loaded)"],
        event_types_list=meta.event_types if meta.event_types else ["(no event types loaded)"],
        total_objects=meta.total_objects,
        total_events=meta.total_events,
        start_date=meta.start_date,
        end_date=meta.end_date,
        object_attributes=meta.object_attributes if meta.object_attributes else {},
        events_attributes=meta.events_attributes if meta.events_attributes else {},
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
        events_attributes=info.events_attributes,
        object_attributes=info.object_attributes,
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
        print("Type :quit, :exit or Ctrl+C to exit.\n")

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

                append_instruction = globals().get("APPEND_INSTRUCTION")
                turn_messages = provider.build_user_turn(
                    user_text, append_instruction if append_instruction else ""
                )
                messages.extend(turn_messages)

                prompt_tokens = estimate_tokens(messages, args.model)
                print(f"Estimated prompt tokens: {prompt_tokens}")

                if not args.force:
                    try:
                        confirm = input("Send? [Y/n]: ").strip().lower()
                    except (KeyboardInterrupt, EOFError):
                        print("\nCancelled.")
                        for _ in turn_messages:
                            messages.pop()
                        continue
                    if confirm.lower() in {"n", "no"}:
                        print("Cancelled.")
                        for _ in turn_messages:
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
