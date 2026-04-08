"""Configuration constants and paths for omg-cli."""

from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".omg_cli"
DEFAULT_MODELS_FILE = DEFAULT_CONFIG_DIR / "models.toml"
DEFAULT_CONFIG_FILE = DEFAULT_CONFIG_DIR / "config.toml"
DEFAULT_HISTORY_FILE = DEFAULT_CONFIG_DIR / "input_history.json"
MAX_HISTORY_SIZE = 200
