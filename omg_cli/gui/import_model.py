"""Model import interface for GUI - single-page form with provider selection."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

from pydantic import SecretStr
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget
from qfluentwidgets import (
    BodyLabel,
    CardWidget,
    CheckBox,
    ComboBox,
    EditableComboBox,
    LineEdit,
    PasswordLineEdit,
    PrimaryPushButton,
    PushButton,
    StrongBodyLabel,
)
from qfluentwidgets import FluentIcon as FIF

from omg_cli.config import ModelConfig, get_config_manager
from omg_cli.config.models import ProviderType
from omg_cli.log import logger

if TYPE_CHECKING:
    from omg_cli.context.chat import ChatContext

# Provider options with display name and default base URL
PROVIDERS: list[tuple[ProviderType, str, str]] = [
    ("openai", "OpenAI", "https://api.openai.com/v1"),
    ("anthropic", "Anthropic", "https://api.anthropic.com"),
    ("deepseek", "DeepSeek", "https://api.deepseek.com/v1"),
    ("openai_legacy", "OpenAI Compatible", ""),
]

PROVIDER_NAMES = {prov[0]: prov[1] for prov in PROVIDERS}
PROVIDER_DEFAULT_URLS = {prov[0]: prov[2] for prov in PROVIDERS}


class ImportModelInterface(QWidget):
    """Model import page with form-based input."""

    modelImported = Signal(str)  # Emitted with model name after successful import

    def __init__(self, context: "ChatContext | None" = None, parent: QWidget | None = None) -> None:
        super().__init__(parent=parent)
        self.context = context
        self._task: asyncio.Task = None
        self._hide_task: asyncio.Task = None
        self.setObjectName("importModelInterface")
        self.setStyleSheet("ImportModelInterface { background-color: #f5f6f8; }")

        self._init_ui()

    def _init_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(40, 20, 40, 20)
        main_layout.setSpacing(20)

        # Title
        title = StrongBodyLabel(self.tr("导入模型"), self)
        main_layout.addWidget(title)

        # Description
        desc = BodyLabel(
            self.tr(
                "填写模型提供商信息。Base URL 和 API Key 必填。模型名称为空时，点击提供商下拉框可自动获取可用模型列表。"
            ),
            self,
        )
        desc.setWordWrap(True)
        main_layout.addWidget(desc)

        # Form card
        form_card = CardWidget(self)
        form_card.setObjectName("import-form-card")
        form_card.setBorderRadius(8)
        form_card.setStyleSheet(
            "CardWidget#import-form-card {"
            "  background-color: rgba(255, 255, 255, 0.95);"
            "  border: 1px solid rgba(0, 0, 0, 0.08);"
            "  border-radius: 8px;"
            "}"
        )

        form_layout = QVBoxLayout(form_card)
        form_layout.setContentsMargins(20, 20, 20, 20)
        form_layout.setSpacing(12)

        # Provider selector row
        form_layout.addWidget(BodyLabel(self.tr("提供商 (Provider)"), form_card))
        self.provider_combo = ComboBox(form_card)
        self.provider_combo.addItems([PROVIDER_NAMES[prov] for prov, _, _ in PROVIDERS])
        self.provider_combo.setCurrentIndex(0)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        form_layout.addWidget(self.provider_combo)

        # Base URL row
        form_layout.addWidget(BodyLabel(self.tr("Base URL"), form_card))
        self.base_url_input = EditableComboBox(form_card)
        self.base_url_input.setPlaceholderText(self.tr("https://..."))
        # Pre-fill with default
        self.base_url_input.setText(PROVIDER_DEFAULT_URLS[PROVIDERS[0][0]])
        form_layout.addWidget(self.base_url_input)

        # API Key row
        form_layout.addWidget(BodyLabel(self.tr("API Key"), form_card))
        self.api_key_input = PasswordLineEdit(form_card)
        self.api_key_input.setPlaceholderText(self.tr("sk-..."))
        form_layout.addWidget(self.api_key_input)

        # Model name row (optional - will auto-fetch if empty)
        form_layout.addWidget(BodyLabel(self.tr("模型名称"), form_card))
        self.model_name_input = EditableComboBox(form_card)
        self.model_name_input.setPlaceholderText(self.tr("如: gpt-4o, claude-3-opus (留空自动获取)"))
        form_layout.addWidget(self.model_name_input)

        # Max context row
        form_layout.addWidget(BodyLabel(self.tr("最大上下文长度(Max Tokens)"), form_card))
        self.max_context_input = LineEdit(form_card)
        self.max_context_input.setText("150000")
        form_layout.addWidget(self.max_context_input)

        # Custom name row (optional)
        form_layout.addWidget(BodyLabel(self.tr("自定义名称 (可选)"), form_card))
        self.custom_name_input = LineEdit(form_card)
        self.custom_name_input.setPlaceholderText(self.tr("留空使用模型名称"))
        form_layout.addWidget(self.custom_name_input)

        # Flash model checkbox
        self.flash_checkbox = CheckBox(self.tr("清亮模型（用于轻量任务，如 compact toolcall）"), form_card)
        self.flash_checkbox.setChecked(False)
        form_layout.addWidget(self.flash_checkbox)

        # Error label
        self.error_label = BodyLabel("", form_card)
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("color: #ff6b6b;")
        self.error_label.hide()
        form_layout.addWidget(self.error_label)

        form_layout.addStretch(1)

        # Button row
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(0, 0, 0, 0)
        button_layout.setSpacing(10)

        self.import_button = PrimaryPushButton(self.tr("导入"), form_card)
        self.import_button.setIcon(FIF.ADD)
        self.import_button.clicked.connect(self._on_import_clicked)
        button_layout.addWidget(self.import_button)

        self.cancel_button = PushButton(self.tr("清空"), form_card)
        self.cancel_button.clicked.connect(self._on_reset_clicked)
        button_layout.addWidget(self.cancel_button)

        button_layout.addStretch(1)
        form_layout.addLayout(button_layout)

        main_layout.addWidget(form_card, stretch=1)

    def _on_provider_changed(self, index: int) -> None:
        """Update base URL when provider changes."""
        if 0 <= index < len(PROVIDERS):
            provider = PROVIDERS[index][0]
            default_url = PROVIDER_DEFAULT_URLS[provider]
            self.base_url_input.setText(default_url)

    def _on_reset_clicked(self) -> None:
        """Clear all form fields."""
        self.base_url_input.setText(PROVIDER_DEFAULT_URLS[PROVIDERS[self.provider_combo.currentIndex()][0]])
        self.api_key_input.setText("")
        self.model_name_input.setText("")
        self.max_context_input.setText("150000")
        self.custom_name_input.setText("")
        self.flash_checkbox.setChecked(False)
        self.error_label.hide()

    def _on_import_clicked(self) -> None:
        """Handle import button click."""
        self._task = asyncio.create_task(self._do_import())

    async def _do_import(self) -> None:
        """Perform model import (async)."""
        # Validate inputs
        base_url = self.base_url_input.text().strip()
        api_key = self.api_key_input.text().strip()
        model_name = self.model_name_input.text().strip()
        max_context_str = self.max_context_input.text().strip()
        flash = self.flash_checkbox.isChecked()
        custom_name = self.custom_name_input.text().strip()

        if not base_url:
            self._show_error(self.tr("⚠ 请输入 Base URL"))
            return

        if not api_key:
            self._show_error(self.tr("⚠ 请输入 API Key"))
            return

        if not model_name:
            self._show_error(self.tr("⚠ 请输入或选择模型名称"))
            return

        try:
            max_context = int(max_context_str)
            if max_context <= 0:
                raise ValueError()
        except ValueError:
            self._show_error(self.tr("⚠ Max Context 必须是正整数"))
            return

        # Get provider
        provider_idx = self.provider_combo.currentIndex()
        if not 0 <= provider_idx < len(PROVIDERS):
            self._show_error(self.tr("⚠ 提供商选择无效"))
            return

        provider = PROVIDERS[provider_idx][0]

        # Parse thinking support from model name suffix
        thinking_override = None
        clean_model = model_name
        if model_name.endswith("+t"):
            thinking_override = True
            clean_model = model_name[:-2]
        elif model_name.endswith("-t"):
            thinking_override = False
            clean_model = model_name[:-2]

        # Generate unique config name
        name = custom_name or clean_model.split("/")[-1]
        config_manager = get_config_manager()
        base_name = name
        for i in range(2, 100):
            if not config_manager.get_model(name):
                break
            name = f"{base_name}-{i}"

        # Determine thinking support (default based on provider)
        default_thinking = provider in ["anthropic", "deepseek"]
        thinking_supported = thinking_override if thinking_override is not None else default_thinking

        # Create and save model config
        model_config = ModelConfig(
            name=name,
            provider=provider,
            model=clean_model,
            base_url=base_url,
            api_key=SecretStr(api_key),
            thinking_supported=thinking_supported,
            flash=flash,
            max_context=max_context,
        )

        try:
            config_manager.add_model(model_config)

            # Set as default if it's the first model
            if len(config_manager.list_models()) == 1:
                config_manager.set_default_model(name)

            # Reset form on success
            self._on_reset_clicked()
            self._show_success(self.tr(f"✓ 模型 '{name}' 导入成功"))

            # Switch to new model if we have a context
            if self.context is not None:
                try:
                    success = await self.context.switch_model(name)
                    if success:
                        logger.info(f"自动切换到新模型: {name}")
                    else:
                        logger.warning(f"切换到新模型失败: {name}")
                except Exception as e:
                    logger.error(f"切换模型失败: {e}")

            # Emit signal for other UI components to refresh
            self.modelImported.emit(name)

        except Exception as exc:
            self._show_error(self.tr(f"⚠ 导入失败: {exc}"))
            logger.error(f"Model import failed: {exc}")

    def _show_error(self, message: str) -> None:
        """Display error message."""
        self.error_label.setText(message)
        self.error_label.setStyleSheet("color: #ff6b6b;")
        self.error_label.show()

    def _show_success(self, message: str) -> None:
        """Display success message."""
        self.error_label.setText(message)
        self.error_label.setStyleSheet("color: #51cf66;")
        self.error_label.show()

        # Auto-hide success message after 3 seconds
        async def _hide():
            await asyncio.sleep(3)
            self.error_label.hide()

        self._hide_task = asyncio.create_task(_hide())
