# This file is part of the Kimi CLI project
# https://github.com/MoonshotAI/kimi-cli

import asyncio
import fnmatch
import re
from typing import Annotated

import aiofiles
from anyio import Path
from pydantic import Field

from omg_cli.types.tool import ToolError

from . import register_tool


async def _python_grep_fallback(
    *,
    pattern: str,
    search_path: Path,
    include: str | None,
    exclude: str | None,
) -> str:
    """Fallback grep implementation when ripgrep is unavailable."""
    try:
        compiled_pattern = re.compile(pattern)
    except re.error as exc:
        raise ToolError(f"Grep failed: invalid regex pattern: {exc}") from exc

    matches: list[str] = []
    root = str(search_path)

    async for file_path in search_path.rglob("*"):
        if not await file_path.is_file():
            continue

        rel_path = str(file_path)[len(root) :].lstrip("\\/").replace("\\", "/")
        if include and not fnmatch.fnmatch(rel_path, include):
            continue
        if exclude and fnmatch.fnmatch(rel_path, exclude):
            continue

        try:
            async with aiofiles.open(file_path, encoding="utf-8", errors="replace") as f:
                content = await f.read()
        except Exception:
            continue

        for line_number, line in enumerate(content.splitlines(), start=1):
            if compiled_pattern.search(line):
                matches.append(f"{file_path}:{line_number}:{line}")

    return "\n".join(matches) if matches else "No matches found."


@register_tool(confirm=True, tags=["system", "file"])
async def Shell(
    command: Annotated[str, Field(description="The shell command to execute.")],
    timeout: Annotated[  # noqa: ASYNC109
        int,
        Field(default=60, description="Timeout in seconds."),
    ] = 60,
) -> str:
    """Execute a shell command and return the output."""
    proc = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        raise ToolError(f"Timeout after {timeout}s")

    output = stdout.decode("utf-8", errors="replace")
    error_output = stderr.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        raise ToolError(f"Exit {proc.returncode}: {error_output or output}")

    return output + (f"\n[stderr]: {error_output}" if error_output else "")


@register_tool(tags=["system", "file"])
async def ReadFile(
    path: Annotated[str, Field(description="The absolute path to the file to read.")],
    start_line: Annotated[
        int | None,
        Field(default=None, description="Start reading from this line (1-indexed)."),
    ] = None,
    limit: Annotated[
        int,
        Field(default=100, description="Maximum number of lines to read."),
    ] = 100,
) -> str:
    """Read the contents of a file.

    IMPORTANT: Read files in chunks of ≤100 lines unless necessary.
    For longer files, use multiple reads.
    """
    file_path = Path(path)
    if not await file_path.exists():
        raise ToolError(f"Not found: {path}")
    if not await file_path.is_file():
        raise ToolError(f"Not a file: {path}")

    if not file_path.is_absolute():
        raise ToolError(f"`{path}` is not an absolute path. You must provide an absolute path to read a file.")

    try:
        async with aiofiles.open(file_path, encoding="utf-8") as f:
            content = await f.read()
    except Exception as e:
        raise ToolError(f"Read failed: {e}")

    lines = content.splitlines()

    if start_line is not None:
        start = max(0, start_line - 1)
        lines = lines[start:]
    if limit is not None:
        lines = lines[:limit]

    return "\n".join(lines)


@register_tool(confirm=True, tags=["system", "file"])
async def WriteFile(
    path: Annotated[str, Field(description="The absolute path to the file to write.")],
    content: Annotated[str, Field(description="The content to write to the file.")],
    append: Annotated[
        bool,
        Field(default=False, description="If True, append to the file instead of overwriting."),
    ] = False,
) -> str:
    """
    Write content to a file. Creates parent directories if needed.

    When the content to write is too long (e.g. > 100 lines),
    use this tool multiple times instead of a single call.
    """
    file_path = Path(path)
    if not await file_path.exists():
        raise ToolError(f"Not found: {path}")
    if not await file_path.is_file():
        raise ToolError(f"Not a file: {path}")

    if not file_path.is_absolute():
        raise ToolError(f"`{path}` is not an absolute path. You must provide an absolute path to read a file.")

    try:
        await file_path.parent.mkdir(parents=True, exist_ok=True)
        mode = "a" if append else "w"
        async with aiofiles.open(file_path, mode, encoding="utf-8") as f:
            await f.write(content)
    except Exception as e:
        raise ToolError(f"Write failed: {e}")

    return f"{'Appended' if append else 'Wrote'} {len(content.encode('utf-8'))} bytes to {path}"


@register_tool(confirm=True, tags=["system", "file"])
async def StrReplace(
    path: Annotated[str, Field(description="The absol       ute path to the file to modify.")],
    old_str: Annotated[str, Field(description="The string to replace. Must match exactly.")],
    new_str: Annotated[str, Field(description="The replacement string.")],
    count: Annotated[
        int | None,
        Field(default=None, description="Maximum number of replacements. None means replace all."),
    ] = None,
) -> str:
    """
    Replace specific strings within a specified file.

    Only use this tool on text files.
    Multi-line strings are supported.
    Can specify a single edit or a list of edits in one call.
    You should prefer this tool over WriteFile tool and Bash `sed` command.
    """
    file_path = Path(path)
    if not await file_path.exists():
        raise ToolError(f"Not found: {path}")
    if not await file_path.is_file():
        raise ToolError(f"Not a file: {path}")

    if not file_path.is_absolute():
        raise ToolError(f"`{path}` is not an absolute path. You must provide an absolute path to read a file.")

    try:
        async with aiofiles.open(file_path, encoding="utf-8") as f:
            content = await f.read()
    except Exception as e:
        raise ToolError(f"Read failed: {e}")

    if old_str not in content:
        raise ToolError("String not found. Use ReadFile to verify exact content.")

    replacements = content.count(old_str) if count is None else min(content.count(old_str), count)
    new_content = content.replace(old_str, new_str, count) if count else content.replace(old_str, new_str)

    try:
        async with aiofiles.open(file_path, "w", encoding="utf-8") as f:
            await f.write(new_content)
    except Exception as e:
        raise ToolError(f"Write failed: {e}")

    return f"Replaced {replacements} occurrence(s) in {path}"


@register_tool(tags=["system", "file"])
async def Grep(
    pattern: Annotated[str, Field(description="The ripgrep pattern to search for.")],
    path: Annotated[
        str | None,
        Field(default=None, description="The path to search in. Defaults to current directory."),
    ] = None,
    include: Annotated[
        str | None,
        Field(default=None, description="File glob pattern to include (e.g., '*.py')."),
    ] = None,
    exclude: Annotated[
        str | None,
        Field(default=None, description="File glob pattern to exclude (e.g., '*.txt')."),
    ] = None,
) -> str:
    """
    A powerful search tool based-on ripgrep.

    - This is your PREFERRED and RECOMMENDED tool for searching code patterns, finding text in files, and locating specific strings.
    - ALWAYS use Grep tool instead of running `grep` or `rg` command with Shell tool.
    - Use the ripgrep pattern syntax, not grep syntax. E.g. you need to escape braces like `\\{` to search for `{`.
    """  # noqa: E501
    search_path = Path(path) if path else (await Path.cwd())

    cmd_parts = ["rg", "--line-number", "--no-heading", "--color=never"]

    if include:
        cmd_parts.extend(["--glob", include])
    if exclude:
        cmd_parts.extend(["--glob", f"!{exclude}"])

    cmd_parts.extend(["--", pattern, str(search_path)])

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd_parts,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        return await _python_grep_fallback(
            pattern=pattern,
            search_path=search_path,
            include=include,
            exclude=exclude,
        )

    stdout, stderr = await proc.communicate()

    output = stdout.decode("utf-8", errors="replace")
    error_output = stderr.decode("utf-8", errors="replace")

    if proc.returncode == 1:
        return "No matches found."
    if proc.returncode != 0:
        raise ToolError(f"Grep failed: {error_output or output}")

    return output if output else "No matches found."


@register_tool(tags=["system", "file"])
async def Glob(
    pattern: Annotated[str, Field(description="Glob pattern, e.g. '*.py', '**/*.toml'.")],
    path: Annotated[
        str | None,
        Field(default=None, description="Search root directory. None means current working directory."),
    ] = None,
    recursive: Annotated[
        bool,
        Field(default=False, description="If True, recursively match subdirectories using rglob."),
    ] = False,
    limit: Annotated[
        int,
        Field(default=100, description="Maximum number of results to return."),
    ] = 100,
) -> str:
    """Search for files matching a glob pattern."""
    search_path = Path(path) if path else (await Path.cwd())

    if not search_path.is_absolute():
        raise ToolError(f"`{path}` is not an absolute path. You must provide an absolute path to search.")

    if recursive:
        matches = [str(p) async for p in search_path.rglob(pattern)]
    else:
        matches = [str(p) async for p in search_path.glob(pattern)]

    if not matches:
        return "No matches found."

    matches = sorted(matches)

    if len(matches) > limit:
        remaining = len(matches) - limit
        return "\n".join(matches[:limit]) + f"\n... and {remaining} more"

    return "\n".join(matches)


@register_tool(tags=["system", "file"])
async def ListFiles(
    path: Annotated[
        str | None,
        Field(default=None, description="The directory path to list. Defaults to current working directory."),
    ] = None,
    pattern: Annotated[
        str | None,
        Field(default=None, description="Optional glob pattern to filter files (e.g., '*.py')."),
    ] = None,
    recursive: Annotated[
        bool,
        Field(default=False, description="If True, recursively list files in subdirectories."),
    ] = False,
    limit: Annotated[
        int,
        Field(default=100, description="Maximum number of results to return."),
    ] = 100,
) -> str:
    """List files and directories in a given path, showing details like type, size, and modification time.

    Use this tool to explore the directory structure instead of Shell's `ls` or `dir` commands.
    The output is sorted alphabetically, with directories listed first.
    Each line shows: type (📄 file / 📁 dir), size (human-readable), last modified time, and name.
    """
    search_path = Path(path) if path else (await Path.cwd())

    if not search_path.is_absolute():
        raise ToolError(
            f"`{path}` is not an absolute path. You must provide an absolute path to list files."
        )

    if not await search_path.exists():
        raise ToolError(f"Not found: {path or search_path}")
    if not await search_path.is_dir():
        raise ToolError(f"Not a directory: {path or search_path}")

    entries: list[tuple[str, str, str, str]] = []  # (name_for_sort, type_label, size, mtime, display_name)

    async def _collect_entries(directory: Path) -> None:
        """Collect entries from a single directory (non-recursive)."""
        async for entry in directory.iterdir():
            name = entry.name
            # Apply pattern filter if specified
            if pattern and not fnmatch.fnmatch(name, pattern):
                continue
            try:
                stat = await entry.stat()
            except OSError:
                continue

            if await entry.is_dir():
                type_label = "📁"
                size_str = "-"
            else:
                type_label = "📄"
                size_str = _format_size(stat.st_size)

            mtime = _format_time(stat.st_mtime)
            entries.append((name.lower(), type_label, size_str, mtime, name))

    if recursive:
        # For recursive, walk the tree depth-first
        async for entry in search_path.rglob("*"):
            if pattern and not fnmatch.fnmatch(entry.name, pattern):
                continue
            try:
                stat = await entry.stat()
            except OSError:
                continue

            rel_path = str(entry.relative_to(search_path)).replace("\\", "/")
            if await entry.is_dir():
                type_label = "📁"
                size_str = "-"
            else:
                type_label = "📄"
                size_str = _format_size(stat.st_size)

            mtime = _format_time(stat.st_mtime)
            entries.append((rel_path.lower(), type_label, size_str, mtime, rel_path))
    else:
        await _collect_entries(search_path)

    if not entries:
        return "No files found."

    # Sort: directories first (📁 before 📄), then by name
    entries.sort(key=lambda x: (x[1], x[0]))

    # Determine column widths for alignment
    max_size_width = max(len(e[2]) for e in entries)
    max_time_width = max(len(e[3]) for e in entries)

    lines: list[str] = []
    for _, type_label, size_str, mtime, display_name in entries:
        lines.append(f"{type_label}  {size_str:>{max_size_width}}  {mtime:{max_time_width}}  {display_name}")

    if len(lines) > limit:
        remaining = len(lines) - limit
        lines = lines[:limit]
        lines.append(f"... and {remaining} more")

    return "\n".join(lines)


def _format_size(size: int) -> str:
    """Format file size in human-readable form."""
    for unit in ("B", "K", "M", "G", "T"):
        if size < 1024:
            return f"{size}{unit}"
        size //= 1024
    return f"{size}P"


def _format_time(timestamp: float) -> str:
    """Format a Unix timestamp into a readable date-time string."""
    import datetime

    dt = datetime.datetime.fromtimestamp(timestamp)
    return dt.strftime("%Y-%m-%d %H:%M:%S")


TOOL_LIST = [
    Shell,
    ReadFile,
    WriteFile,
    StrReplace,
    Grep,
    Glob,
    ListFiles,
]
