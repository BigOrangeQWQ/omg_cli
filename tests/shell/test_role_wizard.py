"""Tests for RoleWizard."""

from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from omg_cli.config.manager import ConfigManager
from omg_cli.config.models import ModelConfig, RoleConfig
from omg_cli.config.role import RoleManager
from omg_cli.shell.role_wizard import RoleWizard, RoleWizardResult


class WizardApp(App):
    def __init__(self, config_manager: ConfigManager, role_manager: RoleManager) -> None:
        super().__init__()
        self.config_manager = config_manager
        self.role_manager = role_manager
        self.result: RoleWizardResult | None = None

    def compose(self) -> ComposeResult:
        yield RoleWizard(config_manager=self.config_manager, role_manager=self.role_manager)

    def on_role_wizard_completed(self, message: RoleWizard.Completed) -> None:
        self.result = message.result
        self.exit()


@pytest.fixture
def temp_config_dir():
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


class TestRoleWizardPage1:
    @pytest.mark.asyncio
    async def test_select_existing_role(self, temp_config_dir: Path) -> None:
        cm = ConfigManager(config_dir=temp_config_dir)
        rm = RoleManager(config_dir=temp_config_dir)
        rm.add_role_config(RoleConfig(name="coder", desc="Writes code", adapter_name="gpt-4"))
        cm.add_model(
            ModelConfig(
                name="gpt-4",
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
            )
        )

        app = WizardApp(cm, rm)
        async with app.run_test() as pilot:
            await pilot.press("enter")
            await pilot.pause()

        assert app.result is not None
        assert app.result.role_name == "coder"
        assert app.result.is_new is False


class TestRoleWizardPage2:
    @pytest.mark.asyncio
    async def test_create_new_role(self, temp_config_dir: Path) -> None:
        cm = ConfigManager(config_dir=temp_config_dir)
        rm = RoleManager(config_dir=temp_config_dir)
        cm.add_model(
            ModelConfig(
                name="gpt-4",
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
            )
        )

        app = WizardApp(cm, rm)
        async with app.run_test() as pilot:
            # No existing roles, should be on page 2
            name_input = app.query_one("#rw-p2-name")
            desc_input = app.query_one("#rw-p2-desc")
            model_input = app.query_one("#rw-p2-model")

            name_input.value = "reviewer"
            desc_input.text = "Reviews code"
            model_input.value = "gpt-4"
            name_input.focus()

            await pilot.press("enter")

        assert app.result is not None
        assert app.result.role_name == "reviewer"
        assert app.result.is_new is True

        role = rm.get_role_config("reviewer")
        assert role is not None
        assert role.desc == "Reviews code"
        assert role.adapter_name == "gpt-4"

    @pytest.mark.asyncio
    async def test_duplicate_name_error(self, temp_config_dir: Path) -> None:
        cm = ConfigManager(config_dir=temp_config_dir)
        rm = RoleManager(config_dir=temp_config_dir)
        rm.add_role_config(RoleConfig(name="coder", desc="", adapter_name="gpt-4"))
        cm.add_model(
            ModelConfig(
                name="gpt-4",
                provider="openai",
                model="gpt-4",
                base_url="https://api.openai.com/v1",
                api_key="sk-test",
            )
        )

        app = WizardApp(cm, rm)
        async with app.run_test() as pilot:
            # On page 1 because role exists, move to create option and enter
            await pilot.press("down", "enter")

            name_input = app.query_one("#rw-p2-name")
            name_input.value = "coder"
            name_input.focus()

            await pilot.press("enter")
            await pilot.pause()

            assert app.result is None
            error_widget = app.query_one("#rw-p2-error")
            assert "已存在" in error_widget.render().plain

    @pytest.mark.asyncio
    async def test_missing_model_error(self, temp_config_dir: Path) -> None:
        cm = ConfigManager(config_dir=temp_config_dir)
        rm = RoleManager(config_dir=temp_config_dir)

        app = WizardApp(cm, rm)
        async with app.run_test() as pilot:
            name_input = app.query_one("#rw-p2-name")
            name_input.value = "tester"
            name_input.focus()

            await pilot.press("enter")
            await pilot.pause()

            assert app.result is None
            error_widget = app.query_one("#rw-p2-error")
            assert "请选择模型" in error_widget.render().plain or "未找到模型" in error_widget.render().plain
