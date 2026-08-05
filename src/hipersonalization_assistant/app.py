from __future__ import annotations

import sys

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from .config import Settings
from .gui import MainWindow
from .resources import resource_path


APPLICATION_NAME = "hipersonalization订单处理助手 v0.13 by Robin+Codex"


def main() -> int:
    application = QApplication(sys.argv)
    application.setApplicationName(APPLICATION_NAME)
    application.setApplicationDisplayName(APPLICATION_NAME)
    application.setWindowIcon(QIcon(str(resource_path("assets/hipersonalization.ico"))))
    window = MainWindow(Settings.from_environment())
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
