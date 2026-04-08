"""Tool management protocol for ChatContext."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
import inspect
from typing import Any

from src.omg_cli.types.message import ToolCall
from src.omg_cli.types.tool import Tool, ToolError

type ToolConfirmationHandler = Callable[
    [ToolCall, Tool[Any]],
    "ToolConfirmationDecision | Awaitable[ToolConfirmationDecision]",
]


class ToolConfirmationDecision:
    """Decision for tool call confirmation."""

    def __init__(
        self,
        approved: bool,
        reason: str | None = None,
        next_steps: str | None = None,
        session_approved: bool = False,
    ) -> None:
        self.approved = approved
        self.reason = reason
        self.next_steps = next_steps
        self.session_approved = session_approved


class ToolManagerProtocol:
    """Protocol for managing tools and tool execution."""

    def __init__(self) -> None:
        self._tool_map: dict[str, Tool[Any]] = {}
        self._tool_confirmation_handler: ToolConfirmationHandler | None = None
        self._session_approve_all: bool = False

    def register_tool(self, tool: Tool[Any]) -> None:
        """Register a tool."""
        self._tool_map[tool.name] = tool

    def unregister_tool(self, name: str) -> bool:
        """Unregister a tool by name. Returns True if removed."""
        if name in self._tool_map:
            del self._tool_map[name]
            return True
        return False

    def get_tool(self, name: str) -> Tool[Any] | None:
        """Get a tool by name."""
        return self._tool_map.get(name)

    def list_tools(self) -> list[Tool[Any]]:
        """List all registered tools."""
        return list(self._tool_map.values())

    def set_tool_confirmation_handler(self, handler: ToolConfirmationHandler | None) -> None:
        """Set the handler for tool call confirmation."""
        self._tool_confirmation_handler = handler

    def _setup_tools(self, tools: Sequence[Tool[Any]]) -> None:
        """Setup initial tools."""
        for tool in tools:
            self.register_tool(tool)

    async def _confirm_tool_call(
        self,
        tool_call: ToolCall,
        tool: Tool[Any],
    ) -> ToolConfirmationDecision:
        """Confirm a tool call with the handler."""
        if self._session_approve_all:
            return ToolConfirmationDecision(approved=True)

        if self._tool_confirmation_handler is None:
            return ToolConfirmationDecision(
                approved=False,
                reason="No confirmation handler configured",
            )

        confirmation_result = self._tool_confirmation_handler(tool_call, tool)
        if inspect.isawaitable(confirmation_result):
            decision = await confirmation_result
        else:
            decision = confirmation_result

        if decision.approved and decision.session_approved:
            self._session_approve_all = True

        return decision

    async def _execute_tool(
        self,
        tool_call: ToolCall,
        emit_callback: Callable[[Any], Awaitable[None]] | None = None,
    ) -> Any:
        """Execute a single tool call.

        Args:
            tool_call: The tool call to execute
            emit_callback: Optional callback for emitting events

        Returns:
            The tool execution result

        Raises:
            ToolError: If tool execution fails
        """
        tool_name = tool_call.function.name
        tool = self._tool_map.get(tool_name)

        if tool is None:
            raise ToolError(f"Tool '{tool_name}' is not registered")

        if tool.confirm:
            decision = await self._confirm_tool_call(tool_call, tool)
            if not decision.approved:
                rejection: dict[str, Any] = {"error": "Tool call rejected by user"}
                if decision.reason:
                    rejection["reason"] = decision.reason
                if decision.next_steps:
                    rejection["next_steps"] = decision.next_steps
                return rejection

        try:
            return await tool(**tool_call.function.arguments)
        except ToolError:
            raise
        except Exception as exc:
            raise ToolError(f"Tool '{tool_name}' failed: {exc}") from exc
