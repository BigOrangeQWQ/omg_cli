#!/usr/bin/env python3
"""OMG CLI - AI-powered terminal assistant."""

import argparse
import sys

from dotenv import load_dotenv

from src.omg_cli.abstract.none import NoneAdapter
from src.omg_cli.config import get_adapter_manager
from src.omg_cli.context import ChatContext
from src.omg_cli.log import logger
from src.omg_cli.prompts.system_prompt import SYSTEM_PROMPT
from src.omg_cli.shell import run_terminal


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
    logger.info("Starting OMG CLI...")

    args = parser.parse_args()

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
        system_prompt=SYSTEM_PROMPT,
    )

    # Run TUI (this will block until app exits)
    run_terminal(context, debug_mode=args.debug)


if __name__ == "__main__":
    main()
