"""Reticulum config setup dialog for unlocked desktop sessions."""
from __future__ import annotations

from PySide6 import QtWidgets

from talon_core import TalonCoreSession
from talon_core.network.rns_config import (
    auto_interface_config,
    default_reticulum_config,
    tcp_client_config,
    tcp_server_config,
)


class ReticulumConfigDialog(QtWidgets.QDialog):
    """Raw Reticulum config editor shown only after TALON DB unlock."""

    def __init__(
        self,
        core: TalonCoreSession,
        parent: QtWidgets.QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._core = core
        self._last_valid = False
        self._saved_text = ""
        self.setWindowTitle("Reticulum Configuration")
        self.setMinimumSize(820, 620)

        self.heading = QtWidgets.QLabel("Reticulum Configuration")
        self.heading.setObjectName("dialogHeading")
        self.path_label = QtWidgets.QLabel("")
        self.path_label.setWordWrap(True)

        self.editor = QtWidgets.QPlainTextEdit()
        self.editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        self.editor.textChanged.connect(self._validate_current_text)

        self.validation_panel = QtWidgets.QTextEdit()
        self.validation_panel.setReadOnly(True)
        self.validation_panel.setMinimumHeight(120)

        self.default_button = QtWidgets.QPushButton("TALON Default")
        self.default_button.clicked.connect(self._use_default_template)
        self.auto_button = QtWidgets.QPushButton("AutoInterface")
        self.auto_button.clicked.connect(self._use_auto_template)
        self.tcp_server_button = QtWidgets.QPushButton("TCP Server")
        self.tcp_server_button.clicked.connect(self._use_tcp_server_template)
        self.tcp_client_button = QtWidgets.QPushButton("TCP Client")
        self.tcp_client_button.clicked.connect(self._use_tcp_client_template)
        self.import_button = QtWidgets.QPushButton("Import ~/.reticulum/config")
        self.import_button.clicked.connect(self._import_default_config)

        template_row = QtWidgets.QHBoxLayout()
        template_row.addWidget(self.default_button)
        template_row.addWidget(self.auto_button)
        template_row.addWidget(self.tcp_server_button)
        template_row.addWidget(self.tcp_client_button)
        template_row.addStretch(1)
        template_row.addWidget(self.import_button)

        self.validate_button = QtWidgets.QPushButton("Validate")
        self.validate_button.clicked.connect(self._validate_current_text)
        self.save_button = QtWidgets.QPushButton("Save")
        self.save_button.clicked.connect(self._save_clicked)
        self.continue_button = QtWidgets.QPushButton("Continue")
        self.continue_button.clicked.connect(self._continue_clicked)
        self.cancel_button = QtWidgets.QPushButton("Cancel")
        self.cancel_button.clicked.connect(self.reject)

        action_row = QtWidgets.QHBoxLayout()
        action_row.addStretch(1)
        action_row.addWidget(self.validate_button)
        action_row.addWidget(self.cancel_button)
        action_row.addWidget(self.save_button)
        action_row.addWidget(self.continue_button)

        layout = QtWidgets.QVBoxLayout(self)
        layout.addWidget(self.heading)
        layout.addWidget(self.path_label)
        layout.addLayout(template_row)
        layout.addWidget(self.editor, stretch=1)
        layout.addWidget(self.validation_panel)
        layout.addLayout(action_row)

        self._load_initial_text()

    def _load_initial_text(self) -> None:
        status = self._core.reticulum_config_status()
        self.path_label.setText(f"TALON Reticulum config: {status.path}")
        text = self._core.load_reticulum_config_text()
        self._saved_text = text
        self.editor.setPlainText(text)
        self._render_validation(status.validation)
        self.continue_button.setEnabled(status.exists and status.valid)

    def _validate_current_text(self) -> None:
        validation = self._core.validate_reticulum_config_text(self.editor.toPlainText())
        self._render_validation(validation)
        status = self._core.reticulum_config_status()
        is_dirty = self.editor.toPlainText() != self._saved_text
        self.continue_button.setEnabled(status.exists and validation.valid and not is_dirty)

    def _render_validation(self, validation: object) -> None:
        errors = tuple(getattr(validation, "errors", ()) or ())
        warnings = tuple(getattr(validation, "warnings", ()) or ())
        self._last_valid = bool(getattr(validation, "valid", False))
        lines: list[str] = []
        if errors:
            lines.append("Errors")
            lines.extend(f"- {message}" for message in errors)
        if warnings:
            if lines:
                lines.append("")
            lines.append("Warnings")
            lines.extend(f"- {message}" for message in warnings)
        if not lines:
            lines.append("Reticulum config is valid.")
        self.validation_panel.setPlainText("\n".join(lines))
        self.save_button.setEnabled(self._last_valid)

    def _save_clicked(self) -> None:
        try:
            result = self._core.save_reticulum_config_text(self.editor.toPlainText())
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Reticulum Configuration", str(exc))
            self._validate_current_text()
            return
        self._render_validation(result.validation)
        self._saved_text = self.editor.toPlainText()
        self.continue_button.setEnabled(True)
        if result.restart_required:
            QtWidgets.QMessageBox.information(
                self,
                "Reticulum Configuration",
                "Reticulum is already running. Restart TALON to apply this config.",
            )
        self.accept()

    def _continue_clicked(self) -> None:
        validation = self._core.validate_reticulum_config_text(self.editor.toPlainText())
        self._render_validation(validation)
        if not validation.valid:
            return
        status = self._core.reticulum_config_status()
        if not status.exists:
            self.save_button.setFocus()
            return
        self.accept()

    def _import_default_config(self) -> None:
        try:
            result = self._core.import_default_reticulum_config()
            self.editor.setPlainText(self._core.load_reticulum_config_text())
        except Exception as exc:
            QtWidgets.QMessageBox.warning(self, "Reticulum Import", str(exc))
            self._validate_current_text()
            return
        self._render_validation(result.validation)
        self._saved_text = self.editor.toPlainText()
        self.continue_button.setEnabled(True)
        if result.restart_required:
            QtWidgets.QMessageBox.information(
                self,
                "Reticulum Import",
                "Reticulum is already running. Restart TALON to apply this config.",
            )
        self.accept()

    def _use_default_template(self) -> None:
        self.editor.setPlainText(default_reticulum_config(self._core.mode))

    def _use_auto_template(self) -> None:
        self.editor.setPlainText(auto_interface_config(self._core.mode))

    def _use_tcp_server_template(self) -> None:
        port, ok = QtWidgets.QInputDialog.getInt(
            self,
            "TCP Server Port",
            "Port",
            4242,
            1,
            65535,
        )
        if not ok:
            return
        self.editor.setPlainText(tcp_server_config(listen_ip="0.0.0.0", port=port))

    def _use_tcp_client_template(self) -> None:
        host, ok = QtWidgets.QInputDialog.getText(
            self,
            "TCP Server Host",
            "Server host",
        )
        host = host.strip()
        if not ok or not host:
            return
        port, ok = QtWidgets.QInputDialog.getInt(
            self,
            "TCP Server Port",
            "Port",
            4242,
            1,
            65535,
        )
        if not ok:
            return
        self.editor.setPlainText(tcp_client_config(host, port=port))
