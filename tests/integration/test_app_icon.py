"""The application icon: packaged with the code and set for every window."""

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QApplication

from scope_gui.__main__ import ICON, setup_application


def test_icon_renders_at_taskbar_size(qapp):
    assert ICON.is_file()
    setup_application(qapp, "Scope GUI")
    assert QApplication.applicationName() == "Scope GUI"
    icon = qapp.windowIcon()
    assert not icon.isNull()
    image = icon.pixmap(QSize(16, 16)).toImage()
    assert image.width() == 16
    assert image.pixelColor(8, 8).alpha() == 255  # drawn, not an empty placeholder
