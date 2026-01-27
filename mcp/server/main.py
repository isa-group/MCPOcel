"""Entry point for running the OCEL MCP server."""

import argparse
import sys
from pathlib import Path

# Ensure repo root is on sys.path when executed as a script (python main.py)
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp.server.mcp_ocel_server import run_mcp_server


def main() -> None:
    parser = argparse.ArgumentParser(
        description="MCP Server para análisis agnóstico de OCEL 2.0"
    )
    parser.add_argument(
        "--ocel-path",
        type=str,
        help="Ruta al archivo OCEL (prioridad sobre OCEL_FILE env var)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Habilitar DEBUG logging",
    )

    args = parser.parse_args()
    run_mcp_server(ocel_path=args.ocel_path, debug=args.debug)


if __name__ == "__main__":
    main()
