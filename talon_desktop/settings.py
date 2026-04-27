"""Desktop-local persistent UI settings."""
from __future__ import annotations

import os
import pathlib

from PySide6 import QtCore, QtWidgets


SETTINGS_PATH_ENV = "TALON_DESKTOP_SETTINGS_PATH"


def desktop_settings() -> QtCore.QSettings:
    """Return the Qt settings store for local desktop UI preferences."""
    override = os.environ.get(SETTINGS_PATH_ENV)
    if override:
        path = pathlib.Path(override).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        return QtCore.QSettings(str(path), QtCore.QSettings.IniFormat)
    return QtCore.QSettings(
        QtCore.QSettings.IniFormat,
        QtCore.QSettings.UserScope,
        "TALON",
        "TALON Desktop",
    )


def settings_byte_array(value: object) -> QtCore.QByteArray | None:
    """Normalize a QSettings byte value from native and INI backends."""
    if isinstance(value, QtCore.QByteArray):
        return value if not value.isEmpty() else None
    if isinstance(value, (bytes, bytearray)):
        byte_array = QtCore.QByteArray(bytes(value))
        return byte_array if not byte_array.isEmpty() else None
    return None


def restore_header_state(table: QtWidgets.QTableWidget, settings: QtCore.QSettings, key: str) -> None:
    state = settings_byte_array(settings.value(key))
    if state is not None:
        table.horizontalHeader().restoreState(state)


def save_header_state(table: QtWidgets.QTableWidget, settings: QtCore.QSettings, key: str) -> None:
    settings.setValue(key, table.horizontalHeader().saveState())


def restore_splitter_state(splitter: QtWidgets.QSplitter, settings: QtCore.QSettings, key: str) -> None:
    state = settings_byte_array(settings.value(key))
    if state is not None:
        splitter.restoreState(state)


def save_splitter_state(splitter: QtWidgets.QSplitter, settings: QtCore.QSettings, key: str) -> None:
    settings.setValue(key, splitter.saveState())
