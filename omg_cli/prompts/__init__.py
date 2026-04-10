from pathlib import Path

PROMPTS_DIR = Path(__file__).parent

COMPACT_MD = (PROMPTS_DIR / "compact.md").read_text("utf-8")

SYSTEM_PROMPT = (PROMPTS_DIR / "system.md").read_text("utf-8")

ROLE_PROMPT = (PROMPTS_DIR / "role.md").read_text("utf-8")


def render_system_prompt(workdir: Path) -> str:
    return SYSTEM_PROMPT.format(
        WORKDIR=str(workdir),
        AGENTS_PATH=str(workdir / "AGENTS.md"),
        NOTES_PATH=str(workdir / "NOTES.md"),
    )


def render_role_prompt(
    role_name: str,
    role_description: str,
    personal_space_path: Path,
    workdir: Path,
) -> str:
    return ROLE_PROMPT.format(
        ROLE_NAME=role_name,
        ROLE_DESCRIPTION=role_description,
        ROLE_PERSONAL_SPACE_PATH=str(personal_space_path),
        AGENTS_PATH=str(workdir / "AGENTS.md"),
        NOTES_PATH=str(workdir / "NOTES.md"),
    )
