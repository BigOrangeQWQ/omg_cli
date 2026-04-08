"""Configuration management for omg-cli."""

from src.omg_cli.config.adapter_manager import AdapterManager, get_adapter_manager
from src.omg_cli.config.constants import (
    DEFAULT_CONFIG_DIR,
    DEFAULT_CONFIG_FILE,
    DEFAULT_HISTORY_FILE,
    DEFAULT_MODELS_FILE,
    MAX_HISTORY_SIZE,
)
from src.omg_cli.config.history import InputHistory
from src.omg_cli.config.manager import ConfigManager, get_config_manager
from src.omg_cli.config.models import ModelConfig, ProviderType, UserConfig
from src.omg_cli.config.session_storage import SessionMetadata, SessionStorage

__all__ = [
    "DEFAULT_CONFIG_DIR",
    "DEFAULT_CONFIG_FILE",
    "DEFAULT_HISTORY_FILE",
    "DEFAULT_MODELS_FILE",
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
