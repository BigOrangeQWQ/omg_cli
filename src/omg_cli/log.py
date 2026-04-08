import os

from loguru import logger

# Remove default stderr handler
logger.remove()

level = os.getenv("LOG_LEVEL", "INFO").upper()
logger.add(
    "omg-cli.log",
    rotation="10 MB",
    retention="10 days",
    compression="zip",
    backtrace=True,
    diagnose=True,
    enqueue=True,
    level=level,
)

# Disable by default, enable with --debug
logger.disable("src.omg_cli")
