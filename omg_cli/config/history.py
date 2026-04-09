"""Input history persistence for omg-cli."""

import json

from omg_cli.config.constants import DEFAULT_HISTORY_FILE, MAX_HISTORY_SIZE


class InputHistory:
    """Manages persistent input history for the terminal composer.

    Uses an append-only JSON Lines file for fast incremental writes.
    The file is truncated to the most recent max_size entries at startup.
    """

    def __init__(self, max_size: int = MAX_HISTORY_SIZE) -> None:
        self._max_size = max_size
        self._entries: list[str] = self._load()

    def _load(self) -> list[str]:
        """Load input history from disk (JSON Lines format).

        Truncates the file to max_size entries if it has grown beyond that.
        """
        entries: list[str] = []
        try:
            if DEFAULT_HISTORY_FILE.exists():
                with open(DEFAULT_HISTORY_FILE, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            entries.append(json.loads(line))
        except Exception:
            pass

        if len(entries) > self._max_size:
            entries = entries[-self._max_size :]
            try:
                DEFAULT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
                with open(DEFAULT_HISTORY_FILE, "w", encoding="utf-8") as f:
                    for entry in entries:
                        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            except Exception:
                pass

        return entries

    def _append(self, text: str) -> None:
        """Append a single entry to the history file."""
        try:
            DEFAULT_HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
            with open(DEFAULT_HISTORY_FILE, "a", encoding="utf-8") as f:
                f.write(json.dumps(text, ensure_ascii=False) + "\n")
        except Exception:
            pass

    def add(self, text: str) -> None:
        """Add a submitted text to the history."""
        if text and (not self._entries or self._entries[-1] != text):
            self._entries.append(text)
            self._append(text)

    @property
    def entries(self) -> list[str]:
        """Return a copy of the current history entries."""
        return self._entries.copy()
