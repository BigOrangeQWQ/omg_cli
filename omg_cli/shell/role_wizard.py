"""Role wizard for Channel mode - select existing or create new role."""

from dataclasses import dataclass
from typing import ClassVar

from textual.app import ComposeResult
from textual.binding import BindingType
from textual.containers import Horizontal, Vertical
from textual.events import Click
from textual.message import Message
from textual.widgets import Input, TextArea

from omg_cli.config import get_config_manager
from omg_cli.config.models import RoleConfig
from omg_cli.config.role import get_role_manager
from omg_cli.shell.widgets import ComposerTextArea, SafeStatic


@dataclass
class RoleWizardResult:
    role_name: str
    is_new: bool


class RoleWizard(Vertical):
    """2-page wizard: Page 1=select existing role, Page 2=create new role form."""

    can_focus = True
    can_focus_children = True
    mouse_enabled = True

    class Completed(Message):
        """Posted when the wizard finishes (role selected or created)."""

        def __init__(self, result: RoleWizardResult | None, *, exit_on_cancel: bool) -> None:
            self.result = result
            self.exit_on_cancel = exit_on_cancel
            super().__init__()

    BINDINGS: ClassVar[list[BindingType]] = [
        ("up", "cursor_up", "Up"),
        ("down", "cursor_down", "Down"),
        ("enter", "confirm", "Confirm"),
        ("ctrl+c", "handle_ctrl_c", "Back/Exit"),
        ("ctrl+d", "quit_app", "Quit"),
    ]

    def __init__(
        self,
        *,
        config_manager=None,
        role_manager=None,
        exit_on_cancel: bool = True,
    ) -> None:
        super().__init__(classes="role-wizard")
        self.page = 1  # 1=select, 2=create
        self.selected_index = 0
        self._exit_on_cancel = exit_on_cancel
        self._config_manager = config_manager or get_config_manager()
        self._role_manager = role_manager or get_role_manager()
        self._existing_roles: list[RoleConfig] = self._role_manager.list_roles_config()
        self._model_names: list[str] = [m.name for m in self._config_manager.list_models()]

        self.page1_widgets: list = []
        self.page2_widgets: list = []
        self.model_option_widgets: list[SafeStatic] = []
        self._last_selected_index: int = -1
        self._last_model_selected_index: int = -1

    def compose(self) -> ComposeResult:
        yield SafeStatic("🎭 Role 设置", classes="wizard-title")
        yield SafeStatic("", classes="wizard-spacer")

        # ===== Page 1: Existing role selection =====
        yield SafeStatic("选择默认 Role:", classes="wizard-label", id="rw-p1-label")
        for i, role in enumerate(self._existing_roles):
            display = f"{role.name} - {role.desc}" if role.desc else role.name
            yield SafeStatic(
                self._format_option(i, display),
                classes="wizard-option",
                id=f"rw-p1-role-{i}",
            )
        yield SafeStatic(
            self._format_option(len(self._existing_roles), "➕ 创建新 Role"),
            classes="wizard-option",
            id="rw-p1-create",
        )

        # ===== Page 2: Create form =====
        with Vertical(classes="wizard-form"):
            yield SafeStatic("Role 名称:", classes="wizard-label-small")
            with Horizontal(classes="wizard-input-row"):
                yield Input(placeholder="如: coder", id="rw-p2-name")

            yield SafeStatic("角色简介:", classes="wizard-label-small")
            yield TextArea(
                placeholder="描述该角色的职责与系统提示词...",
                id="rw-p2-desc",
                soft_wrap=True,
                show_line_numbers=False,
                highlight_cursor_line=False,
            )

            yield SafeStatic("选择模型:", classes="wizard-label-small")
            yield Input(placeholder="输入或选择模型配置名", id="rw-p2-model")

            yield SafeStatic(
                "可用模型 (↑↓选择, Enter确认):",
                classes="wizard-label-small",
                id="rw-p2-model-list-label",
            )
            for i in range(8):
                yield SafeStatic("", classes="wizard-option", id=f"rw-p2-model-opt-{i}")

            yield SafeStatic("", classes="wizard-error", id="rw-p2-error")

    def on_mount(self) -> None:
        # Page 1 widgets
        self.page1_widgets = [
            self.query_one("#rw-p1-label", SafeStatic),
        ]
        for i in range(len(self._existing_roles)):
            self.page1_widgets.append(self.query_one(f"#rw-p1-role-{i}", SafeStatic))
        self.page1_widgets.append(self.query_one("#rw-p1-create", SafeStatic))

        # Page 2 widgets
        wizard_form = self.query_one(".wizard-form", Vertical)
        self.page2_widgets = [wizard_form]
        self.page2_widgets.extend(
            [
                self.query_one("#rw-p2-name", Input),
                self.query_one("#rw-p2-desc", TextArea),
                self.query_one("#rw-p2-model", Input),
                self.query_one("#rw-p2-model-list-label", SafeStatic),
                self.query_one("#rw-p2-error", SafeStatic),
            ]
        )
        for i in range(8):
            w = self.query_one(f"#rw-p2-model-opt-{i}", SafeStatic)
            self.model_option_widgets.append(w)
            self.page2_widgets.append(w)

        # If no existing roles, skip to page 2
        if not self._existing_roles:
            self.page = 2
        else:
            self.page = 1
            self.selected_index = 0
            self._update_role_options()

        self._update_visibility()
        self.call_after_refresh(self._set_focus)

    def _set_focus(self) -> None:
        if self.page == 1:
            self.can_focus_children = False
            self.focus()
            self.can_focus_children = True
        else:
            try:
                self.query_one("#rw-p2-name", Input).focus()
            except Exception:
                self.focus()

    def _update_visibility(self) -> None:
        show_p1 = self.page == 1
        for w in self.page1_widgets:
            w.styles.display = "block" if show_p1 else "none"

        show_p2 = self.page == 2
        for w in self.page2_widgets:
            w.styles.display = "block" if show_p2 else "none"

        # Hide model list initially on page 2
        if show_p2:
            self.query_one("#rw-p2-model-list-label", SafeStatic).styles.display = "none"
            for w in self.model_option_widgets:
                w.styles.display = "none"

        self.call_after_refresh(self._set_focus)

    def _format_option(self, index: int, name: str, selected: bool = False) -> str:
        prefix = "→ " if selected else "  "
        return f"{prefix}{name}"

    def _update_role_options(self) -> None:
        last = self._last_selected_index
        current = self.selected_index
        total = len(self._existing_roles) + 1

        def _update_idx(idx: int) -> None:
            if idx < 0 or idx >= total:
                return
            if idx < len(self._existing_roles):
                role = self._existing_roles[idx]
                display = f"{role.name} - {role.desc}" if role.desc else role.name
                widget = self.query_one(f"#rw-p1-role-{idx}", SafeStatic)
                widget.update(self._format_option(idx, display, idx == current))
            else:
                widget = self.query_one("#rw-p1-create", SafeStatic)
                widget.update(self._format_option(idx, "➕ 创建新 Role", idx == current))

        if last != current:
            _update_idx(last)
            _update_idx(current)
        self._last_selected_index = current

    def _update_model_list(self, models: list[str]) -> None:
        label = self.query_one("#rw-p2-model-list-label", SafeStatic)
        self._last_model_selected_index = -1
        if models:
            label.styles.display = "block"
            for i, w in enumerate(self.model_option_widgets):
                if i < len(models):
                    w.update(self._format_option(i, models[i], i == 0))
                    w.styles.display = "block"
                    w.data_model = models[i]
                else:
                    w.styles.display = "none"
                    w.data_model = None
            self.selected_index = 0
        else:
            label.styles.display = "none"
            for w in self.model_option_widgets:
                w.styles.display = "none"
                w.data_model = None

    # ===== Actions =====

    def action_cursor_up(self) -> None:
        if self.page == 1:
            total_options = len(self._existing_roles) + 1
            self.selected_index = (self.selected_index - 1) % total_options
            self._update_role_options()
        elif self.page == 2:
            if self.query_one("#rw-p2-model-list-label", SafeStatic).styles.display == "block":
                visible = [w for w in self.model_option_widgets if w.styles.display == "block"]
                if visible:
                    self.selected_index = (self.selected_index - 1) % len(visible)
                    self._update_model_selection()

    def action_cursor_down(self) -> None:
        if self.page == 1:
            total_options = len(self._existing_roles) + 1
            self.selected_index = (self.selected_index + 1) % total_options
            self._update_role_options()
        elif self.page == 2:
            if self.query_one("#rw-p2-model-list-label", SafeStatic).styles.display == "block":
                visible = [w for w in self.model_option_widgets if w.styles.display == "block"]
                if visible:
                    self.selected_index = (self.selected_index + 1) % len(visible)
                    self._update_model_selection()

    def _update_model_selection(self) -> None:
        visible = [w for w in self.model_option_widgets if w.styles.display == "block"]
        last = self._last_model_selected_index
        current = self.selected_index

        def _update_idx(idx: int) -> None:
            if 0 <= idx < len(visible):
                w = visible[idx]
                if w.data_model:
                    w.update(self._format_option(idx, w.data_model, idx == current))

        if last != current:
            _update_idx(last)
            _update_idx(current)
        self._last_model_selected_index = current

    async def action_confirm(self) -> None:
        if self.page == 1:
            if self.selected_index < len(self._existing_roles):
                await self._select_existing_role()
            else:
                self._go_to_page2()
        else:
            if self.query_one("#rw-p2-model-list-label", SafeStatic).styles.display == "block":
                self._select_model_from_list()
            else:
                await self._submit_form()

    async def action_handle_ctrl_c(self) -> None:
        if self.page == 1:
            await self._resolve(None)
        else:
            if self.query_one("#rw-p2-model-list-label", SafeStatic).styles.display == "block":
                self._hide_model_list()
            elif self._existing_roles:
                self._go_to_page1()
            else:
                await self._resolve(None)

    def action_quit_app(self) -> None:
        self.app.exit()

    # ===== Navigation =====

    def _go_to_page1(self) -> None:
        self.page = 1
        self.selected_index = 0
        self._last_selected_index = -1
        self._last_model_selected_index = -1
        self._clear_error()
        self._update_visibility()

    def _go_to_page2(self) -> None:
        self.page = 2
        self.selected_index = 0
        self._last_selected_index = -1
        self._last_model_selected_index = -1
        self._clear_error()
        self._update_visibility()

    def _hide_model_list(self) -> None:
        self.query_one("#rw-p2-model-list-label", SafeStatic).styles.display = "none"
        for w in self.model_option_widgets:
            w.styles.display = "none"
            w.data_model = None

    # ===== Event Handlers =====

    async def on_click(self, event: Click) -> None:
        target_id = getattr(event.control, "id", None)

        if self.page == 1:
            if target_id and target_id.startswith("rw-p1-role-"):
                try:
                    idx = int(target_id.split("-")[-1])
                    self.selected_index = idx
                    self._update_role_options()
                    await self._select_existing_role()
                except ValueError:
                    pass
            elif target_id == "rw-p1-create":
                self._go_to_page2()
            return

        if self.page == 2:
            # Model list click
            if self.query_one("#rw-p2-model-list-label", SafeStatic).styles.display == "block":
                if target_id and target_id.startswith("rw-p2-model-opt-"):
                    try:
                        idx = int(target_id.split("-")[-1])
                        self._select_model_by_index(idx)
                    except ValueError:
                        pass
                return
            # Model input click - show list
            if target_id == "rw-p2-model":
                self._update_model_list(self._model_names)
                return

    def on_input_changed(self, event: Input.Changed) -> None:
        if self.page == 2 and event.control.id == "rw-p2-model":
            prefix = event.value.lower().strip()
            if prefix:
                filtered = [m for m in self._model_names if prefix in m.lower()]
                self._update_model_list(filtered)
            else:
                self._update_model_list(self._model_names)

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        if self.page == 2:
            model_list_label = self.query_one("#rw-p2-model-list-label", SafeStatic)
            if event.input.id == "rw-p2-model" and model_list_label.styles.display == "block":
                self._select_model_from_list()
            else:
                await self._submit_form()

    async def on_focus(self, event) -> None:
        if self.page == 2:
            focused = self.app.focused
            if focused and focused.id == "rw-p2-model":
                if self.query_one("#rw-p2-model-list-label", SafeStatic).styles.display != "block":
                    self._update_model_list(self._model_names)

    async def _select_existing_role(self) -> None:
        if not self._existing_roles:
            self._show_error("没有可用的 Role，请先创建")
            return
        if not (0 <= self.selected_index < len(self._existing_roles)):
            self._show_error("请先选择一个 Role")
            return
        role_name = self._existing_roles[self.selected_index].name
        await self._resolve(RoleWizardResult(role_name=role_name, is_new=False))

    def _select_model_by_index(self, index: int) -> None:
        widget = self.model_option_widgets[index]
        if widget.data_model:
            self.query_one("#rw-p2-model", Input).value = widget.data_model
            self._hide_model_list()

    def _select_model_from_list(self) -> None:
        visible = [w for w in self.model_option_widgets if w.styles.display == "block"]
        for i, w in enumerate(visible):
            if i == self.selected_index and w.data_model:
                self.query_one("#rw-p2-model", Input).value = w.data_model
                self._hide_model_list()
                return

    # ===== Form Submission =====

    def _show_error(self, message: str) -> None:
        self.query_one("#rw-p2-error", SafeStatic).update(message)

    def _clear_error(self) -> None:
        self.query_one("#rw-p2-error", SafeStatic).update("")

    async def _submit_form(self) -> None:
        name_input = self.query_one("#rw-p2-name", Input)
        desc_input = self.query_one("#rw-p2-desc", TextArea)
        model_input = self.query_one("#rw-p2-model", Input)

        name = name_input.value.strip()
        desc = desc_input.text.strip()
        model = model_input.value.strip()

        if not name:
            self._show_error("⚠ 请输入 Role 名称")
            name_input.focus()
            return

        if self._role_manager.get_role_config(name) is not None:
            self._show_error(f"⚠ Role '{name}' 已存在")
            name_input.focus()
            return

        if not model:
            self._show_error("⚠ 请选择模型")
            model_input.focus()
            return

        if self._config_manager.get_model(model) is None:
            self._show_error(f"⚠ 未找到模型配置 '{model}'，请先 /import")
            model_input.focus()
            return

        self._clear_error()

        role_config = RoleConfig(name=name, desc=desc, adapter_name=model)
        self._role_manager.add_role_config(role_config)

        await self._resolve(RoleWizardResult(role_name=name, is_new=True))

    async def _resolve(self, result: RoleWizardResult | None) -> None:
        self._cleanup()
        self.post_message(self.Completed(result, exit_on_cancel=self._exit_on_cancel))
        await self.remove()

    def _cleanup(self) -> None:
        from .app import ChatTerminalApp

        if isinstance(self.app, ChatTerminalApp):
            try:
                composer = self.app.query_one("#composer", ComposerTextArea)
                composer.styles.display = "block"
                composer.focus()
            except Exception:
                pass
