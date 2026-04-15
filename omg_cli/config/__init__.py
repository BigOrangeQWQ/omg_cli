"""Configuration management for omg-cli."""

from omg_cli.config.adapter_manager import AdapterManager, get_adapter_manager
from omg_cli.config.channel import ChannelManager, get_channel_manager
from omg_cli.config.constants import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_HISTORY_FILE,
    MAX_HISTORY_SIZE,
)
from omg_cli.config.history import InputHistory
from omg_cli.config.manager import ConfigManager, get_config_manager
from omg_cli.config.models import ChannelConfig, ModelConfig, ProviderType, UserConfig
from omg_cli.config.role import RoleManager, get_role_manager
from omg_cli.config.session_storage import (
    ChannelSessionStorage,
    ChatSessionStorage,
    SessionMetadata,
    SessionStorageBase,
)

__all__ = [
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_HISTORY_FILE",
    "MAX_HISTORY_SIZE",
    "AdapterManager",
    "ChannelConfig",
    "ChannelManager",
    "ChannelSessionStorage",
    "ChatSessionStorage",
    "ConfigManager",
    "InputHistory",
    "ModelConfig",
    "ProviderType",
    "RoleManager",
    "SessionMetadata",
    "SessionStorageBase",
    "UserConfig",
    "get_adapter_manager",
    "get_channel_manager",
    "get_config_manager",
    "get_role_manager",
]
