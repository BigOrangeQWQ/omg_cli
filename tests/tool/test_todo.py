"""Tests for TodoProtocol."""

from inline_snapshot import snapshot
import pytest

from omg_cli.tool import ToolManager
from omg_cli.tool.todo import TodoList, TodoProtocol
from omg_cli.types.tool import ToolError


class TestTodoList:
    """Tests for TodoList dataclass."""

    def test_parse_empty_content(self):
        todo_list = TodoList()
        todo_list.parse("")
        assert todo_list.items == snapshot([])

    def test_parse_single_task(self):
        todo_list = TodoList()
        todo_list.parse("(A) Test task")
        assert len(todo_list.items) == 1
        assert todo_list.items[0].priority == snapshot("A")
        assert todo_list.items[0].bare_description() == snapshot("Test task")

    def test_parse_multiple_tasks(self):
        todo_list = TodoList()
        todo_list.parse("(A) First task\n(B) Second task\nThird task")
        assert len(todo_list.items) == 3
        assert todo_list.items[0].priority == snapshot("A")
        assert todo_list.items[1].priority == snapshot("B")
        assert todo_list.items[2].priority == snapshot(None)

    def test_parse_completed_task(self):
        todo_list = TodoList()
        todo_list.parse("x Completed task")
        assert len(todo_list.items) == 1
        assert todo_list.items[0].is_completed == snapshot(True)

    def test_parse_with_projects_and_contexts(self):
        todo_list = TodoList()
        todo_list.parse("(A) Task +project @context")
        task = todo_list.items[0]
        assert task.projects == snapshot(["project"])
        assert task.contexts == snapshot(["context"])


class TestTodoProtocol:
    """Tests for TodoProtocol."""

    @pytest.fixture
    def protocol(self):
        return TodoProtocol()

    def test_init_creates_empty_todo_list(self, protocol):
        assert protocol._todo_list.items == snapshot([])

    def test_sort_key_completed_last(self, protocol):
        from pytodotxt import Task

        pending = Task()
        pending.parse("(A) Pending")

        completed = Task()
        completed.parse("x Completed")

        assert protocol._sort_key(pending) < protocol._sort_key(completed)

    def test_sort_key_priority_order(self, protocol):
        from pytodotxt import Task

        task_a = Task()
        task_a.parse("(A) Task A")

        task_b = Task()
        task_b.parse("(B) Task B")

        task_none = Task()
        task_none.parse("No priority")

        assert protocol._sort_key(task_a) == snapshot((0, 0))
        assert protocol._sort_key(task_b) == snapshot((0, 1))
        assert protocol._sort_key(task_none) == snapshot((0, 26))

    def test_fmt_pending_task(self, protocol):
        from pytodotxt import Task

        task = Task()
        task.parse("(A) Test task")
        result = protocol._fmt(task, 1)
        assert result == snapshot("1. ☐ (A) Test task")

    def test_fmt_completed_task(self, protocol):
        from pytodotxt import Task

        task = Task()
        task.parse("x Completed task")
        result = protocol._fmt(task, 1)
        assert result == snapshot("1. ✓ ( ) Completed task")

    def test_tools_returns_three_tools(self, protocol):
        tools = protocol.todo_tools()
        assert len(tools) == 3
        names = [t.name for t in tools]
        assert names == snapshot(["set_todo", "get_todo", "complete_todo"])


class TestTodoTools:
    """Tests for tool functions."""

    @pytest.mark.asyncio
    async def test_set_todo_loads_tasks(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        result = await tools["set_todo"](content="(A) Task 1\n(B) Task 2")

        assert result == snapshot("Loaded 2 tasks (2 pending)")
        assert len(protocol._todo_list.items) == 2

    @pytest.mark.asyncio
    async def test_set_todo_empty_content_raises_error(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        with pytest.raises(ToolError, match="Content cannot be empty"):
            await tools["set_todo"](content="")

    @pytest.mark.asyncio
    async def test_set_todo_whitespace_only_raises_error(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        with pytest.raises(ToolError, match="Content cannot be empty"):
            await tools["set_todo"](content="   \n   ")

    @pytest.mark.asyncio
    async def test_set_todo_no_valid_tasks_raises_error(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        # This has content but no valid todo items (empty lines don't count)
        with pytest.raises(ToolError, match="Content cannot be empty"):
            await tools["set_todo"](content="   \n   \n   ")

    @pytest.mark.asyncio
    async def test_set_todo_replaces_existing(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        await tools["set_todo"](content="(A) First")
        await tools["set_todo"](content="(B) Second")

        assert len(protocol._todo_list.items) == 1
        assert protocol._todo_list.items[0].bare_description() == snapshot("Second")

    @pytest.mark.asyncio
    async def test_get_todo_empty_list(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        result = await tools["get_todo"]()

        assert result == snapshot("No tasks.")

    @pytest.mark.asyncio
    async def test_get_todo_sorts_by_priority(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        await tools["set_todo"](content="(C) Low priority\n(A) High priority\n(B) Medium")
        result = await tools["get_todo"](limit=5)

        assert result == snapshot("""\
1. ☐ (A) High priority
2. ☐ (B) Medium
3. ☐ (C) Low priority""")

    @pytest.mark.asyncio
    async def test_get_todo_respects_limit(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        await tools["set_todo"](content="(A) Task 1\n(B) Task 2\n(C) Task 3")
        result = await tools["get_todo"](limit=2)

        assert result == snapshot("""\
1. ☐ (A) Task 1
2. ☐ (B) Task 2""")

    @pytest.mark.asyncio
    async def test_get_todo_excludes_completed(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        await tools["set_todo"](content="(A) Pending\nx Completed")
        result = await tools["get_todo"]()

        assert result == snapshot("1. ☐ (A) Pending")

    @pytest.mark.asyncio
    async def test_complete_todo_by_index(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        await tools["set_todo"](content="(A) Task 1\n(B) Task 2")
        result = await tools["complete_todo"](identifiers="1")

        assert result == snapshot("""\
✅ Completed 1 task(s):
  - Task 1""")
        assert protocol._todo_list.items[0].is_completed is True

    @pytest.mark.asyncio
    async def test_complete_todo_by_text(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        await tools["set_todo"](content="(A) Specific task name")
        result = await tools["complete_todo"](identifiers="Specific task name")

        assert result == snapshot("""\
✅ Completed 1 task(s):
  - Specific task name""")
        assert protocol._todo_list.items[0].is_completed is True

    @pytest.mark.asyncio
    async def test_complete_todo_batch(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        await tools["set_todo"](content="(A) Task 1\n(B) Task 2\n(C) Task 3")
        result = await tools["complete_todo"](identifiers="1,3")

        assert result == snapshot("""\
✅ Completed 2 task(s):
  - Task 1
  - Task 3""")
        assert protocol._todo_list.items[0].is_completed is True
        assert protocol._todo_list.items[2].is_completed is True
        assert protocol._todo_list.items[1].is_completed is False

    @pytest.mark.asyncio
    async def test_complete_todo_not_found_raises_error(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        await tools["set_todo"](content="(A) Task 1")
        with pytest.raises(ToolError, match="No pending tasks found"):
            await tools["complete_todo"](identifiers="999")

    @pytest.mark.asyncio
    async def test_complete_todo_partial_match_unique(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        await tools["set_todo"](content="(A) Unique task name")
        result = await tools["complete_todo"](identifiers="Unique")

        assert result == snapshot("""\
✅ Completed 1 task(s):
  - Unique task name""")
        assert protocol._todo_list.items[0].is_completed is True

    @pytest.mark.asyncio
    async def test_complete_todo_partial_match_ambiguous_raises_error(self):
        protocol = TodoProtocol()
        tools = {t.name: t for t in protocol.todo_tools()}

        await tools["set_todo"](content="(A) Task A\n(B) Task B")
        with pytest.raises(ToolError, match="Ambiguous identifier"):
            await tools["complete_todo"](identifiers="Task")


class TestTodoProtocolInheritance:
    """Tests that TodoProtocol can be properly inherited."""

    def test_inheritance_stores_data_in_instance(self):
        class MyContext(TodoProtocol):
            def __init__(self):
                super().__init__()
                self.custom_attr = "test"

        ctx = MyContext()
        assert hasattr(ctx, "_todo_list")
        assert hasattr(ctx, "custom_attr")
        assert ctx.custom_attr == snapshot("test")

    def test_tools_bound_to_instance(self):
        class MyContext(TodoProtocol):
            pass

        ctx1 = MyContext()
        ctx2 = MyContext()

        tools1 = {t.name: t for t in ctx1.todo_tools()}
        tools2 = {t.name: t for t in ctx2.todo_tools()}

        assert set(tools1.keys()) == snapshot({"set_todo", "get_todo", "complete_todo"})
        assert set(tools2.keys()) == snapshot({"set_todo", "get_todo", "complete_todo"})


class TestToolRegistration:
    """Tests for Tool registration with ToolManager."""

    @pytest.fixture(autouse=True)
    def clear_manager(self):
        ToolManager.clear()
        yield
        ToolManager.clear()

    def test_register_tools(self):
        protocol = TodoProtocol()
        tools = protocol.todo_tools()

        for tool in tools:
            registered = ToolManager.register(tool)
            assert registered.name in ToolManager.tools

        assert list(ToolManager.tools.keys()) == snapshot(["set_todo", "get_todo", "complete_todo"])

    @pytest.mark.asyncio
    async def test_registered_tools_callable(self):
        protocol = TodoProtocol()
        for tool in protocol.todo_tools():
            ToolManager.register(tool)

        set_tool = ToolManager.get("set_todo")
        result = await set_tool(content="(A) Test task")
        assert result == snapshot("Loaded 1 tasks (1 pending)")
