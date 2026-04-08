#!/usr/bin/env python3
"""OMG CLI - AI-powered terminal assistant."""

import argparse
import sys

from src.omg_cli.abstract.openai_legacy import OpenAILegacy
from src.omg_cli.config import get_config_manager
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

    # Load configuration
    config_manager = get_config_manager()

    # Check if any models are configured
    if not config_manager.has_models():
        logger.info("未配置任何模型，请先使用 /import 命令导入模型")
        logger.info("启动 TUI 后，输入 /import 开始导入")
        # Continue to TUI which will show import wizard automatically

    # Get default or specified model
    model_config = None
    if args.model:
        model_config = config_manager.get_model(args.model)
        if model_config is None:
            logger.error(f"错误: 未找到模型 '{args.model}'")
            logger.info(f"可用的模型: {[m.name for m in config_manager.list_models()]}")
            sys.exit(1)
    else:
        model_config = config_manager.get_default_model()

    # If no model configured, create a placeholder context
    # The TUI will prompt for import
    if model_config is None:
        # Create a dummy adapter that will be replaced after import
        adapter = OpenAILegacy(
            api_key="placeholder",
            model="placeholder",
            base_url="https://api.openai.com/v1",
        )
    else:
        adapter = model_config.create_adapter()

    # Create chat context
    context = ChatContext(
        provider=adapter,
        system_prompt=SYSTEM_PROMPT,
    )

    # Run TUI (this will block until app exits)
    run_terminal(context, debug_mode=args.debug)


if __name__ == "__main__":
    main()
