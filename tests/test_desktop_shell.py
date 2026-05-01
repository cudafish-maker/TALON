import pathlib
import logging
import os
import subprocess
import sys
import types

import pytest

from talon_core.constants import SITREP_LEVELS
from talon_core.services.events import (
    RecordMutation,
    linked_records_changed,
    operator_revoked,
    record_changed,
)
from talon_desktop.assets import (
    build_create_payload as build_asset_create_payload,
    build_update_payload as build_asset_update_payload,
    can_verify_asset,
    item_from_asset,
)
from talon_desktop.chat import (
    build_create_channel_payload,
    build_dm_payload,
    build_message_payload,
    can_delete_channel,
    can_delete_message,
    grid_reference_items_from_context,
    item_from_channel,
    item_from_message,
)
from talon_desktop.community_safety import (
    assignment_item_from_assignment,
    build_assignment_payload,
    build_checkin_payload,
)
from talon_desktop.documents import (
    build_upload_payload as build_document_upload_payload,
    can_delete_document,
    can_download_document,
    can_upload_document,
    document_error_message,
    item_from_document_entry,
    is_macro_risk_filename,
)
from talon_desktop.events import desktop_update_from_event, refresh_sections_for_events
from talon_desktop.logs import DesktopLogBuffer
from talon_desktop.map_data import build_map_overlays, project_lat_lon
from talon_desktop.map_tiles import (
    MAX_TILE_REQUESTS,
    TILE_LAYERS_BY_KEY,
    build_tile_plan,
    lat_lon_for_scene_point,
    pan_bounds_by_scene_delta,
    scene_point_for_lat_lon,
    zoom_bounds_around_scene_point,
)
from talon_desktop.missions import (
    build_create_payload as build_mission_create_payload,
    item_from_mission,
    parse_coordinate_lines,
    server_actions_for_status,
)
from talon_desktop.navigation import (
    desktop_sections_for_legacy_targets,
    navigation_items,
    section_for_key,
)
from talon_desktop.operators import (
    audit_severity,
    build_operator_update_payload,
    can_edit_operator,
    can_renew_operator,
    can_revoke_operator,
    item_from_audit_entry,
    item_from_enrollment_token,
    item_from_operator,
)
from talon_desktop.sitreps import (
    DEFAULT_TEMPLATE_KEY,
    SITREP_TEMPLATES,
    available_operator_items,
    build_create_payload,
    build_filter_payload,
    feed_item_from_entry,
    severity_counts,
    should_play_audio,
    sitrep_template_for_key,
)

_QT_SMOKE_SCRIPT = r"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets

from talon_core import TalonCoreSession
from talon_desktop.app import DesktopPage, MainWindow
from talon_desktop.map_page import MapPage
from talon_desktop.navigation import navigation_items
from talon_desktop.qt_events import CoreEventBridge

config_path = sys.argv[1]
mode = sys.argv[2]
navigate = sys.argv[3] == "navigate"

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path).start()
window = None
try:
    core.unlock_with_key(bytes(range(32)))
    bridge = CoreEventBridge()
    window = MainWindow(core, bridge)
    expected = [item.key for item in navigation_items(mode)]
    actual = [
        window.nav.item(index).data(QtCore.Qt.UserRole)
        for index in range(window.nav.count())
    ]
    assert actual == expected, (actual, expected)
    assert set(window._pages) == set(expected), (window._pages.keys(), expected)
    dashboard = window._pages["dashboard"]
    assert isinstance(dashboard, DesktopPage)
    assert not isinstance(dashboard, MapPage)
    assert dashboard.heading.text() == "Dashboard"
    assert dashboard.summary.text() == "Core session and operational summary."
    assert dashboard.findChildren(MapPage) == []
    assert window.network_setup_button.text() == "Network Setup"
    assert window.network_setup_button.isEnabled()
    assert window.nav.is_expanded() is True
    window.nav.toggle()
    assert window.nav.is_expanded() is False
    window.nav.toggle()
    assert window.nav.is_expanded() is True
    if navigate:
        for index, key in enumerate(expected):
            window.nav.setCurrentRow(index)
            app.processEvents()
            assert window.stack.currentIndex() == index, (key, window.stack.currentIndex())
            assert window.nav.currentItem().data(QtCore.Qt.UserRole) == key
    print("|".join(actual))
finally:
    if window is not None:
        window.close()
    core.close()
    app.processEvents()
"""

_QT_UNLOCK_SMOKE_SCRIPT = r"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets

from talon_core import TalonCoreSession
from talon_desktop.app import DesktopRuntime, LoginWindow, MainWindow

config_path = sys.argv[1]
mode = sys.argv[2]

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path).start()
runtime = DesktopRuntime(core, start_sync=False)
try:
    core.start_reticulum = lambda: None
    runtime.login_window = LoginWindow(core.mode)
    def _show_main(*, sync_warning=""):
        runtime.main_window = MainWindow(core, runtime.event_bridge)
    runtime.show_main = _show_main
    runtime.unlock("DesktopSmoke-1")
    deadline = time.time() + 15.0
    result = None
    while time.time() < deadline:
        app.processEvents()
        if mode == "server" and runtime.main_window is not None:
            result = "server-main"
            break
        if (
            mode == "client"
            and runtime.login_window is not None
            and not runtime.login_window.enrollment_group.isHidden()
        ):
            assert not runtime.login_window.network_setup_button.isHidden()
            assert runtime.login_window.network_setup_button.isEnabled()
            result = "client-enrollment"
            break
        time.sleep(0.02)
    assert result is not None, "desktop runtime unlock smoke timed out"
    print(result)
finally:
    if runtime.main_window is not None:
        runtime.main_window.close()
    if runtime.login_window is not None:
        runtime.login_window.close()
    core._reticulum_started = False
    runtime.shutdown()
    app.processEvents()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

_QT_RETICULUM_FAILURE_SCRIPT = r"""
import os
import sys
import time
import hashlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets

from talon_core import TalonCoreSession
from talon_core.crypto.keystore import derive_key, load_or_create_salt
from talon_core.network.rns_config import save_reticulum_config_text
from talon_desktop.app import DesktopRuntime, LoginWindow

config_path = sys.argv[1]

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path).start()
runtime = DesktopRuntime(core, start_sync=True)
try:
    db_key = derive_key("DesktopSmoke-1", load_or_create_salt(core.paths.salt_path))
    marker_key = hashlib.blake2b(
        db_key,
        digest_size=32,
        person=b"TALONRNSCFGv2",
        salt=hashlib.sha256(b"talon:reticulum-config-marker").digest()[:16],
    ).digest()
    save_reticulum_config_text(
        core.paths.rns_config_dir,
        "[reticulum]\n"
        "  enable_transport = False\n"
        "  share_instance = No\n"
        "\n"
        "[interfaces]\n"
        "  [[TALON AutoInterface]]\n"
        "    type = AutoInterface\n"
        "    enabled = Yes\n",
        mode=core.mode,
        marker_key=marker_key,
    )
    def _fail_reticulum():
        raise RuntimeError("rns unavailable")
    core.start_reticulum = _fail_reticulum
    runtime.login_window = LoginWindow(core.mode)
    runtime.unlock("DesktopSmoke-1")
    deadline = time.time() + 5.0
    while time.time() < deadline:
        app.processEvents()
        message = runtime.login_window.status_label.text()
        if "Reticulum failed to start: rns unavailable" in message:
            print("reticulum-error-visible")
            break
        time.sleep(0.02)
    else:
        raise AssertionError(runtime.login_window.status_label.text())
finally:
    if runtime.login_window is not None:
        runtime.login_window.close()
    runtime.shutdown()
    app.processEvents()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

_QT_UNLOCK_ORDER_SCRIPT = r"""
import os
import sys
import time
import hashlib

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from talon_core import TalonCoreSession
from talon_core.crypto.keystore import derive_key, load_or_create_salt
from talon_core.network.rns_config import save_reticulum_config_text
from talon_desktop.app import DesktopRuntime, LoginWindow, MainWindow

config_path = sys.argv[1]
mode = sys.argv[2]

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path).start()
runtime = DesktopRuntime(core, start_sync=True)
calls = []
try:
    db_key = derive_key("DesktopSmoke-1", load_or_create_salt(core.paths.salt_path))
    marker_key = hashlib.blake2b(
        db_key,
        digest_size=32,
        person=b"TALONRNSCFGv2",
        salt=hashlib.sha256(b"talon:reticulum-config-marker").digest()[:16],
    ).digest()
    save_reticulum_config_text(
        core.paths.rns_config_dir,
        "[reticulum]\n"
        "  enable_transport = True\n"
        "  share_instance = No\n"
        "\n"
        "[interfaces]\n"
        "  [[TALON AutoInterface]]\n"
        "    type = AutoInterface\n"
        "    enabled = Yes\n",
        mode=core.mode,
        marker_key=marker_key,
    )
    def _start_reticulum():
        calls.append(("reticulum", core.is_unlocked))
        assert core.is_unlocked is True
        core._reticulum_started = True
    def _start_sync(*, init_reticulum=True):
        calls.append(("sync", init_reticulum, core.reticulum_started))
        assert init_reticulum is False
        assert core.reticulum_started is True
    core.start_reticulum = _start_reticulum
    core.start_sync = _start_sync
    runtime.login_window = LoginWindow(core.mode)
    def _show_main(*, sync_warning=""):
        runtime.main_window = MainWindow(core, runtime.event_bridge)
    runtime.show_main = _show_main
    runtime.unlock("DesktopSmoke-1")
    deadline = time.time() + 15.0
    while time.time() < deadline:
        app.processEvents()
        if runtime.main_window is not None:
            break
        time.sleep(0.02)
    else:
        raise AssertionError("unlock order smoke timed out")
    assert calls == [("reticulum", True), ("sync", False, True)], calls
    print("unlock-order-ok")
finally:
    if runtime.main_window is not None:
        runtime.main_window.close()
    if runtime.login_window is not None:
        runtime.login_window.close()
    core._reticulum_started = False
    runtime.shutdown()
    app.processEvents()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

_QT_CONFIG_GATE_REJECT_SCRIPT = r"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from talon_core import TalonCoreSession
import talon_desktop.app as app_module
from talon_desktop.app import DesktopRuntime, LoginWindow

config_path = sys.argv[1]

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path).start()
runtime = DesktopRuntime(core, start_sync=True)
try:
    class FakeReticulumConfigDialog:
        def __init__(self, core, parent=None):
            assert core.is_unlocked is True
            print("config-dialog-opened")
        def exec(self):
            return QtWidgets.QDialog.Rejected
    app_module.ReticulumConfigDialog = FakeReticulumConfigDialog
    def _start_reticulum():
        raise AssertionError("Reticulum must not start before config is accepted")
    core.start_reticulum = _start_reticulum
    runtime.login_window = LoginWindow(core.mode)
    runtime.unlock("DesktopSmoke-1")
    deadline = time.time() + 15.0
    while time.time() < deadline:
        app.processEvents()
        message = runtime.login_window.status_label.text()
        if "Reticulum setup is required before network startup." in message:
            assert not runtime.login_window.network_setup_button.isHidden()
            assert runtime.login_window.network_setup_button.isEnabled()
            print("config-gate-rejected")
            break
        time.sleep(0.02)
    else:
        raise AssertionError(runtime.login_window.status_label.text())
finally:
    if runtime.login_window is not None:
        runtime.login_window.close()
    runtime.shutdown()
    app.processEvents()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

_QT_CONFIG_GATE_CONTINUE_SCRIPT = r"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from talon_core import TalonCoreSession
import talon_desktop.app as app_module
from talon_desktop.app import DesktopRuntime, LoginWindow, MainWindow

config_path = sys.argv[1]
mode = sys.argv[2]

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path).start()
runtime = DesktopRuntime(core, start_sync=True)
events = []
try:
    class FakeReticulumConfigDialog:
        def __init__(self, core, parent=None):
            self.core = core
            assert core.is_unlocked is True
        def exec(self):
            events.append("config")
            self.core.save_reticulum_config_text(self.core.load_reticulum_config_text())
            return QtWidgets.QDialog.Accepted
    app_module.ReticulumConfigDialog = FakeReticulumConfigDialog
    def _start_reticulum():
        events.append("reticulum")
        assert core.is_unlocked is True
        core._reticulum_started = True
    def _start_sync(*, init_reticulum=True):
        events.append("sync")
        assert init_reticulum is False
        assert core.reticulum_started is True
    core.start_reticulum = _start_reticulum
    core.start_sync = _start_sync
    runtime.login_window = LoginWindow(core.mode)
    def _show_main(*, sync_warning=""):
        runtime.main_window = MainWindow(core, runtime.event_bridge)
    runtime.show_main = _show_main
    runtime.unlock("DesktopSmoke-1")
    deadline = time.time() + 15.0
    result = None
    while time.time() < deadline:
        app.processEvents()
        if mode == "server" and runtime.main_window is not None:
            result = "server-main"
            break
        if (
            mode == "client"
            and runtime.login_window is not None
            and not runtime.login_window.enrollment_group.isHidden()
        ):
            result = "client-enrollment"
            break
        time.sleep(0.02)
    assert result is not None, "config gate continue smoke timed out"
    assert events == ["config", "reticulum", "sync"], events
    print("config-gate-continued-" + result)
finally:
    if runtime.main_window is not None:
        runtime.main_window.close()
    if runtime.login_window is not None:
        runtime.login_window.close()
    core._reticulum_started = False
    runtime.shutdown()
    app.processEvents()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

_QT_NETWORK_SETUP_RETRY_SCRIPT = r"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from talon_core import TalonCoreSession
import talon_desktop.app as app_module
from talon_desktop.app import DesktopRuntime

config_path = sys.argv[1]

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path).start()
runtime = DesktopRuntime(core, start_sync=True)
events = []
try:
    class FakeReticulumConfigDialog:
        calls = 0
        def __init__(self, core, parent=None):
            self.core = core
            assert core.is_unlocked is True
        def exec(self):
            FakeReticulumConfigDialog.calls += 1
            if FakeReticulumConfigDialog.calls == 1:
                events.append("config-reject")
                return QtWidgets.QDialog.Rejected
            events.append("config-accept")
            self.core.save_reticulum_config_text(self.core.load_reticulum_config_text())
            return QtWidgets.QDialog.Accepted
    app_module.ReticulumConfigDialog = FakeReticulumConfigDialog
    def _start_reticulum():
        events.append("reticulum")
        assert core.is_unlocked is True
        core._reticulum_started = True
    def _start_sync(*, init_reticulum=True):
        events.append("sync")
        assert init_reticulum is False
        assert core.reticulum_started is True
    core.start_reticulum = _start_reticulum
    core.start_sync = _start_sync
    runtime.show_login()
    runtime.unlock("DesktopSmoke-1")
    deadline = time.time() + 15.0
    while time.time() < deadline:
        app.processEvents()
        if (
            runtime.login_window is not None
            and "Reticulum setup is required before network startup."
            in runtime.login_window.status_label.text()
        ):
            break
        time.sleep(0.02)
    else:
        raise AssertionError(runtime.login_window.status_label.text())
    assert runtime.login_window.network_setup_button.isEnabled()
    runtime.login_window.network_setup_button.click()
    deadline = time.time() + 15.0
    while time.time() < deadline:
        app.processEvents()
        if not runtime.login_window.enrollment_group.isHidden():
            break
        time.sleep(0.02)
    else:
        raise AssertionError(runtime.login_window.status_label.text())
    assert events == ["config-reject", "config-accept", "reticulum", "sync"], events
    print("network-setup-retry-ok")
finally:
    if runtime.main_window is not None:
        runtime.main_window.close()
    if runtime.login_window is not None:
        runtime.login_window.close()
    runtime.shutdown()
    app.processEvents()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

_QT_MAIN_NETWORK_SETUP_SCRIPT = r"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from talon_core import TalonCoreSession
import talon_desktop.app as app_module
from talon_desktop.app import DesktopRuntime, MainWindow

config_path = sys.argv[1]
mode = sys.argv[2]

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path).start()
runtime = DesktopRuntime(core, start_sync=False)
events = []
try:
    class FakeReticulumConfigDialog:
        def __init__(self, core, parent=None):
            assert core.is_unlocked is True
            assert isinstance(parent, MainWindow)
            events.append("main-parent")
        def exec(self):
            events.append("accepted")
            return QtWidgets.QDialog.Accepted
    app_module.ReticulumConfigDialog = FakeReticulumConfigDialog
    core.unlock_with_key(bytes(range(32)))
    runtime.main_window = MainWindow(core, runtime.event_bridge)
    runtime.main_window.networkSetupRequested.connect(runtime.configure_network)
    runtime.main_window.show()
    app.processEvents()
    runtime.main_window.network_setup_button.click()
    app.processEvents()
    assert events == ["main-parent", "accepted"], events
    assert runtime.main_window.network_setup_button.isEnabled()
    assert runtime.main_window.statusBar().currentMessage() == "Network settings saved."
    print("main-network-setup-ok-" + mode)
finally:
    if runtime.main_window is not None:
        runtime.main_window.close()
    if runtime.login_window is not None:
        runtime.login_window.close()
    runtime.shutdown()
    app.processEvents()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

_QT_NETWORK_METHOD_WARNING_SCRIPT = r"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets

from talon_core import TalonCoreSession
from talon_core.network.rns_config import tcp_client_config
from talon_desktop.app import DIRECT_TCP_PRIVACY_WARNING_TEXT, MainWindow
from talon_desktop.qt_events import CoreEventBridge

config_path = sys.argv[1]
settings_path = sys.argv[4]

class FakeClientSync:
    def __init__(self):
        self.session_id = 1

    def status(self):
        return {
            "started": True,
            "connected": True,
            "enrolled": True,
            "operator_id": 2,
            "last_sync_at": 12345,
            "connection_session_id": self.session_id,
        }

    def stop(self):
        pass

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path).start()
window = None
try:
    core.unlock_with_key(bytes(range(32)))
    core.save_reticulum_config_text(tcp_client_config("203.0.113.44", port=4242))
    settings = QtCore.QSettings(settings_path, QtCore.QSettings.IniFormat)
    window = MainWindow(core, CoreEventBridge(), settings=settings)
    shown = []
    window._show_direct_tcp_privacy_warning = lambda: shown.append(
        DIRECT_TCP_PRIVACY_WARNING_TEXT
    )
    fake = FakeClientSync()
    core._client_sync = fake
    window._refresh_network_method_status()
    app.processEvents()
    assert window.network_method_badge.text() == "Connected via TCP"
    assert window.network_method_badge.property("warning") is True
    assert len(shown) == 1
    assert "VPN" in shown[0]
    assert "203.0.113.44" not in shown[0]
    window._refresh_network_method_status()
    app.processEvents()
    assert len(shown) == 1
    fake.session_id = 2
    window._refresh_network_method_status()
    app.processEvents()
    assert len(shown) == 2
    print("network-method-warning-ok")
finally:
    if window is not None:
        window.close()
    core._client_sync = None
    core.close()
    app.processEvents()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

_QT_UNACCEPTED_CONFIG_GATE_SCRIPT = r"""
import os
import sys
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from talon_core import TalonCoreSession
from talon_core.network.rns_config import default_reticulum_config
import talon_desktop.app as app_module
from talon_desktop.app import DesktopRuntime, LoginWindow, MainWindow

config_path = sys.argv[1]

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path).start()
runtime = DesktopRuntime(core, start_sync=True)
try:
    core.paths.rns_config_dir.mkdir(parents=True, exist_ok=True)
    (core.paths.rns_config_dir / "config").write_text(
        default_reticulum_config(core.mode),
        encoding="utf-8",
    )
    class FakeReticulumConfigDialog:
        def __init__(self, core, parent=None):
            self.core = core
            status = core.reticulum_config_status()
            assert status.exists is True
            assert status.accepted is False
            print("config-dialog-opened")
        def exec(self):
            self.core.save_reticulum_config_text(self.core.load_reticulum_config_text())
            print("config-dialog-accepted")
            return QtWidgets.QDialog.Accepted
    app_module.ReticulumConfigDialog = FakeReticulumConfigDialog
    def _start_reticulum():
        assert core.reticulum_config_status().accepted is True
        core._reticulum_started = True
    def _start_sync(*, init_reticulum=True):
        assert init_reticulum is False
    core.start_reticulum = _start_reticulum
    core.start_sync = _start_sync
    runtime.login_window = LoginWindow(core.mode)
    def _show_main(*, sync_warning=""):
        runtime.main_window = MainWindow(core, runtime.event_bridge)
    runtime.show_main = _show_main
    runtime.unlock("DesktopSmoke-1")
    deadline = time.time() + 15.0
    while time.time() < deadline:
        app.processEvents()
        if runtime.main_window is not None:
            print("unaccepted-config-gate-continued")
            break
        time.sleep(0.02)
    else:
        raise AssertionError(runtime.login_window.status_label.text())
finally:
    if runtime.main_window is not None:
        runtime.main_window.close()
    if runtime.login_window is not None:
        runtime.login_window.close()
    runtime.shutdown()
    app.processEvents()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

_QT_RETICULUM_CONFIG_BUTTONS_SCRIPT = r"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from talon_core import TalonCoreSession
from talon_desktop.reticulum_config_dialog import ReticulumConfigDialog

config_path = sys.argv[1]

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path).start()
dialog = None
try:
    core.unlock_with_key(bytes(range(32)))
    dialog = ReticulumConfigDialog(core)
    texts = sorted(
        button.text() for button in dialog.findChildren(QtWidgets.QPushButton)
    )
    print("|".join(texts))
finally:
    if dialog is not None:
        dialog.close()
    core.close()
    app.processEvents()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

_QT_SETTINGS_SMOKE_SCRIPT = r"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets

from talon_core import TalonCoreSession
from talon_desktop.app import MainWindow
from talon_desktop.qt_events import CoreEventBridge

config_path = sys.argv[1]
settings_path = sys.argv[4]

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path, mode="server").start()
first = None
second = None
try:
    core.unlock_with_key(bytes(range(32)))
    settings = QtCore.QSettings(settings_path, QtCore.QSettings.IniFormat)
    stale_horizontal_splitter = QtWidgets.QSplitter(QtCore.Qt.Horizontal)
    stale_horizontal_splitter.addWidget(QtWidgets.QLabel("Selection"))
    stale_horizontal_splitter.addWidget(QtWidgets.QLabel("Missions"))
    stale_horizontal_splitter.addWidget(QtWidgets.QLabel("SITREPs"))
    settings.setValue(
        "server/main_window/pages/map/splitters/0",
        stale_horizontal_splitter.saveState(),
    )
    first = MainWindow(core, CoreEventBridge(), settings=settings)
    assert first._pages["map"].right_panel_splitter.orientation() == QtCore.Qt.Vertical
    first._pages["map"].right_panel_splitter.setSizes([80, 320, 120])
    documents_row = None
    for index in range(first.nav.count()):
        if first.nav.item(index).data(QtCore.Qt.UserRole) == "documents":
            documents_row = index
            break
    assert documents_row is not None
    first.nav.setCurrentRow(documents_row)
    first._pages["assets"].table.setColumnWidth(1, 211)
    app.processEvents()
    first.close()
    app.processEvents()

    settings = QtCore.QSettings(settings_path, QtCore.QSettings.IniFormat)
    assert settings.value("server/main_window/last_section") == "documents"
    assert settings.value("server/main_window/geometry") is not None
    assert settings.value("server/main_window/splitters/main") is not None
    assert settings.value("server/main_window/pages/assets/tables/0") is not None
    assert settings.value("server/main_window/pages/map/splitters/0") is not None

    second = MainWindow(core, CoreEventBridge(), settings=settings)
    app.processEvents()
    assert second.nav.currentItem().data(QtCore.Qt.UserRole) == "documents"
    assert second._pages["assets"].table.columnWidth(1) == 211
    map_splitter_sizes = second._pages["map"].right_panel_splitter.sizes()
    assert second._pages["map"].right_panel_splitter.orientation() == QtCore.Qt.Vertical
    assert len(map_splitter_sizes) == 3
    assert map_splitter_sizes[1] > map_splitter_sizes[2]
    print("settings-ok")
finally:
    if second is not None:
        second.close()
    if first is not None:
        first.close()
    core.close()
    app.processEvents()
"""

_QT_WINDOW_BOUNDARY_SCRIPT = r"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets

from talon_core import TalonCoreSession
from talon_desktop.app import CurrentPageStack, MainWindow
from talon_desktop.qt_events import CoreEventBridge

config_path = sys.argv[1]
settings_path = sys.argv[4]

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path, mode="server").start()
first = None
second = None
try:
    core.unlock_with_key(bytes(range(32)))
    settings = QtCore.QSettings(settings_path, QtCore.QSettings.IniFormat)
    first = MainWindow(core, CoreEventBridge(), settings=settings)
    first.resize(2000, 1400)
    first.move(-300, -200)
    first.close()
    app.processEvents()

    second = MainWindow(core, CoreEventBridge(), settings=settings)
    assert isinstance(second.stack, CurrentPageStack)
    assert second.stack.minimumSizeHint() == second._pages["dashboard"].minimumSizeHint()
    assert second.stack.minimumSizeHint().height() < second._pages["sitreps"].minimumSizeHint().height()

    map_row = None
    for index in range(second.nav.count()):
        if second.nav.item(index).data(QtCore.Qt.UserRole) == "map":
            map_row = index
            break
    assert map_row is not None
    second.nav.setCurrentRow(map_row)
    app.processEvents()
    assert second.stack.minimumSizeHint() == second._pages["map"].minimumSizeHint()
    assert second.minimumSizeHint().height() < second._pages["sitreps"].minimumSizeHint().height()

    second.nav.setCurrentRow(0)
    second.show()
    app.processEvents()
    available = app.primaryScreen().availableGeometry()
    assert second.width() <= available.width()
    assert second.height() <= available.height()
    assert second.x() >= available.x()
    assert second.y() >= available.y()
    print("window-boundary-ok")
finally:
    if second is not None:
        second.close()
    if first is not None:
        first.close()
    core.close()
    app.processEvents()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

_QT_SITREP_COMPOSER_SWITCH_SCRIPT = r"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets

from talon_core import TalonCoreSession
from talon_desktop.app import CurrentPageStack, MainWindow
from talon_desktop.qt_events import CoreEventBridge
from talon_desktop.sitrep_page import SitrepCreateDialog, SitrepPage

config_path = sys.argv[1]
settings_path = sys.argv[4]

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
core = TalonCoreSession(config_path=config_path, mode="server").start()
window = None

def row_for(window, key):
    for index in range(window.nav.count()):
        if window.nav.item(index).data(QtCore.Qt.UserRole) == key:
            return index
    raise AssertionError(f"missing nav row {key}")

try:
    core.unlock_with_key(bytes(range(32)))
    long_body = "Lost dog found, coyote attack\n" + "\n".join(
        f"Detail line {index}: continued operational context for review."
        for index in range(40)
    )
    core.command(
        "sitreps.create",
        {
            "level": "FLASH",
            "body": long_body,
            "location_label": "North trail",
            "lat": 44.872081,
            "lon": -73.162733,
        },
    )
    settings = QtCore.QSettings(settings_path, QtCore.QSettings.IniFormat)
    window = MainWindow(core, CoreEventBridge(), settings=settings)
    window.show()
    app.processEvents()

    assert isinstance(window.stack, CurrentPageStack)
    assert window.stack.objectName() == "pageStack"

    sitrep_row = row_for(window, "sitreps")
    map_row = row_for(window, "map")
    window.nav.setCurrentRow(sitrep_row)
    app.processEvents()
    sitrep_page = window._pages["sitreps"]
    assert isinstance(sitrep_page, SitrepPage)
    assert window.stack.currentWidget() is sitrep_page
    assert not sitrep_page.isHidden()
    assert sitrep_page.new_button.text() == "New SITREP"
    assert not hasattr(sitrep_page, "template_combo")
    sitrep_page.refresh()
    app.processEvents()
    assert isinstance(sitrep_page.detail_body_field, QtWidgets.QTextEdit)
    assert sitrep_page.detail_body_field.isReadOnly()
    assert (
        sitrep_page.detail_body_field.verticalScrollBarPolicy()
        == QtCore.Qt.ScrollBarAsNeeded
    )
    assert "Detail line 39" in sitrep_page.detail_body_field.toPlainText()
    assert sitrep_page.detail_body_field.verticalScrollBar().maximum() > 0
    assert sitrep_page.append_button.isVisibleTo(sitrep_page)
    assert sitrep_page.assign_button.isVisibleTo(sitrep_page)
    assert not hasattr(sitrep_page, "ack_button")

    dialog = SitrepCreateDialog(core, parent=sitrep_page)
    dialog.show()
    app.processEvents()
    assert not hasattr(dialog, "template_combo")
    assert dialog.context_group.isCheckable()
    assert dialog.context_group.isChecked() is False
    dialog.body_field.setPlainText("Minimal report")
    assert dialog.payload() == {"level": "ROUTINE", "body": "Minimal report"}
    dialog.close()

    window.nav.setCurrentRow(map_row)
    app.processEvents()
    assert window.stack.currentWidget() is window._pages["map"]
    assert not window._pages["map"].isHidden()
    assert sitrep_page.isHidden()
    print("sitrep-composer-switch-ok")
finally:
    if window is not None:
        window.close()
    core.close()
    app.processEvents()
sys.stdout.flush()
sys.stderr.flush()
os._exit(0)
"""

_QT_PICKER_ZOOM_SCRIPT = r"""
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from talon_desktop.map_picker import DraftMapOverlay, MapCoordinateDialog
from talon_desktop.map_tiles import TILE_LAYERS_BY_KEY, build_tile_plan

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
dialog = MapCoordinateDialog(
    core=None,
    title="Picker",
    mode="point",
    draft_overlays=[
        DraftMapOverlay(
            label="Draft ICP",
            mode="point",
            points=((42.0, -71.0),),
        )
    ],
)
try:
    assert dialog._draft_overlays[0].label == "Draft ICP"
    assert any(item.toolTip() == "Draft ICP" for item in dialog._scene.items())
    before = dialog._bounds
    before_generation = dialog._tile_generation
    before_plan = build_tile_plan(TILE_LAYERS_BY_KEY["osm"], before)
    dialog._zoom_at_scene_point(500.0, 350.0, 480)
    after = dialog._bounds
    after_plan = build_tile_plan(TILE_LAYERS_BY_KEY["osm"], after)

    assert dialog._tile_generation == before_generation + 1
    assert after.max_lat - after.min_lat < before.max_lat - before.min_lat
    assert after.max_lon - after.min_lon < before.max_lon - before.min_lon
    assert after_plan.zoom >= before_plan.zoom
    assert dialog.view.transform().m11() > 0
    print("picker-zoom-refresh-ok")
finally:
    dialog.close()
    app.processEvents()
"""

_QT_MISSION_CREATE_EMBEDDED_MAP_SCRIPT = r"""
import os
import pathlib
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets

from talon_desktop.map_picker import MapCoordinateDialog
from talon_desktop.mission_page import MissionCreateDialog

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class FakeCore:
    mode = sys.argv[2]

    def __init__(self) -> None:
        self.paths = types.SimpleNamespace(data_dir=pathlib.Path(sys.argv[1]).parent)

    def read_model(self, name, filters=None):
        if name in {"assets.list", "operators.list"}:
            return []
        if name == "assignments.board":
            return {"assignments": []}
        if name == "map.context":
            return types.SimpleNamespace(
                assets=[],
                zones=[],
                waypoints=[],
                missions=[],
                assignments=[],
            )
        if name == "sitreps.list":
            return []
        raise KeyError(name)


dialog = MissionCreateDialog(FakeCore())
try:
    dialog.operation_window_enabled.setChecked(True)
    start = QtCore.QDateTime.fromString("2026-04-30 10:00", "yyyy-MM-dd HH:mm")
    dialog.operation_start_time.setDateTime(start)
    dialog.operation_end_time.setDateTime(start)
    try:
        dialog._operation_window_text()
    except ValueError as exc:
        assert "after start" in str(exc)
    else:
        raise AssertionError("Equal operation window endpoints should be rejected")
    dialog.operation_end_time.setDateTime(start.addSecs(60))
    assert dialog._operation_window_text() == (
        "2026-04-30 10:00 - 2026-04-30 10:01"
    )

    assert isinstance(dialog.map_picker, MapCoordinateDialog)
    assert not dialog.map_picker.isWindow()
    assert dialog.map_picker.cancel_button.isHidden()
    assert dialog.tabs.tabText(dialog.tabs.currentIndex()) == "Area / Route"
    legend = dialog.findChild(QtWidgets.QWidget, "missionIconLegend")
    assert legend is not None
    assert dialog._map_target is not None
    assert dialog._map_target[2] == "AO Polygon"
    dialog.ao_field.setPlainText(
        "40.000000, -75.000000\n"
        "40.010000, -75.000000\n"
        "40.010000, -75.010000"
    )
    app.processEvents()
    assert len(dialog.map_picker.selected_points) == 3

    dialog._draw_route()
    assert dialog._map_target[2] == "Route / Waypoints"
    assert not any(
        isinstance(widget, MapCoordinateDialog) and widget.isWindow()
        for widget in QtWidgets.QApplication.topLevelWidgets()
    )
    dialog.map_picker._add_point(40.1, -75.1)
    dialog._apply_map_selection()
    assert dialog.route_field.toPlainText() == "40.100000, -75.100000"

    dialog._pick_point(dialog.staging_area_field, "Staging Area")
    dialog.map_picker._add_point(40.2, -75.2)
    dialog._apply_map_selection()
    assert dialog.staging_area_field.text() == "40.200000, -75.200000"
    print("mission-create-embedded-map-ok")
finally:
    dialog.close()
    app.processEvents()
"""

_QT_MAP_TILE_RENDERER_SCRIPT = r"""
import logging
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtGui, QtNetwork, QtWidgets

from talon_desktop.map_data import DEFAULT_MAP_BOUNDS
from talon_desktop.map_scene_tiles import MapTileSceneRenderer, SHARED_TILE_PIXMAP_CACHE
from talon_desktop.map_tiles import TILE_LAYERS_BY_KEY, build_tile_plan

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
scene = QtWidgets.QGraphicsScene()
network = QtNetwork.QNetworkAccessManager()
renderer = MapTileSceneRenderer(
    scene=scene,
    network=network,
    user_agent="TALON test",
    logger=logging.getLogger("test.map_tiles"),
)
plan = build_tile_plan(TILE_LAYERS_BY_KEY["osm"], DEFAULT_MAP_BOUNDS)
tile = plan.requests[0]
pixmap = QtGui.QPixmap(16, 16)
pixmap.fill(QtGui.QColor("#123456"))
SHARED_TILE_PIXMAP_CACHE.put(tile.url, pixmap)

renderer.begin_frame()
renderer.request_tiles([tile])
first_items = [
    item for item in scene.items()
    if isinstance(item, QtWidgets.QGraphicsPixmapItem)
]
assert len(first_items) == 1
assert first_items[0].zValue() == -20

renderer.begin_frame()
stale_items = [
    item for item in scene.items()
    if isinstance(item, QtWidgets.QGraphicsPixmapItem)
]
assert len(stale_items) == 1
assert stale_items[0].zValue() == -25

renderer.request_tiles([tile])
current_items = [
    item for item in scene.items()
    if isinstance(item, QtWidgets.QGraphicsPixmapItem)
]
assert len(current_items) == 1
assert current_items[0].zValue() == -20
print("map-tile-renderer-retains-stale-ok")
"""

_QT_MAP_PANEL_SCRIPT = r"""
import os
import pathlib
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets

from talon_desktop.map_page import MapPage

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])

class FakeCore:
    mode = sys.argv[2]

    def __init__(self) -> None:
        self.paths = types.SimpleNamespace(data_dir=pathlib.Path(sys.argv[1]).parent)
        self.map_filters = []

    def read_model(self, name, filters=None):
        if name == "map.context":
            self.map_filters.append(dict(filters or {}))
            selected_mission_id = (filters or {}).get("mission_id")
            assets = [
                types.SimpleNamespace(
                    id=1,
                    label="Relay",
                    category="radio",
                    verified=True,
                    mission_id=7,
                    lat=39.953,
                    lon=-75.163,
                ),
                types.SimpleNamespace(
                    id=2,
                    label="Cache",
                    category="supply",
                    verified=False,
                    mission_id=None,
                    lat=40.5,
                    lon=-75.5,
                ),
            ]
            if selected_mission_id is not None:
                assets = [
                    asset for asset in assets
                    if asset.mission_id == selected_mission_id
                ]
            return types.SimpleNamespace(
                assets=assets,
                zones=[],
                waypoints=[],
                missions=[
                    types.SimpleNamespace(
                        id=7,
                        title="North Route",
                        status="active",
                    )
                ],
            )
        if name == "sitreps.list":
            selected_mission_id = (filters or {}).get("mission_id")
            sitreps = [
                types.SimpleNamespace(
                    id=9,
                    level="ROUTINE",
                    body="Comms check complete.",
                    asset_id=1,
                    mission_id=7,
                )
            ]
            if selected_mission_id is not None:
                sitreps = [
                    sitrep for sitrep in sitreps
                    if sitrep.mission_id == selected_mission_id
                ]
            return sitreps
        raise KeyError(name)

core = FakeCore()
page = MapPage(core)
try:
    page.refresh()
    assert page.left_panel.objectName() == "mapLeftPanel"
    assert page.right_panel.objectName() == "mapRightPanel"
    assert not page.left_panel.isHidden()
    assert not page.right_panel.isHidden()
    assert page.right_panel_splitter.orientation() == QtCore.Qt.Vertical
    assert page.right_panel_splitter.count() == 3
    assert page.asset_panel_list.count() == 2
    assert page.mission_panel_list.count() == 1
    assert page.sitrep_panel_list.count() == 1
    page._resize_scene(900.0, 500.0)
    scene_rect = page._scene.sceneRect()
    assert scene_rect.width() == 900.0
    assert scene_rect.height() == 500.0
    app.processEvents()
    before_bounds = page._view_bounds
    page.asset_panel_list.setCurrentRow(1)
    app.processEvents()
    after_bounds = page._view_bounds
    assert after_bounds.max_lat - after_bounds.min_lat < (
        before_bounds.max_lat - before_bounds.min_lat
    )
    assert after_bounds.max_lon - after_bounds.min_lon < (
        before_bounds.max_lon - before_bounds.min_lon
    )
    assert after_bounds.min_lat < 40.5 < after_bounds.max_lat
    assert after_bounds.min_lon < -75.5 < after_bounds.max_lon
    assert any(
        str(item.data(0)) == "asset:2"
        for item in page._scene.selectedItems()
    )

    page.mission_panel_list.setCurrentRow(0)
    app.processEvents()
    assert page.mission_filter.currentData() == 7
    assert core.map_filters[-1] == {"mission_id": 7}
    assert page.asset_panel_list.count() == 1
    assert page.asset_panel_list.item(0).text().startswith("Relay")
    mission_bounds = page._view_bounds
    assert mission_bounds.min_lat < 39.953 < mission_bounds.max_lat
    assert mission_bounds.min_lon < -75.163 < mission_bounds.max_lon

    page._toggle_panel("left")
    assert page.left_panel.isHidden()
    assert page.left_toggle.findChild(QtWidgets.QToolButton).text() == ">"
    page._toggle_panel("left")
    assert not page.left_panel.isHidden()

    page._toggle_panel("right")
    assert page.right_panel.isHidden()
    assert page.right_toggle.findChild(QtWidgets.QToolButton).text() == "<"
    page._toggle_panel("right")
    assert not page.right_panel.isHidden()

    print(f"map-panels-ok-{FakeCore.mode}")
finally:
    page.close()
    app.processEvents()
"""

_QT_DOCUMENT_EXPLORER_SCRIPT = r"""
import os
import pathlib
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtCore, QtWidgets

from talon_desktop.document_page import DocumentPage, DocumentTableWidget

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class FakeCore:
    mode = "server"

    def __init__(self) -> None:
        self.paths = types.SimpleNamespace(data_dir=pathlib.Path(sys.argv[1]).parent)
        self.commands = []
        self.documents = [
            types.SimpleNamespace(
                id=1,
                filename="alpha.txt",
                mime_type="text/plain",
                size_bytes=12,
                file_path="1.bin",
                sha256_hash="a" * 64,
                folder_path="Mission Files",
                description="Alpha",
                uploaded_by=1,
                uploaded_at=1_700_000_000,
                version=1,
            ),
            types.SimpleNamespace(
                id=2,
                filename="nested.txt",
                mime_type="text/plain",
                size_bytes=24,
                file_path="2.bin",
                sha256_hash="b" * 64,
                folder_path="Mission Files/Lost Dog",
                description="Nested",
                uploaded_by=1,
                uploaded_at=1_700_000_001,
                version=1,
            ),
        ]

    def read_model(self, name, filters=None):
        if name == "documents.list":
            return [
                types.SimpleNamespace(document=document, uploader_callsign="SERVER")
                for document in self.documents
            ]
        raise KeyError(name)

    def command(self, name, **kwargs):
        self.commands.append((name, dict(kwargs)))
        if name == "documents.move":
            doc = self._doc(kwargs["document_id"])
            doc.folder_path = kwargs["folder_path"]
            return types.SimpleNamespace(document=doc)
        if name == "documents.rename":
            doc = self._doc(kwargs["document_id"])
            doc.filename = kwargs["filename"]
            return types.SimpleNamespace(document=doc)
        if name == "documents.rename_folder":
            old = kwargs["folder_path"]
            new = kwargs["new_folder_path"]
            changed = []
            for doc in self.documents:
                if doc.folder_path == old or doc.folder_path.startswith(old + "/"):
                    suffix = doc.folder_path[len(old):].lstrip("/")
                    doc.folder_path = new if not suffix else f"{new}/{suffix}"
                    changed.append(doc)
            return types.SimpleNamespace(document=changed[0] if changed else None)
        if name == "documents.delete_folder":
            folder = kwargs["folder_path"]
            self.documents = [
                doc
                for doc in self.documents
                if doc.folder_path != folder and not doc.folder_path.startswith(folder + "/")
            ]
            return types.SimpleNamespace(document=None)
        raise KeyError(name)

    def _doc(self, document_id):
        for document in self.documents:
            if document.id == int(document_id):
                return document
        raise KeyError(document_id)


def folder_item(page, folder_path):
    iterator = QtWidgets.QTreeWidgetItemIterator(page.folder_tree)
    while iterator.value():
        item = iterator.value()
        if item.data(0, QtCore.Qt.UserRole) == folder_path:
            return item
        iterator += 1
    raise AssertionError(folder_path)


core = FakeCore()
page = DocumentPage(core)
try:
    page.refresh()
    assert isinstance(page.table, DocumentTableWidget)
    assert page.table.contextMenuPolicy() == QtCore.Qt.CustomContextMenu
    assert page.folder_tree.contextMenuPolicy() == QtCore.Qt.CustomContextMenu
    assert page.table.dragEnabled()
    assert page.folder_tree.acceptDrops()

    page._move_document_to_folder(1, "Archive")
    assert core._doc(1).folder_path == "Archive"
    assert core.commands[-1][0] == "documents.move"

    page._selected_folder_path = None
    page.refresh()
    page._select_document_id(1)
    row = page.table.selectionModel().selectedRows()[0].row()
    page.table.item(row, 0).setText("renamed-alpha.txt")
    app.processEvents()
    assert core._doc(1).filename == "renamed-alpha.txt"
    assert core.commands[-1][0] == "documents.rename"

    page._rename_folder_path("Archive", "Renamed Archive")
    assert core._doc(1).folder_path == "Renamed Archive"
    assert core.commands[-1][0] == "documents.rename_folder"

    page.folder_tree.setCurrentItem(folder_item(page, "Mission Files"))
    QtWidgets.QMessageBox.question = staticmethod(
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes
    )
    page._delete_selected_folder()
    assert all(not doc.folder_path.startswith("Mission Files") for doc in core.documents)
    assert core.commands[-1][0] == "documents.delete_folder"

    print("document-explorer-actions-ok")
finally:
    page.close()
    app.processEvents()
"""

_QT_ASSIGNMENT_CLOSEOUT_SCRIPT = r"""
import os
import pathlib
import sys
import types

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from talon_desktop.community_safety_page import AssignmentPage, CheckInDialog

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


class FakeCore:
    mode = "server"

    def __init__(self) -> None:
        self.paths = types.SimpleNamespace(data_dir=pathlib.Path(sys.argv[1]).parent)
        self.commands = []
        self.operators = [
            types.SimpleNamespace(id=8, callsign="ASTER", revoked=False, skills=["medic"], profile={}),
            types.SimpleNamespace(id=9, callsign="BRAVO", revoked=False, skills=["comms"], profile={}),
        ]
        self.assignments = [
            types.SimpleNamespace(
                id=42,
                title="North Shelter patrol",
                assignment_type="foot_patrol",
                status="active",
                priority="ROUTINE",
                team_lead="Aster",
                backup_operator="Sol",
                assigned_operator_ids=[8],
                last_checkin_at=None,
                last_checkin_state="",
                checkin_interval_min=20,
                overdue_threshold_min=5,
                created_at=1_700_000_000,
                support_reason="",
                location_label="North Shelter",
                lat=None,
                lon=None,
                mission_id=None,
                protected_label="",
                escalation_contact="",
                handoff_notes="",
            )
        ]

    def read_model(self, name, filters=None):
        if name == "assignments.board":
            return {
                "assignments": self.assignments,
                "operators": self.operators,
                "sync": types.SimpleNamespace(pending_outbox_count=0),
            }
        if name == "assignments.detail":
            return {
                "assignment": self.assignments[0],
                "checkins": [],
                "mission_title": "",
            }
        if name == "operators.list":
            return self.operators
        raise KeyError(name)

    def command(self, name, payload=None, **kwargs):
        data = dict(payload or {})
        data.update(kwargs)
        self.commands.append((name, data))
        if name == "assignments.update_status":
            self.assignments[0].status = data["status"]
            return types.SimpleNamespace(assignment_id=data["assignment_id"])
        if name == "assignments.checkin":
            return types.SimpleNamespace(checkin_id=5)
        raise KeyError(name)


core = FakeCore()
page = AssignmentPage(core)
try:
    page.refresh()
    assert page.checkin_button.text() == "Server Check-In"
    assert not page.closeout_button.isHidden()
    assert not page.abort_button.isHidden()

    dialog = CheckInDialog(
        page._items[0],
        operators=core.operators,
        allow_operator_choice=True,
    )
    try:
        assert dialog.operator_combo.count() == 2
        dialog.operator_combo.setCurrentIndex(1)
        payload = dialog.payload()
        assert payload["operator_id"] == 9
    finally:
        dialog.close()

    QtWidgets.QMessageBox.question = staticmethod(
        lambda *args, **kwargs: QtWidgets.QMessageBox.Yes
    )
    page._close_assignment("completed")
    assert core.assignments[0].status == "completed"
    assert core.commands[-1] == (
        "assignments.update_status",
        {"assignment_id": 42, "status": "completed"},
    )

    print("assignment-closeout-actions-ok")
finally:
    page.close()
    app.processEvents()
"""

_QT_ICON_RENDER_SCRIPT = r"""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6 import QtWidgets

from talon_core.assets import CATEGORY_LABEL
from talon_desktop.icons import asset_marker_pixmap, desktop_nav_icon
from talon_desktop.mission_icons import MISSION_LOCATION_ICON_KEYS, draw_mission_location_icon
from talon_desktop.navigation import navigation_items

app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
for item in navigation_items("server"):
    icon = desktop_nav_icon(item.key)
    assert not icon.isNull(), item.key
    assert not icon.pixmap(24, 24).isNull(), item.key

for category in CATEGORY_LABEL:
    verified = asset_marker_pixmap(category, verified=True)
    unverified = asset_marker_pixmap(category, verified=False)
    selected = asset_marker_pixmap(category, verified=False, selected=True)
    assert not verified.isNull(), category
    assert not unverified.isNull(), category
    assert not selected.isNull(), category

scene = QtWidgets.QGraphicsScene()
for index, key in enumerate(MISSION_LOCATION_ICON_KEYS):
    item = draw_mission_location_icon(scene, key, 24 + index * 30, 24)
    assert item.data(0) == key

print("icons-ok")
"""


def test_desktop_navigation_includes_documents_for_client_and_server() -> None:
    assert [item.key for item in navigation_items("server")] == [
        "map",
        "chat",
        "missions",
        "sitreps",
        "assets",
        "assignments",
        "documents",
        "operators",
        "enrollment",
        "clients",
        "audit",
        "keys",
        "dashboard",
    ]
    assert [item.key for item in navigation_items("client")] == [
        "map",
        "chat",
        "missions",
        "sitreps",
        "assets",
        "assignments",
        "documents",
        "operators",
        "dashboard",
    ]


def test_desktop_log_buffer_tracks_warning_count() -> None:
    buffer = DesktopLogBuffer()
    logger = logging.getLogger("talon.desktop.test")
    info_record = logger.makeRecord(
        logger.name,
        logging.INFO,
        __file__,
        1,
        "info message",
        (),
        None,
    )
    warning_record = logger.makeRecord(
        logger.name,
        logging.WARNING,
        __file__,
        2,
        "warning message",
        (),
        None,
    )

    buffer.handle(info_record)
    buffer.handle(warning_record)

    assert buffer.warning_count() == 1
    assert len(buffer.formatted_lines()) == 2
    assert "warning message" in buffer.formatted_lines()[-1]


def test_desktop_navigation_keeps_admin_sections_server_only() -> None:
    client_keys = {item.key for item in navigation_items("client")}
    server_keys = {item.key for item in navigation_items("server")}

    assert {"enrollment", "clients", "audit", "keys"}.isdisjoint(client_keys)
    assert {"enrollment", "clients", "audit", "keys"}.issubset(server_keys)


def test_desktop_custom_icons_cover_navigation_and_asset_categories() -> None:
    pytest.importorskip("PySide6")
    from talon_core.assets import CATEGORY_LABEL
    from talon_desktop.icons import (
        ASSET_ICON_CATEGORIES,
        NAV_ICON_KEYS,
    )

    assert {item.key for item in navigation_items("server")} <= NAV_ICON_KEYS
    assert set(CATEGORY_LABEL) <= ASSET_ICON_CATEGORIES

    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONPATH"] = str(pathlib.Path.cwd())
    result = subprocess.run(
        [sys.executable, "-c", _QT_ICON_RENDER_SCRIPT],
        cwd=pathlib.Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        timeout=20,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "icons-ok" in result.stdout


def test_desktop_event_mapping_refreshes_documents_section() -> None:
    update = desktop_update_from_event(record_changed("documents", 42))

    assert update.kind == "record_changed"
    assert update.refresh_sections == frozenset({"documents"})
    assert update.mutations[0].table == "documents"
    assert update.mutations[0].record_id == 42


def test_desktop_event_mapping_refreshes_sitrep_workflow_surfaces() -> None:
    followup_update = desktop_update_from_event(record_changed("sitrep_followups", 42))
    document_update = desktop_update_from_event(record_changed("sitrep_documents", 43))

    assert followup_update.refresh_sections == frozenset(
        {"dashboard", "map", "sitreps"}
    )
    assert document_update.refresh_sections == frozenset(
        {"dashboard", "documents", "map", "sitreps"}
    )


def test_desktop_community_safety_helpers() -> None:
    assignment = types.SimpleNamespace(
        id=7,
        title="North Shelter evening support",
        assignment_type="protective_detail",
        status="needs_support",
        priority="PRIORITY",
        team_lead="Aster",
        backup_operator="Sol",
        checkin_interval_min=20,
        overdue_threshold_min=5,
        created_at=1_700_000_000,
        last_checkin_state="need_backup",
        last_checkin_at=1_700_000_600,
        assigned_operator_ids=[2, 3],
        support_reason="Presence and de-escalation support",
        location_label="North Shelter",
    )
    item = assignment_item_from_assignment(assignment, now=1_700_000_700)
    assert item.type_label == "Protective detail"
    assert item.status_label == "Needs support"
    assert item.needs_support is True
    assert item.next_checkin_label == "Needs acknowledgement"

    assignment_payload = build_assignment_payload(
        assignment_type="foot_patrol",
        title="Oak Loop",
        assigned_operator_ids=[2],
        required_skills=["medic"],
        lat_text="40.123456",
        lon_text="-75.25",
    )
    assert assignment_payload["assignment_type"] == "foot_patrol"
    assert assignment_payload["assigned_operator_ids"] == [2]
    assert assignment_payload["lat"] == pytest.approx(40.123456)
    assert assignment_payload["lon"] == pytest.approx(-75.25)
    with pytest.raises(ValueError, match="Both latitude and longitude"):
        build_assignment_payload(
            assignment_type="foot_patrol",
            title="Oak Loop",
            lat_text="40.123456",
        )

    checkin_payload = build_checkin_payload(
        assignment_id=7,
        state="ok",
        note="All clear",
    )
    assert checkin_payload == {
        "assignment_id": 7,
        "state": "ok",
        "note": "All clear",
    }

def test_desktop_event_mapping_refreshes_asset_surfaces() -> None:
    update = desktop_update_from_event(record_changed("assets", 42))

    assert update.refresh_sections == frozenset({"assets", "dashboard", "map"})


def test_qt_smoke_constructs_main_window_offscreen(tmp_path: pathlib.Path) -> None:
    result = _run_qt_smoke(tmp_path, mode="server", navigate=False)

    assert "dashboard" in result.stdout
    assert "keys" in result.stdout


@pytest.mark.parametrize("mode", ("client", "server"))
def test_qt_smoke_navigates_every_desktop_section(
    tmp_path: pathlib.Path,
    mode: str,
) -> None:
    result = _run_qt_smoke(tmp_path, mode=mode, navigate=True)

    keys = result.stdout.strip().split("|")
    assert keys == [item.key for item in navigation_items(mode)]


@pytest.mark.parametrize(
    ("mode", "expected"),
    (("server", "server-main"), ("client", "client-enrollment")),
)
def test_qt_smoke_unlocks_desktop_runtime_paths(
    tmp_path: pathlib.Path,
    mode: str,
    expected: str,
) -> None:
    result = _run_qt_subprocess(
        _QT_UNLOCK_SMOKE_SCRIPT,
        tmp_path,
        mode=mode,
        extra_arg="unlock",
        timeout=30,
    )

    assert expected in result.stdout


def test_qt_client_unlock_surfaces_reticulum_start_failure(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_RETICULUM_FAILURE_SCRIPT,
        tmp_path,
        mode="client",
        extra_arg="reticulum-failure",
        timeout=30,
    )

    assert "reticulum-error-visible" in result.stdout


def test_qt_unlock_starts_reticulum_after_db_unlock(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_UNLOCK_ORDER_SCRIPT,
        tmp_path,
        mode="server",
        extra_arg="unlock-order",
        timeout=30,
    )

    assert "unlock-order-ok" in result.stdout


def test_qt_missing_reticulum_config_opens_setup_before_network_start(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_CONFIG_GATE_REJECT_SCRIPT,
        tmp_path,
        mode="client",
        extra_arg="config-gate-reject",
        timeout=30,
    )

    assert "config-dialog-opened" in result.stdout
    assert "config-gate-rejected" in result.stdout


def test_qt_client_network_setup_button_recovers_after_setup_reject(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_NETWORK_SETUP_RETRY_SCRIPT,
        tmp_path,
        mode="client",
        extra_arg="network-setup-retry",
        timeout=30,
    )

    assert "network-setup-retry-ok" in result.stdout


@pytest.mark.parametrize("mode", ("client", "server"))
def test_qt_main_window_network_setup_button_opens_setup(
    tmp_path: pathlib.Path,
    mode: str,
) -> None:
    result = _run_qt_subprocess(
        _QT_MAIN_NETWORK_SETUP_SCRIPT,
        tmp_path,
        mode=mode,
        extra_arg="main-network-setup",
        timeout=30,
    )

    assert f"main-network-setup-ok-{mode}" in result.stdout


def test_qt_network_method_badge_warns_for_each_direct_tcp_session(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_NETWORK_METHOD_WARNING_SCRIPT,
        tmp_path,
        mode="client",
        extra_arg="network-method-warning",
        timeout=30,
    )

    assert "network-method-warning-ok" in result.stdout


def test_qt_unaccepted_reticulum_config_opens_setup_before_network_start(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_UNACCEPTED_CONFIG_GATE_SCRIPT,
        tmp_path,
        mode="server",
        extra_arg="config-gate-unaccepted",
        timeout=30,
    )

    assert "config-dialog-opened" in result.stdout
    assert "config-dialog-accepted" in result.stdout
    assert "unaccepted-config-gate-continued" in result.stdout


def test_qt_reticulum_config_buttons_use_operator_transport_names(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_RETICULUM_CONFIG_BUTTONS_SCRIPT,
        tmp_path,
        mode="server",
        extra_arg="config-buttons",
        timeout=30,
    )

    assert "Yggdrasil Server" in result.stdout
    assert "Yggdrasil Client" in result.stdout
    assert "i2pd Server" in result.stdout
    assert "i2pd Client" in result.stdout


@pytest.mark.parametrize(
    ("mode", "expected"),
    (("server", "server-main"), ("client", "client-enrollment")),
)
def test_qt_saving_valid_reticulum_config_continues_startup(
    tmp_path: pathlib.Path,
    mode: str,
    expected: str,
) -> None:
    result = _run_qt_subprocess(
        _QT_CONFIG_GATE_CONTINUE_SCRIPT,
        tmp_path,
        mode=mode,
        extra_arg="config-gate-continue",
        timeout=30,
    )

    assert f"config-gate-continued-{expected}" in result.stdout


def test_qt_smoke_persists_desktop_window_and_view_settings(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_SETTINGS_SMOKE_SCRIPT,
        tmp_path,
        mode="server",
        extra_arg="settings",
        timeout=30,
    )

    assert "settings-ok" in result.stdout


def test_qt_main_window_stays_within_available_screen(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_WINDOW_BOUNDARY_SCRIPT,
        tmp_path,
        mode="server",
        extra_arg="window-boundary",
        timeout=30,
    )

    assert "window-boundary-ok" in result.stdout


def test_qt_sitrep_minimal_composer_and_page_switch_repaint(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_SITREP_COMPOSER_SWITCH_SCRIPT,
        tmp_path,
        mode="server",
        extra_arg="sitrep-composer-switch",
        timeout=30,
    )

    assert "sitrep-composer-switch-ok" in result.stdout


def test_qt_picker_zoom_refreshes_tiles_and_bounds(tmp_path: pathlib.Path) -> None:
    result = _run_qt_subprocess(
        _QT_PICKER_ZOOM_SCRIPT,
        tmp_path,
        mode="server",
        extra_arg="picker-zoom",
        timeout=30,
    )

    assert "picker-zoom-refresh-ok" in result.stdout


def test_qt_mission_create_uses_embedded_map_picker(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_MISSION_CREATE_EMBEDDED_MAP_SCRIPT,
        tmp_path,
        mode="server",
        extra_arg="mission-create-embedded-map",
        timeout=30,
    )

    assert "mission-create-embedded-map-ok" in result.stdout


def test_qt_map_tile_renderer_keeps_stale_tiles_until_replacement(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_MAP_TILE_RENDERER_SCRIPT,
        tmp_path,
        mode="server",
        extra_arg="map-tile-renderer",
        timeout=30,
    )

    assert "map-tile-renderer-retains-stale-ok" in result.stdout


@pytest.mark.parametrize("mode", ("client", "server"))
def test_qt_map_page_has_collapsible_side_panels(
    tmp_path: pathlib.Path,
    mode: str,
) -> None:
    result = _run_qt_subprocess(
        _QT_MAP_PANEL_SCRIPT,
        tmp_path,
        mode=mode,
        extra_arg="map-panels",
        timeout=30,
    )

    assert f"map-panels-ok-{mode}" in result.stdout


def test_qt_document_page_explorer_actions(tmp_path: pathlib.Path) -> None:
    result = _run_qt_subprocess(
        _QT_DOCUMENT_EXPLORER_SCRIPT,
        tmp_path,
        mode="server",
        extra_arg="document-explorer",
        timeout=30,
    )

    assert "document-explorer-actions-ok" in result.stdout


def test_qt_assignment_closeout_and_server_checkin_actions(
    tmp_path: pathlib.Path,
) -> None:
    result = _run_qt_subprocess(
        _QT_ASSIGNMENT_CLOSEOUT_SCRIPT,
        tmp_path,
        mode="server",
        extra_arg="assignment-closeout",
        timeout=30,
    )

    assert "assignment-closeout-actions-ok" in result.stdout


@pytest.mark.parametrize("mode", ("client", "server"))
def test_desktop_cli_package_smoke_exits_offscreen(
    tmp_path: pathlib.Path,
    mode: str,
) -> None:
    python = pathlib.Path(".venv/bin/python")
    if not python.exists():
        pytest.skip("Project venv Python is not available for PySide6 smoke tests.")
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONPATH"] = str(pathlib.Path.cwd())
    env["TALON_DESKTOP_SETTINGS_PATH"] = str(tmp_path / f"{mode}-cli-settings.ini")

    result = subprocess.run(
        [str(python), "-m", "talon_desktop", "--smoke", "--mode", mode],
        cwd=pathlib.Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert f"TALON_DESKTOP_SMOKE_OK {mode}" in result.stdout


def test_desktop_cli_exposes_package_loopback_smoke() -> None:
    from talon_desktop.main import build_parser

    args = build_parser().parse_args(["--loopback-smoke"])

    assert args.loopback_smoke is True


@pytest.mark.parametrize(
    ("mode", "enable_transport"),
    (("server", True), ("client", False)),
)
def test_loopback_smoke_accepts_temp_reticulum_config_after_unlock(
    tmp_path: pathlib.Path,
    mode: str,
    enable_transport: bool,
) -> None:
    from talon_core import TalonCoreSession
    from talon_core.network.rns_config import reticulum_acceptance_path
    from talon_desktop.main import (
        _accept_loopback_reticulum_config,
        _client_tcp_interface,
        _server_tcp_interface,
        _write_loopback_app_config,
        _write_rns_config,
    )

    config_path, rns_dir = _write_loopback_app_config(tmp_path, mode)
    stanza = (
        _server_tcp_interface(4242)
        if mode == "server"
        else _client_tcp_interface(4242)
    )
    _write_rns_config(rns_dir, stanza, enable_transport=enable_transport)
    core = TalonCoreSession(config_path=config_path, mode=mode).start()
    try:
        core.unlock_with_key(bytes(range(32)))
        assert core.reticulum_config_status().accepted is False

        _accept_loopback_reticulum_config(core)

        assert core.reticulum_config_status().accepted is True
        marker_text = reticulum_acceptance_path(rns_dir).read_text(encoding="utf-8")
        assert "version = 2" in marker_text
        assert f"mode = {mode}" in marker_text
        assert "hmac =" in marker_text
    finally:
        core.close()


def _run_qt_smoke(
    tmp_path: pathlib.Path,
    *,
    mode: str,
    navigate: bool,
) -> subprocess.CompletedProcess[str]:
    return _run_qt_subprocess(
        _QT_SMOKE_SCRIPT,
        tmp_path,
        mode=mode,
        extra_arg="navigate" if navigate else "construct",
        timeout=30,
    )


def _run_qt_subprocess(
    script: str,
    tmp_path: pathlib.Path,
    *,
    mode: str,
    extra_arg: str,
    timeout: int,
) -> subprocess.CompletedProcess[str]:
    python = pathlib.Path(".venv/bin/python")
    if not python.exists():
        pytest.skip("Project venv Python is not available for PySide6 smoke tests.")
    config_path = _write_desktop_config(tmp_path, mode)
    env = os.environ.copy()
    env.setdefault("QT_QPA_PLATFORM", "offscreen")
    env["PYTHONPATH"] = str(pathlib.Path.cwd())
    env["TALON_DESKTOP_SETTINGS_PATH"] = str(tmp_path / f"{mode}-desktop-settings.ini")
    result = subprocess.run(
        [
            str(python),
            "-c",
            script,
            str(config_path),
            mode,
            extra_arg,
            str(tmp_path / f"{mode}-desktop-settings.ini"),
        ],
        cwd=pathlib.Path.cwd(),
        env=env,
        text=True,
        capture_output=True,
        timeout=timeout,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return result


def _write_desktop_config(tmp_path: pathlib.Path, mode: str) -> pathlib.Path:
    data_dir = tmp_path / f"{mode}-data"
    rns_dir = tmp_path / f"{mode}-rns"
    documents_dir = tmp_path / f"{mode}-documents"
    config_path = tmp_path / f"{mode}.ini"
    config_path.write_text(
        "\n".join(
            [
                "[talon]",
                f"mode = {mode}",
                "",
                "[paths]",
                f"data_dir = {data_dir}",
                f"rns_config_dir = {rns_dir}",
                "",
                "[documents]",
                f"storage_path = {documents_dir}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path


def test_desktop_event_mapping_expands_linked_records() -> None:
    event = linked_records_changed(
        RecordMutation("changed", "assets", 1),
        RecordMutation("deleted", "missions", 2),
    )

    update = desktop_update_from_event(event)

    assert update.refresh_sections == frozenset({"assets", "dashboard", "map", "missions"})


def test_desktop_event_mapping_requests_lock_on_revocation() -> None:
    update = desktop_update_from_event(operator_revoked(7))

    assert update.lock_reason == "revoked"
    assert {"dashboard", "operators"}.issubset(update.refresh_sections)


def test_refresh_sections_for_events_combines_updates() -> None:
    sections = refresh_sections_for_events(
        (record_changed("documents", 1), record_changed("messages", 2))
    )

    assert sections == frozenset({"documents", "chat"})


def test_refresh_sections_for_network_table_refresh_events() -> None:
    from talon_core.services.events import ui_refresh_requested

    sections = refresh_sections_for_events(
        (ui_refresh_requested(ui_targets=("assets", "main")),)
    )

    assert sections == frozenset({"assets", "dashboard", "map"})


def test_map_tile_plan_builds_visible_osm_tiles() -> None:
    from talon_desktop.map_data import MapBounds

    bounds = MapBounds(min_lat=42.9, max_lat=43.2, min_lon=-71.3, max_lon=-71.0)
    plan = build_tile_plan(TILE_LAYERS_BY_KEY["osm"], bounds)

    assert plan.zoom >= 10
    assert 1 <= len(plan.requests) <= MAX_TILE_REQUESTS
    assert all(
        request.url.startswith("https://tile.openstreetmap.org/")
        for request in plan.requests
    )
    assert all(
        request.scene_width > 0 and request.scene_height > 0
        for request in plan.requests
    )


def test_map_tile_plan_covers_custom_scene_without_internal_margin() -> None:
    from talon_desktop.map_data import MapBounds

    scene_width = 1218.0
    scene_height = 852.0
    bounds = MapBounds(min_lat=42.9, max_lat=43.2, min_lon=-71.3, max_lon=-71.0)

    plan = build_tile_plan(
        TILE_LAYERS_BY_KEY["osm"],
        bounds,
        scene_width=scene_width,
        scene_height=scene_height,
        scene_margin=0.0,
    )

    assert min(request.scene_x for request in plan.requests) <= 0.0
    assert min(request.scene_y for request in plan.requests) <= 0.0
    assert max(
        request.scene_x + request.scene_width for request in plan.requests
    ) >= scene_width
    assert max(
        request.scene_y + request.scene_height for request in plan.requests
    ) >= scene_height


def test_map_tile_layers_expose_required_base_maps() -> None:
    assert {"osm", "topo", "satellite"}.issubset(TILE_LAYERS_BY_KEY)
    assert "openmaps.fr/opentopomap" in TILE_LAYERS_BY_KEY["topo"].url(
        zoom=4,
        x=1,
        y=2,
    )
    assert (
        "World_Imagery/MapServer/tile/4/2/1"
        in TILE_LAYERS_BY_KEY["satellite"].url(
            zoom=4,
            x=1,
            y=2,
        )
    )


def test_map_scene_projection_uses_web_mercator_bounds() -> None:
    from talon_desktop.map_data import MapBounds

    bounds = MapBounds(min_lat=40.0, max_lat=45.0, min_lon=-75.0, max_lon=-70.0)
    x, y = scene_point_for_lat_lon(bounds, 42.5, -72.5)

    assert 48.0 < x < 952.0
    assert 48.0 < y < 652.0


def test_legacy_target_mapping_can_refresh_main_desktop_surfaces() -> None:
    assert desktop_sections_for_legacy_targets({"main"}) == frozenset(
        {"dashboard", "map"}
    )
    assert section_for_key("documents").label == "Documents"


def test_pyproject_does_not_expose_active_kivy_dependencies() -> None:
    tomllib = pytest.importorskip("tomllib")
    project = tomllib.loads(pathlib.Path("pyproject.toml").read_text(encoding="utf-8"))

    base_deps = set(project["project"]["dependencies"])
    optional_deps = project["project"]["optional-dependencies"]
    desktop_deps = set(optional_deps["desktop"])
    all_optional_deps = {
        dep
        for deps in optional_deps.values()
        for dep in deps
    }

    assert "legacy-kivy" not in optional_deps
    assert not any(dep.startswith("kivy") for dep in base_deps | all_optional_deps)
    assert not any(dep.startswith("kivymd") for dep in base_deps | all_optional_deps)
    assert not any("mapview" in dep.lower() for dep in base_deps | all_optional_deps)
    assert "PySide6>=6.7" in desktop_deps


def test_sitrep_create_payload_strips_body_and_keeps_links() -> None:
    payload = build_create_payload(
        level="FLASH",
        body="  Bridge blocked  ",
        template="contact",
        asset_id=12,
        mission_id=34,
    )

    assert payload == {
        "level": "FLASH",
        "body": "Bridge blocked",
        "template": "contact",
        "asset_id": 12,
        "mission_id": 34,
    }


def test_sitrep_create_payload_supports_location_and_filters() -> None:
    payload = build_create_payload(
        level="PRIORITY",
        body="  Welfare team needs support  ",
        assignment_id=9,
        location_label="North Gate",
        lat_text="40.123456",
        lon_text="-75.25",
        location_precision="exact",
        location_source="map",
    )

    assert payload["assignment_id"] == 9
    assert payload["location_label"] == "North Gate"
    assert payload["lat"] == 40.123456
    assert payload["lon"] == -75.25
    assert payload["location_precision"] == "exact"
    assert payload["location_source"] == "map"
    assert build_filter_payload(
        level_filter="PRIORITY",
        status_filter="open",
        unresolved_only=True,
        has_location=True,
        pending_sync_only=True,
        assignment_id=9,
    ) == {
        "level_filter": "PRIORITY",
        "status_filter": "open",
        "unresolved_only": True,
        "has_location": True,
        "pending_sync_only": True,
        "assignment_id": 9,
    }


def test_sitrep_create_payload_rejects_empty_body() -> None:
    with pytest.raises(ValueError, match="body is required"):
        build_create_payload(level="ROUTINE", body="   ")
    with pytest.raises(ValueError, match="Both latitude and longitude"):
        build_create_payload(level="ROUTINE", body="Located", lat_text="40.0")


def test_sitrep_templates_are_valid_and_include_free_text_default() -> None:
    keys = {template.key for template in SITREP_TEMPLATES}

    assert DEFAULT_TEMPLATE_KEY in keys
    assert sitrep_template_for_key(DEFAULT_TEMPLATE_KEY).body == ""
    assert len(keys) == len(SITREP_TEMPLATES)
    for template in SITREP_TEMPLATES:
        assert template.label
        assert template.level in SITREP_LEVELS
        if template.key != DEFAULT_TEMPLATE_KEY:
            assert "Location:" in template.body


def test_sitrep_audio_policy_is_flash_only_and_opt_in() -> None:
    assert should_play_audio("FLASH", True) is True
    assert should_play_audio("FLASH_OVERRIDE", True) is True
    assert should_play_audio("FLASH", False) is False
    assert should_play_audio("IMMEDIATE", True) is False


def test_sitrep_feed_item_normalizes_core_tuple() -> None:
    sitrep = types.SimpleNamespace(
        id=5,
        level="IMMEDIATE",
        body=b"Need transport",
        mission_id=8,
        asset_id=13,
        assignment_id=7,
        status="assigned",
        assigned_to="Team Bravo",
        location_label="North Gate",
        lat=40.0,
        lon=-75.0,
        location_source="device",
        created_at=123456,
    )

    item = feed_item_from_entry((sitrep, "ALPHA", "Truck"))

    assert item.id == 5
    assert item.level == "IMMEDIATE"
    assert item.body == "Need transport"
    assert item.callsign == "ALPHA"
    assert item.asset_label == "Truck"
    assert item.assignment_id == 7
    assert item.status == "assigned"
    assert item.has_location is True
    assert item.needs_attention is True
    assert severity_counts([item])["IMMEDIATE"] == 1

    routine = types.SimpleNamespace(
        id=6,
        level="ROUTINE",
        body="Status normal",
        mission_id=None,
        asset_id=None,
        status="closed",
        created_at=123457,
    )
    assert feed_item_from_entry((routine, "ALPHA", None)).needs_attention is False


def test_sitrep_available_operator_items_excludes_assigned_work() -> None:
    operators = [
        types.SimpleNamespace(id=1, callsign="SERVER", revoked=False, skills=[]),
        types.SimpleNamespace(id=2, callsign="ALPHA", revoked=False, skills=["medic"]),
        types.SimpleNamespace(id=3, callsign="BRAVO", revoked=False, skills=["comms"]),
        types.SimpleNamespace(id=4, callsign="CHARLIE", revoked=True, skills=[]),
        types.SimpleNamespace(id=5, callsign="DELTA", revoked=False, skills=[]),
    ]
    assignments = [
        types.SimpleNamespace(
            status="active",
            assigned_operator_ids=[2],
        )
    ]
    sitreps = [
        (
            types.SimpleNamespace(
                id=10,
                status="assigned",
                assigned_to="BRAVO",
            ),
            "ALPHA",
            None,
        ),
        (
            types.SimpleNamespace(
                id=11,
                status="assigned",
                assigned_to="DELTA",
            ),
            "ALPHA",
            None,
        ),
    ]

    available = available_operator_items(
        operators,
        assignments=assignments,
        sitreps=sitreps,
        current_sitrep_id=11,
    )

    assert [item.callsign for item in available] == ["DELTA"]
    assert available[0].skills == ()


def test_asset_create_payload_validates_and_normalizes_fields() -> None:
    payload = build_asset_create_payload(
        category="cache",
        label="  North Cache  ",
        description="  Dry box  ",
        lat_text="40.123456",
        lon_text="-75.25",
    )

    assert payload == {
        "category": "cache",
        "label": "North Cache",
        "description": "Dry box",
        "lat": 40.123456,
        "lon": -75.25,
    }


def test_asset_payload_rejects_invalid_coordinates() -> None:
    with pytest.raises(ValueError, match="Both latitude and longitude"):
        build_asset_create_payload(
            category="cache",
            label="Cache",
            description="",
            lat_text="40.0",
            lon_text="",
        )
    with pytest.raises(ValueError, match="Latitude"):
        build_asset_create_payload(
            category="cache",
            label="Cache",
            description="",
            lat_text="100",
            lon_text="20",
        )


def test_asset_update_payload_keeps_asset_id_and_optional_location() -> None:
    payload = build_asset_update_payload(
        asset_id=9,
        label="Relay",
        description="Updated",
        lat_text="",
        lon_text="",
    )

    assert payload == {
        "asset_id": 9,
        "label": "Relay",
        "description": "Updated",
        "lat": None,
        "lon": None,
    }


def test_asset_item_and_verification_policy() -> None:
    asset = types.SimpleNamespace(
        id=3,
        category="vehicle",
        label="Truck",
        description="",
        lat=None,
        lon=None,
        verified=False,
        created_by=7,
        confirmed_by=None,
        mission_id=None,
        deletion_requested=True,
    )

    item = item_from_asset(asset)

    assert item.category_label == "Vehicle"
    assert item.deletion_requested is True
    assert can_verify_asset(mode="server", operator_id=7, asset_created_by=7) is True
    assert can_verify_asset(mode="client", operator_id=7, asset_created_by=7) is False
    assert can_verify_asset(mode="client", operator_id=8, asset_created_by=7) is True


def test_map_overlays_project_assets_zones_routes_and_sitreps() -> None:
    asset = types.SimpleNamespace(
        id=1,
        label="Cache",
        category="cache",
        verified=True,
        mission_id=9,
        lat=40.0,
        lon=-75.0,
    )
    zone = types.SimpleNamespace(
        id=2,
        label="AO",
        zone_type="AO",
        mission_id=9,
        polygon=[[39.9, -75.1], [40.1, -75.1], [40.1, -74.9]],
    )
    waypoints = [
        types.SimpleNamespace(
            id=3,
            label="Start",
            sequence=1,
            mission_id=9,
            lat=39.95,
            lon=-75.05,
        ),
        types.SimpleNamespace(
            id=4,
            label="End",
            sequence=2,
            mission_id=9,
            lat=40.05,
            lon=-74.95,
        ),
    ]
    mission = types.SimpleNamespace(
        id=9,
        title="Route Mission",
        staging_area="40.030000, -75.020000",
        demob_point="",
        key_locations={"medical": "40.040000, -75.010000"},
    )
    assignment = types.SimpleNamespace(
        id=6,
        title="North Gate watch",
        assignment_type="fixed_post",
        status="needs_support",
        priority="PRIORITY",
        last_checkin_state="need_backup",
        lat=40.02,
        lon=-75.03,
    )
    sitrep = types.SimpleNamespace(
        id=5,
        level="FLASH",
        body=b"At cache",
        asset_id=1,
        assignment_id=None,
        mission_id=9,
    )
    native_sitrep = types.SimpleNamespace(
        id=6,
        level="PRIORITY",
        body="Need support",
        asset_id=None,
        assignment_id=6,
        mission_id=9,
        status="acknowledged",
        location_label="North Gate",
        location_source="map",
        lat=40.02,
        lon=-75.03,
    )
    context = types.SimpleNamespace(
        assets=[asset],
        zones=[zone],
        waypoints=waypoints,
        missions=[mission],
        assignments=[assignment],
    )

    overlays = build_map_overlays(context, sitrep_entries=[sitrep, native_sitrep])

    assert overlays.assets[0].label == "Cache"
    assert overlays.assignments[0].title == "North Gate watch"
    assert overlays.zones[0].label == "AO"
    assert overlays.routes[0].mission_label == "Route Mission"
    assert [item.key for item in overlays.mission_locations] == ["staging_area", "medical"]
    assert [point.id for point in overlays.waypoints] == [3, 4]
    assert overlays.sitreps[0].body == "At cache"
    assert overlays.sitreps[0].point == overlays.assets[0].point
    assert overlays.sitreps[1].assignment_id == 6
    assert overlays.sitreps[1].location_source == "map"
    assert overlays.sitreps[1].point.lat == pytest.approx(40.02)


def test_map_projection_keeps_coordinates_inside_scene() -> None:
    context = types.SimpleNamespace(
        assets=[
            types.SimpleNamespace(
                id=1,
                label="A",
                category="cache",
                verified=False,
                mission_id=None,
                lat=10.0,
                lon=20.0,
            ),
            types.SimpleNamespace(
                id=2,
                label="B",
                category="cache",
                verified=False,
                mission_id=None,
                lat=11.0,
                lon=21.0,
            ),
        ],
        zones=[],
        waypoints=[],
        missions=[],
    )
    overlays = build_map_overlays(context)
    point = project_lat_lon(overlays.bounds, 10.5, 20.5)

    assert 0 <= point.x <= 1000
    assert 0 <= point.y <= 700


def test_map_auto_bounds_match_scene_aspect() -> None:
    context = types.SimpleNamespace(
        assets=[
            types.SimpleNamespace(
                id=1,
                label="West",
                category="team",
                verified=True,
                mission_id=None,
                lat=40.0,
                lon=-90.0,
            ),
            types.SimpleNamespace(
                id=2,
                label="East",
                category="team",
                verified=True,
                mission_id=None,
                lat=40.2,
                lon=-70.0,
            ),
        ],
        zones=[],
        waypoints=[],
        missions=[],
        assignments=[],
    )
    overlays = build_map_overlays(
        context,
        scene_width=1200.0,
        scene_height=600.0,
        scene_margin=0.0,
    )
    from talon_desktop.map_tiles import world_pixel

    left, top = world_pixel(overlays.bounds.max_lat, overlays.bounds.min_lon, 20)
    right, bottom = world_pixel(overlays.bounds.min_lat, overlays.bounds.max_lon, 20)
    assert ((right - left) / (bottom - top)) == pytest.approx(2.0, rel=0.02)


def test_map_projection_round_trips_scene_points() -> None:
    context = types.SimpleNamespace(
        assets=[
            types.SimpleNamespace(
                id=1,
                label="Relay",
                category="radio",
                verified=True,
                mission_id=None,
                lat=39.953,
                lon=-75.163,
            ),
        ],
        zones=[],
        waypoints=[],
        missions=[],
    )
    overlays = build_map_overlays(context)
    x, y = scene_point_for_lat_lon(overlays.bounds, 39.953, -75.163)
    lat, lon = lat_lon_for_scene_point(overlays.bounds, x, y)

    assert lat == pytest.approx(39.953, abs=0.000001)
    assert lon == pytest.approx(-75.163, abs=0.000001)


def test_map_projection_round_trips_custom_scene_size() -> None:
    from talon_desktop.map_data import MapBounds

    bounds = MapBounds(min_lat=39.0, max_lat=41.0, min_lon=-76.0, max_lon=-74.0)
    x, y = scene_point_for_lat_lon(
        bounds,
        39.953,
        -75.163,
        scene_width=1218.0,
        scene_height=852.0,
        scene_margin=0.0,
    )
    lat, lon = lat_lon_for_scene_point(
        bounds,
        x,
        y,
        scene_width=1218.0,
        scene_height=852.0,
        scene_margin=0.0,
    )

    assert 0.0 <= x <= 1218.0
    assert 0.0 <= y <= 852.0
    assert lat == pytest.approx(39.953, abs=0.000001)
    assert lon == pytest.approx(-75.163, abs=0.000001)


def test_map_wheel_zoom_bounds_request_higher_resolution_tiles() -> None:
    context = types.SimpleNamespace(
        assets=[
            types.SimpleNamespace(
                id=1,
                label="Relay",
                category="radio",
                verified=True,
                mission_id=None,
                lat=39.953,
                lon=-75.163,
            ),
        ],
        zones=[],
        waypoints=[],
        missions=[],
    )
    overlays = build_map_overlays(context)
    base_plan = build_tile_plan(TILE_LAYERS_BY_KEY["osm"], overlays.bounds)
    zoomed_bounds = zoom_bounds_around_scene_point(overlays.bounds, 500.0, 350.0, 8.0)
    zoomed_plan = build_tile_plan(TILE_LAYERS_BY_KEY["osm"], zoomed_bounds)
    zoomed_overlays = build_map_overlays(context, bounds=zoomed_bounds)

    assert zoomed_bounds.max_lat - zoomed_bounds.min_lat < (
        overlays.bounds.max_lat - overlays.bounds.min_lat
    )
    assert zoomed_bounds.max_lon - zoomed_bounds.min_lon < (
        overlays.bounds.max_lon - overlays.bounds.min_lon
    )
    assert zoomed_plan.zoom > base_plan.zoom
    assert 0 <= zoomed_overlays.assets[0].point.x <= 1000
    assert 0 <= zoomed_overlays.assets[0].point.y <= 700


def test_map_pan_bounds_follow_drag_direction() -> None:
    from talon_desktop.map_data import MapBounds

    before = MapBounds(min_lat=40.0, max_lat=45.0, min_lon=-75.0, max_lon=-70.0)
    after = pan_bounds_by_scene_delta(before, 100.0, 100.0)

    assert after.min_lon < before.min_lon
    assert after.max_lon < before.max_lon
    assert after.min_lat > before.min_lat
    assert after.max_lat > before.max_lat
    assert (after.max_lat - after.min_lat) == pytest.approx(
        before.max_lat - before.min_lat,
        rel=0.02,
    )


def test_mission_create_payload_parses_assets_ao_and_route() -> None:
    payload = build_mission_create_payload(
        title="  Cache Sweep  ",
        description="  Verify caches  ",
        asset_ids=[2, "3"],
        mission_type="search",
        priority="IMMEDIATE",
        lead_coordinator="ALPHA",
        organization="Team 1",
        ao_text="40.0, -75.0\n40.1, -75.0\n40.1, -74.9",
        route_text="40.0 -75.0\n40.1 -74.9",
        activation_time="2026-04-28 10:00",
        operation_window="0800-1800",
        max_duration="8h",
        staging_area="40.000000, -75.000000",
        demob_point="40.100000, -74.900000",
        standdown_criteria="All caches verified",
        phases=[{"name": "Ingress", "objective": "Reach cache", "duration": "1h"}],
        constraints=["Two-person teams"],
        support_medical="Aid station",
        support_logistics="Fuel",
        support_comms="Repeater",
        support_equipment="Generator",
        custom_resources=[{"label": "Water", "details": "20 gal"}],
        objectives=[{"label": "Primary", "criteria": "Cache verified"}],
        key_locations={"command_post": "40.000000, -75.000000", "empty": ""},
    )

    assert payload["title"] == "Cache Sweep"
    assert payload["description"] == "Verify caches"
    assert payload["asset_ids"] == [2, 3]
    assert payload["priority"] == "IMMEDIATE"
    assert payload["ao_polygon"] == [[40.0, -75.0], [40.1, -75.0], [40.1, -74.9]]
    assert payload["route"] == [(40.0, -75.0), (40.1, -74.9)]
    assert payload["activation_time"] == "2026-04-28 10:00"
    assert payload["phases"] == [
        {"name": "Ingress", "objective": "Reach cache", "duration": "1h"}
    ]
    assert payload["constraints"] == ["Two-person teams"]
    assert payload["custom_resources"] == [{"label": "Water", "details": "20 gal"}]
    assert payload["objectives"] == [{"label": "Primary", "criteria": "Cache verified"}]
    assert payload["key_locations"] == {"command_post": "40.000000, -75.000000"}


def test_mission_payload_rejects_invalid_title_priority_and_geometry() -> None:
    with pytest.raises(ValueError, match="title"):
        build_mission_create_payload(
            title=" ",
            description="",
            asset_ids=[],
        )
    with pytest.raises(ValueError, match="priority"):
        build_mission_create_payload(
            title="Mission",
            description="",
            asset_ids=[],
            priority="BAD",
        )
    with pytest.raises(ValueError, match="AO polygon"):
        build_mission_create_payload(
            title="Mission",
            description="",
            asset_ids=[],
            ao_text="40,-75\n41,-75",
        )


def test_mission_coordinate_parser_and_server_actions() -> None:
    assert parse_coordinate_lines(
        "40,-75\n41,-76",
        label="Route",
        minimum_points=1,
        empty_ok=False,
    ) == [(40.0, -75.0), (41.0, -76.0)]
    assert server_actions_for_status("pending_approval") == (
        "approve",
        "reject",
        "abort",
        "delete",
    )
    assert server_actions_for_status("active") == ("complete", "abort", "delete")


def test_mission_item_normalizes_status_label() -> None:
    mission = types.SimpleNamespace(
        id=8,
        title="Cache Sweep",
        description="",
        status="pending_approval",
        priority="PRIORITY",
        mission_type="search",
        created_by=1,
    )

    item = item_from_mission(mission)

    assert item.id == 8
    assert item.status_label == "Pending Approval"


def test_chat_channel_helpers_normalize_names_and_delete_policy() -> None:
    default_channel = types.SimpleNamespace(
        id=1,
        name="#flash",
        mission_id=None,
        is_dm=False,
        group_type="emergency",
    )
    dm_channel = types.SimpleNamespace(
        id=2,
        name="dm:1:7",
        mission_id=None,
        is_dm=True,
        group_type="direct",
    )

    default_item = item_from_channel(default_channel)
    dm_item = item_from_channel(dm_channel, operator_lookup={1: "SERVER", 7: "ALPHA"})

    assert default_item.display_name == "#flash"
    assert default_item.group_label == "Emergency"
    assert default_item.is_default is True
    assert dm_item.display_name == "DM SERVER / ALPHA"
    assert build_create_channel_payload(" ops ") == {"name": "ops"}
    assert can_delete_channel("server", default_item) is False
    assert can_delete_channel("server", dm_item) is True
    assert can_delete_channel("client", dm_item) is False


def test_chat_message_payload_and_item_preserve_urgent_grid_state() -> None:
    payload = build_message_payload(
        channel_id=4,
        body="  Move now  ",
        is_urgent=True,
        grid_ref=" 18T WL 000 000 ",
    )
    message = types.SimpleNamespace(
        id=9,
        channel_id=4,
        sender_id=7,
        body=b"Move now",
        sent_at=123456,
        is_urgent=True,
        grid_ref="18T WL 000 000",
    )

    item = item_from_message((message, "ALPHA"))

    assert payload == {
        "channel_id": 4,
        "body": "Move now",
        "is_urgent": True,
        "grid_ref": "18T WL 000 000",
    }
    assert item.callsign == "ALPHA"
    assert item.body == "Move now"
    assert item.is_urgent is True
    assert item.grid_ref == "18T WL 000 000"
    assert can_delete_message("server", item) is True
    assert can_delete_message("client", item) is False


def test_chat_grid_reference_items_are_built_from_map_context() -> None:
    context = types.SimpleNamespace(
        assets=[
            types.SimpleNamespace(
                id=1,
                label="Cache",
                category="cache",
                lat=40.1234567,
                lon=-75.25,
            ),
            types.SimpleNamespace(
                id=2,
                label="No Location",
                category="vehicle",
                lat=None,
                lon=None,
            ),
        ],
        waypoints=[
            types.SimpleNamespace(
                id=3,
                label="Rally",
                mission_id=9,
                sequence=2,
                lat=40.5,
                lon=-75.5,
            )
        ],
        zones=[
            types.SimpleNamespace(
                id=4,
                label="AO",
                zone_type="OBJECTIVE",
                polygon=[[40.0, -75.0], [40.0, -74.0], [41.0, -74.0]],
            )
        ],
    )
    sitrep = types.SimpleNamespace(id=5, level="ROUTINE", asset_id=1)
    native_sitrep = types.SimpleNamespace(
        id=6,
        level="PRIORITY",
        asset_id=None,
        lat=40.75,
        lon=-75.75,
    )

    items = grid_reference_items_from_context(context, sitrep_entries=[sitrep, native_sitrep])
    references = {item.reference for item in items}

    assert "ASSET Cache 40.123457, -75.250000" in references
    assert "WAYPOINT Rally 40.500000, -75.500000" in references
    assert "ZONE AO 40.333333, -74.333333" in references
    assert "SITREP ROUTINE #5 40.123457, -75.250000" in references
    assert "SITREP PRIORITY #6 40.750000, -75.750000" in references
    assert all("No Location" not in item.reference for item in items)


def test_chat_payload_helpers_reject_invalid_inputs() -> None:
    with pytest.raises(ValueError, match="Channel name"):
        build_create_channel_payload("   ")
    with pytest.raises(ValueError, match="Message body"):
        build_message_payload(channel_id=1, body="   ")
    with pytest.raises(ValueError, match="yourself"):
        build_dm_payload(current_operator_id=7, peer_operator_id=7)


def test_document_upload_payload_reads_file_and_strips_description(tmp_path: pathlib.Path) -> None:
    path = tmp_path / "brief.txt"
    path.write_bytes(b"field notes")

    payload = build_document_upload_payload(
        path,
        description="  daily brief  ",
        folder_path="Plans/Day 1",
    )

    assert payload == {
        "raw_filename": "brief.txt",
        "file_data": b"field notes",
        "description": "daily brief",
        "folder_path": "Plans/Day 1",
    }


def test_document_item_and_policy_helpers() -> None:
    document = types.SimpleNamespace(
        id=12,
        filename="status.docm",
        mime_type="application/vnd.ms-word.document.macroEnabled.12",
        size_bytes=2048,
        description="Macro-capable briefing",
        folder_path="Plans/Day 1",
        uploaded_by=1,
        uploaded_at=1_700_000_000,
        sha256_hash="abcdef1234567890abcdef1234567890",
    )
    entry = types.SimpleNamespace(document=document, uploader_callsign="SERVER")

    item = item_from_document_entry(entry)

    assert item.filename == "status.docm"
    assert item.size_label == "2.0 KB"
    assert item.uploader_callsign == "SERVER"
    assert item.folder_path == "Plans/Day 1"
    assert item.hash_preview == "abcdef1234567890abcdef12..."
    assert item.is_macro_risk is True
    assert is_macro_risk_filename("brief.xlsx") is True
    assert is_macro_risk_filename("brief.txt") is False
    assert can_upload_document("server") is True
    assert can_upload_document("client") is False
    assert can_download_document(item) is True
    assert can_delete_document("server", item) is True
    assert can_delete_document("client", item) is False


def test_document_error_messages_are_operator_facing() -> None:
    from talon_core.documents import (
        DocumentBlockedExtension,
        DocumentIntegrityError,
        DocumentSizeExceeded,
    )

    assert document_error_message(DocumentSizeExceeded("too large")).startswith(
        "File too large"
    )
    assert document_error_message(DocumentBlockedExtension("blocked")).startswith(
        "File type not allowed"
    )
    assert document_error_message(DocumentIntegrityError("bad hash")).startswith(
        "Integrity check failed"
    )


def test_operator_item_status_and_policy_helpers() -> None:
    operator = types.SimpleNamespace(
        id=2,
        callsign="ALPHA",
        rns_hash="abcdef1234567890abcdef",
        skills=["medic", "comms"],
        profile={"display_name": "Alpha One", "role": "lead", "notes": "night team"},
        enrolled_at=100,
        lease_expires_at=4_600,
        revoked=False,
    )
    item = item_from_operator(operator, now=1_000)

    assert item.callsign == "ALPHA"
    assert item.rns_preview == "abcdef1234567890..."
    assert item.skills_label == "medic, comms"
    assert item.status == "active"
    assert item.status_label == "OK (1h)"
    assert item.display_name == "Alpha One"
    assert can_edit_operator(mode="server", current_operator_id=1, item=item) is True
    assert can_edit_operator(mode="client", current_operator_id=2, item=item) is True
    assert can_edit_operator(mode="client", current_operator_id=3, item=item) is False
    assert can_renew_operator("server", item) is True
    assert can_revoke_operator("server", item) is True

    locked = item_from_operator(
        types.SimpleNamespace(
            **{**operator.__dict__, "id": 3, "lease_expires_at": 999}
        ),
        now=1_000,
    )
    revoked = item_from_operator(
        types.SimpleNamespace(
            **{**operator.__dict__, "id": 4, "revoked": True}
        ),
        now=1_000,
    )

    assert locked.status == "locked"
    assert revoked.status == "revoked"
    assert can_revoke_operator("server", revoked) is False


def test_operator_update_payload_normalizes_profile_and_skills() -> None:
    payload = build_operator_update_payload(
        operator_id=7,
        display_name="  Alpha One  ",
        role="  Lead  ",
        notes="  North route  ",
        selected_skills=["medic", "comms"],
        custom_skills_text=" Medic, drone\nlogistics ",
    )

    assert payload == {
        "operator_id": 7,
        "skills": ["medic", "comms", "drone", "logistics"],
        "profile": {
            "display_name": "Alpha One",
            "role": "Lead",
            "notes": "North route",
        },
    }


def test_enrollment_and_audit_helpers_format_admin_rows() -> None:
    token = types.SimpleNamespace(
        token="a" * 64,
        created_at=1_000,
        expires_at=1_600,
        used_at=None,
        operator_id=None,
    )
    entry = types.SimpleNamespace(
        id=9,
        event="operator_revoked",
        payload={"operator_id": 7, "callsign": "ALPHA"},
        occurred_at=2_000,
    )

    token_item = item_from_enrollment_token(token, now=1_000)
    audit_item = item_from_audit_entry(entry)

    assert token_item.token_preview == ("a" * 32) + "..."
    assert token_item.remaining_label == "10 min"
    assert audit_item.payload_label == "callsign=ALPHA  operator_id=7"
    assert audit_item.severity == "danger"
    assert audit_severity("lease_renewed") == "positive"
