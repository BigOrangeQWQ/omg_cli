"""Tests for built-in tools."""

import pytest

from omg_cli.tool.tools import Glob
from omg_cli.types.tool import ToolError


class TestGlob:
    """Tests for Glob tool."""

    @pytest.fixture
    def file_tree(self, tmp_path):
        """Create a temporary file tree for glob tests."""
        # Files in root
        (tmp_path / "alpha.py").write_text("alpha")
        (tmp_path / "beta.py").write_text("beta")
        (tmp_path / "gamma.txt").write_text("gamma")

        # Files in subdirectory
        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()
        (sub_dir / "delta.py").write_text("delta")
        (sub_dir / "epsilon.py").write_text("epsilon")

        # Nested subdirectory
        nested_dir = sub_dir / "nested"
        nested_dir.mkdir()
        (nested_dir / "zeta.py").write_text("zeta")
        (nested_dir / "eta.txt").write_text("eta")

        return tmp_path

    @pytest.mark.asyncio
    async def test_non_recursive_glob(self, file_tree):
        """Non-recursive glob should only match files in the root directory."""
        result = await Glob(pattern="*.py", path=str(file_tree), recursive=False)

        expected_paths = sorted([
            str(file_tree / "alpha.py"),
            str(file_tree / "beta.py"),
        ])
        assert result == "\n".join(expected_paths)

    @pytest.mark.asyncio
    async def test_recursive_glob(self, file_tree):
        """Recursive glob should match files in all subdirectories."""
        result = await Glob(pattern="**/*.py", path=str(file_tree), recursive=True)

        expected_paths = sorted([
            str(file_tree / "alpha.py"),
            str(file_tree / "beta.py"),
            str(file_tree / "sub" / "delta.py"),
            str(file_tree / "sub" / "epsilon.py"),
            str(file_tree / "sub" / "nested" / "zeta.py"),
        ])
        assert result == "\n".join(expected_paths)

    @pytest.mark.asyncio
    async def test_limit_truncation(self, file_tree):
        """Limit should truncate results and indicate remaining matches."""
        result = await Glob(pattern="**/*.py", path=str(file_tree), recursive=True, limit=2)

        expected_paths = sorted([
            str(file_tree / "alpha.py"),
            str(file_tree / "beta.py"),
            str(file_tree / "sub" / "delta.py"),
            str(file_tree / "sub" / "epsilon.py"),
            str(file_tree / "sub" / "nested" / "zeta.py"),
        ])
        assert result == "\n".join(expected_paths[:2]) + "\n... and 3 more"

    @pytest.mark.asyncio
    async def test_no_matches(self, file_tree):
        """No matches should return a specific message."""
        result = await Glob(pattern="*.nonexistent", path=str(file_tree), recursive=False)
        assert result == "No matches found."

    @pytest.mark.asyncio
    async def test_relative_path_raises_tool_error(self):
        """A relative path should raise ToolError."""
        with pytest.raises(ToolError):
            await Glob(pattern="*.py", path="relative/path", recursive=False)
