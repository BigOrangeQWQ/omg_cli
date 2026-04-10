"""Channel configuration manager."""

from functools import lru_cache
from pathlib import Path
import tomllib
from typing import Any

import tomli_w

from omg_cli.config.constants import DEFAULT_CONFIG_DIR
from omg_cli.config.models import ChannelConfig


class ChannelManager:
    """Manages channel configurations independently from ConfigManager."""

    def __init__(self, config_dir: Path | None = None) -> None:
        self.config_dir = config_dir or DEFAULT_CONFIG_DIR
        self.config_file = self.config_dir / "config.toml"

    def _ensure_dir_exists(self) -> None:
        """Ensure config directory exists with secure permissions."""
        self.config_dir.mkdir(parents=True, exist_ok=True)
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

    def list_channels(self) -> list[ChannelConfig]:
        """List all configured channels."""
        data = self._load_toml()
        channels: list[ChannelConfig] = []
        channels_data = data.get("channels", {})
        if isinstance(channels_data, dict):
            for project_path, value in channels_data.items():
                channel_data = dict(value) if isinstance(value, dict) else {}
                channel_data["project_path"] = project_path
                try:
                    channels.append(ChannelConfig.model_validate(channel_data))
                except Exception:
                    continue
        return channels

    def save_channels(self, channels: list[ChannelConfig]) -> None:
        """Save channel configurations to TOML [channels.<project_path>] sections."""
        data = self._load_toml()

        if "channels" in data:
            del data["channels"]
        # Also migrate legacy key if present
        if "channel_defaults" in data:
            del data["channel_defaults"]

        channels_data: dict[str, dict[str, Any]] = {}
        for channel in channels:
            channels_data[channel.project_path] = channel.model_dump(exclude={"project_path"})

        if channels_data:
            data["channels"] = channels_data

        self._save_toml(data)

    def add_channel(self, channel: ChannelConfig) -> None:
        """Add or update a channel configuration."""
        channels = self.list_channels()
        channels = [c for c in channels if c.project_path != channel.project_path]
        channels.append(channel)
        self.save_channels(channels)

    def get_channel(self, project_path: str) -> ChannelConfig | None:
        """Get a channel configuration by project path."""
        for c in self.list_channels():
            if c.project_path == project_path:
                return c
        return None

    def get_channel_default_role(self, project_path: str) -> str | None:
        """Get the default role name for a given project path."""
        channel = self.get_channel(project_path)
        if channel is not None:
            return channel.default_role
        return None

    def set_channel_default_role(self, project_path: str, role_name: str) -> None:
        """Set the default role name for a given project path."""
        channel = self.get_channel(project_path)
        if channel is None:
            channel = ChannelConfig(project_path=project_path)
        channel.default_role = role_name
        self.add_channel(channel)

    def list_channel_defaults(self) -> dict[str, str]:
        """List all project-path to default-role mappings."""
        return {c.project_path: c.default_role for c in self.list_channels() if c.default_role is not None}

    def get_assigned_roles(self, project_path: str) -> list[str]:
        """Get assigned roles for a given project path."""
        channel = self.get_channel(project_path)
        if channel is not None:
            return list(channel.assigned_roles)
        return []

    def set_assigned_roles(self, project_path: str, roles: list[str]) -> None:
        """Set assigned roles for a given project path."""
        channel = self.get_channel(project_path)
        if channel is None:
            channel = ChannelConfig(project_path=project_path)
        channel.assigned_roles = list(roles)
        self.add_channel(channel)

    def add_assigned_role(self, project_path: str, role_name: str) -> None:
        """Add an assigned role for a given project path."""
        channel = self.get_channel(project_path)
        if channel is None:
            channel = ChannelConfig(project_path=project_path)
        if role_name not in channel.assigned_roles:
            channel.assigned_roles.append(role_name)
            self.add_channel(channel)

    def remove_assigned_role(self, project_path: str, role_name: str) -> None:
        """Remove an assigned role for a given project path."""
        channel = self.get_channel(project_path)
        if channel is None:
            return
        if role_name in channel.assigned_roles:
            channel.assigned_roles.remove(role_name)
            self.add_channel(channel)


@lru_cache(maxsize=1)
def get_channel_manager() -> ChannelManager:
    """Get the singleton ChannelManager instance."""
    return ChannelManager()
