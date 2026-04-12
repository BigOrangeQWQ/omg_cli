import asyncio
from pathlib import Path
from typing import Any, ClassVar

from textual.binding import BindingType
from textual.containers import Vertical

from omg_cli.config.channel import get_channel_manager
from omg_cli.context.role import ChannelContext
from omg_cli.types.command import MetaCommand
from omg_cli.types.event import (
    BaseEvent,
    RoleActivityEvent,
    SessionMessageEvent,
    ThreadMessageEvent,
    ThreadSpawnedEvent,
    ThreadStatusChangedEvent,
)
from omg_cli.types.message import Message, TextSegment

from .channel_widgets import (
    InspectWidget,
    RoleSelectorDialog,
    ThreadCreateWidget,
    ThreadListView,
)
from .meta_app import MetaApp
from .role_wizard import RoleWizard
from .widgets import (
    ComposerTextArea,
    ContextFooter,
    MessageHistoryView,
)


class ChannelTerminalApp(MetaApp):
    BINDINGS: ClassVar[list[BindingType]] = [
        ("ctrl+l", "clear_session", "清空会话"),
        ("ctrl+c", "interrupt", "打断输出"),
        ("ctrl+d", "quit", "退出"),
    ]

    def __init__(self, channel_context: ChannelContext) -> None:
        super().__init__(channel_context.default_context)
        self.channel_context = channel_context
        self.active_thread_id = 0
        self._inspect_widget: InspectWidget | None = None
        self._register_channel_commands()

    def _register_channel_commands(self) -> None:
        app = self

        async def role_handler(ctx, args: str):
            await app._show_role_wizard()

        async def default_handler(ctx, args: str):
            await app._show_default_role_selector()

        async def thread_handler(ctx, args: str):
            await app._show_thread_create_widget()

        async def threads_handler(ctx, args: str):
            await app._show_thread_list()

        async def inspect_handler(ctx, args: str):
            parts = args.strip().split(maxsplit=1)
            if not parts:
                await ctx.logger.error("用法: /inspect [thread_id] <role_name>")
                return
            if len(parts) == 1:
                thread_id = app.active_thread_id
                role_name = parts[0]
            else:
                try:
                    thread_id = int(parts[0])
                except ValueError:
                    thread_id = app.active_thread_id
                    role_name = args.strip()
                else:
                    role_name = parts[1]
            thread = app.channel_context.thread_map.get(thread_id)
            if thread is None:
                await ctx.logger.error(f"Thread {thread_id} 不存在")
                return
            activities = thread.role_activities.get(role_name, [])
            await app._show_inspect_widget(thread_id, role_name, activities)

        def inspect_completer(ctx, prefix: str) -> list[str]:
            prefix_stripped = prefix.strip()
            parts = prefix_stripped.split(maxsplit=1)
            role_prefix = ""
            if len(parts) >= 1:
                if parts[0].isdigit():
                    role_prefix = parts[1] if len(parts) > 1 else ""
                else:
                    role_prefix = prefix_stripped
            return [
                r.name for r in app.channel_context.roles if r.name.lower().startswith(role_prefix.lower())
            ]

        self.context.register_command(
            MetaCommand(
                name="role",
                description="Create or configure a role",
                description_zh="创建或配置 Role",
                handler=role_handler,
            )
        )
        self.context.register_command(
            MetaCommand(
                name="default",
                description="Set the default role for this channel",
                description_zh="设置当前 Channel 的 Default Role",
                handler=default_handler,
            )
        )
        self.context.register_command(
            MetaCommand(
                name="thread",
                description="Create a new thread",
                description_zh="创建新 Thread",
                handler=thread_handler,
            )
        )
        self.context.register_command(
            MetaCommand(
                name="threads",
                description="Open thread list to switch",
                description_zh="打开 Thread 列表以切换",
                handler=threads_handler,
            )
        )
        self.context.register_command(
            MetaCommand(
                name="inspect",
                description="Inspect role activities in a thread",
                description_zh="查看线程中某个 Role 的动作记录",
                handler=inspect_handler,
                completer=inspect_completer,
            )
        )

    async def on_mount(self) -> None:
        await super().on_mount()
        await self.check_and_show_import_wizard()
        from omg_cli.config import get_config_manager

        if get_config_manager().has_models():
            await self._check_default_role()

    async def on_model_imported(self, model_name: str) -> None:
        await super().on_model_imported(model_name)
        await self._check_default_role()

    async def _check_default_role(self) -> None:
        project_path = str(Path.cwd())
        channel_manager = get_channel_manager()
        default_role = channel_manager.get_channel_default_role(project_path)
        if default_role:
            await self._load_channel(default_role)
            return

        if self.channel_context.roles:
            await self._show_default_role_selector()
        else:
            await self._show_role_wizard(exit_on_cancel=False)

    async def _hide_chat(self) -> None:
        self.query_one("#composer", ComposerTextArea).styles.display = "none"
        self.query_one("#messages", MessageHistoryView).styles.display = "none"

    async def _show_chat(self) -> None:
        self.query_one("#composer", ComposerTextArea).styles.display = "block"
        messages_view = self.query_one("#messages", MessageHistoryView)
        messages_view.styles.display = "block"
        self.refresh(layout=True)
        self._focus_composer()

    async def _mount_approval_widget(self, widget, *, focus: bool = True) -> None:
        await self._hide_chat()
        container = self.query_one("#approval-container", Vertical)
        await container.mount(widget)
        if focus:
            self.call_after_refresh(widget.focus)

    async def _show_default_role_selector(self) -> None:
        dialog = RoleSelectorDialog(self.channel_context.roles)
        await self._mount_approval_widget(dialog)
        selected = await dialog.wait()
        await self._show_chat()
        if selected is not None:
            project_path = str(Path.cwd())
            get_channel_manager().set_channel_default_role(project_path, selected.name)
            await self._load_channel(selected.name)
        elif not self.channel_context.default_role_name:
            await self._show_default_role_selector()

    async def _show_role_wizard(self, *, exit_on_cancel: bool = False) -> None:
        wizard = RoleWizard(exit_on_cancel=exit_on_cancel)
        await self._mount_approval_widget(wizard)

    async def on_role_wizard_completed(self, event: RoleWizard.Completed) -> None:
        if event.result is None and event.exit_on_cancel:
            self.exit()
            return
        await self._show_chat()
        if event.result is not None and event.result.is_new:
            # Auto-set as default if this is the first role ever created
            if not self.channel_context.default_role_name and not self.channel_context.roles:
                project_path = str(Path.cwd())
                get_channel_manager().set_channel_default_role(project_path, event.result.role_name)
                await self._load_channel(event.result.role_name)

    async def _load_channel(self, default_role_name: str) -> None:
        self.channel_context.set_default_role(default_role_name)
        footer = self.query_one(ContextFooter)
        footer.update_channel_status(default_role_name)
        await self.logger.info(f"Channel default role: {default_role_name}")

    async def _show_thread_create_widget(self) -> None:
        widget = ThreadCreateWidget(self.channel_context.roles)
        await self._mount_approval_widget(widget, focus=False)
        widget.focus()

    async def on_thread_create_widget_completed(self, event: ThreadCreateWidget.Completed) -> None:
        result = await self.channel_context.spawn_thread(
            event.title,
            event.description,
            event.assigned_roles,
        )
        thread = self.channel_context.thread_map.get(result.thread_id)
        if thread is not None and thread.messages and self.active_thread_id == thread.id:
            await self._mount_message(thread.messages[-1])
        await self._show_chat()

    async def on_thread_create_widget_cancelled(self, event: ThreadCreateWidget.Cancelled) -> None:
        await self._show_chat()

    async def _show_thread_list(self) -> None:
        existing = list(self.query("ThreadListView"))
        for widget in existing:
            if widget.is_mounted:
                await widget.remove()

        await self._hide_chat()
        if self.focused is not None:
            self.focused.blur()

        chat_panel = self.query_one("#chat-panel", Vertical)
        list_view = ThreadListView(list(self.channel_context.threads))
        await chat_panel.mount(list_view)
        list_view.focus()

    async def _hide_thread_list(self) -> None:
        existing = list(self.query("ThreadListView"))
        for widget in existing:
            if widget.is_mounted:
                await widget.remove()
        await self._show_chat()

    async def on_thread_list_view_thread_selected(self, event: ThreadListView.ThreadSelected) -> None:
        await self._hide_thread_list()
        await self._switch_to_thread(event.thread_id)

    async def on_thread_list_view_dismissed(self, event: ThreadListView.Dismissed) -> None:
        await self._hide_thread_list()

    async def _on_thread_spawned(self, event: ThreadSpawnedEvent) -> None:
        if event.thread.id not in self.channel_context.thread_map:
            self.channel_context.threads.append(event.thread)
            self.channel_context.thread_map[event.thread.id] = event.thread
            self.channel_context.thread_roles[event.thread.id] = {
                r.name: self.channel_context.role_contexts[r.name]
                for r in self.channel_context.roles
            }
        for list_view in self.query(ThreadListView):
            list_view.update_threads(list(self.channel_context.threads))
            list_view.set_selected_thread_id(event.thread.id)
            await list_view._refresh_items()
        await self._switch_to_thread(event.thread.id)
        if event.thread.id == self.active_thread_id:
            await self._mount_message(event.first_message)

    async def _on_user_message_submitted(self, text: str) -> None:
        if self.active_thread_id == 0:
            await super()._on_user_message_submitted(text)
            return

        composer = self.query_one(ComposerTextArea)
        composer.load_text("")
        self._sync_composer_height()

        message = Message(role="user", content=[TextSegment(text=text)])
        await self.channel_context.dispatch_to_thread(self.active_thread_id, message)
        await self._mount_message(message)

    async def _handle_context_event(self, event: BaseEvent) -> None:
        if isinstance(event, ThreadMessageEvent):
            thread = self._get_thread(event.thread_id)
            if thread is not None and event.message not in thread.messages:
                thread.messages.append(event.message)
            if self.active_thread_id == event.thread_id:
                await super()._handle_context_event(SessionMessageEvent(message=event.message))
            for list_view in self.query(ThreadListView):
                if list_view.is_mounted:
                    list_view.update_threads(list(self.channel_context.threads))
                    await list_view._refresh_items()
            return

        if isinstance(event, RoleActivityEvent):
            if self.active_thread_id == event.thread_id:
                variant = {
                    "error": "error",
                    "tool_call": "status",
                    "thinking": "status",
                    "stream": "status",
                    "status": "status",
                }.get(event.activity_type, "status")
                await self._mount_status(f"{event.content}", variant=variant)
            if (
                self._inspect_widget is not None
                and self._inspect_widget.is_mounted
                and self._inspect_widget.thread_id == event.thread_id
                and self._inspect_widget.role_name == event.role_name
            ):
                from omg_cli.types.channel import RoleActivityRecord
                self._inspect_widget.add_record(
                    RoleActivityRecord(activity_type=event.activity_type, content=event.content)
                )
            return

        if isinstance(event, SessionMessageEvent):
            thread = self._get_thread(0)
            if thread is not None and event.message not in thread.messages:
                thread.messages.append(event.message)
            if self.active_thread_id == 0:
                await super()._handle_context_event(event)
            return

        if isinstance(event, ThreadStatusChangedEvent):
            for list_view in self.query(ThreadListView):
                if list_view.is_mounted:
                    list_view.update_threads(list(self.channel_context.threads))
                    await list_view._refresh_items()
            return

        if isinstance(event, ThreadSpawnedEvent):
            await self._on_thread_spawned(event)
            return

        await super()._handle_context_event(event)

    async def _switch_to_thread(self, thread_id: int) -> None:
        await self.logger.debug(f"[_switch_to_thread] start thread_id={thread_id}")
        self.active_thread_id = thread_id
        messages_view = self.query_one("#messages", MessageHistoryView)
        thread = self._get_thread(thread_id)
        await self.logger.debug(
            f"[_switch_to_thread] thread={thread}, messages_count={len(thread.messages) if thread else 0}"
        )
        if thread is not None:
            await self.logger.debug(f"[_switch_to_thread] calling load_messages with {len(thread.messages)} messages")
            await messages_view.load_messages(thread.messages)
            await self.logger.debug(
                f"[_switch_to_thread] load_messages done, children_count={len(list(messages_view.children))}"
            )
        else:
            await self.logger.debug("[_switch_to_thread] no thread, removing children")
            await messages_view.remove_children()
        # Allow background Markdown renders to finish before final layout refresh
        await asyncio.sleep(0)
        messages_view.refresh(layout=True)
        messages_view.call_after_refresh(messages_view.scroll_end, animate=False)
        await self.logger.debug(
            f"[_switch_to_thread] done, messages_view region={messages_view.region}, size={messages_view.size}"
        )
        composer = self.query_one("#composer", ComposerTextArea)
        composer.placeholder = f"Thread #{thread_id} - Enter 发送..."

    def _get_thread(self, thread_id: int):
        return self.channel_context.thread_map.get(thread_id)


    async def _show_inspect_widget(self, thread_id: int, role_name: str, activities: list[Any]) -> None:
        await self._hide_inspect_widget()
        await self._hide_chat()
        chat_panel = self.query_one("#chat-panel", Vertical)
        self._inspect_widget = InspectWidget(thread_id, role_name)
        await chat_panel.mount(self._inspect_widget)
        self._inspect_widget.load_records(activities)

    async def _hide_inspect_widget(self) -> None:
        if self._inspect_widget is not None and self._inspect_widget.is_mounted:
            await self._inspect_widget.remove()
        self._inspect_widget = None
        await self._show_chat()

    async def on_inspect_widget_dismissed(self, event: InspectWidget.Dismissed) -> None:
        await self._hide_inspect_widget()
