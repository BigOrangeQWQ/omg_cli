"""MCP (Model Context Protocol) management protocol for ChatContext."""

from typing import Any

from src.omg_cli.log import logger
from src.omg_cli.mcp import MCPClientWrapper, MCPServerConfig
from src.omg_cli.types.tool import Tool


class MCPManagerProtocol:
    """Protocol for managing MCP server connections."""

    def __init__(self) -> None:
        self._mcp_clients: dict[str, MCPClientWrapper] = {}

    async def connect_mcp_server(self, config: MCPServerConfig) -> list[Tool[str]] | None:
        """Connect to an MCP server and return its tools.

        Returns:
            List of tools from the MCP server, or None if connection failed.
            Caller should register these tools using register_tool().
        """
        if config.name in self._mcp_clients:
            logger.warning(f"MCP server '{config.name}' is already connected")
            return None

        try:
            client = MCPClientWrapper(config)
            await client.connect()
            self._mcp_clients[config.name] = client

            tools = client.to_internal_tools()
            logger.info(f"MCP server '{config.name}' connected ({len(tools)} tools)")
            return tools
        except Exception as exc:
            logger.error(f"Failed to connect MCP server '{config.name}': {exc}")
            return None

    async def disconnect_mcp_server(self, name: str) -> list[str] | None:
        """Disconnect an MCP server.

        Returns:
            List of tool names that should be unregistered, or None if not found.
        """
        client = self._mcp_clients.pop(name, None)
        if client is None:
            return None

        # Return tool names to be unregistered by caller
        tool_names = [t.name for t in client.tools]
        await client.disconnect()
        logger.info(f"MCP server '{name}' disconnected")
        return tool_names

    async def disconnect_all_mcp_servers(self) -> list[str]:
        """Disconnect all MCP servers.

        Returns:
            Combined list of all tool names that should be unregistered.
        """
        all_tool_names: list[str] = []
        for name in list(self._mcp_clients.keys()):
            tool_names = await self.disconnect_mcp_server(name)
            if tool_names:
                all_tool_names.extend(tool_names)
        return all_tool_names

    async def initialize_mcp_servers(self, configs: list[MCPServerConfig] | None = None) -> list[Tool[str]]:
        """Load MCP server configs and auto-connect.

        Args:
            configs: List of MCP server configurations to connect.
                     If None, loads from config_manager automatically.

        Returns:
            Combined list of all tools from successfully connected servers.
        """
        all_tools: list[Tool[str]] = []

        if configs is None:
            from src.omg_cli.config import get_config_manager

            configs = get_config_manager().list_mcp_servers()

        if not configs:
            return all_tools

        logger.info(f"Initializing {len(configs)} MCP server(s)...")
        for config in configs:
            tools = await self.connect_mcp_server(config)
            if tools:
                all_tools.extend(tools)
        return all_tools

    def list_mcp_servers(self, configs: list[MCPServerConfig] | None = None) -> list[dict[str, Any]]:
        """List MCP servers with their connection status.

        Args:
            configs: Optional list of server configs to check status for.
                    If not provided, only shows connected servers.

        Returns:
            List of server status dictionaries.
        """
        result = []

        # If configs provided, show status for all configured servers
        if configs:
            for config in configs:
                client = self._mcp_clients.get(config.name)
                result.append(
                    {
                        "name": config.name,
                        "transport": config.type,
                        "connected": client is not None and client.is_connected,
                        "tool_count": len(client.tools) if client else 0,
                    }
                )
        else:
            # Only show connected servers
            for name, client in self._mcp_clients.items():
                result.append(
                    {
                        "name": name,
                        "transport": "unknown",  # Client doesn't store transport type
                        "connected": client.is_connected,
                        "tool_count": len(client.tools),
                    }
                )
        return result

    def get_mcp_client(self, name: str) -> MCPClientWrapper | None:
        """Get an MCP client by name."""
        return self._mcp_clients.get(name)

    def is_mcp_connected(self, name: str) -> bool:
        """Check if an MCP server is connected."""
        client = self._mcp_clients.get(name)
        return client is not None and client.is_connected
