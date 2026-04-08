"""Tests for Role and RoleManager."""

from pathlib import Path

import pytest

from src.omg_cli.role_manager import RoleManager
from src.omg_cli.types.role import Role, parse_role_manifest, serialize_role


class TestRoleModel:
    def test_role_name_normalization(self) -> None:
        role = Role(name="  my/role\\name  ", description="desc", system_prompt="prompt")
        assert role.name == "my_role_name"

    def test_serialize_role_with_description(self) -> None:
        role = Role(name="assistant", description="A helper", system_prompt="You are helpful.")
        text = serialize_role(role)
        assert text.startswith("---\n")
        assert 'name: "assistant"' in text
        assert 'description: "A helper"' in text
        assert "You are helpful." in text

    def test_serialize_role_without_description(self) -> None:
        role = Role(name="coder", system_prompt="You are a coder.")
        text = serialize_role(role)
        assert 'name: "coder"' in text
        assert "description:" not in text
        assert "You are a coder." in text


class TestParseRoleManifest:
    def test_parse_with_frontmatter(self, tmp_path: Path) -> None:
        soul_md = tmp_path / "soul.md"
        soul_md.write_text(
            "---\n"
            "name: test-role\n"
            "description: A test role\n"
            "---\n"
            "\n"
            "You are a test role.\n",
            encoding="utf-8",
        )
        role = parse_role_manifest(soul_md)
        assert role is not None
        assert role.name == "test-role"
        assert role.description == "A test role"
        assert role.system_prompt == "You are a test role."

    def test_parse_from_directory(self, tmp_path: Path) -> None:
        role_dir = tmp_path / "my-role"
        role_dir.mkdir()
        (role_dir / "soul.md").write_text(
            "---\n"
            "name: dir-role\n"
            "description: From dir\n"
            "---\n"
            "Prompt here.\n",
            encoding="utf-8",
        )
        role = parse_role_manifest(role_dir)
        assert role is not None
        assert role.name == "dir-role"
        assert role.system_prompt == "Prompt here."

    def test_parse_no_frontmatter(self, tmp_path: Path) -> None:
        soul_md = tmp_path / "soul.md"
        soul_md.write_text("Just a plain prompt.\n", encoding="utf-8")
        role = parse_role_manifest(soul_md)
        assert role is not None
        assert role.name == tmp_path.name  # stem from parent when path is file
        assert role.description == ""
        assert role.system_prompt == "Just a plain prompt."

    def test_parse_missing_file(self, tmp_path: Path) -> None:
        assert parse_role_manifest(tmp_path / "ghost") is None


class TestRoleManager:
    def test_create_role(self, tmp_path: Path) -> None:
        manager = RoleManager(soul_dir=tmp_path)
        role = Role(name="creator", description="Creates things", system_prompt="Create.")
        role_dir = manager.create(role)

        assert role_dir.exists()
        assert (role_dir / "soul.md").exists()
        assert (role_dir / "notes").exists()
        assert (role_dir / "notes").is_dir()

    def test_create_duplicate_raises(self, tmp_path: Path) -> None:
        manager = RoleManager(soul_dir=tmp_path)
        role = Role(name="dup", system_prompt="Dup.")
        manager.create(role)
        with pytest.raises(FileExistsError):
            manager.create(role)

    def test_save_and_load(self, tmp_path: Path) -> None:
        manager = RoleManager(soul_dir=tmp_path)
        role = Role(name="saver", description="Saves", system_prompt="Save me.")
        manager.save(role)

        loaded = manager.load("saver")
        assert loaded is not None
        assert loaded.name == "saver"
        assert loaded.description == "Saves"
        assert loaded.system_prompt == "Save me."

    def test_exists_and_delete(self, tmp_path: Path) -> None:
        manager = RoleManager(soul_dir=tmp_path)
        role = Role(name="deleter", system_prompt="Delete me.")
        manager.save(role)

        assert manager.exists("deleter") is True
        assert manager.delete("deleter") is True
        assert manager.exists("deleter") is False
        assert manager.delete("deleter") is False

    def test_list_roles(self, tmp_path: Path) -> None:
        manager = RoleManager(soul_dir=tmp_path)
        manager.save(Role(name="alpha", system_prompt="Alpha."))
        manager.save(Role(name="beta", system_prompt="Beta."))

        roles = manager.list_roles()
        names = {r.name for r in roles}
        assert names == {"alpha", "beta"}

    def test_ensure_notes_dir(self, tmp_path: Path) -> None:
        manager = RoleManager(soul_dir=tmp_path)
        role = Role(name="noter", system_prompt="Notes.")
        manager.save(role)

        notes = manager.ensure_notes_dir("noter")
        assert notes.exists()
        assert notes.is_dir()
        assert notes.name == "notes"
