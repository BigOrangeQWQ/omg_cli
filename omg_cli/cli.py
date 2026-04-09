"""CLI entry point for omg-cli.

This module re-exports the run_terminal function from the shell module
for backward compatibility.
"""

from omg_cli.shell import run_terminal

__all__ = ["run_terminal"]
