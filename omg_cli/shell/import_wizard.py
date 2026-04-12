"""Model import wizard - 2 pages: provider selection + config form."""

import secrets
from typing import ClassVar

from pydantic import SecretStr
from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.widget import Widget
from textual.widgets import Input, Static

from omg_cli.abstract import ChatAdapter
from omg_cli.abstract.anthropic import AnthropicAPI
from omg_cli.abstract.deepseek import DeepSeekAPI
from omg_cli.abstract.openai import OpenAIAPI
from omg_cli.abstract.openai_legacy import OpenAILegacy
from omg_cli.config import ModelConfig, ProviderType, get_config_manager
from omg_cli.shell.widgets import ComposerTextArea, SafeStatic

ADAPTER_MAP: dict[ProviderType, type | None] = {
    "openai": OpenAIAPI,
    "anthropic": AnthropicAPI,
    "deepseek": DeepSeekAPI,
    "openai_legacy": OpenAILegacy,
}


# Provider options: (key, display_name, default_base_url)
PROVIDERS: list[tuple[ProviderType, str, str]] = [
    ("openai", "OpenAI", "https://api.openai.com/v1"),
    ("anthropic", "Anthropic", "https://api.anthropic.com"),
    ("deepseek", "DeepSeek", "https://api.deepseek.com/v1"),
    ("openai_legacy", "OpenAI Compatible", ""),
]

# Common models for providers without list API
COMMON_MODELS: dict[ProviderType, list[str]] = {
    "anthropic": [
        "claude-3-opus-20240229",
        "claude-3-sonnet-20240229",
        "claude-3-haiku-20240307",
        "claude-3-5-sonnet-20241022",
        "claude-3-5-sonnet-20240620",
    ],
    "deepseek": [
        "deepseek-chat",
        "deepseek-reasoner",
    ],
    "openai": [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-4",
        "gpt-3.5-turbo",
    ],
    "openai_legacy": [],
}


class ImportWizard(Vertical):
    """2-page wizard: Page 1=Provider, Page 2=Config Form (URL, Key, Model, Name).

    Controls:
    - Page 1 (Provider): ↑↓=选择, Enter=下一步, Ctrl+C=退出
    - Page 2 (Config): Enter=导入, Ctrl+C=返回上一页
    - Focus model input with API key set to auto-fetch model list
    """

    can_focus = True
    can_focus_children = True
    mouse_enabled = True

    BINDINGS: ClassVar[list[BindingType]] = [
        ("up", "prev_option", "Previous"),
        ("down", "next_option", "Next"),
        ("enter", "confirm", "Confirm"),
        ("ctrl+c", "handle_ctrl_c", "Back/Exit"),
    ]

    def __init__(self) -> None:
        super().__init__(classes="import-wizard")
        self.page = 1  # Page 1=provider, Page 2=config form
        self.selected_index = 0
        self.selected_model_index = 0
        self.provider: ProviderType | None = None
        self.default_base_url: str = ""

        # Widget collections - populated in on_mount
        self.page1_widgets: list[Static | SafeStatic] = []
        self.page2_widgets: list[Widget] = []
        self.model_option_widgets: list[SafeStatic] = []
        self._current_models: list[str] = []  # Store models for filtering
        self._page2_inputs = [
            "p2-input-baseurl",
            "p2-input-apikey",
            "p2-input-model",
            "p2-input-maxcontext",
            "p2-input-custom",
        ]

    def compose(self) -> ComposeResult:
        # ===== Shared Title (always visible) =====
        yield SafeStatic("📥 导入新模型", classes="wizard-title")
        yield SafeStatic("", classes="wizard-spacer")

        # ===== Page 1: Provider Selection =====
        yield SafeStatic("选择提供商:", classes="wizard-label", id="p1-label")

        for i, (_, name, _) in enumerate(PROVIDERS):
            yield SafeStatic(self._format_option(i, name), classes="wizard-option", id=f"p1-provider-{i}")

        # ===== Page 2: Config Form (90% width container) =====
        with Vertical(classes="wizard-form"):
            # Base URL row
            yield SafeStatic("Base URL:", classes="wizard-label-small")
            with Horizontal(classes="wizard-input-row"):
                yield Input(placeholder="https://...", id="p2-input-baseurl")

            # API Key row
            yield SafeStatic("API Key:", classes="wizard-label-small")
            with Horizontal(classes="wizard-input-row"):
                yield Input(password=True, placeholder="sk-...", id="p2-input-apikey")

            # Model Name row
            yield SafeStatic("模型名称:", classes="wizard-label-small")
            with Horizontal(classes="wizard-input-row"):
                yield Input(placeholder="如: gpt-4o, claude-3-opus", id="p2-input-model")

            # Model selection list (hidden by default)
            yield SafeStatic("可用模型 (↑↓选择, Enter确认):", classes="wizard-label-small", id="p2-model-list-label")
            for i in range(8):  # Max 8 options
                yield SafeStatic("", classes="wizard-option", id=f"p2-model-opt-{i}")

            # Max Context row
            yield SafeStatic("Max Context (tokens):", classes="wizard-label-small")
            with Horizontal(classes="wizard-input-row"):
                yield Input(value="150000", id="p2-input-maxcontext")

            # Custom Name row
            yield SafeStatic("自定义名称 (可选):", classes="wizard-label-small")
            with Horizontal(classes="wizard-input-row"):
                yield Input(placeholder="留空使用模型名称", id="p2-input-custom")

            # Thinking mode hint
            yield SafeStatic("", classes="wizard-hint", id="p2-hint-thinking")

            # Error message area
            yield SafeStatic("", classes="wizard-error", id="p2-error")

    def on_mount(self) -> None:
        """Setup widget references and initial state."""
        self.page = 1
        self.selected_index = 0

        # Page 1 widgets
        self.page1_widgets = [
            self.query_one("#p1-label", SafeStatic),
        ]
        for i in range(len(PROVIDERS)):
            self.page1_widgets.append(self.query_one(f"#p1-provider-{i}", SafeStatic))

        # Page 2 widgets
        wizard_form = self.query_one(".wizard-form", Vertical)
        self.page2_widgets = [wizard_form]

        # Add all form children
        self.page2_widgets.extend(
            [
                self.query_one("#p2-input-baseurl", Input),
                self.query_one("#p2-input-apikey", Input),
                self.query_one("#p2-input-model", Input),
                self.query_one("#p2-model-list-label", SafeStatic),
                self.query_one("#p2-input-maxcontext", Input),
                self.query_one("#p2-input-custom", Input),
                self.query_one("#p2-hint-thinking", SafeStatic),
                self.query_one("#p2-error", SafeStatic),
            ]
        )

        # Model option widgets
        self.model_option_widgets = []
        for i in range(8):
            widget = self.query_one(f"#p2-model-opt-{i}", SafeStatic)
            self.model_option_widgets.append(widget)
            self.page2_widgets.append(widget)

        self._update_visibility()
        self._update_options()
        self.call_after_refresh(self._set_focus)

    def _set_focus(self) -> None:
        """Set focus based on current page."""
        if self.page == 1:
            self.focus()
        else:
            try:
                self.query_one("#p2-input-baseurl", Input).focus()
            except Exception:
                self.focus()

    def _format_option(self, index: int, name: str, selected: bool = False) -> str:
        prefix = "→ " if selected else "  "
        return f"{prefix}{name}"

    def _update_options(self) -> None:
        """Update provider selection display."""
        for i, widget in enumerate(self.page1_widgets[1:]):  # Skip label
            name = PROVIDERS[i][1]
            widget.update(self._format_option(i, name, i == self.selected_index))

    def _update_visibility(self) -> None:
        """Show/hide pages based on current page."""
        # Page 1
        show_p1 = self.page == 1
        for widget in self.page1_widgets:
            widget.styles.display = "block" if show_p1 else "none"

        # Page 2
        show_p2 = self.page == 2
        for widget in self.page2_widgets:
            widget.styles.display = "block" if show_p2 else "none"

        # Hide model list initially
        if show_p2:
            self.query_one("#p2-model-list-label", SafeStatic).styles.display = "none"
            for widget in self.model_option_widgets:
                widget.styles.display = "none"

        self.call_after_refresh(self._set_focus)

    # ===== Actions =====

    def action_prev_option(self) -> None:
        if self.page == 1:
            self.selected_index = (self.selected_index - 1) % len(PROVIDERS)
            self._update_options()
        elif self.page == 2:
            # Check if model list is showing
            if self.query_one("#p2-model-list-label", SafeStatic).styles.display == "block":
                self._prev_model_option()
            else:
                self._focus_prev_input()

    def action_next_option(self) -> None:
        if self.page == 1:
            self.selected_index = (self.selected_index + 1) % len(PROVIDERS)
            self._update_options()
        elif self.page == 2:
            # Check if model list is showing
            if self.query_one("#p2-model-list-label", SafeStatic).styles.display == "block":
                self._next_model_option()
            else:
                self._focus_next_input()

    def _focus_next_input(self) -> None:
        """Focus next input field on Page 2."""
        focused = self.app.focused
        if not focused or not focused.id:
            self.query_one("#p2-input-baseurl", Input).focus()
            return
        try:
            current_idx = self._page2_inputs.index(focused.id)
            next_idx = (current_idx + 1) % len(self._page2_inputs)
            self.query_one(f"#{self._page2_inputs[next_idx]}", Input).focus()
        except (ValueError, IndexError):
            self.query_one("#p2-input-baseurl", Input).focus()

    def _focus_prev_input(self) -> None:
        """Focus previous input field on Page 2."""
        focused = self.app.focused
        if not focused or not focused.id:
            self.query_one("#p2-input-baseurl", Input).focus()
            return
        try:
            current_idx = self._page2_inputs.index(focused.id)
            prev_idx = (current_idx - 1) % len(self._page2_inputs)
            self.query_one(f"#{self._page2_inputs[prev_idx]}", Input).focus()
        except (ValueError, IndexError):
            self.query_one("#p2-input-baseurl", Input).focus()

    def _next_model_option(self) -> None:
        """Select next model in the list."""
        visible_models = [w for w in self.model_option_widgets if w.styles.display == "block"]
        if not visible_models:
            return
        self.selected_model_index = (self.selected_model_index + 1) % len(visible_models)
        self._update_model_selection()

    def _prev_model_option(self) -> None:
        """Select previous model in the list."""
        visible_models = [w for w in self.model_option_widgets if w.styles.display == "block"]
        if not visible_models:
            return
        self.selected_model_index = (self.selected_model_index - 1) % len(visible_models)
        self._update_model_selection()

    def _update_model_selection(self) -> None:
        """Update the visual selection in model list."""
        visible_models = [w for w in self.model_option_widgets if w.styles.display == "block"]
        for i, widget in enumerate(visible_models):
            if hasattr(widget, "data_model") and widget.data_model:
                selected = i == self.selected_model_index
                widget.update(self._format_option(i, widget.data_model, selected))

    async def action_confirm(self) -> None:
        """Enter key action."""
        if self.page == 1:
            self._go_to_page2()
        else:
            # Check if model list is showing
            if self.query_one("#p2-model-list-label", SafeStatic).styles.display == "block":
                self._select_model_from_list()
            else:
                await self._submit_form()

    async def action_handle_ctrl_c(self) -> None:
        """Ctrl+C action: Page 1=Exit, Page 2=Back to Page 1."""
        if self.page == 1:
            self._cleanup()
            await self.remove()
        else:
            # If model list is showing, hide it
            if self.query_one("#p2-model-list-label", SafeStatic).styles.display == "block":
                self._hide_model_list()
            else:
                self._go_to_page1()

    # ===== Event Handlers =====

    def on_click(self, event: Click) -> None:
        """Handle mouse click."""
        target_id = getattr(event.control, "id", None)

        # Provider selection on Page 1
        if self.page == 1:
            if target_id and target_id.startswith("p1-provider-"):
                try:
                    idx = int(target_id.split("-")[-1])
                    self.selected_index = idx
                    self._update_options()
                    self._go_to_page2()
                except (ValueError, IndexError):
                    pass
            return

        # Model input click on Page 2 - fetch models
        if self.page == 2:
            if target_id == "p2-input-model":
                apikey_input = self.query_one("#p2-input-apikey", Input)
                if apikey_input.value.strip():
                    label = self.query_one("#p2-model-list-label", SafeStatic)
                    if label.styles.display != "block":
                        self._fetch_models()
                return

            # Model list selection
            if self.query_one("#p2-model-list-label", SafeStatic).styles.display == "block":
                if target_id and target_id.startswith("p2-model-opt-"):
                    try:
                        idx = int(target_id.split("-")[-1])
                        self._select_model_by_index(idx)
                    except (ValueError, IndexError):
                        pass
                return

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        """Enter in any input on page 2 submits the form."""
        if self.page == 2:
            await self._submit_form()

    def on_input_changed(self, event: Input.Changed) -> None:
        """Filter model list when user types in model input."""
        if self.page == 2 and event.control.id == "p2-input-model":
            label = self.query_one("#p2-model-list-label", SafeStatic)
            if label.styles.display == "block":
                prefix = event.value.lower().strip()
                if prefix:
                    # Filter models
                    filtered = [m for m in self._current_models if prefix in m.lower()]
                    if filtered:
                        self._update_filtered_model_list(filtered)
                    else:
                        # No matches, hide list
                        self._hide_model_list()
                else:
                    # Empty prefix, show all
                    self._update_filtered_model_list(self._current_models)

    async def on_focus(self, event) -> None:
        """Auto-fetch models when model input gets focus and API key is set."""
        if self.page == 2:
            # Check if the focused widget is the model input
            focused = self.app.focused
            if focused and focused.id == "p2-input-model":
                apikey_input = self.query_one("#p2-input-apikey", Input)
                if apikey_input.value.strip():
                    # Only fetch if list is not already showing
                    label = self.query_one("#p2-model-list-label", SafeStatic)
                    if label.styles.display != "block":
                        self._fetch_models()

    # ===== Navigation =====

    def _go_to_page2(self) -> None:
        """Go from provider selection to config form."""
        self.provider = PROVIDERS[self.selected_index][0]
        self.default_base_url = PROVIDERS[self.selected_index][2]

        # Pre-fill base URL
        baseurl_input = self.query_one("#p2-input-baseurl", Input)
        baseurl_input.value = self.default_base_url

        # Update thinking hint based on provider default
        self._update_thinking_hint()

        self.page = 2
        self._update_visibility()

    def _go_to_page1(self) -> None:
        """Go back from config form to provider selection."""
        self.page = 1
        self._hide_model_list()
        self._clear_error()
        self._update_visibility()

    def _update_thinking_hint(self) -> None:
        """Update thinking mode hint based on provider."""
        try:
            hint_widget = self.query_one("#p2-hint-thinking", SafeStatic)
            default_thinking = self.provider in ["anthropic", "deepseek"]
            status = "✓ 默认启用" if default_thinking else "✗ 默认关闭"
            hint_widget.update(f"Thinking: {status} (模型名+t启用/-t禁用)")
        except Exception:
            pass

    # ===== Model List =====

    def _fetch_models(self) -> None:
        """Fetch available models from API (async wrapper)."""
        self.run_worker(self._fetch_models_async())

    async def _fetch_models_async(self) -> None:
        """Fetch available models from API."""
        if not self.provider:
            return

        baseurl_input = self.query_one("#p2-input-baseurl", Input)
        apikey_input = self.query_one("#p2-input-apikey", Input)

        base_url = baseurl_input.value.strip()
        api_key = apikey_input.value.strip()

        if not base_url:
            self._show_error("⚠ 请先填写 Base URL")
            return

        # Use dummy key if not provided
        used_dummy_key = False
        if not api_key:
            api_key = f"dummy-{secrets.token_hex(8)}"
            used_dummy_key = True

        self._clear_error()

        # Get adapter class
        adapter_class = ADAPTER_MAP.get(self.provider)
        if not adapter_class:
            # Fallback to common models
            models = COMMON_MODELS.get(self.provider, [])
            self._show_model_list(models)
            return

        # Create adapter and fetch models
        try:
            # Use a placeholder model name for listing
            adapter: ChatAdapter = adapter_class(
                api_key=api_key,
                model="placeholder",
                base_url=base_url,
                stream=False,
            )
            models = await adapter.list_models()
            if models:
                self._show_model_list(models)
            else:
                # Empty result, hide list
                self._hide_model_list()
        except Exception:
            # API call failed
            if used_dummy_key:
                # Dummy key failed, show empty list (user can type manually)
                self._hide_model_list()
            else:
                # Real key failed, fallback to common models
                models = COMMON_MODELS.get(self.provider, [])
                self._show_model_list(models)

    def _show_model_list(self, models: list[str]) -> None:
        """Show model selection list."""
        self._current_models = models

        # Update label
        label = self.query_one("#p2-model-list-label", SafeStatic)
        label.styles.display = "block"

        # Show available models
        for i, widget in enumerate(self.model_option_widgets):
            if i < len(models):
                widget.update(self._format_option(i, models[i], i == 0))
                widget.styles.display = "block"
                widget.data_model = models[i]  # Store model name
            else:
                widget.styles.display = "none"
                widget.data_model = None

        self.selected_model_index = 0

    def _update_filtered_model_list(self, models: list[str]) -> None:
        """Update display with filtered model list."""
        for i, widget in enumerate(self.model_option_widgets):
            if i < len(models):
                widget.update(self._format_option(i, models[i], i == 0))
                widget.styles.display = "block"
                widget.data_model = models[i]
            else:
                widget.styles.display = "none"
                widget.data_model = None
        self.selected_model_index = 0

    def _hide_model_list(self) -> None:
        """Hide model selection list."""
        label = self.query_one("#p2-model-list-label", SafeStatic)
        label.styles.display = "none"
        for widget in self.model_option_widgets:
            widget.styles.display = "none"

    def _select_model_by_index(self, index: int) -> None:
        """Select model at index."""
        widget = self.model_option_widgets[index]
        if hasattr(widget, "data_model") and widget.data_model:
            model_input = self.query_one("#p2-input-model", Input)
            model_input.value = widget.data_model
            self._hide_model_list()

    def _select_model_from_list(self) -> None:
        """Select currently highlighted model."""
        for i, widget in enumerate(self.model_option_widgets):
            if widget.styles.display == "block" and hasattr(widget, "data_model"):
                # Find selected one (with → prefix)
                if widget.data_model:
                    model_input = self.query_one("#p2-input-model", Input)
                    model_input.value = widget.data_model
                    self._hide_model_list()
                    return

    # ===== Form Submission =====

    def _show_error(self, message: str) -> None:
        try:
            self.query_one("#p2-error", SafeStatic).update(message)
        except Exception:
            pass

    def _clear_error(self) -> None:
        try:
            self.query_one("#p2-error", SafeStatic).update("")
        except Exception:
            pass

    async def _submit_form(self) -> None:
        """Submit config form and save model."""
        baseurl_input = self.query_one("#p2-input-baseurl", Input)
        model_input = self.query_one("#p2-input-model", Input)
        apikey_input = self.query_one("#p2-input-apikey", Input)
        maxcontext_input = self.query_one("#p2-input-maxcontext", Input)
        customname_input = self.query_one("#p2-input-custom", Input)

        base_url = baseurl_input.value.strip()
        model = model_input.value.strip()
        api_key = apikey_input.value.strip()
        max_context_str = maxcontext_input.value.strip()
        custom_name = customname_input.value.strip()

        # Validate
        if not base_url:
            self._show_error("⚠ 请输入 Base URL")
            baseurl_input.focus()
            return
        if not model:
            self._show_error("⚠ 请输入模型名称")
            model_input.focus()
            return
        if not api_key:
            self._show_error("⚠ 请输入 API Key")
            apikey_input.focus()
            return
        if not self.provider:
            self._show_error("⚠ 内部错误: 未选择提供商")
            return

        # Validate max_context
        try:
            max_context = int(max_context_str)
        except ValueError:
            self._show_error("⚠ Max Context 必须是正整数")
            maxcontext_input.focus()
            return
        if max_context <= 0:
            self._show_error("⚠ Max Context 必须是正整数")
            maxcontext_input.focus()
            return

        self._clear_error()

        # Parse model name for thinking suffix (+t or -t)
        thinking_override = None
        clean_model = model
        if model.endswith("+t"):
            thinking_override = True
            clean_model = model[:-2]
        elif model.endswith("-t"):
            thinking_override = False
            clean_model = model[:-2]

        # Generate unique name (empty custom name uses model name)
        name = custom_name or clean_model.split("/")[-1]
        config_manager = get_config_manager()
        base_name = name
        for i in range(2, 100):
            if not config_manager.get_model(name):
                break
            name = f"{base_name}-{i}"

        # Create and save config
        # Default based on provider, but allow override via +t/-t suffix
        default_thinking = self.provider in ["anthropic", "deepseek"]
        thinking_supported = thinking_override if thinking_override is not None else default_thinking
        model_config = ModelConfig(
            name=name,
            provider=self.provider,
            model=clean_model,
            base_url=base_url,
            api_key=SecretStr(api_key),
            thinking_supported=thinking_supported,
            max_context=max_context,
        )
        config_manager.add_model(model_config)

        if len(config_manager.list_models()) == 1:
            config_manager.set_default_model(name)

        self._cleanup()
        await self.remove()

        from .app import ChatTerminalApp

        if isinstance(self.app, ChatTerminalApp):
            # Clear messages and show success in message history, then reload model
            import asyncio

            self._pending_task = asyncio.create_task(self.app.on_model_imported(name))

    # ===== Cleanup =====

    def _cleanup(self) -> None:
        """Restore composer when wizard closes."""
        from .app import ChatTerminalApp

        if isinstance(self.app, ChatTerminalApp):
            try:
                composer = self.app.query_one("#composer", ComposerTextArea)
                composer.styles.display = "block"
                composer.focus()
            except Exception:
                pass
