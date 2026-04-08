from src.omg_cli.context import ChatContext
from src.omg_cli.types.skill import normalize_skill_id


async def switch_model(ctx: ChatContext, args: str) -> None:
    """Switch to another model. Usage: /switch <model_name>"""
    if not args.strip():
        await ctx.logger.error("用法: /switch <模型名称>")
        return

    from src.omg_cli.config import get_config_manager

    config_manager = get_config_manager()
    model_name = args.strip()

    # Set as default model in config
    if config_manager.set_default_model(model_name):
        # Switch model in current context
        await ctx.switch_model(model_name)
    else:
        await ctx.logger.error(f"未找到模型: {model_name}")


async def list_models(ctx: ChatContext, args: str) -> None:
    """List available models."""
    from src.omg_cli.config import get_config_manager

    config = get_config_manager()
    models = config.list_models()

    if not models:
        await ctx.logger.info("No models configured. Use /import to add models.")
        return

    current_model = config.get_default_model()
    current_name = current_model.name if current_model else None

    lines = ["Available models:"]
    for model in models:
        current = " (current)" if model.name == current_name else ""
        lines.append(f"  • {model.name} ({model.provider}){current}")

    await ctx.logger.info("\n".join(lines))


async def clear_session(ctx: ChatContext, args: str) -> None:
    """Clear all messages in the current session."""
    await ctx.reset()


async def show_help(ctx: ChatContext, args: str) -> None:
    """Show help for commands or general usage."""
    commands = ctx.list_commands()

    if args.strip():
        # Show help for specific command
        cmd_name = args.strip().lstrip("/")
        for cmd in commands:
            if cmd.name == cmd_name:
                await ctx.logger.info(f"/{cmd.name}: {cmd.description_zh}")
                return
        await ctx.logger.info(f"未知命令: /{cmd_name}")
    else:
        # Show all commands
        lines = ["可用命令:"]
        for cmd in commands:
            lines.append(f"  /{cmd.name:<15} {cmd.description_zh}")
        await ctx.logger.info("\n".join(lines))


async def quit_app(ctx: ChatContext, args: str) -> None:
    """Exit the application."""
    from src.omg_cli.types.event import AppExitEvent

    await ctx._emit(AppExitEvent())


async def list_tools(ctx: ChatContext, args: str) -> None:
    """List all available tools."""
    tools = ctx.list_tools()
    if not tools:
        await ctx.logger.info("No tools available.")
        return

    lines = ["Available tools:"]
    for tool in tools:
        lines.append(f"  • {tool.name}")
    await ctx.logger.info("\n".join(lines))


async def list_mcp_servers(ctx: ChatContext, args: str) -> None:
    """List configured MCP servers and their connection status."""
    servers = ctx.list_mcp_servers()
    if not servers:
        await ctx.logger.info("No MCP servers configured.")
        return

    lines = ["MCP servers:"]
    for s in servers:
        status = "connected" if s["connected"] else "disconnected"
        lines.append(f"  • {s['name']} ({s['transport']}) — {status}, {s['tool_count']} tools")
    await ctx.logger.info("\n".join(lines))


async def connect_mcp_server(ctx: ChatContext, args: str) -> None:
    """Connect to a configured MCP server. Usage: /mcp connect <name>"""
    name = args.strip()
    if not name:
        await ctx.logger.error("Usage: /mcp connect <name>")
        return

    from src.omg_cli.config import get_config_manager

    config_manager = get_config_manager()
    config = config_manager.get_mcp_server(name)
    if config is None:
        await ctx.logger.error(f"MCP server not found: {name}")
        return

    tools = await ctx.connect_mcp_server(config)
    if tools is None:
        await ctx.logger.error(f"Failed to connect MCP server: {name}")
    else:
        await ctx.logger.success(f"Connected to MCP server '{name}' with {len(tools)} tools")


async def disconnect_mcp_server(ctx: ChatContext, args: str) -> None:
    """Disconnect from an MCP server. Usage: /mcp disconnect <name>"""
    name = args.strip()
    if not name:
        await ctx.logger.error("Usage: /mcp disconnect <name>")
        return

    tool_names = await ctx.disconnect_mcp_server(name)
    if tool_names is None:
        await ctx.logger.error(f"MCP server not connected: {name}")
    else:
        await ctx.logger.success(f"Disconnected from MCP server '{name}' ({len(tool_names)} tools removed)")


async def reload_mcp_servers(ctx: ChatContext, args: str) -> None:
    """Reload all MCP server configurations and reconnect."""
    from src.omg_cli.config import get_config_manager

    config_manager = get_config_manager()
    configs = config_manager.list_mcp_servers()

    await ctx.disconnect_all_mcp_servers()
    tools = await ctx.initialize_mcp_servers(configs)
    await ctx.logger.success(f"Reloaded MCP servers: {len(tools)} tools from {len(configs)} server(s)")


async def set_mcp_mode(ctx: ChatContext, enabled: bool) -> None:
    """Enable or disable MCP mode."""
    ctx.mcp_mode = enabled
    status = "enabled" if enabled else "disabled"
    await ctx.logger.success(f"MCP mode {status}")


async def show_mcp_status(ctx: ChatContext) -> None:
    """Show MCP mode status and connected servers."""
    mode_status = "on" if ctx.mcp_mode else "off"
    lines = [f"MCP mode: {mode_status}"]

    servers = ctx.list_mcp_servers()
    if servers:
        lines.append("Connected servers:")
        for s in servers:
            status = "connected" if s["connected"] else "disconnected"
            lines.append(f"  • {s['name']} — {status}, {s['tool_count']} tools")
    else:
        lines.append("No MCP servers configured.")

    await ctx.logger.info("\n".join(lines))


def model_completer(ctx: ChatContext, prefix: str) -> list[str]:
    """Complete model names for /switch command."""
    from src.omg_cli.config import get_config_manager

    config = get_config_manager()
    models = config.list_models()

    prefix_lower = prefix.lower()
    return [model.name for model in models if model.name.lower().startswith(prefix_lower)]


from src.omg_cli.types.command import MetaCommand


def mcp_completer(ctx: ChatContext, prefix: str) -> list[str]:
    """Complete MCP server names for /mcp connect/disconnect."""
    from src.omg_cli.config import get_config_manager

    config = get_config_manager()
    servers = config.list_mcp_servers()
    prefix_lower = prefix.lower()
    return [s.name for s in servers if s.name.lower().startswith(prefix_lower)]


def register_commands(ctx: ChatContext) -> None:
    """Register all commands with the context."""
    commands = [
        MetaCommand(
            name="switch",
            description="Switch to a different model",
            description_zh="切换到其他模型",
            handler=switch_model,
            completer=model_completer,
        ),
        MetaCommand(
            name="models",
            description="List available models",
            description_zh="列出可用模型",
            handler=list_models,
        ),
        MetaCommand(
            name="clear",
            description="Clear the session",
            description_zh="清空当前会话",
            handler=clear_session,
        ),
        MetaCommand(
            name="help",
            description="Show help information",
            description_zh="显示帮助信息",
            handler=show_help,
        ),
        MetaCommand(
            name="quit",
            description="Exit the application",
            description_zh="退出应用",
            handler=quit_app,
        ),
        MetaCommand(
            name="tools",
            description="List available tools",
            description_zh="列出可用工具",
            handler=list_tools,
        ),
        MetaCommand(
            name="mcp",
            description="MCP server management",
            description_zh="MCP 服务器管理",
            handler=mcp_handler,
        ),
        MetaCommand(
            name="skills",
            description="Anthropic skills management",
            description_zh="Anthropic Skills 管理",
            handler=skills_handler,
        ),
    ]

    for cmd in commands:
        ctx.register_command(cmd)


async def list_skills(ctx: ChatContext, args: str) -> None:
    """List enabled Anthropic skills for the current session."""
    if not ctx.skills:
        await ctx.logger.info("No skills enabled for this session.")
        return

    lines = ["Enabled skills:"]
    for skill in ctx.skills:
        version_str = f" (v{skill.version})" if skill.version else ""
        lines.append(f"  • {skill.skill_id}{version_str} [{skill.type}]")
    await ctx.logger.info("\n".join(lines))


async def add_skill(ctx: ChatContext, args: str) -> None:
    """Add a skill to the current session. Usage: /skills add <skill_id>"""
    skill_id = args.strip()
    if not skill_id:
        await ctx.logger.error("Usage: /skills add <skill_id>")
        return

    skill_ref = normalize_skill_id(skill_id)
    if any(s.skill_id == skill_ref.skill_id for s in ctx.skills):
        await ctx.logger.warn(f"Skill '{skill_ref.skill_id}' is already enabled")
        return

    ctx.skills.append(skill_ref)
    await ctx.logger.success(f"Added skill: {skill_ref.skill_id}")


async def remove_skill(ctx: ChatContext, args: str) -> None:
    """Remove a skill from the current session. Usage: /skills remove <skill_id>"""
    skill_id = args.strip()
    if not skill_id:
        await ctx.logger.error("Usage: /skills remove <skill_id>")
        return

    original_len = len(ctx.skills)
    ctx.skills = [s for s in ctx.skills if s.skill_id != skill_id]
    if len(ctx.skills) < original_len:
        await ctx.logger.success(f"Removed skill: {skill_id}")
    else:
        await ctx.logger.error(f"Skill not found: {skill_id}")


async def clear_skills(ctx: ChatContext, args: str) -> None:
    """Clear all skills from the current session."""
    ctx.skills.clear()
    await ctx.logger.success("Cleared all skills")


async def skills_handler(ctx: ChatContext, args: str) -> None:
    """Route skills sub-commands."""
    parts = args.strip().split(maxsplit=1)
    if not parts:
        await list_skills(ctx, "")
        return

    subcmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    match subcmd:
        case "list":
            await list_skills(ctx, rest)
        case "add":
            await add_skill(ctx, rest)
        case "remove":
            await remove_skill(ctx, rest)
        case "clear":
            await clear_skills(ctx, rest)
        case _:
            await ctx.logger.error(
                f"Unknown skills sub-command: {subcmd}. Available: list, add, remove, clear"
            )


async def mcp_handler(ctx: ChatContext, args: str) -> None:
    """Route MCP sub-commands."""
    parts = args.strip().split(maxsplit=1)
    if not parts:
        await list_mcp_servers(ctx, "")
        return

    subcmd = parts[0].lower()
    rest = parts[1] if len(parts) > 1 else ""

    match subcmd:
        case "list":
            await list_mcp_servers(ctx, rest)
        case "connect":
            await connect_mcp_server(ctx, rest)
        case "disconnect":
            await disconnect_mcp_server(ctx, rest)
        case "reload":
            await reload_mcp_servers(ctx, rest)
        case "on":
            await set_mcp_mode(ctx, True)
        case "off":
            await set_mcp_mode(ctx, False)
        case "status":
            await show_mcp_status(ctx)
        case _:
            await ctx.logger.error(
                f"Unknown MCP sub-command: {subcmd}. Available: list, connect, disconnect, reload, on, off, status"
            )
