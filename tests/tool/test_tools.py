"""Tests for built-in tools."""

import asyncio

import pytest

from omg_cli.tool.tools import Glob, Grep, ListFiles
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

        expected_paths = sorted(
            [
                str(file_tree / "alpha.py"),
                str(file_tree / "beta.py"),
            ]
        )
        assert result == "\n".join(expected_paths)

    @pytest.mark.asyncio
    async def test_recursive_glob(self, file_tree):
        """Recursive glob should match files in all subdirectories."""
        result = await Glob(pattern="**/*.py", path=str(file_tree), recursive=True)

        expected_paths = sorted(
            [
                str(file_tree / "alpha.py"),
                str(file_tree / "beta.py"),
                str(file_tree / "sub" / "delta.py"),
                str(file_tree / "sub" / "epsilon.py"),
                str(file_tree / "sub" / "nested" / "zeta.py"),
            ]
        )
        assert result == "\n".join(expected_paths)

    @pytest.mark.asyncio
    async def test_limit_truncation(self, file_tree):
        """Limit should truncate results and indicate remaining matches."""
        result = await Glob(pattern="**/*.py", path=str(file_tree), recursive=True, limit=2)

        expected_paths = sorted(
            [
                str(file_tree / "alpha.py"),
                str(file_tree / "beta.py"),
                str(file_tree / "sub" / "delta.py"),
                str(file_tree / "sub" / "epsilon.py"),
                str(file_tree / "sub" / "nested" / "zeta.py"),
            ]
        )
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


class TestGrep:
    """Tests for Grep tool."""

    @pytest.fixture
    def grep_tree(self, tmp_path):
        """Create files for grep fallback tests."""
        (tmp_path / "a.py").write_text("hello world\nneedle here\n", encoding="utf-8")
        (tmp_path / "b.txt").write_text("needle in txt\n", encoding="utf-8")
        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()
        (sub_dir / "c.py").write_text("another needle\n", encoding="utf-8")
        return tmp_path

    @pytest.mark.asyncio
    async def test_fallback_when_rg_not_found(self, grep_tree, monkeypatch):
        """Should fallback to python implementation when rg binary is missing."""

        async def _raise_not_found(*args, **kwargs):
            raise FileNotFoundError("rg not found")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_not_found)

        result = await Grep(pattern="needle", path=str(grep_tree), include="*.py")

        assert str(grep_tree / "a.py") in result
        assert str(grep_tree / "sub" / "c.py") in result
        assert str(grep_tree / "b.txt") not in result

    @pytest.mark.asyncio
    async def test_fallback_respects_exclude(self, grep_tree, monkeypatch):
        """Fallback grep should honor exclude glob patterns."""

        async def _raise_not_found(*args, **kwargs):
            raise FileNotFoundError("rg not found")

        monkeypatch.setattr(asyncio, "create_subprocess_exec", _raise_not_found)

        result = await Grep(pattern="needle", path=str(grep_tree), exclude="sub/*.py")

        assert str(grep_tree / "a.py") in result
        assert str(grep_tree / "sub" / "c.py") not in result


class TestListFiles:
    """Tests for ListFiles tool."""

    @pytest.fixture
    def list_tree(self, tmp_path):
        """Create a temporary file tree for list tests."""
        # Files in root
        (tmp_path / "alpha.py").write_text("x" * 100)
        (tmp_path / "beta.py").write_text("y" * 200)
        (tmp_path / "gamma.txt").write_text("z" * 300)

        # Subdirectories
        sub_dir = tmp_path / "sub"
        sub_dir.mkdir()
        (sub_dir / "delta.py").write_text("d" * 50)
        (sub_dir / "epsilon.py").write_text("e" * 150)

        # Nested subdirectory
        nested_dir = sub_dir / "nested"
        nested_dir.mkdir()
        (nested_dir / "zeta.py").write_text("z" * 10)
        (nested_dir / "eta.txt").write_text("h" * 2048)

        return tmp_path

    @pytest.mark.asyncio
    async def test_list_root_non_recursive(self, list_tree):
        """Non-recursive listing should show root files and dirs."""
        result = await ListFiles(path=str(list_tree), recursive=False)

        # Should contain files and sub directory
        assert "📄" in result
        assert "📁" in result
        assert "alpha.py" in result
        assert "beta.py" in result
        assert "gamma.txt" in result
        assert "sub" in result
        # Should NOT contain nested files
        assert "delta.py" not in result
        assert "zeta.py" not in result

    @pytest.mark.asyncio
    async def test_list_root_recursive(self, list_tree):
        """Recursive listing should show all files and dirs."""
        result = await ListFiles(path=str(list_tree), recursive=True)

        assert "alpha.py" in result
        assert "sub/delta.py" in result
        assert "sub/nested/zeta.py" in result
        assert "sub/nested/eta.txt" in result

    @pytest.mark.asyncio
    async def test_list_with_pattern(self, list_tree):
        """Pattern should filter by file name."""
        result = await ListFiles(path=str(list_tree), pattern="*.py", recursive=False)

        assert "alpha.py" in result
        assert "beta.py" in result
        assert "gamma.txt" not in result
        assert "sub" not in result

    @pytest.mark.asyncio
    async def test_list_non_recursive_directories_first(self, list_tree):
        """Non-recursive output should list directories before files."""
        result = await ListFiles(path=str(list_tree), recursive=False)
        lines = [line for line in result.split("\n") if line and not line.startswith("...")]

        # Find indices of first file and first dir entry
        dir_indices = [i for i, line in enumerate(lines) if line.startswith("📁")]
        file_indices = [i for i, line in enumerate(lines) if line.startswith("📄")]

        if dir_indices and file_indices:
            assert all(d < f for d in dir_indices for f in file_indices), (
                "Directories should come before files"
            )

    @pytest.mark.asyncio
    async def test_limit_truncation(self, list_tree):
        """Limit should truncate results."""
        result = await ListFiles(path=str(list_tree), recursive=False, limit=2)
        lines = [line for line in result.split("\n") if line]
        assert lines[-1].startswith("... and")
        assert len(lines) == 3  # 2 entries + ... and more

    @pytest.mark.asyncio
    async def test_no_matches(self, list_tree):
        """No matches with pattern should return a specific message."""
        result = await ListFiles(path=str(list_tree), pattern="*.nonexistent", recursive=False)
        assert result == "No files found."

    @pytest.mark.asyncio
    async def test_not_found_raises_tool_error(self):
        """Non-existent path should raise ToolError."""
        with pytest.raises(ToolError, match="Not found"):
            await ListFiles(path="Z:\\nonexistent\\path\\for\\test")

    @pytest.mark.asyncio
    async def test_file_path_raises_tool_error(self, list_tree):
        """A file path (not directory) should raise ToolError."""
        with pytest.raises(ToolError, match="Not a directory"):
            await ListFiles(path=str(list_tree / "alpha.py"))

    @pytest.mark.asyncio
    async def test_relative_path_raises_tool_error(self):
        """A relative path should raise ToolError."""
        with pytest.raises(ToolError):
            await ListFiles(path="relative/path")

    @pytest.mark.asyncio
    async def test_size_formatting(self, list_tree):
        """File sizes should be human-readable."""
        # gamma.txt has 300 bytes -> should show 300B
        result = await ListFiles(path=str(list_tree), recursive=True)
        # The 2K file should show with size
        assert "sub/nested/eta.txt" in result
        # alpha.py has 100B
        assert any("100B" in line and "alpha.py" in line for line in result.split("\n"))

    @pytest.mark.asyncio
    async def test_default_path_is_cwd(self):
        """Default path should be current working directory."""
        result = await ListFiles(recursive=False)
        assert isinstance(result, str)
        assert len(result) > 0
