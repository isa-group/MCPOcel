"""Standalone entrypoint for the MCP client CLI."""

from dotenv import load_dotenv
import sys
from pathlib import Path

# Ensure repo root is on sys.path when executed as a script (python main.py)
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from mcp_ocel.client.cli import main

if __name__ == "__main__":
    load_dotenv()
    main()
