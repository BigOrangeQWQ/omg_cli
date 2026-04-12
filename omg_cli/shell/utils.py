"""Utility functions for the shell TUI."""

from typing import Any

from omg_cli.types.message import Message
from omg_cli.utils import _format_arguments


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
