import os

from loguru import logger

# Remove default stderr handler to only log to file
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
