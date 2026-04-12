"""Tests for RoleManager."""

from pathlib import Path
import tempfile

import pytest

from omg_cli.config.models import RoleConfig
from omg_cli.config.role import RoleManager


@pytest.fixture
def temp_config_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


@pytest.fixture
def manager(temp_config_dir: Path):
    return RoleManager(config_dir=temp_config_dir)


class TestRoleManager:
    def test_empty_roles(self, manager: RoleManager) -> None:
        assert manager.list_roles() == []
        assert manager.get_role("any") is None

    def test_list_roles_instantiation(self, manager: RoleManager, temp_config_dir: Path) -> None:
        manager.save_roles_config([
            RoleConfig(name="coder", desc="Writes code", adapter_name="gpt-4"),
        ])

        roles = manager.list_roles()
        assert len(roles) == 1
        assert roles[0].name == "coder"
        assert roles[0].desc == "Writes code"
        assert roles[0].adapter_name == "gpt-4"
        assert roles[0].personal_space == temp_config_dir / "roles" / "coder"
        assert roles[0].personal_space.exists()

    def test_get_role(self, manager: RoleManager) -> None:
        manager.save_roles_config([
            RoleConfig(name="a", desc="", adapter_name="m1"),
            RoleConfig(name="b", desc="", adapter_name="m2"),
        ])

        role = manager.get_role("b")
        assert role is not None
        assert role.name == "b"
        assert role.adapter_name == "m2"

    def test_default_personal_space_fallback(self, manager: RoleManager, temp_config_dir: Path) -> None:
        manager.save_roles_config([
            RoleConfig(name="no_space", desc="", adapter_name="m1"),
        ])

        role = manager.get_role("no_space")
        assert role is not None
        assert role.personal_space == temp_config_dir / "roles" / "no_space"
