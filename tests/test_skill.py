"""Tests for skill manifest parsing."""

from pathlib import Path

from omg_cli.types.skill import parse_skill_manifest


class TestParseSkillManifest:
    def test_parse_from_directory(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "test-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: test-skill\ndescription: A test skill for validation\n---\n\n# Test Skill\n",
            encoding="utf-8",
        )

        manifest = parse_skill_manifest(skill_dir)

        assert manifest is not None
        assert manifest.name == "test-skill"
        assert manifest.description == "A test skill for validation"
        assert manifest.source == "local"
        assert manifest.path == skill_dir

    def test_parse_from_file_path(self, tmp_path: Path) -> None:
        skill_file = tmp_path / "SKILL.md"
        skill_file.write_text(
            "---\nname: direct-file\ndescription: Parsed from direct file path\n---\n",
            encoding="utf-8",
        )

        manifest = parse_skill_manifest(skill_file)

        assert manifest is not None
        assert manifest.name == "direct-file"
        assert manifest.description == "Parsed from direct file path"
        assert manifest.path == tmp_path

    def test_missing_name_returns_none(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\ndescription: Missing name field\n---\n",
            encoding="utf-8",
        )

        assert parse_skill_manifest(skill_dir) is None

    def test_missing_description_returns_none(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "bad-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: missing-desc\n---\n",
            encoding="utf-8",
        )

        assert parse_skill_manifest(skill_dir) is None

    def test_no_frontmatter_returns_none(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "plain-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "# Plain Markdown\n\nNo YAML frontmatter here.\n",
            encoding="utf-8",
        )

        assert parse_skill_manifest(skill_dir) is None

    def test_incomplete_frontmatter_returns_none(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "incomplete-skill"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            "---\nname: incomplete\n",
            encoding="utf-8",
        )

        assert parse_skill_manifest(skill_dir) is None

    def test_non_dict_frontmatter_returns_none(self, tmp_path: Path) -> None:
        skill_dir = tmp_path / "str-frontmatter"
        skill_dir.mkdir()
        (skill_dir / "SKILL.md").write_text(
            '---\n"just a string"\n---\n',
            encoding="utf-8",
        )

        assert parse_skill_manifest(skill_dir) is None

    def test_missing_file_returns_none(self, tmp_path: Path) -> None:
        non_existent = tmp_path / "does-not-exist"

        assert parse_skill_manifest(non_existent) is None
