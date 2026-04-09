"""Tests for ConfigManager, focusing on TOML-based MCP server configuration."""

from pathlib import Path
import tempfile

import pytest

from omg_cli.config.manager import ConfigManager
from omg_cli.config.models import UserConfig
from omg_cli.mcp import MCPServerConfig


@pytest.fixture
def temp_config_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def manager(temp_config_dir: Path):
    return ConfigManager(config_dir=temp_config_dir)


class TestUserConfig:
    def test_load_save_user_config(self, manager: ConfigManager) -> None:
        config = UserConfig(default_model="gpt-4")
        manager.save_user_config(config)

        loaded = manager.load_user_config()
        assert loaded.default_model == "gpt-4"

    def test_user_config_defaults(self, manager: ConfigManager) -> None:
        loaded = manager.load_user_config()
        assert loaded.default_model is None


class TestMCPServers:
    def test_empty_mcp_servers(self, manager: ConfigManager) -> None:
        assert manager.list_mcp_servers() == []

    def test_add_and_get_mcp_server(self, manager: ConfigManager) -> None:
        server = MCPServerConfig(
            name="filesystem",
            type="stdio",
            command="npx",
            args=["-y", "@modelcontextprotocol/server-filesystem"],
        )
        manager.add_mcp_server(server)

        servers = manager.list_mcp_servers()
        assert len(servers) == 1
        assert servers[0].name == "filesystem"
        assert servers[0].type == "stdio"
        assert servers[0].command == "npx"
        assert servers[0].args == ["-y", "@modelcontextprotocol/server-filesystem"]

        fetched = manager.get_mcp_server("filesystem")
        assert fetched is not None
        assert fetched.name == "filesystem"

    def test_update_existing_mcp_server(self, manager: ConfigManager) -> None:
        manager.add_mcp_server(MCPServerConfig(name="remote", type="sse", url="https://old.example.com"))
        manager.add_mcp_server(MCPServerConfig(name="remote", type="sse", url="https://new.example.com"))

        servers = manager.list_mcp_servers()
        assert len(servers) == 1
        assert servers[0].url == "https://new.example.com"

    def test_mcp_servers_and_user_config_coexist(self, manager: ConfigManager) -> None:
        manager.save_user_config(UserConfig(default_model="claude-3-opus"))
        manager.add_mcp_server(MCPServerConfig(name="github", type="stdio", command="npx"))

        assert manager.load_user_config().default_model == "claude-3-opus"
        assert len(manager.list_mcp_servers()) == 1
        assert manager.get_mcp_server("github") is not None

    def test_codex_style_toml_parsing(self, manager: ConfigManager) -> None:
        """Verify that a Codex-style TOML snippet can be parsed directly."""
        toml_text = """
default_model = "gpt-4"

[mcp_servers.github]
type = "stdio"
command = "npx"
args = ["-y", "@modelcontextprotocol/server-github"]

[mcp_servers.github.env]
GITHUB_TOKEN = "secret"
"""
        manager.config_file.write_text(toml_text, encoding="utf-8")

        assert manager.load_user_config().default_model == "gpt-4"

        servers = manager.list_mcp_servers()
        assert len(servers) == 1
        assert servers[0].name == "github"
        assert servers[0].type == "stdio"
        assert servers[0].command == "npx"
        assert servers[0].env == {"GITHUB_TOKEN": "secret"}

    def test_toml_none_values_filtered(self, manager: ConfigManager) -> None:
        """Ensure None fields (e.g. url for stdio servers) are not written to TOML."""
        manager.add_mcp_server(MCPServerConfig(name="fs", type="stdio", command="npx"))

        raw = manager.config_file.read_text(encoding="utf-8")
        assert "url" not in raw
