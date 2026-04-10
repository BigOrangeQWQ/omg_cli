import asyncio
from asyncio import TaskGroup
from collections.abc import Sequence
from pathlib import Path
import re

from pydantic import BaseModel

from omg_cli.config.role import RoleManager, get_role_manager
from omg_cli.context.meta import MetaContext, tool_call_to_message
from omg_cli.prompts import render_role_prompt
from omg_cli.types.channel import Role, Thread
from omg_cli.types.event import SessionErrorEvent
from omg_cli.types.message import Message, TextSegment, ToolCall
from omg_cli.types.skill import SkillRef
from omg_cli.types.tool import Tool, ToolError


class ChannelContext:
    def __init__(
        self, channel_name: str, roles: Sequence[Role], threads: Sequence[Thread], default_role_name: str | None = None
    ):
        self.channel_name = channel_name
        self.roles = list(roles)

        self.role_contexts: dict[str, ThreadRoleContext] = {}
        for role in self.roles:
            self.initialize_role_context(role)

        self.threads = list(threads)
        self.thread_map: dict[int, Thread] = {t.id: t for t in self.threads}

        # TODO: Refactor to avoid this redundant mapping
        self.thread_roles: dict[int, dict[str, ThreadRoleContext]] = {
            t.id: {r.name: self.role_contexts[r.name] for r in self.roles} for t in self.threads
        }

        self.default_role_name = default_role_name
        self._bg_tasks: set[asyncio.Task] = set()

    def initialize_role_context(self, role: Role) -> None:
        ctx = ThreadRoleContext(role=role)

        async def _send_message(thread_id: int, content: str) -> None:
            await self.send_message(role_name=role.name, thread_id=thread_id, content=content)

        class SendMessageArguments(BaseModel):
            thread_id: int
            content: str

        ctx.register_tool(
            Tool(
                name="send_message",
                description="Send a message to the thread. \
                    This is the only way for the role to communicate with other roles.\
                    IMPORTANT: Messages will ONLY be received by \
                    other roles if you explicitly mention them using '@' in the content.",
                params_model=SendMessageArguments,
            ).bind(_send_message)
        )

        async def _get_recent_messages(thread_id: int, limit: int = 10) -> list[Message]:
            messages = self.get_recent_messages(thread_id, limit)
            return messages

        class GetRecentMessagesArguments(BaseModel):
            thread_id: int
            limit: int = 10

        ctx.register_tool(
            Tool(
                name="get_recent_messages",
                description="Retrieve the most recent messages from the current thread.",
                params_model=GetRecentMessagesArguments,
            ).bind(_get_recent_messages)
        )
        self.role_contexts[role.name] = ctx

    @staticmethod
    def _extract_mentions(content: str) -> list[str]:
        return re.findall(r"@(\w{1,14})\b", content)

    async def send_message(self, role_name: str, thread_id: int, content: str) -> None:
        thread = self.thread_map.get(thread_id)
        if thread is None:
            raise ValueError(f"Thread with id {thread_id} not found in channel '{self.channel_name}'")

        role = next((r for r in self.roles if r.name == role_name), None)
        if role is None:
            raise ValueError(f"Role with name '{role_name}' not found in channel '{self.channel_name}'")

        mentions = self._extract_mentions(content)

        message = Message(
            role="assistant",
            name=role_name,
            content=[TextSegment(text=content)],
        )

        async def _send_to_mentions():
            async with TaskGroup() as tg:
                for mention in mentions:
                    ctx = self.thread_roles[thread_id].get(mention)
                    if ctx is not None and mention != role_name:
                        tg.create_task(ctx.send(message))

        self._spawn(_send_to_mentions())

        thread.messages.append(message)

    def _spawn(self, coro) -> asyncio.Task:
        task = asyncio.create_task(coro)
        self._bg_tasks.add(task)
        task.add_done_callback(self._bg_tasks.discard)
        return task

    def get_recent_messages(self, thread_id: int, limit: int = 10) -> list[Message]:
        thread = self.thread_map.get(thread_id)
        if thread is None:
            raise ValueError(f"Thread with id {thread_id} not found in channel '{self.channel_name}'")
        if not thread.messages:
            return []
        return thread.messages[-limit:]


class ThreadRoleContext(MetaContext):
    """Sub-agent runtime container that auto-approves tool calls.

    RoleContext inherits MetaContext infrastructure and specializes it for
    unattended multi-agent execution inside a Channel.
    """

    def __init__(
        self,
        *,
        role: Role,
        tools: list[Tool] | None = None,
        messages: list[Message] | None = None,
        skills: list[SkillRef] | None = None,
    ) -> None:
        self.role = role
        super().__init__(
            provider=role.adapter,
            system_prompt=render_role_prompt(
                role_name=role.name,
                role_description=role.desc,
                personal_space_path=role.personal_space,
                workdir=Path.cwd(),
            ),
            tools=tools,
            messages=messages,
            skills=skills,
        )

    async def _run_single_tool_call(self, tool_call: ToolCall) -> Message:
        tool_name = tool_call.function.name
        await self.logger.debug(f"Tool call started: {tool_name}")

        tool = self._tool_map.get(tool_name)
        if tool is None:
            error_message = f"Tool '{tool_name}' is not registered"
            await self._emit(SessionErrorEvent(error=error_message))
            return tool_call_to_message(tool_call, {"error": error_message})

        try:
            result = await tool(**tool_call.function.arguments)
        except ToolError as exc:
            error_message = str(exc)
            await self._emit(SessionErrorEvent(error=f"Tool '{tool_name}' failed: {error_message}"))
            return tool_call_to_message(tool_call, {"error": error_message})
        except Exception as exc:
            error_message = f"Tool '{tool_name}' failed unexpectedly: {exc}"
            await self._emit(SessionErrorEvent(error=error_message))
            return tool_call_to_message(tool_call, {"error": str(exc)})

        await self.logger.debug(f"Tool call completed: {tool_name}")
        return tool_call_to_message(tool_call, result)


__all__ = ["ChannelContext", "RoleManager", "ThreadRoleContext", "get_role_manager"]
