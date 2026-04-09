"""Configuration management for omg-cli."""

from omg_cli.config.adapter_manager import AdapterManager, get_adapter_manager
from omg_cli.config.constants import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_HISTORY_FILE,
    MAX_HISTORY_SIZE,
)
from omg_cli.config.history import InputHistory
from omg_cli.config.manager import ConfigManager, get_config_manager
from omg_cli.config.models import ModelConfig, ProviderType, UserConfig
from omg_cli.config.session_storage import SessionMetadata, SessionStorage

__all__ = [
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_HISTORY_FILE",
    "MAX_HISTORY_SIZE",
    "AdapterManager",
    "ConfigManager",
    "InputHistory",
    "ModelConfig",
    "ProviderType",
    "SessionMetadata",
    "SessionStorage",
    "UserConfig",
    "get_adapter_manager",
    "get_config_manager",
]
