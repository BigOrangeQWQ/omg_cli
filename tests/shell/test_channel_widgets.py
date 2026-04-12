"""Tests for Channel mode widgets."""

import asyncio
from pathlib import Path

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Button

from omg_cli.shell.channel_widgets import (
    MentionPalette,
    RoleSelectorDialog,
    ThreadCreateWidget,
    ThreadPlanningWidget,
    ThreadSidebar,
    _MentionInput,
)
from omg_cli.types.channel import Channel, Role, Thread, ThreadStatus


class RoleSelectorApp(App):
    def __init__(self, roles: list[Role]) -> None:
        super().__init__()
        self.roles = roles
        self.result: Role | None = None

    def compose(self) -> ComposeResult:
        yield RoleSelectorDialog(self.roles)

    async def on_mount(self) -> None:
        dialog = self.query_one(RoleSelectorDialog)
        dialog.focus()
        self._task = asyncio.create_task(self._do_wait(dialog))

    async def _do_wait(self, dialog: RoleSelectorDialog) -> None:
        self.result = await dialog.wait()
        self.exit()


class MentionApp(App):
    def __init__(self, roles: list[Role]) -> None:
        super().__init__()
        self.roles = roles
        self.result: str | None = None

    def compose(self) -> ComposeResult:
        yield MentionPalette(self.roles)

    async def on_mount(self) -> None:
        palette = self.query_one(MentionPalette)
        palette.focus()
        palette.update_prefix("co")
        self._task = asyncio.create_task(self._do_wait(palette))

    async def _do_wait(self, palette: MentionPalette) -> None:
        self.result = await palette.wait()
        self.exit()


class TestRoleSelectorDialog:
    @pytest.mark.asyncio
    async def test_select_first_role(self) -> None:
        roles = [
            Role(name="coder", desc="Writes code", personal_space=Path("/tmp"), adapter_name="m1"),
            Role(name="reviewer", desc="Reviews code", personal_space=Path("/tmp"), adapter_name="m2"),
        ]
        app = RoleSelectorApp(roles)
        async with app.run_test() as pilot:
            await pilot.press("enter")
        assert app.result is not None
        assert app.result.name == "coder"

    @pytest.mark.asyncio
    async def test_select_second_role(self) -> None:
        roles = [
            Role(name="coder", desc="", personal_space=Path("/tmp"), adapter_name="m1"),
            Role(name="reviewer", desc="", personal_space=Path("/tmp"), adapter_name="m2"),
        ]
        app = RoleSelectorApp(roles)
        async with app.run_test() as pilot:
            await pilot.press("down", "enter")
        assert app.result is not None
        assert app.result.name == "reviewer"


class TestMentionPalette:
    @pytest.mark.asyncio
    async def test_filter_and_select(self) -> None:
        roles = [
            Role(name="coder", desc="", personal_space=Path("/tmp"), adapter_name="m1"),
            Role(name="reviewer", desc="", personal_space=Path("/tmp"), adapter_name="m2"),
        ]
        app = MentionApp(roles)
        async with app.run_test() as pilot:
            await pilot.press("enter")
        assert app.result == "coder"

    @pytest.mark.asyncio
    async def test_dismiss(self) -> None:
        roles = [Role(name="coder", desc="", personal_space=Path("/tmp"), adapter_name="m1")]
        app = MentionApp(roles)
        async with app.run_test() as pilot:
            await pilot.press("escape")
        assert app.result is None


class TestThreadPlanningWidget:
    def test_names_roundtrip(self) -> None:
        widget = ThreadPlanningWidget([], [Role(name="a", desc="", personal_space=Path("/tmp"), adapter_name="m")])
        assert widget._display_to_names("@a,@b") == ["a", "b"]
        assert widget._names_to_display(["x", "y"]) == "@x,@y"

    def test_parse_empty_display(self) -> None:
        widget = ThreadPlanningWidget([], [Role(name="a", desc="", personal_space=Path("/tmp"), adapter_name="m")])
        assert widget._display_to_names("") == []
        assert widget._display_to_names("  ") == []
        assert widget._display_to_names("@") == []

    @pytest.mark.asyncio
    async def test_confirm_produces_threads(self) -> None:
        roles = [Role(name="dev", desc="", personal_space=Path("/tmp"), adapter_name="m")]
        threads = [Thread(id=1, title="Task", assigned_role_names=["dev"])]

        class PlanningApp(App):
            def compose(self):
                yield ThreadPlanningWidget(threads, roles)

        app = PlanningApp()
        async with app.run_test():
            widget = app.query_one(ThreadPlanningWidget)
            # Simulate clicking confirm
            confirm_btn = app.query_one("#plan-confirm", Button)
            confirm_btn.press()
            result = await widget.wait()

        assert result is not None
        assert len(result) == 1
        assert result[0].title == "Task"
        assert result[0].assigned_role_names == ["dev"]


class TestThreadSidebar:
    @pytest.mark.asyncio
    async def test_render_threads(self) -> None:
        role = Role(name="coder", desc="", personal_space=Path("/tmp"), adapter_name="m")
        channel = Channel(name="dev", roles=[role])
        channel.add_thread("闲聊")
        channel.add_thread("任务1")
        channel.threads[1].status = ThreadStatus.RUNNING

        class SidebarApp(App):
            def compose(self) -> ComposeResult:
                yield ThreadSidebar(channel, active_thread_id=1)

        app = SidebarApp()
        async with app.run_test():
            sidebar = app.query_one(ThreadSidebar)
            items = list(sidebar.query(".thread-item"))
            assert len(items) == 2
            assert "闲聊" in items[0].render().plain
            assert "任务1" in items[1].render().plain
            assert "▶" in items[1].render().plain
            assert "thread-item--active" in items[0].classes

    @pytest.mark.asyncio
    async def test_click_selects_thread(self) -> None:
        role = Role(name="coder", desc="", personal_space=Path("/tmp"), adapter_name="m")
        channel = Channel(name="dev", roles=[role])
        channel.add_thread("闲聊")
        channel.add_thread("任务1")

        selected_ids: list[int] = []

        class SidebarApp(App):
            def compose(self) -> ComposeResult:
                yield ThreadSidebar(channel, active_thread_id=1)

            def on_thread_sidebar_thread_selected(self, event: ThreadSidebar.ThreadSelected) -> None:
                selected_ids.append(event.thread_id)

        app = SidebarApp()
        async with app.run_test() as pilot:
            items = list(app.query(".thread-item"))
            # Click second item
            await pilot.click(items[1])

        assert selected_ids == [2]

    @pytest.mark.asyncio
    async def test_set_active_updates_classes(self) -> None:
        role = Role(name="coder", desc="", personal_space=Path("/tmp"), adapter_name="m")
        channel = Channel(name="dev", roles=[role])
        channel.add_thread("闲聊")
        channel.add_thread("任务1")

        class SidebarApp(App):
            def compose(self) -> ComposeResult:
                yield ThreadSidebar(channel, active_thread_id=1)

        app = SidebarApp()
        async with app.run_test():
            sidebar = app.query_one(ThreadSidebar)
            items = list(sidebar.query(".thread-item"))
            assert "thread-item--active" in items[0].classes
            sidebar.set_active(2)
            assert "thread-item--active" not in items[0].classes
            assert "thread-item--active" in items[1].classes


class TestThreadCreateWidget:
    @pytest.mark.asyncio
    async def test_mention_complete_in_assign_input(self) -> None:
        roles = [
            Role(name="coder", desc="", personal_space=Path("/tmp"), adapter_name="m1"),
            Role(name="reviewer", desc="", personal_space=Path("/tmp"), adapter_name="m2"),
        ]

        class CreateApp(App):
            def compose(self) -> ComposeResult:
                yield ThreadCreateWidget(roles)

        app = CreateApp()
        async with app.run_test() as pilot:
            assign_input = app.query_one("#tc-assign", _MentionInput)
            assign_input.focus()

            await pilot.press("@", "c", "o")
            await pilot.pause()

            palette = app.query_one(".mention-palette", MentionPalette)
            assert palette.styles.display != "none"

            await pilot.press("enter")
            await pilot.pause()

            assert assign_input.value == "@coder,"
