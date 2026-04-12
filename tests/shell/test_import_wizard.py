"""Tests for ImportWizard."""

from pathlib import Path

import pytest
from textual.app import App, ComposeResult

from omg_cli.config.manager import ConfigManager
from omg_cli.shell.import_wizard import ImportWizard


class WizardApp(App):
    def compose(self) -> ComposeResult:
        yield ImportWizard()


@pytest.fixture
def temp_config_dir(tmp_path: Path):
    return tmp_path


class TestImportWizard:
    @pytest.mark.asyncio
    async def test_submit_with_max_context(self, temp_config_dir: Path, monkeypatch) -> None:
        cm = ConfigManager(config_dir=temp_config_dir)
        monkeypatch.setattr(
            "omg_cli.shell.import_wizard.get_config_manager", lambda: cm
        )

        app = WizardApp()
        async with app.run_test() as pilot:
            # Page 1: select provider (openai is first, press enter)
            await pilot.press("enter")
            await pilot.pause()

            # Page 2: fill form
            baseurl_input = app.query_one("#p2-input-baseurl")
            apikey_input = app.query_one("#p2-input-apikey")
            model_input = app.query_one("#p2-input-model")
            maxcontext_input = app.query_one("#p2-input-maxcontext")
            customname_input = app.query_one("#p2-input-custom")

            baseurl_input.value = "https://api.openai.com/v1"
            apikey_input.value = "sk-test"
            model_input.value = "gpt-4o"
            maxcontext_input.value = "64000"
            customname_input.value = "my-gpt4o"

            await pilot.press("enter")
            await pilot.pause()

        model = cm.get_model("my-gpt4o")
        assert model is not None
        assert model.max_context == 64000
        assert model.provider == "openai"
        assert model.model == "gpt-4o"

    @pytest.mark.asyncio
    async def test_invalid_max_context_shows_error(self, temp_config_dir: Path, monkeypatch) -> None:
        cm = ConfigManager(config_dir=temp_config_dir)
        monkeypatch.setattr(
            "omg_cli.shell.import_wizard.get_config_manager", lambda: cm
        )

        app = WizardApp()
        async with app.run_test() as pilot:
            # Page 1: select provider
            await pilot.press("enter")
            await pilot.pause()

            # Page 2: fill form with invalid max_context
            baseurl_input = app.query_one("#p2-input-baseurl")
            apikey_input = app.query_one("#p2-input-apikey")
            model_input = app.query_one("#p2-input-model")
            maxcontext_input = app.query_one("#p2-input-maxcontext")

            baseurl_input.value = "https://api.openai.com/v1"
            apikey_input.value = "sk-test"
            model_input.value = "gpt-4o"
            maxcontext_input.value = "abc"

            await pilot.press("enter")
            await pilot.pause()

            # Wizard should still be on page 2
            wizard = app.query_one(ImportWizard)
            assert wizard.page == 2
            error_widget = app.query_one("#p2-error")
            assert "必须是正整数" in str(error_widget.render())
            assert cm.get_model("gpt-4o") is None
