"""MCP Client to communicate with the OCEL MCP Server via JSON-RPC 2.0 over TCP."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

# Default server connection settings
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9820


@dataclass
class OcelInfo:
    """OCEL metadata returned from the MCP server."""
    object_types: List[str]
    event_types: List[str]
    total_objects: int
    total_events: int
    start_date: str
    end_date: str


class MCPClientError(Exception):
    """Error communicating with the MCP server."""
    pass


class MCPClient:
    """Client to communicate with the MCP server via TCP socket (JSON-RPC 2.0)."""

    def __init__(
        self,
        host: str = DEFAULT_HOST,
        port: int = DEFAULT_PORT,
        timeout: float = 30.0,
    ):
        """
        Initialize the MCP client.

        Args:
            host: Server hostname or IP address.
            port: Server TCP port.
            timeout: Socket timeout in seconds.
        """
        self.host = host
        self.port = port
        self.timeout = timeout
        self._socket: Optional[socket.socket] = None
        self._request_id = 0

    def connect(self) -> None:
        """Connect to the MCP server."""
        if self._socket is not None:
            return

        try:
            self._socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._socket.settimeout(self.timeout)
            self._socket.connect((self.host, self.port))
        except socket.error as e:
            self._socket = None
            raise MCPClientError(f"Failed to connect to {self.host}:{self.port}: {e}")

    def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._socket is not None:
            try:
                self._socket.close()
            except Exception:
                pass
            self._socket = None

    def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a JSON-RPC 2.0 request and wait for response."""
        if self._socket is None:
            raise MCPClientError("Not connected. Call connect() first.")

        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
        }
        if params:
            request["params"] = params

        try:
            # Send request (newline-delimited JSON)
            message = json.dumps(request) + "\n"
            self._socket.sendall(message.encode("utf-8"))

            # Receive response (read until newline)
            buffer = b""
            while b"\n" not in buffer:
                chunk = self._socket.recv(4096)
                if not chunk:
                    raise MCPClientError("Connection closed by server")
                buffer += chunk

            response_line = buffer.split(b"\n")[0]
            response = json.loads(response_line.decode("utf-8"))

            if "error" in response:
                error = response["error"]
                if isinstance(error, dict):
                    raise MCPClientError(f"Server error: {error.get('message', error)}")
                raise MCPClientError(f"Server error: {error}")

            return response.get("result", {})

        except socket.timeout:
            raise MCPClientError("Request timed out")
        except json.JSONDecodeError as e:
            raise MCPClientError(f"Invalid JSON response: {e}")
        except MCPClientError:
            raise
        except Exception as e:
            raise MCPClientError(f"Communication error: {e}")

    def initialize(self) -> Dict[str, Any]:
        """Send initialize request to the server."""
        return self._send_request("initialize")

    def get_ocel_info(self) -> OcelInfo:
        """Get OCEL metadata from the server."""
        result = self._send_request("ocel/info")
        return OcelInfo(
            ocel_path=result.get("ocel_path", ""),
            object_types=result.get("object_types", []),
            event_types=result.get("event_types", []),
            total_objects=result.get("total_objects", 0),
            total_events=result.get("total_events", 0),
            start_date=result.get("start_date", "N/A"),
            end_date=result.get("end_date", "N/A"),
        )

    def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from the server."""
        result = self._send_request("tools/list")
        return result.get("tools", [])

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on the server."""
        return self._send_request("tools/call", {"name": tool_name, "arguments": arguments})

    def __enter__(self) -> "MCPClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()
