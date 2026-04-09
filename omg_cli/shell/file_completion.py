"""File completion mixin for directory/path suggestions."""

import functools
from pathlib import Path
from typing import Self


class FileCompletionMixin:
    """Mixin for file/directory completion functionality.

    Provides cached directory/file completion with LRU caching.

    Example:
        class MyApp(FileCompletionMixin):
            pass

        app = MyApp()
        results = await app.get_directory_completions("!src")
    """

    @staticmethod
    @functools.lru_cache(maxsize=128)
    def _get_completions_sync(
        prefix: str,
        max_results: int,
        include_files: bool,
        include_hidden: bool,
    ) -> list[str]:
        """Synchronous completion lookup with LRU caching."""
        # Build search base path
        base_path = Path(".")
        search_name = "*"

        if prefix:
            # Handle path with directory component
            if "/" in prefix:
                dir_part, name_part = prefix.rsplit("/", 1)
                base_path = Path(dir_part) if dir_part else Path(".")
                search_name = f"{name_part}*" if name_part else "*"
            else:
                # Just a name in current directory
                search_name = f"{prefix}*"

            # If prefix itself is a directory, show its contents
            potential_dir = Path(prefix)
            if potential_dir.is_dir() and not prefix.endswith("/"):
                base_path = potential_dir
                search_name = "*"

        # Ensure base path exists and is a directory
        if not base_path.exists() or not base_path.is_dir():
            return []

        # Gather results - separate dirs and files to prioritize directories
        dirs: list[str] = []
        files: list[str] = []
        seen: set[str] = set()

        try:
            # Search for directories first, then files
            for path in sorted(base_path.glob(search_name)):
                if path.name in seen:
                    continue
                seen.add(path.name)

                if not include_hidden and _is_hidden(path.name):
                    continue

                if path.is_dir():
                    dirs.append(f"{path}/")
                elif include_files:
                    files.append(str(path))

        except (OSError, PermissionError):
            pass

        # Combine results: directories first, then files
        results = dirs + files

        # Auto-skip single directory chains: if only one result and it's a directory,
        # recursively get its contents
        if len(results) == 1 and results[0].endswith("/"):
            single_dir = results[0].rstrip("/")
            # Build the new prefix for recursive lookup
            if prefix:
                new_prefix = f"{prefix}/{Path(single_dir).name}"
            else:
                new_prefix = single_dir
            return FileCompletionMixin._get_completions_sync(
                new_prefix,
                max_results,
                include_files,
                include_hidden,
            )

        return _filter_results(results, max_results, include_hidden)

    async def get_directory_completions(
        self: Self,
        word: str,
        *,
        max_results: int = 50,
        include_files: bool = True,
        include_hidden: bool = False,
    ) -> list[str]:
        """Get directory/file completion suggestions.

        Args:
            word: The word to complete (may start with ! which will be stripped)
            max_results: Maximum number of results to return
            include_files: Whether to include files in results
            include_hidden: Whether to include hidden files (starting with _ or .)

        Returns:
            List of path strings (directories end with /)
        """
        # Strip leading ! if present
        prefix = word[1:] if word.startswith("!") else word

        # Use cached static method
        return self._get_completions_sync(
            prefix,
            max_results,
            include_files,
            include_hidden,
        )


def _is_hidden(name: str) -> bool:
    """Check if a file/directory name is hidden."""
    return name.startswith("_") or name.startswith(".")


def _filter_results(
    results: list[str],
    max_results: int,
    include_hidden: bool,
) -> list[str]:
    """Filter and limit results."""
    if include_hidden:
        return results[:max_results]

    # Filter out hidden items (should already be filtered, but double-check)
    filtered = [r for r in results if not _is_hidden(Path(r).name.rstrip("/"))]
    return filtered[:max_results]


__all__ = [
    "FileCompletionMixin",
]
