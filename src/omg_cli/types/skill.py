from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel

type SkillType = Literal["anthropic", "custom"]


class SkillRef(BaseModel):
    """Reference to an Anthropic Skill for use in inference requests."""

    type: SkillType = "custom"
    skill_id: str
    version: str | None = None

    def model_dump(self, **kwargs: Any) -> dict[str, Any]:
        data = super().model_dump(**kwargs)
        if self.version is None:
            data.pop("version", None)
        return data


class SkillManifest(BaseModel):
    """Parsed metadata from a local SKILL.md frontmatter."""

    name: str
    description: str
    source: Literal["local", "anthropic"] = "local"
    path: Path | None = None


BUILTIN_SKILLS: frozenset[str] = frozenset({"xlsx", "pptx", "docx", "pdf"})


def normalize_skill_id(skill_id: str) -> SkillRef:
    """Normalize a raw skill ID string into a SkillRef.

    Built-in Anthropic skills (xlsx, pptx, docx, pdf) are automatically
    typed as 'anthropic'. Everything else defaults to 'custom'.
    """
    skill_id_lower = skill_id.lower().strip()
    if skill_id_lower in BUILTIN_SKILLS:
        return SkillRef(type="anthropic", skill_id=skill_id_lower)
    return SkillRef(type="custom", skill_id=skill_id)


def parse_skill_manifest(skill_path: Path) -> SkillManifest | None:
    """Parse YAML frontmatter from a SKILL.md file.

    Args:
        skill_path: Path to the SKILL.md file (or its parent directory).

    Returns:
        SkillManifest if valid frontmatter is found, otherwise None.
    """
    import yaml

    md_path = skill_path if skill_path.is_file() else skill_path / "SKILL.md"
    if not md_path.exists():
        return None

    try:
        content = md_path.read_text("utf-8")
    except Exception:
        return None

    if not content.startswith("---"):
        return None

    # Split frontmatter from body: ---\n<yaml>\n---\n<body>
    parts = content.split("---", 2)
    if len(parts) < 3:
        return None

    try:
        data = yaml.safe_load(parts[1].strip())
    except Exception:
        return None

    if not isinstance(data, dict):
        return None

    name = data.get("name")
    description = data.get("description")
    if not name or not description:
        return None

    return SkillManifest(
        name=str(name).strip(),
        description=str(description).strip(),
        path=md_path.parent if md_path.name == "SKILL.md" else md_path,
    )
