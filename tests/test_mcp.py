"""Tests for MCP client integration using FastMCP."""

from unittest.mock import AsyncMock, MagicMock, patch

import mcp.types
import pytest

from omg_cli.mcp import (
    MCPClientWrapper,
    MCPServerConfig,
    _convert_tool_result,
)
from omg_cli.types.tool import ToolError


class TestMCPServerConfig:
    """Tests for MCPServerConfig."""

    def test_stdio_config_creation(self) -> None:
        """Test creating stdio server config."""
        config = MCPServerConfig(
            name="test-server",
            type="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem"],
            env={"KEY": "value"},
        )
        assert config.name == "test-server"
        assert config.type == "stdio"
        assert config.command == "npx"
        assert config.args == ["-y", "@modelcontextprotocol/server-filesystem"]
        assert config.env == {"KEY": "value"}

    def test_sse_config_creation(self) -> None:
        """Test creating SSE server config."""
        config = MCPServerConfig(
            name="sse-server",
            type="sse",
            url="http://localhost:3000/sse",
        )
        assert config.name == "sse-server"
        assert config.type == "sse"
        assert config.url == "http://localhost:3000/sse"

    def test_stdio_to_fastmcp_transport(self) -> None:
        """Test converting stdio config to FastMCP transport format."""
        config = MCPServerConfig(
            name="test-server",
            type="stdio",
            command="python",
            args=["server.py"],
            env={"FOO": "bar"},
        )
        transport = config.to_fastmcp_transport()
        assert transport == {
            "command": "python",
            "args": ["server.py"],
            "env": {"FOO": "bar"},
        }

    def test_sse_to_fastmcp_transport(self) -> None:
        """Test converting SSE config to FastMCP transport format."""
        config = MCPServerConfig(
            name="sse-server",
            type="sse",
            url="http://localhost:3000/sse",
        )
        transport = config.to_fastmcp_transport()
        assert transport == {"url": "http://localhost:3000/sse"}

    def test_unknown_transport_raises(self) -> None:
        """Test that unknown transport type raises ValueError."""
        config = MCPServerConfig(
            name="test",
            type="unknown",
        )
        with pytest.raises(ValueError, match="Unknown transport type: unknown"):
            config.to_fastmcp_transport()

    def test_default_values(self) -> None:
        """Test default values for MCPServerConfig."""
        config = MCPServerConfig(name="test")
        assert config.type == "stdio"
        assert config.args == []
        assert config.env == {}
        assert config.command is None
        assert config.url is None


class TestConvertToolResult:
    """Tests for _convert_tool_result function."""

    def test_text_content(self) -> None:
        """Test converting text content."""
        # Mock result with TextContent
        mock_result = MagicMock()
        mock_result.content = [mcp.types.TextContent(type="text", text="Hello, world!")]
        mock_result.is_error = False

        assert _convert_tool_result(mock_result) == "Hello, world!"

    def test_multiple_text_contents(self) -> None:
        """Test converting multiple text contents."""
        mock_result = MagicMock()
        mock_result.content = [
            mcp.types.TextContent(type="text", text="Line 1"),
            mcp.types.TextContent(type="text", text="Line 2"),
        ]
        mock_result.is_error = False

        assert _convert_tool_result(mock_result) == "Line 1\nLine 2"

    def test_image_content(self) -> None:
        """Test converting image content returns placeholder."""
        mock_result = MagicMock()
        mock_result.content = [
            mcp.types.ImageContent(type="image", data="base64data", mimeType="image/png"),
        ]
        mock_result.is_error = False

        assert "[Binary content received]" in _convert_tool_result(mock_result)

    def test_audio_content(self) -> None:
        """Test converting audio content returns placeholder."""
        mock_result = MagicMock()
        mock_result.content = [
            mcp.types.AudioContent(type="audio", data="base64data", mimeType="audio/wav"),
        ]
        mock_result.is_error = False

        assert "[Binary content received]" in _convert_tool_result(mock_result)

    def test_embedded_resource(self) -> None:
        """Test converting embedded resource returns placeholder."""
        mock_result = MagicMock()
        mock_result.content = [
            mcp.types.EmbeddedResource(
                type="resource",
                resource=mcp.types.TextResourceContents(
                    uri="file://test.txt",
                    mimeType="text/plain",
                    text="content",
                ),
            ),
        ]
        mock_result.is_error = False

        assert "[Embedded resource]" in _convert_tool_result(mock_result)

    def test_error_result_raises_tool_error(self) -> None:
        """Test that error result raises ToolError."""
        mock_result = MagicMock()
        mock_result.content = [mcp.types.TextContent(type="text", text="Something went wrong")]
        mock_result.is_error = True

        with pytest.raises(ToolError, match="Something went wrong"):
            _convert_tool_result(mock_result)

    def test_error_result_without_content(self) -> None:
        """Test error result with empty content."""
        mock_result = MagicMock()
        mock_result.content = []
        mock_result.is_error = True

        with pytest.raises(ToolError, match="Tool execution failed"):
            _convert_tool_result(mock_result)

    def test_unknown_content_type(self) -> None:
        """Test converting unknown content type falls back to str()."""

        class UnknownContent:
            def __str__(self) -> str:
                return "unknown content"

        mock_result = MagicMock()
        mock_result.content = [UnknownContent()]
        mock_result.is_error = False

        assert _convert_tool_result(mock_result) == "unknown content"


class TestMCPClientWrapper:
    """Tests for MCPClientWrapper."""

    def test_init(self) -> None:
        """Test client wrapper initialization."""
        config = MCPServerConfig(name="test-server", type="stdio", command="python")
        with patch("omg_cli.mcp.fastmcp.Client") as mock_client:
            wrapper = MCPClientWrapper(config)
            assert wrapper.name == "test-server"
            assert wrapper.tools == []
            mock_client.assert_called_once()

    def test_name_property(self) -> None:
        """Test name property returns config name."""
        config = MCPServerConfig(name="my-server", type="stdio", command="python")
        with patch("omg_cli.mcp.fastmcp.Client"):
            wrapper = MCPClientWrapper(config)
            assert wrapper.name == "my-server"

    def test_is_connected_property(self) -> None:
        """Test is_connected property delegates to client."""
        config = MCPServerConfig(name="test", type="stdio", command="python")
        with patch("omg_cli.mcp.fastmcp.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.is_connected.return_value = True
            mock_client_class.return_value = mock_client

            wrapper = MCPClientWrapper(config)
            assert wrapper.is_connected is True
            mock_client.is_connected.assert_called_once()

    @pytest.mark.asyncio
    async def test_connect_lists_tools(self) -> None:
        """Test connect lists tools from server."""
        config = MCPServerConfig(name="test", type="stdio", command="python")

        mock_tool = mcp.types.Tool(
            name="test_tool",
            description="A test tool",
            inputSchema={"type": "object", "properties": {}},
        )

        with patch("omg_cli.mcp.fastmcp.Client"):
            wrapper = MCPClientWrapper(config)
            # Directly set tools to simulate connect
            wrapper._tools = [mock_tool]

            assert len(wrapper.tools) == 1
            assert wrapper.tools[0].name == "test_tool"

    @pytest.mark.asyncio
    async def test_disconnect_clears_tools(self) -> None:
        """Test disconnect clears cached tools."""
        config = MCPServerConfig(name="test", type="stdio", command="python")

        with patch("omg_cli.mcp.fastmcp.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client.close = AsyncMock()
            mock_client_class.return_value = mock_client

            wrapper = MCPClientWrapper(config)
            wrapper._tools = [MagicMock()]  # Simulate cached tools

            await wrapper.disconnect()

            assert wrapper.tools == []
            mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_call_tool(self) -> None:
        """Test calling a tool through the wrapper."""
        config = MCPServerConfig(name="test", type="stdio", command="python")

        mock_result = MagicMock()
        mock_result.content = [mcp.types.TextContent(type="text", text="Tool result")]
        mock_result.is_error = False

        with patch("omg_cli.mcp.fastmcp.Client") as mock_client_class:
            # Setup async context manager mock
            mock_client_instance = AsyncMock()
            mock_client_instance.call_tool.return_value = mock_result
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

            wrapper = MCPClientWrapper(config)
            result = await wrapper.call_tool("my_tool", {"arg": "value"})

            assert result == "Tool result"

    def test_to_internal_tools(self) -> None:
        """Test converting MCP tools to internal Tool format."""
        config = MCPServerConfig(name="myserver", type="stdio", command="python")

        mock_tool = mcp.types.Tool(
            name="test_tool",
            description="A test tool",
            inputSchema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        )

        with patch("omg_cli.mcp.fastmcp.Client"):
            wrapper = MCPClientWrapper(config)
            wrapper._tools = [mock_tool]

            tools = wrapper.to_internal_tools()

            assert len(tools) == 1
            assert tools[0].name == "myserver_test_tool"
            assert "[myserver]" in tools[0].description
            assert "mcp" in tools[0].tags
            assert "myserver" in tools[0].tags

    @pytest.mark.asyncio
    async def test_tool_runner(self) -> None:
        """Test that created tool runner calls the tool correctly."""
        config = MCPServerConfig(name="test", type="stdio", command="python")

        mock_result = MagicMock()
        mock_result.content = [mcp.types.TextContent(type="text", text="Result")]
        mock_result.is_error = False

        with patch("omg_cli.mcp.fastmcp.Client") as mock_client_class:
            # Setup async context manager mock
            mock_client_instance = AsyncMock()
            mock_client_instance.call_tool.return_value = mock_result
            mock_client_class.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            mock_client_class.return_value.__aexit__ = AsyncMock(return_value=None)

            wrapper = MCPClientWrapper(config)
            runner = wrapper._create_tool_runner("my_tool")

            result = await runner(arg1="value1", arg2="value2")

            assert result == "Result"


class TestMCPClientWrapperEdgeCases:
    """Edge case tests for MCPClientWrapper."""

    @pytest.mark.asyncio
    async def test_connect_with_empty_tool_list(self) -> None:
        """Test connecting to server with no tools."""
        config = MCPServerConfig(name="empty", type="stdio", command="python")

        with patch("omg_cli.mcp.fastmcp.Client"):
            wrapper = MCPClientWrapper(config)
            # Directly set empty tools to simulate connect
            wrapper._tools = []

            assert wrapper.tools == []

    def test_tools_returns_copy(self) -> None:
        """Test that tools property returns a copy."""
        config = MCPServerConfig(name="test", type="stdio", command="python")

        with patch("omg_cli.mcp.fastmcp.Client"):
            wrapper = MCPClientWrapper(config)
            wrapper._tools = [MagicMock()]

            tools1 = wrapper.tools
            tools2 = wrapper.tools

            assert tools1 is not tools2
            assert tools1 == tools2
