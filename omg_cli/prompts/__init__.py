from pathlib import Path

from omg_cli.prompts.system_prompt import SYSTEM_PROMPT as SYSTEM_PROMPT

PROMPTS_DIR = Path(__file__).parent

COMPACT_MD = (PROMPTS_DIR / "compact.md").read_text("utf-8")
