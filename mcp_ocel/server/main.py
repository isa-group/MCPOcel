"""Entry point for running the OCEL MCP server."""

import argparse
import sys
from pathlib import Path
from dotenv import load_dotenv

# Ensure repo root is on sys.path when executed as a script (python main.py)
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_ocel.server.mcp_ocel_server import run_server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MCP Server for domain-agnostic OCEL 2.0 analysis"
    )
    parser.add_argument(
        "--ocel-path",
        type=str,
        help="Path to OCEL file (priority over OCEL_FILE env var)",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Host to bind (default: 127.0.0.1)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Port to listen on (default: 8000)",
    )
    parser.add_argument(
        "--transport",
        choices=["streamable-http", "sse", "stdio"],
        default="streamable-http",
        help="Transport mode (default: streamable-http)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable DEBUG logging",
    )

    args = parser.parse_args()
    run_server(
        host=args.host,
        port=args.port,
        ocel_path=args.ocel_path,
        debug=args.debug,
        transport=args.transport,
    )


if __name__ == "__main__":
    load_dotenv()
    main()
