"""Configuration constants and paths for omg-cli."""

from pathlib import Path

DEFAULT_CONFIG_DIR = Path.home() / ".omg_cli"
DEFAULT_HISTORY_FILE = DEFAULT_CONFIG_DIR / "input_history.txt"
MAX_HISTORY_SIZE = 200
