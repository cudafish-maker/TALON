"""Central PySide6 desktop visual theme."""
from __future__ import annotations

from PySide6 import QtCore, QtGui, QtWidgets


_THEME_MARKER = "_talon_desktop_theme_applied"


def apply_desktop_theme(app: QtWidgets.QApplication) -> None:
    """Apply TALON's dark operational Qt theme once per QApplication."""
    if getattr(app, _THEME_MARKER, False):
        return

    app.setStyle("Fusion")
    app.setPalette(_palette())
    app.setStyleSheet(_stylesheet())
    setattr(app, _THEME_MARKER, True)


def configure_data_table(table: QtWidgets.QTableWidget) -> None:
    """Apply consistent behavior for dense desktop data tables."""
    table.setAlternatingRowColors(True)
    table.setShowGrid(False)
    table.setWordWrap(False)
    table.setCornerButtonEnabled(False)
    table.horizontalHeader().setHighlightSections(False)
    table.horizontalHeader().setDefaultAlignment(
        QtCore.Qt.AlignLeft | QtCore.Qt.AlignVCenter
    )
    table.verticalHeader().setDefaultSectionSize(32)


def _palette() -> QtGui.QPalette:
    palette = QtGui.QPalette()
    background = QtGui.QColor("#0d1214")
    surface = QtGui.QColor("#141b1e")
    panel = QtGui.QColor("#182226")
    text = QtGui.QColor("#d8dee9")
    muted = QtGui.QColor("#93a1a8")
    accent = QtGui.QColor("#8fbcbb")

    palette.setColor(QtGui.QPalette.Window, background)
    palette.setColor(QtGui.QPalette.WindowText, text)
    palette.setColor(QtGui.QPalette.Base, QtGui.QColor("#101719"))
    palette.setColor(QtGui.QPalette.AlternateBase, surface)
    palette.setColor(QtGui.QPalette.ToolTipBase, panel)
    palette.setColor(QtGui.QPalette.ToolTipText, text)
    palette.setColor(QtGui.QPalette.Text, text)
    palette.setColor(QtGui.QPalette.Button, panel)
    palette.setColor(QtGui.QPalette.ButtonText, text)
    palette.setColor(QtGui.QPalette.BrightText, QtGui.QColor("#ff5555"))
    palette.setColor(QtGui.QPalette.Highlight, QtGui.QColor("#28484d"))
    palette.setColor(QtGui.QPalette.HighlightedText, QtGui.QColor("#f6fbfb"))
    palette.setColor(QtGui.QPalette.Link, accent)
    palette.setColor(QtGui.QPalette.PlaceholderText, muted)

    disabled = QtGui.QColor("#617078")
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.Text, disabled)
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.ButtonText, disabled)
    palette.setColor(QtGui.QPalette.Disabled, QtGui.QPalette.WindowText, disabled)
    return palette


def _stylesheet() -> str:
    return """
    QWidget {
        background: #0d1214;
        color: #d8dee9;
        font-family: "Segoe UI", "Inter", "Noto Sans", sans-serif;
        font-size: 10.5pt;
        selection-background-color: #28484d;
        selection-color: #f6fbfb;
    }

    QMainWindow, QDialog, QMessageBox {
        background: #0d1214;
    }

    QLabel {
        background: transparent;
        color: #d8dee9;
    }

    QLabel#title {
        color: #f6fbfb;
        font-size: 22pt;
        font-weight: 750;
        padding: 4px 0;
    }

    QLabel#subtitle {
        color: #93a1a8;
        font-size: 11pt;
    }

    QLabel#pageHeading {
        color: #f6fbfb;
        font-size: 17pt;
        font-weight: 750;
        padding: 2px 0 8px 0;
    }

    QLabel#sectionHeading {
        color: #f6fbfb;
        font-size: 13pt;
        font-weight: 700;
        padding-bottom: 4px;
    }

    QLabel#alertTitle {
        font-size: 18pt;
        font-weight: 800;
    }

    QFrame#sitrepAlertOverlay {
        background: #11181b;
        border: 2px solid #f28c28;
        border-radius: 6px;
    }

    QFrame#sitrepAlertOverlay[severity="flash"],
    QFrame#sitrepAlertOverlay[severity="flash_override"] {
        border-color: #ff5555;
        background: #211318;
    }

    QLabel#sitrepAlertTitle {
        font-size: 18pt;
        font-weight: 850;
    }

    QLabel#sitrepAlertMeta {
        color: #b7c4ca;
        font-size: 9.5pt;
    }

    QLabel#sitrepAlertBody {
        color: #f6fbfb;
        font-size: 12pt;
    }

    QLabel#sideTitle {
        color: #f6fbfb;
        font-size: 16pt;
        font-weight: 800;
    }

    QLabel#sideMode {
        color: #8fbcbb;
        font-size: 9pt;
        font-weight: 700;
    }

    QWidget#sideBar {
        background: #0a0f11;
        border-right: 1px solid #253238;
    }

    QStatusBar {
        background: #0a0f11;
        color: #93a1a8;
        border-top: 1px solid #253238;
        padding: 3px 8px;
    }

    QSplitter::handle {
        background: #1a2529;
        border: 1px solid #253238;
    }

    QSplitter::handle:horizontal {
        width: 7px;
    }

    QSplitter::handle:vertical {
        height: 7px;
    }

    QListWidget, QTableWidget, QTextEdit, QPlainTextEdit, QLineEdit,
    QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {
        background: #11181b;
        color: #d8dee9;
        border: 1px solid #2a3840;
        border-radius: 5px;
    }

    QTextEdit, QPlainTextEdit {
        padding: 8px;
    }

    QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QDateTimeEdit {
        min-height: 30px;
        padding: 4px 8px;
    }

    QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
    QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QDateTimeEdit:focus {
        border-color: #8fbcbb;
        background: #131d20;
    }

    QLineEdit:disabled, QTextEdit:disabled, QPlainTextEdit:disabled,
    QComboBox:disabled {
        background: #101416;
        color: #617078;
        border-color: #20292e;
    }

    QComboBox::drop-down {
        border: 0;
        width: 26px;
    }

    QComboBox QAbstractItemView {
        background: #121a1d;
        border: 1px solid #2a3840;
        selection-background-color: #28484d;
        outline: 0;
    }

    QPushButton {
        background: #1b282d;
        color: #e5edf0;
        border: 1px solid #34474f;
        border-radius: 5px;
        padding: 7px 12px;
        min-height: 28px;
        font-weight: 600;
    }

    QPushButton:hover {
        background: #243942;
        border-color: #4f6b75;
    }

    QPushButton:pressed {
        background: #132126;
        border-color: #8fbcbb;
    }

    QPushButton:disabled {
        background: #141a1d;
        color: #5f6e75;
        border-color: #222d32;
    }

    QPushButton#statusButton {
        min-height: 20px;
        padding: 3px 9px;
        border-radius: 4px;
        color: #b7c4ca;
        background: #121a1d;
    }

    QCheckBox {
        background: transparent;
        spacing: 8px;
        color: #d8dee9;
    }

    QCheckBox::indicator {
        width: 16px;
        height: 16px;
        border: 1px solid #3a4d55;
        border-radius: 3px;
        background: #101719;
    }

    QCheckBox::indicator:checked {
        background: #8fbcbb;
        border-color: #b8d8d7;
    }

    QGroupBox {
        border: 1px solid #253238;
        border-radius: 6px;
        margin-top: 18px;
        padding: 12px 10px 10px 10px;
        color: #d8dee9;
        font-weight: 650;
    }

    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: #8fbcbb;
        background: #0d1214;
    }

    QListWidget {
        outline: 0;
        padding: 4px;
    }

    QListWidget::item {
        padding: 7px 8px;
        border-radius: 4px;
    }

    QListWidget::item:hover {
        background: #19262b;
    }

    QListWidget::item:selected {
        background: #28484d;
        color: #f6fbfb;
    }

    QListWidget#navigationList {
        background: #0a0f11;
        border: 0;
        padding: 6px 0;
    }

    QListWidget#navigationList::item {
        margin: 2px 0;
        padding: 10px 12px;
        color: #aebbc2;
        border-left: 3px solid transparent;
    }

    QListWidget#navigationList::item:hover {
        background: #151f23;
        color: #d8dee9;
    }

    QListWidget#navigationList::item:selected {
        background: #1b2e33;
        color: #f6fbfb;
        border-left: 3px solid #8fbcbb;
    }

    QWidget#navRail {
        background: #0a0f11;
        border: 0;
    }

    QWidget#navRailContent {
        background: #0a0f11;
        border-right: 1px solid #1f2b30;
    }

    QToolButton#navRailButton {
        background: transparent;
        color: #aebbc2;
        border: 0;
        border-left: 3px solid transparent;
        border-radius: 4px;
        padding: 8px 10px;
        text-align: left;
    }

    QToolButton#navRailButton:hover {
        background: #151f23;
        color: #d8dee9;
    }

    QToolButton#navRailButton:checked {
        background: #1b2e33;
        color: #f6fbfb;
        border-left: 3px solid #8fbcbb;
    }

    QToolButton#navRailToggle {
        background: #10181b;
        color: #8fbcbb;
        border: 0;
        border-right: 1px solid #1f2b30;
        font-weight: 700;
    }

    QToolButton#navRailToggle:hover {
        background: #19262b;
        color: #f6fbfb;
    }

    QTableWidget {
        gridline-color: #253238;
        alternate-background-color: #141d20;
        selection-background-color: #28484d;
        selection-color: #f6fbfb;
        outline: 0;
    }

    QTableWidget::item {
        padding: 6px;
    }

    QHeaderView::section {
        background: #172226;
        color: #b7c4ca;
        border: 0;
        border-bottom: 1px solid #34474f;
        padding: 7px 8px;
        font-weight: 700;
    }

    QGraphicsView {
        background: #111619;
        border: 1px solid #2f3437;
        border-radius: 5px;
    }

    QScrollBar:vertical, QScrollBar:horizontal {
        background: #0d1214;
        border: 0;
    }

    QScrollBar:vertical {
        width: 12px;
    }

    QScrollBar:horizontal {
        height: 12px;
    }

    QScrollBar::handle {
        background: #2a3840;
        border-radius: 5px;
        min-height: 28px;
        min-width: 28px;
    }

    QScrollBar::handle:hover {
        background: #3b515a;
    }

    QScrollBar::add-line, QScrollBar::sub-line,
    QScrollBar::add-page, QScrollBar::sub-page {
        background: transparent;
        border: 0;
        width: 0;
        height: 0;
    }

    QToolTip {
        background: #172226;
        color: #f6fbfb;
        border: 1px solid #34474f;
        padding: 6px;
    }
    """
