"""MCP client integration using FastMCP."""

from typing import Any

import fastmcp
from fastmcp.client.client import CallToolResult
import mcp
from pydantic import BaseModel, Field

from src.omg_cli.log import logger
from src.omg_cli.types.tool import Tool, ToolError


def _convert_tool_result(result: CallToolResult) -> str:
    """Convert MCP tool result to string content."""
    parts: list[str] = []
    for part in result.content:
        match part:
            case mcp.types.TextContent(text=text):
                parts.append(text)
            case mcp.types.ImageContent() | mcp.types.AudioContent():
                # Binary content - return as data URI indicator
                parts.append("[Binary content received]")
            case mcp.types.EmbeddedResource():
                parts.append("[Embedded resource]")
            case _:
                parts.append(str(part))

    content = "\n".join(parts)
    if result.is_error:
        raise ToolError(content or "Tool execution failed")
    return content


class MCPServerConfig(BaseModel):
    """Configuration for an MCP server connection."""

    name: str
    """Display name for this server."""

    type: str = "stdio"
    """Transport type: 'stdio' for subprocess, 'sse' for HTTP SSE."""

    command: str | None = None
    """Command to run for stdio transport."""

    args: list[str] = Field(default_factory=list)
    """Arguments for the command."""

    url: str | None = None
    """URL for SSE transport."""

    env: dict[str, str] = Field(default_factory=dict)
    """Environment variables for the subprocess."""

    def to_fastmcp_transport(self) -> dict[str, Any]:
        """Convert config to FastMCP transport config."""
        match self.type:
            case "stdio":
                return {
                    "command": self.command,
                    "args": self.args,
                    "env": self.env,
                }
            case "sse":
                return {"url": self.url}
            case _:
                raise ValueError(f"Unknown transport type: {self.type}")


class MCPClientWrapper:
    """Wrapper around FastMCP Client for omg-cli integration."""

    def __init__(self, config: MCPServerConfig):
        self.config = config
        self._client = fastmcp.Client(config.to_fastmcp_transport())
        self._tools: list[mcp.types.Tool] = []

    @property
    def name(self) -> str:
        return self.config.name

    @property
    def is_connected(self) -> bool:
        return self._client.is_connected()

    @property
    def tools(self) -> list[mcp.types.Tool]:
        return self._tools.copy()

    async def connect(self) -> None:
        """Connect to MCP server and list available tools."""
        logger.debug(f"[MCPClient] Connecting to server: {self.config.name}")

        async with self._client as client:
            self._tools = await client.list_tools()

        logger.debug(f"[MCPClient] Connected to {self.config.name}, found {len(self._tools)} tools")

    async def disconnect(self) -> None:
        """Disconnect from MCP server."""
        await self._client.close()
        self._tools = []
        logger.debug(f"[MCPClient] Disconnected from {self.config.name}")

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Call an MCP tool and return result string."""
        async with self._client as client:
            result = await client.call_tool(tool_name, arguments, timeout=30, raise_on_error=False)
            return _convert_tool_result(result)

    def to_internal_tools(self) -> list[Tool[str]]:
        """Convert MCP tools to internal Tool format."""
        internal_tools: list[Tool[str]] = []

        for mcp_tool in self._tools:
            # Create unique tool name with server prefix
            tool_name = f"{self.config.name}_{mcp_tool.name}"

            # Create Tool directly from MCP inputSchema (no conversion needed)
            tool = Tool[str].from_parameters(
                name=tool_name,
                description=f"[{self.config.name}] {mcp_tool.description or ''}",
                parameters=mcp_tool.inputSchema,
                confirm=False,
                tags=frozenset({"mcp", self.config.name}),
            )

            # Bind the runner
            tool.bind(self._create_tool_runner(mcp_tool.name))
            internal_tools.append(tool)

        return internal_tools

    def _create_tool_runner(self, tool_name: str):
        """Create a runner function for an MCP tool."""

        async def runner(**kwargs):
            return await self.call_tool(tool_name, kwargs)

        return runner
