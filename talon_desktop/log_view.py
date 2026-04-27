"""Qt log viewer for the desktop shell."""
from __future__ import annotations

import logging

from PySide6 import QtCore, QtGui, QtWidgets

from talon_desktop.logs import DesktopLogBuffer


class LogDialog(QtWidgets.QDialog):
    """Readable current-session log view."""

    def __init__(
        self,
        buffer: DesktopLogBuffer,
        *,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._buffer = buffer
        self.setWindowTitle("TALON Session Logs")
        self.setMinimumSize(760, 480)

        title = QtWidgets.QLabel("Session Logs")
        title.setObjectName("pageHeading")
        self.summary = QtWidgets.QLabel("")
        self.summary.setWordWrap(True)
        self.text = QtWidgets.QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)

        refresh_button = QtWidgets.QPushButton("Refresh")
        refresh_button.clicked.connect(self.refresh)
        copy_button = QtWidgets.QPushButton("Copy")
        copy_button.clicked.connect(self.copy_to_clipboard)
        close_button = QtWidgets.QPushButton("Close")
        close_button.clicked.connect(self.accept)

        buttons = QtWidgets.QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(refresh_button)
        buttons.addWidget(copy_button)
        buttons.addWidget(close_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(title)
        layout.addWidget(self.summary)
        layout.addWidget(self.text, stretch=1)
        layout.addLayout(buttons)
        self.refresh()

    @QtCore.Slot()
    def refresh(self) -> None:
        records = self._buffer.records()
        warnings = sum(record.levelno >= logging.WARNING for record in records)
        self.summary.setText(
            f"{len(records)} messages in current session; "
            f"{warnings} warnings or errors."
        )
        lines = [self._buffer.format(record) for record in records]
        self.text.setPlainText("\n".join(lines) if lines else "No log messages.")
        cursor = self.text.textCursor()
        cursor.movePosition(QtGui.QTextCursor.End)
        self.text.setTextCursor(cursor)

    @QtCore.Slot()
    def copy_to_clipboard(self) -> None:
        QtWidgets.QApplication.clipboard().setText(self.text.toPlainText())
