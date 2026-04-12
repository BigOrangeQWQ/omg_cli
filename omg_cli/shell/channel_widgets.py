import asyncio
import re
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.message import Message
from textual.widget import Widget
from textual.widgets import Button, Input, ListItem, ListView, TextArea

from omg_cli.types.channel import Channel, Role, Thread, ThreadStatus

from .widgets import SafeStatic


class RoleSelectorDialog(Vertical):
    """Dialog for selecting the default role in Channel mode."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "select", "Select"),
    ]

    def __init__(self, roles: list[Role]) -> None:
        super().__init__(classes="role-selector-dialog")
        self.roles = roles
        self._future: asyncio.Future[Role | None] | None = None
        self._list_view: ListView | None = None

    def _get_future(self) -> asyncio.Future[Role | None]:
        if self._future is None:
            self._future = asyncio.Future()
        return self._future

    def compose(self) -> ComposeResult:
        yield SafeStatic("选择默认 Role", classes="role-selector-title")
        yield SafeStatic("该 Role 将负责接收你的消息并拆分任务", classes="role-selector-hint")
        with ListView(id="role-selector-list") as list_view:
            self._list_view = list_view
            for role in self.roles:
                display = f"{role.name} - {role.desc}" if role.desc else role.name
                yield ListItem(SafeStatic(display), classes="role-selector-item")

    def on_mount(self) -> None:
        if self._list_view is not None:
            self._list_view.index = 0
            self._list_view.focus()

    def action_cursor_up(self) -> None:
        if self._list_view is not None:
            self._list_view.action_cursor_up()

    def action_cursor_down(self) -> None:
        if self._list_view is not None:
            self._list_view.action_cursor_down()

    async def action_select(self) -> None:
        await self._confirm()

    async def on_list_view_selected(self, _event: ListView.Selected) -> None:
        await self._confirm()

    async def _confirm(self) -> None:
        if self._list_view is None:
            await self._resolve(None)
            return
        index = self._list_view.index
        if index is None or not (0 <= index < len(self.roles)):
            await self._resolve(None)
            return
        await self._resolve(self.roles[index])

    async def _resolve(self, role: Role | None) -> None:
        future = self._get_future()
        if not future.done():
            future.set_result(role)
        await self.remove()

    async def wait(self) -> Role | None:
        return await self._get_future()


class MentionPalette(ListView):
    """Popup for @-mentioning roles inside planning inputs."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "select", "Select"),
        ("ctrl+c", "dismiss", "Cancel"),
        ("escape", "dismiss", "Dismiss"),
    ]

    def __init__(self, roles: list[Role]) -> None:
        super().__init__(classes="mention-palette", id="mention-palette")
        self.roles = roles
        self.role_names = [r.name for r in roles]
        self._future: asyncio.Future[str | None] | None = None
        self._current_prefix: str = ""

    def _get_future(self) -> asyncio.Future[str | None]:
        if self._future is None:
            self._future = asyncio.Future()
        return self._future

    def compose(self) -> ComposeResult:
        for role in self.roles:
            yield ListItem(SafeStatic(f"@{role.name}"), classes="mention-item")

    def update_prefix(self, prefix: str) -> None:
        self._current_prefix = prefix.lower()
        self.clear()
        matches = [name for name in self.role_names if name.lower().startswith(self._current_prefix)]
        for name in matches:
            self.append(ListItem(SafeStatic(f"@{name}"), classes="mention-item"))
        if matches:
            self.styles.display = "block"
            self.index = 0
        else:
            self.styles.display = "none"

    def action_select(self) -> None:
        self._confirm()

    def action_dismiss(self) -> None:
        self._resolve(None)

    def on_list_view_selected(self, _event: ListView.Selected) -> None:
        self._confirm()

    def _confirm(self) -> None:
        highlighted = self.highlighted_child
        if highlighted is None:
            self._resolve(None)
            return
        index = self.index
        if index is None or not (0 <= index < len(self.children)):
            self._resolve(None)
            return
        # Find actual text from the ListItem's Static child
        for child in self.children[index].walk_children():
            if isinstance(child, SafeStatic):
                text = child.render().plain
                self._resolve(text.lstrip("@"))
                return
        self._resolve(None)

    def _resolve(self, role_name: str | None) -> None:
        future = self._get_future()
        if not future.done():
            future.set_result(role_name)
        self.styles.display = "none"

    async def wait(self) -> str | None:
        return await self._get_future()


def _thread_create_parent(widget: Widget) -> "ThreadCreateWidget | None":
    parent = widget.parent
    if isinstance(parent, ThreadCreateWidget):
        return parent
    return None


class _ThreadTitleInput(Input):
    """Input for thread title with Ctrl+C cancel support."""

    async def _on_key(self, event) -> None:
        parent = _thread_create_parent(self)
        if event.key == "ctrl+c" and parent is not None:
            event.stop()
            event.prevent_default()
            await parent.action_cancel()
            return
        await super()._on_key(event)


class _MentionInput(Input):
    """Input that shows MentionPalette when typing @."""

    def __init__(self, *args, roles: list[Role], **kwargs) -> None:
        self.roles = roles
        self._mention_palette: MentionPalette | None = None
        super().__init__(*args, **kwargs)

    def on_mount(self) -> None:
        # Create palette as a sibling in the DOM; actual mounting deferred to parent
        pass

    def _ensure_palette(self) -> MentionPalette | None:
        parent = _thread_create_parent(self)
        if self._mention_palette is None and parent is not None:
            self._mention_palette = MentionPalette(self.roles)
            parent.mount(self._mention_palette)
        return self._mention_palette

    async def _on_key(self, event) -> None:
        parent = _thread_create_parent(self)
        if event.key == "ctrl+c" and parent is not None:
            event.stop()
            event.prevent_default()
            await parent.action_cancel()
            return
        palette = self._ensure_palette()
        if palette is not None and palette.styles.display != "none":
            if event.key in ("up", "down"):
                event.stop()
                event.prevent_default()
                if event.key == "up":
                    palette.action_cursor_up()
                else:
                    palette.action_cursor_down()
                return
            if event.key == "enter":
                event.stop()
                event.prevent_default()
                palette.action_select()
                return
            if event.key == "escape":
                event.stop()
                event.prevent_default()
                palette.action_dismiss()
                return
        await super()._on_key(event)

    def watch_value(self, value: str) -> None:
        # Trigger mention detection on value change
        palette = self._ensure_palette()
        if palette is None:
            return
        cursor = self.cursor_position
        before = value[:cursor]
        match = re.search(r"@([\w]*)$", before)
        if match:
            prefix = match.group(1)
            palette.update_prefix(prefix)
        else:
            palette.styles.display = "none"

    async def on_mentioned(self, role_name: str) -> None:
        """Called by parent widget when a mention is selected."""
        value = self.value
        cursor = self.cursor_position
        before = value[:cursor]
        after = value[cursor:]
        # Replace @prefix with @role_name,
        new_before = re.sub(r"@[\w]*$", f"@{role_name},", before)
        self.value = new_before + after
        self.cursor_position = len(new_before)
        palette = self._ensure_palette()
        if palette is not None:
            palette.styles.display = "none"
        self.focus()


class ThreadPlanningWidget(Vertical):
    """Editable table of planned threads with title, assignees, and reviewers."""

    def __init__(self, threads: list[Thread], roles: list[Role]) -> None:
        super().__init__(classes="thread-planning-widget")
        self.threads = list(threads)
        self.roles = roles
        self._future: asyncio.Future[list[Thread] | None] | None = None
        self._rows: list[Horizontal] = []
        self._title_inputs: list[Input] = []
        self._assign_inputs: list[_MentionInput] = []
        self._review_inputs: list[_MentionInput] = []

    def _get_future(self) -> asyncio.Future[list[Thread] | None]:
        if self._future is None:
            self._future = asyncio.Future()
        return self._future

    def compose(self) -> ComposeResult:
        yield SafeStatic("📋 任务规划", classes="thread-planning-title")
        with Horizontal(classes="thread-planning-header"):
            yield SafeStatic("任务标题", classes="plan-header plan-header-title")
            yield SafeStatic("指派", classes="plan-header plan-header-assign")
            yield SafeStatic("验收", classes="plan-header plan-header-review")
            yield SafeStatic("", classes="plan-header plan-header-del")

        self._rows_container = Vertical(classes="thread-planning-rows")
        yield self._rows_container

        for thread in self.threads:
            yield from self._build_row(thread)

        with Horizontal(classes="thread-planning-buttons"):
            yield Button("+ 添加行", id="plan-add-row", variant="primary")
            yield Button("确认派发", id="plan-confirm", variant="success")
            yield Button("取消", id="plan-cancel", variant="error")

    def _build_row(self, thread: Thread | None = None) -> ComposeResult:
        thread = thread or Thread(id=0, title="")
        with Horizontal(classes="thread-planning-row") as row:
            self._rows.append(row)

            title_input = Input(
                value=thread.title,
                placeholder="任务标题",
                classes="plan-input plan-title",
            )
            self._title_inputs.append(title_input)
            yield title_input

            assign_input = _MentionInput(
                value=self._names_to_display(thread.assigned_role_names),
                placeholder="@role1,@role2",
                classes="plan-input plan-assign",
                roles=self.roles,
            )
            self._assign_inputs.append(assign_input)
            yield assign_input

            review_input = _MentionInput(
                value=self._names_to_display(thread.reviewer_role_names),
                placeholder="@role1",
                classes="plan-input plan-review",
                roles=self.roles,
            )
            self._review_inputs.append(review_input)
            yield review_input

            del_btn = Button("×", classes="plan-del-btn", variant="error")
            yield del_btn

    @staticmethod
    def _names_to_display(names: list[str]) -> str:
        if not names:
            return ""
        return ",".join(f"@{n}" for n in names)

    @staticmethod
    def _display_to_names(text: str) -> list[str]:
        parts = [p.strip().lstrip("@") for p in text.split(",") if p.strip().lstrip("@")]
        return parts

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id
        if btn_id == "plan-add-row":
            # Can't yield from event handler; mount new row manually
            await self._mount_new_row()
            return
        if btn_id == "plan-confirm":
            await self._confirm()
            return
        if btn_id == "plan-cancel":
            await self._resolve(None)
            return
        # Delete row button
        for i, row in enumerate(self._rows):
            if row.query_one(".plan-del-btn") == event.button:
                await self._remove_row(i)
                return

    async def _mount_new_row(self) -> None:
        row = Horizontal(classes="thread-planning-row")
        title_input = Input(value="", placeholder="任务标题", classes="plan-input plan-title")
        assign_input = _MentionInput(
            value="", placeholder="@role1,@role2", classes="plan-input plan-assign", roles=self.roles
        )
        review_input = _MentionInput(value="", placeholder="@role1", classes="plan-input plan-review", roles=self.roles)
        del_btn = Button("×", classes="plan-del-btn", variant="error")
        await self._rows_container.mount(row)
        await row.mount(title_input)
        await row.mount(assign_input)
        await row.mount(review_input)
        await row.mount(del_btn)
        self._rows.append(row)
        self._title_inputs.append(title_input)
        self._assign_inputs.append(assign_input)
        self._review_inputs.append(review_input)

    async def _remove_row(self, index: int) -> None:
        if not (0 <= index < len(self._rows)):
            return
        row = self._rows.pop(index)
        self._title_inputs.pop(index)
        self._assign_inputs.pop(index)
        self._review_inputs.pop(index)
        await row.remove()

    def on_input_changed(self, event: Input.Changed) -> None:
        sender = event.input
        if isinstance(sender, _MentionInput):
            palette = sender._mention_palette
            if palette is not None:
                future = palette._get_future()
                if not future.done():
                    self.run_worker(self._watch_mention_palette(sender, palette), thread=False)

    async def _watch_mention_palette(self, input_widget: _MentionInput, palette: MentionPalette) -> None:
        role_name = await palette.wait()
        if role_name is not None and input_widget.is_mounted:
            await input_widget.on_mentioned(role_name)

    async def _confirm(self) -> None:
        result: list[Thread] = []
        for i in range(len(self._rows)):
            title = self._title_inputs[i].value.strip()
            if not title:
                continue
            assigned = self._display_to_names(self._assign_inputs[i].value)
            reviewers = self._display_to_names(self._review_inputs[i].value)
            result.append(
                Thread(
                    id=i + 1,
                    title=title,
                    assigned_role_names=assigned,
                    reviewer_role_names=reviewers,
                )
            )
        await self._resolve(result)

    async def _resolve(self, threads: list[Thread] | None) -> None:
        future = self._get_future()
        if not future.done():
            future.set_result(threads)
        await self.remove()

    async def wait(self) -> list[Thread] | None:
        return await self._get_future()


class ThreadSidebar(Vertical):
    """Sidebar showing channel threads with status indicators."""

    class ThreadSelected(Message):
        def __init__(self, thread_id: int) -> None:
            self.thread_id = thread_id
            super().__init__()

    def __init__(self, channel: Channel, active_thread_id: int | None = None) -> None:
        super().__init__(classes="thread-sidebar", id="thread-sidebar")
        self.channel = channel
        self.active_thread_id = active_thread_id
        self._thread_items: list[SafeStatic] = []

    def compose(self) -> ComposeResult:
        yield SafeStatic("📋 Threads", classes="thread-sidebar-title")
        with Vertical(classes="thread-sidebar-list"):
            pass

    async def on_mount(self) -> None:
        await self.refresh_threads()

    async def refresh_threads(self) -> None:
        container = self.query_one(".thread-sidebar-list", Vertical)
        # Remove existing items
        for item in self._thread_items:
            await item.remove()
        self._thread_items.clear()

        for thread in self.channel.threads:
            status_icon = self._status_icon(thread.status)
            classes = "thread-item"
            if thread.id == self.active_thread_id:
                classes += " thread-item--active"
            display = f"{status_icon} #{thread.id} {thread.title}"
            item = SafeStatic(display, classes=classes)
            item.data_thread_id = thread.id  # type: ignore[attr-defined]
            await container.mount(item)
            self._thread_items.append(item)

    def set_active(self, thread_id: int | None) -> None:
        self.active_thread_id = thread_id
        for item in self._thread_items:
            tid = getattr(item, "data_thread_id", None)
            classes = set(item.classes)
            if tid == thread_id:
                classes.add("thread-item--active")
            else:
                classes.discard("thread-item--active")
            item.classes = classes

    @staticmethod
    def _status_icon(status: ThreadStatus) -> str:
        mapping = {
            ThreadStatus.DRAFT: "○",
            ThreadStatus.RUNNING: "▶",
            ThreadStatus.DONE: "✓",
            ThreadStatus.ERROR: "✗",
        }
        return mapping.get(status, "○")

    def on_click(self, event) -> None:
        target = event.control
        while target is not None and target is not self:
            tid = getattr(target, "data_thread_id", None)
            if tid is not None:
                self.post_message(self.ThreadSelected(tid))
                return
            target = target.parent



class _ThreadDescArea(TextArea):
    """TextArea for thread description: Enter moves focus, Ctrl+Enter submits."""

    async def _on_key(self, event) -> None:
        parent = _thread_create_parent(self)
        if event.key == "ctrl+c" and parent is not None:
            event.stop()
            event.prevent_default()
            await parent.action_cancel()
            return
        if event.key == "enter" and parent is not None:
            event.stop()
            event.prevent_default()
            self.app.set_focus(parent.query_one("#tc-assign"))
            return
        await super()._on_key(event)


class ThreadCreateWidget(Vertical):
    """Widget for creating a new thread with title, description and role assignees."""

    BINDINGS: ClassVar[list[BindingType]] = [
        ("ctrl+c", "cancel", "Cancel"),
        ("escape", "cancel", "Cancel"),
        ("shift+tab", "confirm", "Confirm"),
    ]

    class Completed(Message):
        def __init__(self, title: str, description: str, assigned_roles: list[str]) -> None:
            self.title = title
            self.description = description
            self.assigned_roles = assigned_roles
            super().__init__()

    class Cancelled(Message):
        pass

    def __init__(self, roles: list[Role]) -> None:
        super().__init__(classes="thread-create-widget")
        self.roles = roles

    def compose(self) -> ComposeResult:
        yield SafeStatic("创建新 Thread (Shift+Tab 提交)", classes="wizard-title")
        yield SafeStatic("标题:", classes="wizard-label-small")
        yield _ThreadTitleInput(placeholder="Thread 标题", id="tc-title")
        yield SafeStatic("描述:", classes="wizard-label-small")
        yield _ThreadDescArea(
            placeholder="Thread 描述...",
            id="tc-desc",
            soft_wrap=True,
            show_line_numbers=False,
        )
        yield SafeStatic("指派 Roles (@role):", classes="wizard-label-small")
        yield _MentionInput(placeholder="@coder,@reviewer", id="tc-assign", roles=self.roles)

    async def action_cancel(self) -> None:
        self.post_message(self.Cancelled())
        await self.remove()

    async def action_confirm(self) -> None:
        await self._confirm()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "tc-title":
            self.query_one("#tc-desc", _ThreadDescArea).focus()
        elif event.input.id == "tc-assign":
            self.query_one("#tc-title", Input).focus()

    async def _confirm(self) -> None:
        title_input = self.query_one("#tc-title", Input)
        desc_input = self.query_one("#tc-desc", _ThreadDescArea)
        assign_input = self.query_one("#tc-assign", _MentionInput)

        title = title_input.value.strip()
        description = desc_input.text.strip()
        assigned = [r.strip().lstrip("@") for r in assign_input.value.split(",") if r.strip().lstrip("@")]

        self.post_message(self.Completed(title, description, assigned))
        await self.remove()


class ThreadListItem(Horizontal):
    """Single row in the thread list."""

    def __init__(self, thread: Thread, selected: bool = False) -> None:
        classes = "thread-list-item"
        if selected:
            classes += " thread-list-item--selected"
        classes += f" thread-list-item--{thread.status.value.strip()}"
        super().__init__(classes=classes)
        self.thread = thread

    def compose(self) -> ComposeResult:
        icon = ThreadListView._status_icon(self.thread.status)
        yield SafeStatic(icon, classes="thread-list-item-icon")
        title = f"#{self.thread.id}  {self.thread.title}"
        yield SafeStatic(title, classes="thread-list-item-title")
        right_parts: list[str] = []
        if self.thread.messages:
            right_parts.append(f"{len(self.thread.messages)} msgs")
        if self.thread.assigned_role_names:
            right_parts.append(", ".join(self.thread.assigned_role_names))
        right = "  |  ".join(right_parts) if right_parts else ""
        yield SafeStatic(right, classes="thread-list-item-meta")


class ThreadListView(Vertical):
    """Full-screen list for selecting a thread."""

    can_focus = True

    BINDINGS: ClassVar[list[BindingType]] = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "select", "Select"),
        ("escape", "dismiss", "Dismiss"),
    ]

    class ThreadSelected(Message):
        def __init__(self, thread_id: int) -> None:
            self.thread_id = thread_id
            super().__init__()

    class Dismissed(Message):
        pass

    def __init__(self, threads: list[Thread]) -> None:
        super().__init__(classes="thread-list-view")
        self._threads = threads
        self._selected_index = 0
        self._item_widgets: list[Widget] = []

    def compose(self) -> ComposeResult:
        yield SafeStatic(
            "📋 选择 Thread（↑↓ 选择，Enter 切换，Esc 取消）",
            classes="thread-list-title",
        )
        yield Vertical(classes="thread-list-items")

    async def on_mount(self) -> None:
        await self._refresh_items()
        self.focus()

    @staticmethod
    def _status_icon(status: ThreadStatus) -> str:
        mapping = {
            ThreadStatus.DRAFT: "○",
            ThreadStatus.RUNNING: "▶",
            ThreadStatus.REVIEW: "◐",
            ThreadStatus.DONE: "✓",
            ThreadStatus.ERROR: "✗",
        }
        return mapping.get(status, "○")

    def _sort_threads(self) -> list[Thread]:
        priority = {
            ThreadStatus.RUNNING: 0,
            ThreadStatus.DRAFT: 1,
            ThreadStatus.REVIEW: 2,
            ThreadStatus.DONE: 3,
            ThreadStatus.ERROR: 4,
        }
        return sorted(self._threads, key=lambda t: (priority.get(t.status, 99), t.id))

    async def _refresh_items(self) -> None:
        container = self.query_one(".thread-list-items", Vertical)
        for item in self._item_widgets:
            await item.remove()
        self._item_widgets.clear()

        if not self._threads:
            empty = SafeStatic(
                "还没有任何 Thread，使用 /thread 创建",
                classes="thread-list-empty",
            )
            await container.mount(empty)
            self._item_widgets.append(empty)
            return

        sorted_threads = self._sort_threads()
        current_status: ThreadStatus | None = None
        for i, thread in enumerate(sorted_threads):
            if thread.status != current_status:
                current_status = thread.status
                header_text = f"  {thread.status.value.strip().upper()}"
                header = SafeStatic(header_text, classes="thread-list-header")
                await container.mount(header)
                self._item_widgets.append(header)

            item = ThreadListItem(thread, selected=(i == self._selected_index))
            await container.mount(item)
            self._item_widgets.append(item)

        self._scroll_to_selected()

    def _scroll_to_selected(self) -> None:
        sorted_threads = self._sort_threads()
        if not (0 <= self._selected_index < len(sorted_threads)):
            return
        target_id = sorted_threads[self._selected_index].id
        for widget in self._item_widgets:
            if isinstance(widget, ThreadListItem) and widget.thread.id == target_id:
                widget.scroll_visible()
                break

    async def action_cursor_up(self) -> None:
        if self._selected_index > 0:
            self._selected_index -= 1
            await self._refresh_items()

    async def action_cursor_down(self) -> None:
        if self._selected_index < len(self._sort_threads()) - 1:
            self._selected_index += 1
            await self._refresh_items()

    async def action_select(self) -> None:
        sorted_threads = self._sort_threads()
        if 0 <= self._selected_index < len(sorted_threads):
            self.post_message(self.ThreadSelected(sorted_threads[self._selected_index].id))
        await self.remove()

    async def action_dismiss(self) -> None:
        self.post_message(self.Dismissed())
        await self.remove()

    async def on_click(self, event) -> None:
        event.stop()
        event.prevent_default()
        target = event.control
        while target is not None and target is not self:
            if isinstance(target, ThreadListItem):
                sorted_threads = self._sort_threads()
                for i, t in enumerate(sorted_threads):
                    if t.id == target.thread.id:
                        self._selected_index = i
                        await self.action_select()
                        return
            target = target.parent
