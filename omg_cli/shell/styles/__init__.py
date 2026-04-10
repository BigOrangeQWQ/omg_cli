"""Assembled CSS for the shell TUI."""

from .base import BASE_CSS
from .channel import CHANNEL_CSS
from .components import COMPONENTS_CSS
from .wizard import WIZARD_CSS

CSS = (
    BASE_CSS
    + COMPONENTS_CSS
    + WIZARD_CSS
    + CHANNEL_CSS
)
