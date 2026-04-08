"""Meta command definitions and registration."""

from src.omg_cli.config import get_config_manager
from src.omg_cli.shell.widgets import MessageHistoryView
from src.omg_cli.types.command import MetaCommand


class CommandRegistrar:
    """Helper class to register default meta commands."""

    def __init__(self, app):
        self.app = app
        self.context = app.context

    def register_all(self) -> None:
        """Register all default meta commands."""
        self._register_new()
        self._register_clear()
        self._register_help()
        self._register_import()
        self._register_models()
        self._register_switch()
        self._register_compact()

    def _register_new(self) -> None:
        """Register /new command."""

        async def cmd_new(ctx, args: str) -> None:
            await ctx.reset()
            await self.app._mount_status("已开启新会话")

        self.context.register_command(
            MetaCommand(
                name="new",
                description="Start a new session",
                description_zh="重置会话，清空所有消息",
                handler=cmd_new,
            )
        )

    def _register_clear(self) -> None:
        """Register /clear command."""

        async def cmd_clear(ctx, args: str) -> None:
            messages_view = self.app.query_one("#messages", MessageHistoryView)
            await messages_view.remove_children()
            self.app._stream_previews.clear()
            await self.app._mount_status("屏幕已清空")

        self.context.register_command(
            MetaCommand(
                name="clear",
                description="Clear the screen",
                description_zh="清屏，保留当前会话",
                handler=cmd_clear,
            )
        )

    def _register_help(self) -> None:
        """Register /help command."""

        async def cmd_help(ctx, args: str) -> None:
            help_text = "可用命令:\n"
            for cmd in ctx.command_registry.get_all():
                help_text += f"  {cmd.full_name} - {cmd.description_zh}\n"
            await self.app._mount_status(help_text)

        self.context.register_command(
            MetaCommand(
                name="help",
                description="Show available commands",
                description_zh="显示所有可用命令",
                handler=cmd_help,
            )
        )

    def _register_import(self) -> None:
        """Register /import command."""

        async def cmd_import(ctx, args: str) -> None:
            # Trigger the import wizard
            await self.app.start_import_wizard()

        self.context.register_command(
            MetaCommand(
                name="import",
                description="Import a new model",
                description_zh="导入新模型",
                handler=cmd_import,
            )
        )

    def _register_models(self) -> None:
        """Register /models command to list configured models."""

        async def cmd_models(ctx, args: str) -> None:
            config_manager = get_config_manager()
            models = config_manager.list_models()

            if not models:
                await self.app._mount_status("未配置任何模型，使用 /import 导入模型")
                return

            default_model = config_manager.load_user_config().default_model

            text = "已配置的模型:\n"
            for m in models:
                marker = " (默认)" if m.name == default_model else ""
                # api_key is SecretStr, display as hidden
                text += f"  • {m.name}{marker}\n"
                text += f"    提供商: {m.provider}\n"
                text += f"    模型: {m.model}\n"
                text += f"    Base URL: {m.base_url}\n"

            await self.app._mount_status(text)

        self.context.register_command(
            MetaCommand(
                name="models",
                description="List configured models",
                description_zh="列出已配置的模型",
                handler=cmd_models,
            )
        )

    def _register_switch(self) -> None:
        """Register /switch command to switch default model."""

        async def cmd_switch(ctx, args: str) -> None:
            if not args.strip():
                await self.app._mount_status("用法: /switch <模型名称>", variant="error")
                return

            config_manager = get_config_manager()
            model_name = args.strip()

            if config_manager.set_default_model(model_name):
                await self.app._mount_status(f"已切换到模型: {model_name}")
                # Reload the model in current context
                await self.app.reload_model()
            else:
                await self.app._mount_status(f"未找到模型: {model_name}", variant="error")

        self.context.register_command(
            MetaCommand(
                name="switch",
                description="Switch to a different model",
                description_zh="切换到其他模型",
                handler=cmd_switch,
            )
        )

    def _register_compact(self) -> None:
        """Register /compact command to compact conversation context."""

        async def cmd_compact(ctx, args: str) -> None:
            # Parse optional keep_recent argument
            keep_recent = 4  # Default value
            if args.strip():
                try:
                    keep_recent = int(args.strip())
                    if keep_recent < 1:
                        await self.app._mount_status("参数错误: keep_recent 必须大于 0", variant="error")
                        return
                except ValueError:
                    await self.app._mount_status("用法: /compact [保留消息数]", variant="error")
                    return

            await self.app._mount_status(f"正在压缩上下文，保留最近 {keep_recent} 条消息...")

            try:
                result = await ctx._compact_context_impl(keep_recent=keep_recent)
                if result is None:
                    await self.app._mount_status("消息数量不足，无需压缩")
                else:
                    await self.app._mount_status("上下文压缩完成")
            except Exception as e:
                await self.app._mount_status(f"压缩失败: {e}", variant="error")

        self.context.register_command(
            MetaCommand(
                name="compact",
                description="Compact conversation context by summarizing older messages",
                description_zh="压缩上下文，总结较早的消息",
                handler=cmd_compact,
            )
        )
