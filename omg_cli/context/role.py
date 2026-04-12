import asyncio
from asyncio import TaskGroup
from collections.abc import Sequence
import contextvars
from pathlib import Path
import re
from typing import Any, Literal

from pydantic import BaseModel

from omg_cli.config.role import RoleManager, get_role_manager
from omg_cli.context.chat import ChatContext
from omg_cli.context.meta import MetaContext, tool_call_to_message
from omg_cli.log import logger
from omg_cli.prompts import render_plan_prompt, render_role_prompt
from omg_cli.types.channel import Role, RoleActivityRecord, Thread, ThreadStatus
from omg_cli.types.event import (
    BaseEvent,
    RoleActivityEvent,
    SessionErrorEvent,
    SessionMessageEvent,
    SessionStatusEvent,
    StatusLevel,
    ThreadMessageEvent,
    ThreadSpawnedEvent,
)
from omg_cli.types.message import Message, TextSegment, ToolCall
from omg_cli.types.skill import SkillRef
from omg_cli.types.tool import Tool, ToolError

_current_thread_id: contextvars.ContextVar[int] = contextvars.ContextVar("_current_thread_id")


class SpawnThreadArguments(BaseModel):
    title: str
    description: str
    assigned_roles: list[str]


class SpawnThreadResult(BaseModel):
    thread_id: int
    title: str
    status: str


class ChannelContext:
    def __init__(
        self,
        channel_name: str,
        provider: Any = None,
        system_prompt: str = "",
        roles: Sequence[Role] | None = None,
        threads: Sequence[Thread] | None = None,
        default_role_name: str | None = None,
    ):
        from omg_cli.config.channel import get_channel_manager
        from omg_cli.config.role import get_role_manager

        self.channel_name = channel_name

        self.roles = list(roles if roles is not None else get_role_manager().list_roles())
        self.role_contexts: dict[str, ThreadRoleContext] = {}
        for role in self.roles:
            self.initialize_role_context(role)

        self.threads = list(threads if threads is not None else [Thread(id=0, title="Default Thread", description="")])
        self.thread_map: dict[int, Thread] = {t.id: t for t in self.threads}

        self.thread_roles: dict[int, dict[str, ThreadRoleContext]] = {
            t.id: {r.name: self.role_contexts[r.name] for r in self.roles} for t in self.threads
        }

        self.default_role_name = default_role_name
        if self.default_role_name is None:
            self.default_role_name = get_channel_manager().get_channel_default_role(channel_name)

        self._bg_tasks: set[asyncio.Task] = set()
        self._spawn_thread_tool: Tool[Any] | None = None
        self._setup_spawn_thread_tool()
        self.initialize_default_role_context(provider=provider, system_prompt=system_prompt)
        self._register_default_context_tools()

    def initialize_role_context(self, role: Role) -> None:
        ctx = ThreadRoleContext(role=role)

        async def _forward_role_event(event: BaseEvent) -> None:
            thread_id = _current_thread_id.get(None)
            if thread_id is None:
                return
            if isinstance(event, SessionMessageEvent):
                await self.default_context._emit(ThreadMessageEvent(thread_id=thread_id, message=event.message))
            elif isinstance(event, SessionStatusEvent):
                if event.level < StatusLevel.INFO:
                    return
                self.record_role_activity(
                    thread_id=thread_id,
                    role_name=role.name,
                    activity_type="status",
                    content=event.detail or "",
                )
                await self.default_context._emit(
                    RoleActivityEvent(
                        thread_id=thread_id,
                        role_name=role.name,
                        activity_type="status",
                        content=event.detail or "",
                    )
                )
            elif isinstance(event, SessionErrorEvent):
                self.record_role_activity(
                    thread_id=thread_id,
                    role_name=role.name,
                    activity_type="error",
                    content=event.error,
                )
                await self.default_context._emit(
                    RoleActivityEvent(
                        thread_id=thread_id,
                        role_name=role.name,
                        activity_type="error",
                        content=event.error,
                    )
                )

        ctx.register_event_handler(BaseEvent, _forward_role_event)

        async def _send_message(thread_id: int, content: str) -> None:
            await self.send_message(role_name=role.name, thread_id=thread_id, content=content)

        class SendMessageArguments(BaseModel):
            thread_id: int
            content: str

        ctx.register_tool(
            Tool(
                name="sendMessage",
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
                name="getRecentMessages",
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
            token = _current_thread_id.set(thread_id)
            try:
                async with TaskGroup() as tg:
                    for mention in mentions:
                        ctx = self.thread_roles[thread_id].get(mention)
                        if ctx is not None and mention != role_name:
                            tg.create_task(ctx.send(message))
            finally:
                _current_thread_id.reset(token)

        self._spawn(_send_to_mentions())

        thread.messages.append(message)

    def add_thread(
        self,
        title: str,
        description: str = "",
        assigned_role_names: list[str] | None = None,
        reviewer_role_names: list[str] | None = None,
        parent_thread_id: int | None = None,
    ) -> Thread:
        next_id = max(self.thread_map.keys(), default=0) + 1
        thread = Thread(
            id=next_id,
            title=title,
            description=description,
            assigned_role_names=list(assigned_role_names or []),
            reviewer_role_names=list(reviewer_role_names or []),
            parent_thread_id=parent_thread_id,
        )
        self.threads.append(thread)
        self.thread_map[thread.id] = thread
        self.thread_roles[thread.id] = {r.name: self.role_contexts[r.name] for r in self.roles}
        return thread

    async def dispatch_to_thread(self, thread_id: int, message: Message) -> None:
        """Append a message to a thread and dispatch it to assigned roles."""
        thread = self.thread_map.get(thread_id)
        if thread is None:
            return

        if message not in thread.messages:
            thread.messages.append(message)

        if thread.status == ThreadStatus.DRAFT:
            thread.status = ThreadStatus.RUNNING

        assigned_roles = thread.assigned_role_names
        if not assigned_roles:
            return

        async def _notify_role(role_name: str) -> None:
            ctx = self.thread_roles[thread_id].get(role_name)
            if ctx is None:
                logger.warning(
                    f"Assigned role '{role_name}' not found for thread {thread_id} in channel '{self.channel_name}'"
                )
                return
            token = _current_thread_id.set(thread_id)
            try:
                logger.debug(f"Dispatching message to role '{role_name}' in thread {thread_id}: {message}")
                await ctx.send(message)
            finally:
                _current_thread_id.reset(token)

        for role_name in assigned_roles:
            logger.debug(f"Scheduling dispatch of message to role '{role_name}' in thread {thread_id}")
            self._spawn(_notify_role(role_name))

    async def spawn_thread(
        self,
        title: str,
        description: str,
        assigned_roles: list[str],
    ) -> SpawnThreadResult:
        logger.info(f"Spawning new thread with title '{title}' and assigned roles {assigned_roles}")
        valid_role_names = {r.name for r in self.roles}
        filtered_roles = [r for r in assigned_roles if r in valid_role_names]
        if not filtered_roles:
            raise ToolError("At least one valid role must be assigned to the thread.")

        thread = self.add_thread(
            title,
            description=description,
            assigned_role_names=filtered_roles,
        )
        self.thread_roles[thread.id] = {
            r.name: self.role_contexts[r.name] for r in self.roles if r.name in filtered_roles
        }
        first_message = self._generate_thread_first_message(thread)
        await self.dispatch_to_thread(thread.id, first_message)

        await self.default_context._emit(ThreadSpawnedEvent(thread=thread, first_message=first_message))

        return SpawnThreadResult(thread_id=thread.id, title=thread.title, status="created")

    def _generate_thread_first_message(self, thread: Thread) -> Message:
        """Generate the first message for a newly created thread."""
        TEMPLATE = f"""
# {thread.title}

ID: #{thread.id}

## Description:
{thread.description or "No description provided."}

## Assigned:
{", ".join(f"@{r}" for r in thread.assigned_role_names) if thread.assigned_role_names else "No roles assigned."}

After receiving the message, you **NEED** to cooperate with each other and divide the work.
"""
        return Message(
            role="user",
            content=[TextSegment(text=TEMPLATE.strip())],
        )

    def _register_default_context_tools(self) -> None:
        self.default_context.register_tool(self.spawn_thread_tool)

        async def _get_recent_messages(thread_id: int, limit: int = 10) -> list[Message]:
            return self.get_recent_messages(thread_id, limit)

        class GetRecentMessagesArguments(BaseModel):
            thread_id: int
            limit: int = 10

        self.default_context.register_tool(
            Tool(
                name="get_recent_messages",
                description="Retrieve the most recent messages from the specified thread.",
                params_model=GetRecentMessagesArguments,
            ).bind(_get_recent_messages)
        )

        async def _list_active_threads(limit: int = 10) -> list[dict[str, Any]]:
            sorted_threads = sorted(
                self.threads,
                key=lambda t: (len(t.messages), t.id),
                reverse=True,
            )[:limit]
            return [
                {
                    "id": t.id,
                    "title": t.title,
                    "status": t.status.value,
                    "message_count": len(t.messages),
                    "assigned_roles": t.assigned_role_names,
                }
                for t in sorted_threads
            ]

        class ListActiveThreadsArguments(BaseModel):
            limit: int = 10

        self.default_context.register_tool(
            Tool(
                name="listActiveThreads",
                description="List recently active threads in the channel with message counts and statuses.",
                params_model=ListActiveThreadsArguments,
            ).bind(_list_active_threads)
        )

        async def _list_available_roles() -> list[dict[str, Any]]:
            return [
                {
                    "name": r.name,
                    "description": r.desc,
                }
                for r in self.roles
            ]

        self.default_context.register_tool(
            Tool(
                name="listAvailableRoles",
                description="List all available roles in the channel for task assignment.",
                params_model=type("ListAvailableRolesArguments", (BaseModel,), {}),
            ).bind(_list_available_roles)
        )

    def initialize_default_role_context(self, provider: Any = None, system_prompt: str = "") -> None:
        default_role = None
        if self.default_role_name:
            default_role = next((r for r in self.roles if r.name == self.default_role_name), None)

        if default_role is not None:
            ctx_provider = default_role.adapter
            ctx_system_prompt = render_plan_prompt(
                role_name=default_role.name,
                role_description=default_role.desc,
                personal_space_path=default_role.personal_space,
                workdir=Path.cwd(),
            )
            self.default_context = ChatContext(provider=ctx_provider, system_prompt=ctx_system_prompt)
            if not default_role.adapter.thinking_supported:
                self.default_context.thinking_mode = False
            for tool_name in ("Shell", "WriteFile", "StrReplace"):
                self.default_context.unregister_tool(tool_name)
        else:
            self.default_context = ChatContext(provider=provider, system_prompt=system_prompt)

    def set_default_role(self, default_role_name: str) -> None:
        from omg_cli.config.role import get_role_manager

        self.roles = get_role_manager().list_roles()
        self.default_role_name = default_role_name
        self.role_contexts.clear()
        for role in self.roles:
            self.initialize_role_context(role)

        for thread in self.threads:
            self.thread_roles[thread.id] = {r.name: self.role_contexts[r.name] for r in self.roles}
        self.initialize_default_role_context()

    def _setup_spawn_thread_tool(self) -> None:
        self._spawn_thread_tool = Tool(
            name="spawnThread",
            description="Create a new thread in the channel with title, description and assigned roles.",
            params_model=SpawnThreadArguments,
            confirm=True,
            tags=frozenset({"channel"}),
        ).bind(self.spawn_thread)

    @property
    def spawn_thread_tool(self) -> Tool[Any]:
        if self._spawn_thread_tool is None:
            raise RuntimeError("spawn_thread_tool has not been initialized")
        return self._spawn_thread_tool

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

    def record_role_activity(
        self,
        thread_id: int,
        role_name: str,
        activity_type: Literal["thinking", "tool_call", "status", "error", "stream"],
        content: str,
    ) -> None:
        thread = self.thread_map.get(thread_id)
        if thread is None:
            return
        thread.role_activities.setdefault(role_name, []).append(
            RoleActivityRecord(activity_type=activity_type, content=content)
        )


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
        system_prompt = render_role_prompt(
            role_name=role.name,
            role_description=role.desc,
            personal_space_path=role.personal_space,
            workdir=Path.cwd(),
        )
        super().__init__(
            provider=role.adapter,
            system_prompt=system_prompt,
            tools=tools,
            messages=messages,
            skills=skills,
        )

    async def round(self, **kwargs) -> None:
        await self.logger.info(f"🤖 {self.role.name} 开始处理...")
        await super().round(**kwargs)
        await self.logger.info(f"🤖 {self.role.name} 处理完成")

    async def _run_single_tool_call(self, tool_call: ToolCall) -> Message:
        tool_name = tool_call.function.name
        await self.logger.info(f"🔧 {self.role.name} 调用工具: {tool_name}")

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

        result_summary = str(result)
        if len(result_summary) > 80:
            result_summary = result_summary[:77] + "..."
        await self.logger.success(f"✅ {self.role.name} 工具完成: {tool_name} → {result_summary}")
        return tool_call_to_message(tool_call, result)


__all__ = ["ChannelContext", "RoleManager", "ThreadRoleContext", "get_role_manager"]
