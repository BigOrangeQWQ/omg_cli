"""Utility functions for the shell TUI."""

import json
from typing import Any

from src.omg_cli.types.message import Message


def _build_message_title(message: Any) -> str:
    """Build the title for a message widget."""
    name = message.name or "AI"
    match message.role:
        case "assistant":
            return f"{name}"
        case "user":
            return ""
        case _:
            return f"{message.role} · {name}"


def _build_thinking_preview(thought_process: str, *, limit: int = 48) -> str:
    """Build a preview of thinking content."""
    single_line = " ".join(thought_process.split())
    if len(single_line) <= limit:
        return single_line or "空思考"
    return f"{single_line[:limit].rstrip()}…"


def _build_thinking_title(thought_process: str) -> str:
    """Build the title for a thinking widget."""
    preview = _build_thinking_preview(thought_process, limit=18)
    return f"> 思考 · {preview}"


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
            # For raw strings, truncate to max_lines lines
            lines = arguments.split("\n")
            if max_lines > 0 and len(lines) > max_lines:
                return "\n".join(lines[-max_lines:])
            return arguments

    if not isinstance(arguments, dict):
        return str(arguments)

    lines = []
    for key, value in arguments.items():
        # Format value based on type
        if isinstance(value, str):
            # Truncate long strings
            display_value = value[:100] + "…" if len(value) > 100 else value
            lines.append(f"{key}: {display_value}")
        elif isinstance(value, dict | list):
            compact = json.dumps(value, ensure_ascii=False)
            if len(compact) > 100:
                compact = compact[:100] + "…"
            lines.append(f"{key}: {compact}")
        else:
            lines.append(f"{key}: {value}")

    # Limit to max_lines, keeping the most recent (last) lines
    if max_lines > 0 and len(lines) > max_lines:
        lines = lines[-max_lines:]

    return "\n".join(lines)


def _format_message_for_copy(message: Message) -> str:
    """Format a message into readable plain text for copying."""
    parts: list[str] = []
    for segment in message.content:
        match segment:
            case segment if hasattr(segment, "text") and segment.type == "text":
                parts.append(segment.text)
            case segment if hasattr(segment, "thought_process") and segment.type == "think":
                parts.append("> Thinking:")
                parts.append(segment.thought_process)
            case segment if hasattr(segment, "tool_name") and segment.type == "tool":
                args = _format_arguments(segment.arguments or {}, max_lines=0)
                parts.append(f"> Tool: {segment.tool_name}")
                if args:
                    parts.append(args)
            case segment if hasattr(segment, "content") and segment.type == "tool_result":
                parts.append(f"> Result: {segment.tool_name}")
                parts.append(str(segment.content))
    return "\n".join(parts)
