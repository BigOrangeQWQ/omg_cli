#!/usr/bin/env python3
"""OMG CLI - AI-powered terminal assistant."""

from pathlib import Path
import sys

from omg_cli.prompts import render_system_prompt

# Ensure the project root is on sys.path so that internal `from omg_cli...`
# imports resolve when launched via an installed console script.
_project_root = Path(__file__).resolve().parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

import argparse

from dotenv import load_dotenv

from omg_cli.abstract.none import NoneAdapter
from omg_cli.config import get_adapter_manager
from omg_cli.context import ChatContext
from omg_cli.log import logger
from omg_cli.shell import run_terminal


def main():
    """Main entry point (synchronous)."""
    parser = argparse.ArgumentParser(
        description="OMG CLI - AI-powered terminal assistant",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode",
    )
    parser.add_argument(
        "--model",
        type=str,
        help="Specify model name to use",
    )
    parser.add_argument(
        "-r",
        "--session-id",
        type=str,
        help="Restore a previous session by its session ID",
    )
    parser.add_argument(
        "--channel",
        action="store_true",
        help="Enable Channel mode for multi-role sub-agent collaboration",
    )
    args = parser.parse_args()

    # Enable logging only in debug mode
    if args.debug:
        logger.enable("omg_cli")
        logger.info("Starting OMG CLI in DEBUG mode")

    load_dotenv()  # Load environment variables from .env file

    # Get adapter manager
    adapter_manager = get_adapter_manager()

    # Get adapter for specified or default model
    adapter = None
    if args.model:
        try:
            adapter = adapter_manager.get_adapter(args.model)
        except ValueError:
            logger.error(f"错误: 未找到模型 '{args.model}'")
            logger.info(f"可用的模型: {adapter_manager.list_adapters()}")
            sys.exit(1)
    else:
        adapter = adapter_manager.default_adapter

    # If no model configured, use NoneAdapter (TUI will prompt for import)
    if adapter is None:
        logger.info("未配置任何模型，请先使用 /import 命令导入模型")
        adapter = NoneAdapter()

    # Create chat context
    context = ChatContext(
        provider=adapter,
        system_prompt=render_system_prompt(Path.cwd()),
    )

    # Restore previous session if session ID is provided
    if args.session_id:
        if not context.load_session(args.session_id):
            logger.error(f"错误: 未找到会话 '{args.session_id}'")
            sys.exit(1)
        logger.info(f"已恢复会话: {args.session_id}")

    # Run TUI (this will block until app exits)
    run_terminal(context, channel=args.channel)


if __name__ == "__main__":
    main()
