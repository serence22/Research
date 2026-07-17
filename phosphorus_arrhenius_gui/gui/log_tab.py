from __future__ import annotations

from PySide6.QtWidgets import QTextEdit, QVBoxLayout, QWidget


class LogTab(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self.text = QTextEdit()
        self.text.setReadOnly(True)
        layout = QVBoxLayout(self)
        layout.addWidget(self.text)

    def set_logs(self, logs: list[str]) -> None:
        self.text.setPlainText("\n".join(logs))
