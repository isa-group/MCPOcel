"""Interactive MCP client to query an LLM about the OCEL schema."""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List

import tiktoken

from .context import SchemaContext
from .mcp_client import MCPClient, MCPClientError, OcelInfo, DEFAULT_HOST, DEFAULT_PORT
from .providers import ProviderError, build_provider

DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "GPT-5.2"
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "shared" / "schemas" / "ocel_2_0.json"


@dataclass
class OcelMetadata:
    """OCEL metadata for the system prompt."""
    object_types: List[str] = field(default_factory=list)
    event_types: List[str] = field(default_factory=list)
    total_objects: int = 0
    total_events: int = 0
    start_date: str = "N/A"
    end_date: str = "N/A"

SYSTEM_PROMPT_TEMPLATE = """
### ROLE & OBJECTIVE
You are an Expert in Object-Centric Process Mining (OCPM) analyzing OCEL 2.0 logs.
Your goal is to discover process inefficiencies, interactions, and flow patterns using the provided toolset.

### DYNAMIC CONTEXT (Current Loaded Log)
The following metadata describes the active dataset. USE ONLY these exact names for queries:
- **Object Types**: {object_types_list}
- **Event Types**: {event_types_list}
- **Log Stats**: {total_objects:,} objects, {total_events:,} events.
- **Time Range**: {start_date} to {end_date}.

### ANALYSIS GUIDELINES
1. **Multiplicity First**: Do not assume a single Case ID. Analyze how events link multiple objects (1:n, m:n relations).
2. **Cardinality**: Identify "Batching" (one event, many objects) vs. "Singular" flows.
3. **Graph Perspective**: Treat the log as a dynamic graph where objects are nodes and events are hyperedges.
4. **Performance**: Calculate throughput times per 'Object Type'.

### OUTPUT FORMAT
- Strict Markdown.
- When citing specific flows, refer to the Object Types defined in the Context above.
- If generating SQL/Python, ensure compatibility with the OCEL 2.0 relational schema (event_map, object_map).
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
    parser.add_argument("--schema-path", default=str(DEFAULT_SCHEMA_PATH), help="Path to OCEL schema JSON")
    parser.add_argument("--host", default=DEFAULT_HOST, help=f"MCP server host (default: {DEFAULT_HOST})")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help=f"MCP server port (default: {DEFAULT_PORT})")
    parser.add_argument("-f", "--force", action="store_true", help="Omitir confirmacion de coste antes de enviar")
    return parser


def fetch_metadata_from_server(host: str, port: int) -> OcelMetadata:
    """Connect to the MCP server and fetch OCEL metadata."""
    print(f"Connecting to MCP server at {host}:{port}...")
    try:
        with MCPClient(host=host, port=port) as client:
            client.initialize()
            info = client.get_ocel_info()
            return OcelMetadata(
                object_types=info.object_types,
                event_types=info.event_types,
                total_objects=info.total_objects,
                total_events=info.total_events,
                start_date=info.start_date,
                end_date=info.end_date,
            )
    except MCPClientError as e:
        print(f"Error connecting to MCP server: {e}")
        print(f"Make sure the server is running: python -m mcp.server --ocel-path <path>")
        sys.exit(1)


def interactive_chat(args: argparse.Namespace) -> None:
    schema_path = Path(args.schema_path).resolve()
    if not schema_path.is_file():
        print(f"Schema not found at: {schema_path}")
        sys.exit(1)

    ctx = SchemaContext(schema_path)
    ctx.load()

    # Get OCEL metadata from MCP server (always required)
    meta = fetch_metadata_from_server(args.host, args.port)
    print(f"  Object Types: {meta.object_types}")
    print(f"  Event Types: {meta.event_types}")
    print(f"  Objects: {meta.total_objects:,} | Events: {meta.total_events:,}")
    print(f"  Time Range: {meta.start_date} to {meta.end_date}")

    system_prompt = format_system_prompt(meta)

    try:
        provider = build_provider(args.provider)
    except ProviderError as exc:
        print(f"Provider error: {exc}")
        sys.exit(1)

    base_messages: List[Dict[str, str]] = [
        {"role": "system", "content": system_prompt},
        {"role": "system", "content": ctx.as_context_block()},
    ]
    history: List[Dict[str, str]] = base_messages.copy()

    print(f"\nProvider: {args.provider} | Model: {args.model}")
    print("Type :quit or Ctrl+C to exit.\n")

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
        history.extend([
            {"role": "user", "content": user_text},
            {"role": "assistant", "content": assistant_reply},
        ])


def main() -> None:
    parser = build_arg_parser()
    args = parser.parse_args()
    interactive_chat(args)


if __name__ == "__main__":
    main()
