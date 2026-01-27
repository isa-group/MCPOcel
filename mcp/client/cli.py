"""Interactive MCP client to query an LLM about the OCEL schema."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Dict, List

import tiktoken

from .context import SchemaContext
from .providers import ProviderError, build_provider

DEFAULT_PROVIDER = "openai"
DEFAULT_MODEL = "GPT-5.2"
DEFAULT_SCHEMA_PATH = Path(__file__).resolve().parents[2] / "shared" / "schemas" / "ocel_2_0.json"

SYSTEM_PROMPT = (
    "Actua como experto en OCEL 2.0. Usa exclusivamente el contexto proporcionado. "
    "Si la informacion no esta en el contexto, pide el fragmento adecuado en lugar de inventar."
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
    parser.add_argument("-f", "--force", action="store_true", help="Omitir confirmacion de coste antes de enviar")
    return parser


def interactive_chat(args: argparse.Namespace) -> None:
    schema_path = Path(args.schema_path).resolve()
    if not schema_path.is_file():
        print(f"Schema not found at: {schema_path}")
        sys.exit(1)

    ctx = SchemaContext(schema_path)
    ctx.load()

    try:
        provider = build_provider(args.provider)
    except ProviderError as exc:
        print(f"Provider error: {exc}")
        sys.exit(1)

    base_messages: List[Dict[str, str]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "system", "content": ctx.as_context_block()},
    ]
    history: List[Dict[str, str]] = base_messages.copy()

    print(f"Provider: {args.provider} | Model: {args.model}")
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
