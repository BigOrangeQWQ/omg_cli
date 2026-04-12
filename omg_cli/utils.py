import json
import random
import string
from typing import Any


def random_string(length: int) -> str:
    return "".join(random.choices(string.ascii_lowercase, k=length))


def snake_to_pascal(snake_str: str) -> str:
    components = snake_str.split("_")
    return "".join(x.title() for x in components)


def _format_arguments(arguments: dict[str, Any] | str, *, max_lines: int = 2) -> str:
    """Format tool arguments in a human-readable way.

    Args:
        arguments: Tool arguments as a dict or JSON string
        max_lines: Maximum number of lines to display (default 2, 0 for unlimited)

    Returns:
        Formatted string like "key: value\nkey2: value2"
    """
    if isinstance(arguments, str):
        if not arguments.strip():
            return ""
        try:
            arguments = json.loads(arguments)
        except json.JSONDecodeError:
            lines = arguments.split("\n")
            if max_lines > 0 and len(lines) > max_lines:
                return "\n".join(lines[-max_lines:])
            return arguments

    if not isinstance(arguments, dict):
        return str(arguments)

    lines = []
    for key, value in arguments.items():
        if isinstance(value, str):
            display_value = value[:100] + "…" if len(value) > 100 else value
            lines.append(f"{key}: {display_value}")
        elif isinstance(value, dict | list):
            compact = json.dumps(value, ensure_ascii=False)
            if len(compact) > 100:
                compact = compact[:100] + "…"
            lines.append(f"{key}: {compact}")
        else:
            lines.append(f"{key}: {value}")

    if max_lines > 0 and len(lines) > max_lines:
        lines = lines[-max_lines:]

    return "\n".join(lines)
