"""Tests for Channel mode domain models."""

from pathlib import Path

from omg_cli.types.channel import Channel, Role, Thread, ThreadStatus


class TestChannelHelpers:
    def test_next_thread_id_auto_increment(self) -> None:
        role = Role(name="coder", desc="Writes code", personal_space=Path("/tmp"), adapter_name="gpt-4")
        channel = Channel(name="dev", roles=[role])

        assert channel.next_thread_id() == 1
        channel.add_thread("First task")
        assert channel.next_thread_id() == 2
        channel.add_thread("Second task")
        assert channel.next_thread_id() == 3

    def test_get_role(self) -> None:
        role_a = Role(name="coder", desc="", personal_space=Path("/tmp"), adapter_name="gpt-4")
        role_b = Role(name="reviewer", desc="", personal_space=Path("/tmp"), adapter_name="claude")
        channel = Channel(name="dev", roles=[role_a, role_b])

        assert channel.get_role("coder") == role_a
        assert channel.get_role("reviewer") == role_b
        assert channel.get_role("missing") is None

    def test_add_thread_defaults(self) -> None:
        role = Role(name="coder", desc="", personal_space=Path("/tmp"), adapter_name="gpt-4")
        channel = Channel(name="dev", roles=[role])

        thread = channel.add_thread("New feature")
        assert thread.id == 1
        assert thread.title == "New feature"
        assert thread.status == ThreadStatus.DRAFT
        assert thread.assigned_role_names == []
        assert thread.reviewer_role_names == []
        assert thread.parent_thread_id is None

    def test_add_thread_with_assignments(self) -> None:
        role = Role(name="coder", desc="", personal_space=Path("/tmp"), adapter_name="gpt-4")
        channel = Channel(name="dev", roles=[role])

        thread = channel.add_thread(
            "Refactor",
            assigned_role_names=["coder"],
            reviewer_role_names=["coder"],
            parent_thread_id=99,
        )
        assert thread.assigned_role_names == ["coder"]
        assert thread.reviewer_role_names == ["coder"]
        assert thread.parent_thread_id == 99


class TestThreadSerialization:
    def test_thread_json_roundtrip(self) -> None:
        thread = Thread(
            id=7,
            title="Test thread",
            assigned_role_names=["a", "b"],
            reviewer_role_names=["c"],
            status=ThreadStatus.RUNNING,
            parent_thread_id=3,
        )
        data = thread.model_dump()
        restored = Thread.model_validate(data)
        assert restored.id == 7
        assert restored.title == "Test thread"
        assert restored.assigned_role_names == ["a", "b"]
        assert restored.reviewer_role_names == ["c"]
        assert restored.status == ThreadStatus.RUNNING
        assert restored.parent_thread_id == 3
