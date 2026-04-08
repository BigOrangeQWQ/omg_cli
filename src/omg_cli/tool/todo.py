"""Todo.txt format protocol for task management."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Annotated, Any

from pydantic import Field, create_model
import pytodotxt

from src.omg_cli.types.tool import Tool, ToolError


@dataclass
class TodoList:
    items: list[pytodotxt.Task] = field(default_factory=list)

    def parse(self, content: str) -> None:
        self.items = []
        for ln in content.splitlines():
            if ln := ln.strip():
                t = pytodotxt.Task()
                t.parse(ln)
                self.items.append(t)


class TodoProtocol:
    """Protocol for todo list management. Inherit to use."""

    def __init__(self) -> None:
        self._todo_list = TodoList()

    def _sort_key(self, t: pytodotxt.Task) -> tuple:
        """Sort: completed last, then by priority A-Z, then no priority."""
        if t.is_completed:
            return (1, 26)
        return (0, ord(t.priority) - ord("A") if t.priority else 26)

    def _fmt(self, t: pytodotxt.Task, idx: int = 0) -> str:
        return f"{idx}. {'✓' if t.is_completed else '☐'} ({t.priority or ' '}) {t.bare_description() or ''}"

    def todo_tools(self) -> list[Tool[Any]]:
        """Return Tool instances bound to this protocol."""
        protocol = self

        async def set_todo(content: str) -> str:
            """Parse and load todo items from Todo.txt format.

            Replaces existing items. Supports:
            - Priority: (A) to (Z), highest to lowest
            - Projects: +projectname
            - Contexts: @context
            - Completed: x task description

            Example:
                (A) Submit report +work
                (B) Buy groceries @errands
                x Completed task

            Raises:
                ToolError: If content is empty or contains no valid tasks.
            """
            if not content or not content.strip():
                raise ToolError("Content cannot be empty")

            protocol._todo_list.parse(content)

            if not protocol._todo_list.items:
                raise ToolError("No valid todo items found. Expected format: '(A) Task description'")

            pending = sum(1 for t in protocol._todo_list.items if not t.is_completed)
            return f"Loaded {len(protocol._todo_list.items)} tasks ({pending} pending)"

        async def get_todo(limit: int = 5) -> str:
            """Get pending todo items sorted by priority (A highest to Z lowest).

            Format: "N. ☐ (P) Task description"
            - N: 1-based index (use for complete_todo)
            - ☐: Pending, ✓: Completed
            - P: Priority (A-Z) or space for none
            """
            tasks = sorted(
                [t for t in protocol._todo_list.items if not t.is_completed],
                key=protocol._sort_key,
            )[:limit]
            return "\n".join(protocol._fmt(t, i + 1) for i, t in enumerate(tasks)) or "No tasks."

        async def complete_todo(identifiers: str) -> str:
            """Mark todo items as completed by index or text match.

            Supports batch completion with comma-separated values.

            Matching order:
            1. Index: "1" or "1,2,3" (from get_todo output)
            2. Exact text match: "Submit report"
            3. Partial text match (only if unique): "report"

            Examples:
                "1"              - Complete task at index 1
                "1,3,5"          - Complete tasks 1, 3, and 5
                "Submit report"  - Complete by exact description
                "groceries"      - Complete by partial match (if unique)

            Raises:
                ToolError: If no tasks found for the given identifier(s).
            """
            items = protocol._todo_list.items
            ids = [s.strip() for s in identifiers.split(",")]
            completed: list[pytodotxt.Task] = []
            ambiguous: list[str] = []

            for ident in ids:
                task = None
                # Try index first
                try:
                    idx = int(ident) - 1
                    if 0 <= idx < len(items) and not items[idx].is_completed:
                        task = items[idx]
                except ValueError:
                    pass

                # Try exact match
                if task is None:
                    for t in items:
                        if not t.is_completed and t.bare_description() == ident:
                            task = t
                            break

                # Try partial match (only if unique)
                if task is None:
                    matches = [t for t in items if not t.is_completed and ident in (t.bare_description() or "")]
                    if len(matches) == 1:
                        task = matches[0]
                    elif len(matches) > 1:
                        ambiguous.append(ident)
                        continue

                if task:
                    task.is_completed = True
                    completed.append(task)

            # Report errors
            if ambiguous:
                raise ToolError(
                    f"Ambiguous identifier(s): {', '.join(repr(a) for a in ambiguous)}. Use exact text or index."
                )

            if not completed:
                raise ToolError(f"No pending tasks found for: {', '.join(repr(i) for i in ids)}")

            return "\n".join(
                [f"✅ Completed {len(completed)} task(s):"] + [f"  - {t.bare_description()}" for t in completed]
            )

        return [
            Tool(
                name="set_todo",
                description="Load todo items from Todo.txt format. "
                "Replaces existing items. Supports: (A) priority, +project, @context, x for completed.",
                params_model=create_model(
                    "SetTodoParams",
                    content=(Annotated[str, Field(description="Todo.txt content. One task per line.")], ...),
                ),
            ).bind(set_todo),
            Tool(
                name="get_todo",
                description="Get pending todo items sorted by priority (A-Z). "
                "Returns formatted list with indices for completion.",
                params_model=create_model(
                    "GetTodoParams",
                    limit=(Annotated[int, Field(default=5, description="Max tasks to return.")], 5),
                ),
            ).bind(get_todo),
            Tool(
                name="complete_todo",
                description="Complete todo items by indices (1,2,3) or text match. "
                "Batch: '1,2,3'. Exact match preferred over partial.",
                params_model=create_model(
                    "CompleteTodoParams",
                    identifiers=(
                        Annotated[str, Field(description="Indices (1,2,3) or text. Comma-separated for batch.")],
                        ...,
                    ),
                ),
            ).bind(complete_todo),
        ]
