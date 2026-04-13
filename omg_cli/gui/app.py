"""Minimal PySide6 GUI entrypoint for omg-cli."""

from typing import Any

from omg_cli.log import logger


class GuiUnavailableError(RuntimeError):
    """Raised when PySide6 is not available in the environment."""


def run_gui(context: Any, channel: bool = False) -> None:
    """Launch a minimal GUI shell.

    The GUI is intentionally small in this first milestone and only establishes
    a stable startup path that can be expanded in future PRs.
    """

    try:
        from PySide6.QtWidgets import QApplication, QLabel, QMainWindow
    except Exception as exc:  # pragma: no cover - depends on local environment
        raise GuiUnavailableError("PySide6 is required for --gui mode. Install it with: uv add pyside6") from exc

    app = QApplication.instance() or QApplication([])

    window = QMainWindow()
    mode = "Channel" if channel else "Chat"
    provider_name = getattr(getattr(context, "provider", None), "model_name", "no-model")
    label = QLabel(
        f"OMG GUI (experimental)\nMode: {mode}\nModel: {provider_name}\n\nGUI module is under active implementation."
    )
    label.setContentsMargins(20, 20, 20, 20)
    window.setCentralWidget(label)
    window.setWindowTitle("OMG GUI")
    window.resize(900, 620)
    window.show()

    logger.info("Launched experimental GUI")
    app.exec()
