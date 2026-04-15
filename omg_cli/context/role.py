import asyncio
from asyncio import TaskGroup
from collections.abc import Sequence
import contextvars
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from pydantic import BaseModel

from omg_cli.config.role import RoleManager, get_role_manager
from omg_cli.config.session_storage import ChannelSessionStorage, ChannelThreadMetadata, SessionMetadata
from omg_cli.context.chat import ChatContext
from omg_cli.context.meta import MetaContext, tool_call_to_message
from omg_cli.log import logger
from omg_cli.prompts import (
    render_plan_prompt,
    render_role_prompt,
    render_role_round_reminder_prompt,
)
from omg_cli.types.channel import Role, RoleActivityRecord, RoleActivityType, Thread, ThreadStatus
from omg_cli.types.event import (
    BaseEvent,
    RoleActivityEvent,
    SessionErrorEvent,
    SessionMessageEvent,
    SessionStatusEvent,
    StatusLevel,
    ThreadMessageEvent,
    ThreadSpawnedEvent,
    ThreadStatusChangedEvent,
)
from omg_cli.types.message import Message, TextSegment, ToolCall
from omg_cli.types.skill import SkillRef
from omg_cli.types.tool import Tool, ToolError
from omg_cli.utils import _format_arguments

_current_thread_id: contextvars.ContextVar[int] = contextvars.ContextVar("_current_thread_id")


class SpawnThreadArguments(BaseModel):
    title: str
    description: str
    assigned_roles: list[str]


class SpawnThreadResult(BaseModel):
    thread_id: int
    title: str
    status: str


class RecentMessage(BaseModel):
    role: str
    name: str | None
    content: str


class ActiveThread(BaseModel):
    id: int
    title: str
    status: str
    message_count: int
    assigned_roles: list[str]


class AvailableRole(BaseModel):
    name: str
    description: str


class UpdateThreadStatusArguments(BaseModel):
    thread_id: int
    status: str


class UpdateThreadStatusResult(BaseModel):
    thread_id: int
    status: str
    success: bool


class ChannelContext:
    def __init__(
        self,
        channel_name: str,
        roles: Sequence[Role] | None = None,
        threads: Sequence[Thread] | None = None,
        default_role_name: str | None = None,
        session_id: str | None = None,
        session_storage: ChannelSessionStorage | None = None,
    ):
        from omg_cli.config.channel import get_channel_manager
        from omg_cli.config.role import get_role_manager

        self.channel_name = channel_name
        self.session_id = session_id or str(uuid4())
        self._session_storage = session_storage or ChannelSessionStorage()
        self._session_metadata = SessionMetadata(
            session_id=self.session_id,
            chat_mode="channel",
            workspace=Path.cwd(),
        )
        self._session_storage.save_metadata(self._session_metadata)

        self.roles = list(roles if roles is not None else get_role_manager().list_roles())
        self.role_contexts: dict[str, ThreadRoleContext] = {}
        self._bg_tasks: set[asyncio.Task] = set()
        self._stalled_reminder_sent: set[int] = set()
        self._spawn_thread_tool: Tool[Any] | None = None

        self.default_role_name = default_role_name
        if self.default_role_name is None:
            self.default_role_name = get_channel_manager().get_channel_default_role(channel_name)

        self.initialize_default_role_context()

        self.threads = list(threads if threads is not None else [Thread(id=0, title="Default Thread", description="")])
        self.thread_map: dict[int, Thread] = {t.id: t for t in self.threads}

        for role in self.roles:
            self.initialize_role_context(role)

        self.thread_roles: dict[int, dict[str, ThreadRoleContext]] = {
            t.id: {r.name: self.role_contexts[r.name] for r in self.roles} for t in self.threads
        }

        self._persist_all_threads()

        self._setup_spawn_thread_tool()
        self._register_default_context_tools()

    def _persist_thread(self, thread_id: int) -> None:
        thread = self.thread_map.get(thread_id)
        if thread is None:
            return

        self._session_storage.save_thread_metadata(self.session_id, ChannelThreadMetadata.from_thread(thread))
        self._session_storage.save_messages(self.session_id, thread_id, thread.messages)

    def _persist_all_threads(self) -> None:
        for thread in self.threads:
            self._persist_thread(thread.id)

    def _persist_role_context(self, thread_id: int, role_name: str) -> None:
        thread_roles = self.thread_roles.get(thread_id)
        if thread_roles is None:
            return

        role_context = thread_roles.get(role_name)
        if role_context is None:
            return

        self._session_storage.save_role_context(
            self.session_id,
            role_name,
            thread_id,
            {
                "messages": [message.model_dump(mode="json") for message in role_context.messages],
                "display_messages": [message.model_dump(mode="json") for message in role_context.display_messages],
                "system_prompt": role_context.system_prompt,
                "role_name": role_context.role.name,
            },
        )

    def initialize_role_context(self, role: Role) -> MetaContext:
        ctx = ThreadRoleContext(role=role)

        async def _forward_role_event(event: BaseEvent) -> None:
            thread_id = _current_thread_id.get(None)
            if thread_id is None:
                return
            if isinstance(event, SessionMessageEvent):
                # Only send_message should produce ThreadMessageEvent.
                # All other role outputs are observed via RoleActivityEvent / inspect.
                if event.message.text:
                    self.record_role_activity(
                        thread_id=thread_id,
                        role_name=role.name,
                        activity_type="message",
                        content=event.message.text,
                    )
                    await self.default_context._emit(
                        RoleActivityEvent(
                            thread_id=thread_id,
                            role_name=role.name,
                            activity_type="message",
                            content=event.message.text,
                        )
                    )
                if event.message.thinking:
                    self.record_role_activity(
                        thread_id=thread_id,
                        role_name=role.name,
                        activity_type="thinking",
                        content=event.message.thinking,
                    )
                    await self.default_context._emit(
                        RoleActivityEvent(
                            thread_id=thread_id,
                            role_name=role.name,
                            activity_type="thinking",
                            content=event.message.thinking,
                        )
                    )
                return
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

        async def _send_message(thread_id: int, content: str) -> bool:
            try:
                success = await self.send_message(thread_id=thread_id, role_name=role.name, content=content)
                return success
            except Exception as exc:
                raise ToolError(f"Failed to send message: {exc}") from exc

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

        async def _get_recent_messages(thread_id: int, limit: int = 10) -> list[RecentMessage]:
            messages = self.get_recent_messages(thread_id, limit)
            return [
                RecentMessage(
                    role=msg.role,
                    name=msg.name,
                    content=msg.text,
                )
                for msg in messages
            ]

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

        return ctx

    @staticmethod
    def _extract_mentions(content: str) -> list[str]:
        return re.findall(r"@(\w{1,14})\b", content)

    def _dispatch_to_roles(self, thread_id: int, message: Message, role_names: list[str]) -> None:
        """Spawn background tasks to dispatch a message to specific roles in a thread."""

        async def _notify() -> None:
            token = _current_thread_id.set(thread_id)
            try:
                dispatched = []
                async with TaskGroup() as tg:
                    for role_name in role_names:
                        ctx = self.thread_roles[thread_id].get(role_name)
                        if ctx is None:
                            logger.warning(
                                f"Role '{role_name}' not found for thread {thread_id} in channel '{self.channel_name}'"
                            )
                            continue
                        logger.debug(f"Dispatching message to role '{role_name}' in thread {thread_id}: {message}")
                        ctx._round_has_effect = False
                        dispatched.append((role_name, ctx))
                        tg.create_task(ctx.send(message))

                any_effect = any(role_ctx._round_has_effect for _, role_ctx in dispatched)
                if dispatched and not any_effect:
                    thread = self.thread_map.get(thread_id)
                    if thread is not None and thread.status == ThreadStatus.RUNNING:
                        thread.status = ThreadStatus.STALLED
                        await self.default_context._emit(
                            ThreadStatusChangedEvent(
                                thread_id=thread_id,
                                status=thread.status.value.strip(),
                            )
                        )
                        for role_name, role_ctx in dispatched:
                            self.record_role_activity(
                                thread_id=thread_id,
                                role_name=role_name,
                                activity_type="status",
                                content=f"{role_name} finished without sending a message or updating thread status",
                            )
                        if thread_id not in self._stalled_reminder_sent:
                            reminder = Message(
                                role="system",
                                name="system",
                                content=[TextSegment(text=render_role_round_reminder_prompt())],
                            )
                            thread.messages.append(reminder)
                            await self.default_context._emit(ThreadMessageEvent(thread_id=thread_id, message=reminder))
                            self._stalled_reminder_sent.add(thread_id)
                            self._persist_thread(thread_id)
                            assigned_roles = thread.assigned_role_names
                            if assigned_roles:
                                self._dispatch_to_roles(thread_id, reminder, assigned_roles)
            finally:
                _current_thread_id.reset(token)

        self._spawn(_notify())

    async def send_message(self, thread_id: int, role_name: str, content: str) -> bool:
        """Publish a message from a role into a thread and dispatch to mentioned roles."""
        thread = self.thread_map.get(thread_id)
        if thread is None:
            raise ValueError(f"Thread with id {thread_id} not found in channel '{self.channel_name}'")

        target_role = next((r for r in self.roles if r.name == role_name), None)
        if target_role is None:
            raise ValueError(f"Role with name '{role_name}' not found in channel '{self.channel_name}'")

        message = Message(
            role="assistant",
            name=role_name,
            content=[TextSegment(text=content)],
        )

        thread.messages.append(message)
        if thread.status == ThreadStatus.STALLED:
            thread.status = ThreadStatus.RUNNING
            self._stalled_reminder_sent.discard(thread_id)
            await self.default_context._emit(
                ThreadStatusChangedEvent(
                    thread_id=thread_id,
                    status=thread.status.value.strip(),
                )
            )
        await self.default_context._emit(ThreadMessageEvent(thread_id=thread_id, message=message))
        self._persist_thread(thread_id)

        mentions = self._extract_mentions(content)
        if mentions:
            self._dispatch_to_roles(thread_id, message, [m for m in mentions if m != role_name])
        return True

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
        )
        self.threads.append(thread)
        self.thread_map[thread.id] = thread
        self.thread_roles[thread.id] = {r.name: self.role_contexts[r.name] for r in self.roles}
        self._persist_thread(thread.id)
        return thread

    async def dispatch_to_thread(self, thread_id: int, message: Message) -> None:
        """Append a message to a thread and dispatch it to assigned roles."""
        thread = self.thread_map.get(thread_id)
        if thread is None:
            return

        if message not in thread.messages:
            thread.messages.append(message)

        if thread.status in (ThreadStatus.DRAFT, ThreadStatus.STALLED):
            thread.status = ThreadStatus.RUNNING
            self._stalled_reminder_sent.discard(thread_id)
            await self.default_context._emit(
                ThreadStatusChangedEvent(
                    thread_id=thread_id,
                    status=thread.status.value.strip(),
                )
            )

        assigned_roles = thread.assigned_role_names
        if not assigned_roles:
            self._persist_thread(thread_id)
            return

        self._dispatch_to_roles(thread_id, message, assigned_roles)
        self._persist_thread(thread_id)

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
        for role_context in self.thread_roles[thread.id].values():
            self.fork_role_context_from_defaults(role_context)
            self._persist_role_context(thread.id, role_context.role.name)

        first_message = self._generate_thread_first_message(thread)
        await self.dispatch_to_thread(thread.id, first_message)

        await self.default_context._emit(ThreadSpawnedEvent(thread=thread, first_message=first_message))

        return SpawnThreadResult(thread_id=thread.id, title=thread.title, status="created")

    def _generate_thread_first_message(self, thread: Thread) -> Message:
        """Generate the first message for a newly created thread."""
        TEMPLATE = f"""
# #{thread.id} {thread.title}

ID: #{thread.id}

## Description:
{thread.description or "No description provided."}

## Assigned:
{", ".join(f"@{r}" for r in thread.assigned_role_names) if thread.assigned_role_names else "No roles assigned."}

After receiving the message, you **NEED** to cooperate with each other and divide the work.
"""
        return Message(
            role="assistant",
            name="system",
            content=[TextSegment(text=TEMPLATE.strip())],
        )

    def _register_default_context_tools(self) -> None:
        self.default_context.register_tool(self.spawn_thread_tool)

        async def _get_recent_messages(thread_id: int, limit: int = 10) -> list[RecentMessage]:
            messages = self.get_recent_messages(thread_id, limit)
            return [
                RecentMessage(
                    role=msg.role,
                    name=msg.name,
                    content=" ".join(str(segment) for segment in msg.content),
                )
                for msg in messages
            ]

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

        async def _list_active_threads(limit: int = 10) -> list[ActiveThread]:
            sorted_threads = sorted(
                self.threads,
                key=lambda t: (len(t.messages), t.id),
                reverse=True,
            )[:limit]
            return [
                ActiveThread(
                    id=t.id,
                    title=t.title,
                    status=t.status.value.strip(),
                    message_count=len(t.messages),
                    assigned_roles=t.assigned_role_names,
                )
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

        async def _list_available_roles() -> list[AvailableRole]:
            return [
                AvailableRole(
                    name=r.name,
                    description=r.desc,
                )
                for r in self.roles
            ]

        self.default_context.register_tool(
            Tool(
                name="listAvailableRoles",
                description="List all available roles in the channel for task assignment.",
                params_model=type("ListAvailableRolesArguments", (BaseModel,), {}),
            ).bind(_list_available_roles)
        )

        async def _update_thread_status(thread_id: int, status: ThreadStatus) -> bool:
            thread = self.thread_map.get(thread_id)
            if thread is None:
                raise ToolError(f"Thread {thread_id} not found")
            status_clean = status.strip().lower()
            for ts in ThreadStatus:
                if ts.value.strip() == status_clean:
                    thread.status = ts
                    break
            else:
                valid = [s.value.strip() for s in ThreadStatus]
                raise ToolError(f"Invalid status '{status}'. Valid: {', '.join(valid)}")
            await self.default_context._emit(
                ThreadStatusChangedEvent(
                    thread_id=thread.id,
                    status=thread.status.value.strip(),
                )
            )
            return True

        self.default_context.register_tool(
            Tool(
                name="updateThreadStatus",
                description="Update the status of a thread. Valid statuses: draft, running, review, done, error.",
                params_model=UpdateThreadStatusArguments,
            ).bind(_update_thread_status)
        )

    @classmethod
    def from_session(
        cls,
        session_id: str,
        *,
        session_storage: ChannelSessionStorage | None = None,
        roles: Sequence[Role] | None = None,
    ) -> "ChannelContext":
        from omg_cli.config.channel import get_channel_manager

        storage = session_storage or ChannelSessionStorage()
        metadata = storage.load_metadata(session_id)
        if metadata is None:
            raise ValueError(f"Session '{session_id}' not found")

        default_role_name = get_channel_manager().get_channel_default_role(str(metadata.workspace))
        if roles:
            role_names = {role.name for role in roles}
            if default_role_name not in role_names:
                default_role_name = roles[0].name
        if default_role_name is None:
            raise ValueError(f"Session '{session_id}' cannot be restored without a default role")

        threads_metadata = storage.list_thread_metadata(session_id)
        threads: list[Thread] = []
        for thread_metadata in threads_metadata:
            thread = Thread(
                id=thread_metadata.thread_id,
                title=thread_metadata.title,
                description=thread_metadata.description,
                assigned_role_names=list(thread_metadata.assigned_role_names),
                reviewer_role_names=list(thread_metadata.reviewer_role_names),
                status=ThreadStatus(thread_metadata.status),
                created_at=thread_metadata.created_at,
            )
            thread.messages = storage.load_messages(session_id, thread.id)
            thread.role_activities = {}
            threads.append(thread)

        context = cls(
            channel_name=str(metadata.workspace),
            roles=roles,
            threads=threads,
            default_role_name=default_role_name,
            session_id=session_id,
            session_storage=storage,
        )

        for thread in context.threads:
            thread.role_activities = {}
            for role_name in context.thread_roles.get(thread.id, {}):
                activities = storage.load_role_activities(session_id, role_name, thread.id)
                if activities:
                    thread.role_activities[role_name] = list(activities)

        return context

    def initialize_default_role_context(self) -> None:
        default_role = None
        if self.default_role_name:
            default_role = next((r for r in self.roles if r.name == self.default_role_name), None)

        old_context = getattr(self, "default_context", None)

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
            raise ValueError("Default role not found and cannot initialize default context")

        if old_context is not None:
            self.default_context._event_manager.copy_handlers_from(old_context._event_manager)

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
        self._persist_all_threads()

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

    def fork_role_context_from_defaults(self, role: MetaContext) -> None:
        role.messages.extend(self.default_context.messages)

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
        activity_type: RoleActivityType,
        content: str,
    ) -> None:
        thread = self.thread_map.get(thread_id)
        if thread is None:
            return
        record = RoleActivityRecord(activity_type=activity_type, content=content)
        thread.role_activities.setdefault(role_name, []).append(record)
        self._session_storage.append_role_activity(self.session_id, role_name, thread_id, record)


class ThreadRoleContext(MetaContext):
    """Sub-agent runtime container that auto-approves tool calls.

    RoleContext inherits MetaContext infrastructure and specializes it for
    unattended multi-agent execution inside a Channel.
    """

    role: Role
    _round_has_effect: bool

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
        self._round_has_effect = False

    async def round(self, **kwargs) -> None:
        await self.logger.info(f"🤖 {self.role.name} 开始处理...")
        self._round_has_effect = False
        await super().round(**kwargs)
        await self.logger.info(f"🤖 {self.role.name} 处理完成")

    async def _run_single_tool_call(self, tool_call: ToolCall) -> Message:
        tool_name = tool_call.function.name
        if tool_name in {"send_message", "updateThreadStatus"}:
            self._round_has_effect = True
        args_str = _format_arguments(tool_call.function.arguments, max_lines=0)
        await self.logger.info(f"🔧 {self.role.name} 调用工具: {tool_name} | 参数: {args_str}")

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

        await self.logger.success(f"✅ {self.role.name} 工具完成: {tool_name}")
        return tool_call_to_message(tool_call, result)


__all__ = ["ChannelContext", "RoleManager", "ThreadRoleContext", "get_role_manager"]
