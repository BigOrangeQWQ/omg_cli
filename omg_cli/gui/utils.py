from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QPainter, QPixmap


def emoji_to_pixmap(emoji: str, size: int = 64) -> QPixmap:
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    font = QFont("Segoe UI Emoji", size)
    painter.setFont(font)
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, emoji)
    painter.end()
    return pixmap
