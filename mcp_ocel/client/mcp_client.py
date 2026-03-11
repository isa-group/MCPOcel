"""MCP Client to communicate with the OCEL MCP Server via HTTP (Streamable HTTP transport)."""

from __future__ import annotations

import asyncio
import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

import httpx

# Add parent directory to path for importing from server
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp_ocel.server.typing_ocel import ToolResponse

# Default server connection settings
DEFAULT_URL = "http://127.0.0.1:8000/mcp"


@dataclass
class OcelInfo:
    """OCEL metadata returned from the MCP server."""
    object_types: List[str]
    event_types: List[str]
    total_objects: int
    total_events: int
    start_date: str
    end_date: str
    events_attributes: Dict[str, List[str]] = None
    object_attributes: Dict[str, List[str]] = None

    def __post_init__(self):
        if self.events_attributes is None:
            self.events_attributes = {}
        if self.object_attributes is None:
            self.object_attributes = {}


class MCPClientError(Exception):
    """Error communicating with the MCP server."""


class MCPClient:
    """
    Async client to communicate with the MCP server via HTTP.
    
    Uses the Streamable HTTP transport for MCP communication.
    Designed to connect to an already-running server.
    
    Usage:
        async with MCPClient("http://localhost:8000/mcp") as client:
            tools = await client.list_tools()
            result = await client.call_tool("get_statistics_by_object_type", {})
    """

    def __init__(
        self,
        server_url: str = DEFAULT_URL,
        timeout: float = 30.0,
    ):
        """
        Initialize the MCP client.

        Args:
            server_url: MCP server endpoint URL (e.g., http://localhost:8000/mcp)
            timeout: Request timeout in seconds.
        """
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self._client: Optional[httpx.AsyncClient] = None
        self._request_id = 0
        self._session_id: Optional[str] = None

    async def connect(self) -> None:
        """Connect to the MCP server and initialize session.
        
        Raises:
            MCPClientError: If connection or initialization fails.
        """
        if self._client is not None:
            return

        try:
            self._client = httpx.AsyncClient(timeout=self.timeout)
            
            # Initialize MCP session
            result = await self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {
                    "name": "ocel-mcp-client",
                    "version": "0.1.0",
                },
            })
            
            # Send initialized notification
            await self._send_notification("notifications/initialized", {})
            
        except httpx.ConnectError as e:
            self._client = None
            raise MCPClientError(f"Failed to connect to {self.server_url}: {e}")
        except Exception as e:
            self._client = None
            raise MCPClientError(f"Failed to initialize MCP session: {e}")

    async def disconnect(self) -> None:
        """Disconnect from the MCP server."""
        if self._client is not None:
            try:
                await self._client.aclose()
            except Exception:
                pass
            self._client = None
            self._session_id = None

    async def _send_request(self, method: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Send a JSON-RPC 2.0 request over HTTP and wait for response."""
        if self._client is None:
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
            headers = {
                "Content-Type": "application/json",
                "Accept": "application/json, text/event-stream",
            }
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id
            
            response = await self._client.post(
                self.server_url,
                json=request,
                headers=headers,
            )
            
            # Store session ID if returned
            if "Mcp-Session-Id" in response.headers:
                self._session_id = response.headers["Mcp-Session-Id"]
            
            if response.status_code >= 400:
                raise MCPClientError(f"Server error {response.status_code}: {response.text}")
            
            # Handle SSE or JSON response
            content_type = response.headers.get("Content-Type", "")
            
            if "text/event-stream" in content_type:
                # Parse SSE response
                return await self._parse_sse_response(response.text)
            else:
                # Regular JSON response
                result = response.json()
                
                if "error" in result:
                    error = result["error"]
                    if isinstance(error, dict):
                        raise MCPClientError(f"Server error: {error.get('message', error)}")
                    raise MCPClientError(f"Server error: {error}")
                
                return result.get("result", {})

        except httpx.TimeoutException:
            raise MCPClientError("Request timed out")
        except json.JSONDecodeError as e:
            raise MCPClientError(f"Invalid JSON response: {e}")
        except MCPClientError:
            raise
        except Exception as e:
            raise MCPClientError(f"Communication error: {e}")

    async def _parse_sse_response(self, sse_text: str) -> Dict[str, Any]:
        """Parse SSE response and extract the result."""
        for line in sse_text.strip().split("\n"):
            if line.startswith("data:"):
                data = line[5:].strip()
                try:
                    result = json.loads(data)
                    if "error" in result:
                        error = result["error"]
                        if isinstance(error, dict):
                            raise MCPClientError(f"Server error: {error.get('message', error)}")
                        raise MCPClientError(f"Server error: {error}")
                    return result.get("result", {})
                except json.JSONDecodeError:
                    continue
        return {}

    async def _send_notification(self, method: str, params: Optional[Dict[str, Any]] = None) -> None:
        """Send a JSON-RPC 2.0 notification (no response expected)."""
        if self._client is None:
            raise MCPClientError("Not connected. Call connect() first.")

        request = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params:
            request["params"] = params

        try:
            headers = {"Content-Type": "application/json"}
            if self._session_id:
                headers["Mcp-Session-Id"] = self._session_id
            
            await self._client.post(
                self.server_url,
                json=request,
                headers=headers,
            )
        except Exception:
            # Notifications don't require response handling
            pass

    async def list_tools(self) -> List[Dict[str, Any]]:
        """List available tools from the server."""
        result = await self._send_request("tools/list")
        return result.get("tools", [])

    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> ToolResponse:
        """
        Call a tool on the server.
        
        Args:
            tool_name: Name of the tool to call
            arguments: Tool arguments
            
        Returns:
            Tool result as ToolResponse (one of the specific response TypedDicts)
        """
        result = await self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })
        
        # Extract content from MCP tool response format
        if isinstance(result, dict):
            content = result.get("content", [])
            if content and isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        try:
                            return json.loads(item.get("text", "{}"))
                        except json.JSONDecodeError:
                            return {"text": item.get("text", "")}
            # Return structured content if available
            if "structuredContent" in result:
                return result["structuredContent"]
        
        return result

    async def list_resources(self) -> List[Dict[str, Any]]:
        """List available resources from the server."""
        result = await self._send_request("resources/list")
        return result.get("resources", [])

    async def read_resource(self, uri: str) -> str:
        """
        Read a resource from the server.
        
        Args:
            uri: Resource URI (e.g., ocel://info)
            
        Returns:
            Resource content as string
        """
        result = await self._send_request("resources/read", {"uri": uri})
        
        contents = result.get("contents", [])
        if contents and isinstance(contents, list):
            content = contents[0]
            if isinstance(content, dict):
                return content.get("text", "")
        
        return ""

    async def get_ocel_info(self) -> OcelInfo:
        """Get OCEL metadata from the server."""
        content = await self.read_resource("ocel://info")
        data = json.loads(content) if content else {}
        
        return OcelInfo(
            object_types=data.get("object_types", []),
            event_types=data.get("event_types", []),
            total_objects=data.get("total_objects", 0),
            total_events=data.get("total_events", 0),
            start_date=data.get("start_date", "N/A"),
            end_date=data.get("end_date", "N/A"),
            events_attributes=data.get("events_attributes", {}),
            object_attributes=data.get("object_attributes", {}),
        )

    async def get_schema_section(self, section: str) -> Dict[str, Any]:
        """
        Get OCEL schema sections from the server.

        Args:
            section: Section to retrieve (eventTypes, objectTypes, events, objects, attributes)

        Returns:
            Dict with schema section data.
        """
        content = await self.read_resource(f"ocel://schema/{section}")
        return json.loads(content) if content else {}

    async def search_ocel(
        self,
        query: str,
        top_k: int = 5,
        chunk_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """
        Perform hybrid semantic search over OCEL data.

        Args:
            query: Natural language query to search for.
            top_k: Number of results to return (default: 5).
            chunk_types: Optional filter for chunk types.

        Returns:
            Dict with search results.
        """
        args = {"query": query, "top_k": top_k}
        if chunk_types:
            args["chunk_types"] = chunk_types
        return await self.call_tool("search_ocel", args)

    async def __aenter__(self) -> "MCPClient":
        await self.connect()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.disconnect()


# ============================================================================
# Sync wrapper for compatibility with existing code
# ============================================================================

class SyncMCPClient:
    """
    Synchronous wrapper over async MCPClient for compatibility.
    Runs async operations in an event loop.
    """
    
    def __init__(self, server_url: str = DEFAULT_URL, timeout: float = 30.0):
        self.server_url = server_url
        self.timeout = timeout
        self._async_client: Optional[MCPClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None

    def connect(self) -> None:
        """Connect to the server."""
        self._loop = asyncio.new_event_loop()
        self._async_client = MCPClient(self.server_url, self.timeout)
        self._loop.run_until_complete(self._async_client.connect())

    def disconnect(self) -> None:
        """Disconnect from the server."""
        if self._async_client and self._loop:
            self._loop.run_until_complete(self._async_client.disconnect())
            self._loop.close()
            self._async_client = None
            self._loop = None

    def list_tools(self) -> List[Dict[str, Any]]:
        if not self._async_client or not self._loop:
            raise MCPClientError("Not connected")
        return self._loop.run_until_complete(self._async_client.list_tools())

    def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> ToolResponse:
        """Call a tool on the server.
        
        Args:
            tool_name: Name of the tool to call.
            arguments: Tool arguments.
            
        Returns:
            ToolResponse from the server.
            
        Raises:
            MCPClientError: If not connected.
        """
        if not self._async_client or not self._loop:
            raise MCPClientError("Not connected")
        return self._loop.run_until_complete(self._async_client.call_tool(tool_name, arguments))

    def get_ocel_info(self) -> OcelInfo:
        if not self._async_client or not self._loop:
            raise MCPClientError("Not connected")
        return self._loop.run_until_complete(self._async_client.get_ocel_info())

    def get_schema_section(self, section: str) -> Dict[str, Any]:
        if not self._async_client or not self._loop:
            raise MCPClientError("Not connected")
        return self._loop.run_until_complete(self._async_client.get_schema_section(section))

    def search_ocel(
        self,
        query: str,
        top_k: int = 5,
        chunk_types: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        if not self._async_client or not self._loop:
            raise MCPClientError("Not connected")
        return self._loop.run_until_complete(
            self._async_client.search_ocel(query, top_k, chunk_types)
        )

    def __enter__(self) -> "SyncMCPClient":
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.disconnect()
