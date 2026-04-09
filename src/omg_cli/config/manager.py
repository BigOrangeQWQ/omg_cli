"""Configuration manager for omg-cli."""

from pathlib import Path
import tomllib
from typing import Any

from pydantic_core import PydanticSerializationError
import tomli_w

from src.omg_cli.config.constants import DEFAULT_CONFIG_DIR
from src.omg_cli.config.models import ModelConfig, UserConfig
from src.omg_cli.mcp import MCPServerConfig


class ConfigManager:
    """Manages omg-cli configuration.

    Security model:
    - Config directory: 0o700 (only owner can access)
    - Config files: 0o600 (only owner can read/write)
    - API keys in memory: Protected by SecretStr (prevents accidental logging)
    """

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR
        self.models_file = self.config_dir / "models.toml"
        self.config_file = self.config_dir / "config.toml"

    def _ensure_dir_exists(self) -> None:
        """Ensure config directory exists with secure permissions."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
        # Set restrictive permissions: only owner can access (rwx------)
        self.config_dir.chmod(0o700)

    def _load_toml(self) -> dict[str, Any]:
        """Load the main TOML config file if it exists."""
        if not self.config_file.exists():
            return {}
        try:
            with open(self.config_file, "rb") as f:
                return tomllib.load(f)
        except Exception:
            return {}

    def _save_toml(self, data: dict[str, Any]) -> None:
        """Save the main TOML config file with secure permissions."""
        self._ensure_dir_exists()
        with open(self.config_file, "wb") as f:
            tomli_w.dump(data, f)
        self.config_file.chmod(0o600)

    def list_models(self) -> list[ModelConfig]:
        """List all configured models."""
        if not self.models_file.exists():
            return []

        try:
            with open(self.models_file, "rb") as f:
                data = tomllib.load(f)
            models_data = data.get("models", {})
            models: list[ModelConfig] = []
            for name, raw in models_data.items():
                if not isinstance(raw, dict):
                    continue
                model_data = dict(raw)
                model_data["name"] = name
                models.append(ModelConfig.from_storage_dict(model_data))
            return models
        except tomllib.TOMLDecodeError, TypeError, KeyError, PydanticSerializationError:
            return []

    def save_models(self, models: list[ModelConfig]) -> None:
        """Save models to file with secure permissions."""
        self._ensure_dir_exists()

        # Prepare data for storage: Codex-style [models.<name>] tables
        storage_data: dict[str, dict] = {}
        for m in models:
            entry = m.to_storage_dict()
            entry.pop("name", None)
            storage_data[m.name] = entry

        with open(self.models_file, "wb") as f:
            tomli_w.dump({"models": storage_data}, f)
        self.models_file.chmod(0o600)

    def add_model(self, model: ModelConfig) -> None:
        """Add a new model."""
        models = self.list_models()
        # Remove existing model with same name
        models = [m for m in models if m.name != model.name]
        models.append(model)
        self.save_models(models)

    def get_model(self, name: str) -> ModelConfig | None:
        """Get a model by name."""
        for m in self.list_models():
            if m.name == name:
                return m
        return None

    def has_models(self) -> bool:
        """Check if any models are configured."""
        return len(self.list_models()) > 0

    def load_user_config(self) -> UserConfig:
        """Load user configuration from TOML."""
        data = self._load_toml()
        return UserConfig(default_model=data.get("default_model"))

    def save_user_config(self, config: UserConfig) -> None:
        """Save user configuration to TOML, preserving MCP server sections."""
        data = self._load_toml()
        data["default_model"] = config.default_model
        self._save_toml(data)

    def get_default_model(self) -> ModelConfig | None:
        """Get the default model."""
        user_config = self.load_user_config()
        if user_config.default_model:
            return self.get_model(user_config.default_model)

        # If no default set, return first available model
        models = self.list_models()
        if models:
            return models[0]
        return None

    def set_default_model(self, name: str) -> bool:
        """Set the default model."""
        if self.get_model(name) is None:
            return False

        user_config = self.load_user_config()
        user_config.default_model = name
        self.save_user_config(user_config)
        return True

    # ------------------------------------------------------------------
    # MCP Servers (TOML format, Codex-compatible)
    # ------------------------------------------------------------------

    def list_mcp_servers(self) -> list[MCPServerConfig]:
        """List all configured MCP servers."""
        data = self._load_toml()
        servers: list[MCPServerConfig] = []

        # Standard nested format: [mcp_servers.<name>]
        mcp_data = data.get("mcp_servers", {})
        if isinstance(mcp_data, dict):
            for name, value in mcp_data.items():
                server_data = dict(value) if isinstance(value, dict) else {}
                server_data["name"] = name
                try:
                    servers.append(MCPServerConfig.model_validate(server_data))
                except Exception:
                    continue

        # Flat format fallback
        for key, value in data.items():
            if not key.startswith("mcp_servers."):
                continue
            name = key[len("mcp_servers.") :]
            if not name:
                continue
            server_data = dict(value) if isinstance(value, dict) else {}
            server_data["name"] = name
            try:
                servers.append(MCPServerConfig.model_validate(server_data))
            except Exception:
                continue

        return servers

    def save_mcp_servers(self, servers: list[MCPServerConfig]) -> None:
        """Save MCP server configurations to TOML [mcp_servers.<name>] sections."""
        data = self._load_toml()

        # Remove existing mcp_servers data (both nested and flat formats)
        if "mcp_servers" in data:
            del data["mcp_servers"]
        for key in list(data.keys()):
            if key.startswith("mcp_servers."):
                del data[key]

        # Add new mcp_servers in nested format
        mcp_data: dict[str, Any] = {}
        for server in servers:
            mcp_data[server.name] = {k: v for k, v in server.model_dump(exclude={"name"}).items() if v is not None}

        if mcp_data:
            data["mcp_servers"] = mcp_data

        self._save_toml(data)

    def add_mcp_server(self, server: MCPServerConfig) -> None:
        """Add a new MCP server configuration."""
        servers = self.list_mcp_servers()
        servers = [s for s in servers if s.name != server.name]
        servers.append(server)
        self.save_mcp_servers(servers)

    def get_mcp_server(self, name: str) -> MCPServerConfig | None:
        """Get an MCP server configuration by name."""
        for s in self.list_mcp_servers():
            if s.name == name:
                return s
        return None


# Global config manager instance
_config_manager: ConfigManager | None = None


def get_config_manager() -> ConfigManager:
    """Get the global config manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ConfigManager()
    return _config_manager
