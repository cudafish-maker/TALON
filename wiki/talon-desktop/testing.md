# Desktop Testing

Desktop tests should cover source behavior, package behavior, and operator
acceptance workflows.

## Current Legacy Test Baseline

- Last recorded full local run: `pytest -q` with 199 passed on 2026-04-25.
- Targeted Linux installer launcher tests passed on 2026-04-26.
- Legacy packaged smoke reached `TalonApp started` locally, but user launch still
  failed on the real target session.

## Latest PySide6 Shell Verification

- 2026-04-27: `pytest -q` passed, 262 passed and 1 skipped after replacing the
  last active `talon.app`/Kivy event test with PySide6 core event bridge
  coverage. The skipped test is PySide6-gated for non-desktop local Python
  environments; desktop CI installs `.[dev,desktop]` and runs it.
- 2026-04-27: `.venv/bin/python -c "from PySide6 import QtCore; ..."` verified
  `CoreEventBridge` emits a documents refresh signal in the PySide6 venv.
- 2026-04-27: `pytest -q tests/test_attribution_flows.py` passed, 3 tests after
  retiring Kivy screen imports from active attribution coverage.
- 2026-04-27: `pytest -q tests/test_desktop_shell.py -k pyproject` passed,
  confirming active project dependency extras no longer expose
  Kivy/KivyMD/mapview.
- 2026-04-27: `pytest -q` passed, 267 tests after removing the legacy Kivy
  build workflow and replacing active Kivy attribution tests with core command
  attribution tests.
- 2026-04-27: `bash -n build/install-talon-desktop.sh` passed after
  role-specific Linux artifact installer wiring.
- 2026-04-27: `pytest -q tests/test_linux_installer.py` passed, 11 tests after
  adding PySide6 client/server artifact installer coverage.
- 2026-04-27: local role split packaging from existing
  `dist/talon-desktop-linux/` produced `talon-desktop-client-linux.tar.gz` and
  `talon-desktop-server-linux.tar.gz`; no-bin/no-desktop install smoke passed
  for both artifacts.
- 2026-04-27: `pytest -q` passed, 267 tests after Linux role artifact split
  installer and workflow updates.
- 2026-04-27: `python -m py_compile talon_desktop/sitreps.py
  talon_desktop/sitrep_page.py talon_desktop/app.py talon_desktop/theme.py
  tests/test_desktop_shell.py` passed after SITREP template and dashboard
  overlay wiring.
- 2026-04-27: `pytest -q tests/test_desktop_shell.py -k sitrep` passed, 6
  tests.
- 2026-04-27: `pytest -q tests/test_desktop_shell.py` passed, 43 tests.
- 2026-04-27: `pytest -q` passed, 258 tests.
- 2026-04-26: `python -m py_compile talon_desktop/__init__.py
  talon_desktop/__main__.py talon_desktop/navigation.py talon_desktop/events.py
  talon_desktop/qt_events.py talon_desktop/main.py talon_desktop/app.py` passed.
- 2026-04-26: `pytest -q tests/test_desktop_shell.py` passed, 7 tests.
- 2026-04-26: `pytest -q` passed, 219 tests.
- 2026-04-26: `python -m py_compile talon_desktop/sitreps.py
  talon_desktop/sitrep_page.py talon_desktop/app.py tests/test_desktop_shell.py`
  passed.
- 2026-04-26: `pytest -q tests/test_desktop_shell.py` passed, 12 tests.
- 2026-04-26: `pytest -q tests/test_desktop_shell.py tests/test_core_session.py
  tests/test_audio_alerts.py` passed, 31 tests.
- 2026-04-26: `.venv/bin/python -m pip install -e ".[desktop]" --dry-run`
  passed and did not resolve Kivy/KivyMD.
- 2026-04-26: `pytest -q` passed, 226 tests.
- 2026-04-26: `pytest -q tests/test_core_session.py tests/test_sync.py
  tests/test_desktop_shell.py` passed, 65 tests after dashboard/sync-status
  read-model wiring.
- 2026-04-26: `python -m py_compile talon_desktop/assets.py
  talon_desktop/asset_page.py talon_desktop/app.py tests/test_desktop_shell.py`
  passed.
- 2026-04-26: `pytest -q tests/test_desktop_shell.py tests/test_core_session.py`
  passed, 29 tests after Assets page wiring.
- 2026-04-26: `pytest -q` passed, 231 tests after Assets page wiring.
- 2026-04-26: `python -m py_compile talon_desktop/map_data.py
  talon_desktop/map_page.py talon_desktop/app.py tests/test_desktop_shell.py`
  passed.
- 2026-04-26: `pytest -q tests/test_desktop_shell.py tests/test_map_data.py
  tests/test_core_session.py` passed, 35 tests after Map page wiring.
- 2026-04-26: `pytest -q` passed, 233 tests after Map page wiring.
- 2026-04-26: `python -m py_compile talon_desktop/missions.py
  talon_desktop/mission_page.py talon_desktop/app.py tests/test_desktop_shell.py`
  passed.
- 2026-04-26: `pytest -q tests/test_desktop_shell.py tests/test_services.py
  tests/test_core_session.py` passed, 44 tests after Missions page wiring.
- 2026-04-26: `pytest -q` passed, 237 tests after Missions page wiring.
- 2026-04-26: `python -m py_compile talon_desktop/chat.py
  talon_desktop/chat_page.py talon_desktop/app.py tests/test_desktop_shell.py`
  passed.
- 2026-04-26: `pytest -q tests/test_desktop_shell.py
  tests/test_core_session.py` passed, 38 tests after Chat page wiring.
- 2026-04-26: `pytest -q` passed, 240 tests after Chat page wiring.
- 2026-04-26: `.venv/bin/python -m py_compile talon_desktop/documents.py
  talon_desktop/document_page.py talon_desktop/app.py tests/test_desktop_shell.py`
  passed.
- 2026-04-26: `pytest -q tests/test_desktop_shell.py
  tests/test_core_session.py tests/test_documents.py` passed, 44 tests after
  Documents page wiring.
- 2026-04-26: `pytest -q` passed, 243 tests after Documents page wiring.
- 2026-04-26: `.venv/bin/python -m py_compile talon_desktop/operators.py
  talon_desktop/operator_page.py talon_desktop/chat_page.py talon_desktop/app.py
  tests/test_desktop_shell.py` passed.
- 2026-04-26: `.venv/bin/python -c "from talon_desktop.operator_page import
  OperatorPage, EnrollmentPage, AuditPage, KeysPage"` passed.
- 2026-04-26: `pytest -q tests/test_desktop_shell.py tests/test_core_session.py`
  passed, 44 tests after Operators/server admin wiring.
- 2026-04-26: `pytest -q` passed, 246 tests after Operators/server admin
  wiring.
- 2026-04-26: `pytest -q tests/test_desktop_shell.py` passed, 35 tests after
  adding offscreen Qt main-window construction and navigation smoke tests.
- 2026-04-26: `pytest -q` passed, 249 tests after Desktop Testing checklist
  completion.
- 2026-04-26: `pytest -q tests/test_desktop_shell.py` passed, 37 tests after
  adding offscreen client/server desktop runtime unlock smoke tests.
- 2026-04-26: same-machine Reticulum TCP loopback smoke passed with
  `RNS_LOOPBACK_SMOKE_OK`; the run covered server token generation, client
  enrollment, and client receipt of a server-created asset through sync.
- 2026-04-26: `pytest -q tests/test_protocol.py` passed, 28 tests after
  Reticulum hash-length enrollment validation hardening.
- 2026-04-26: `pytest -q` passed, 252 tests after Linux Breakpoint A
  development-shell verification.
- 2026-04-26: `pytest -q tests/test_desktop_shell.py` passed, 39 tests after
  adding the package-smoke CLI path.
- 2026-04-26: `pytest -q` passed, 254 tests after PySide6 Linux package smoke
  wiring.
- 2026-04-27: `pytest -q tests/test_desktop_shell.py tests/test_protocol.py`
  passed, 68 tests after adding package-level Reticulum loopback smoke.
- 2026-04-27: `pytest -q` passed, 255 tests after Linux Breakpoint B package
  loopback completion.
- 2026-04-26: `.venv/bin/pyinstaller --clean --noconfirm
  build/pyinstaller-linux-desktop.spec` produced
  `dist/talon-desktop-linux/`.
- 2026-04-26: Packaged executable smoke passed for server and client:
  `QT_QPA_PLATFORM=offscreen dist/talon-desktop-linux/talon-desktop --smoke
  --mode server` and `--mode client`.
- 2026-04-27: `dist/talon-desktop-linux.tar.gz` was rebuilt with SHA-256
  `1f4a5f25557150069399d2a8cc433593677365317f4767bf94e9248e1f960e14`; an
  extracted tarball installer smoke passed with `--no-deps --no-bin
  --no-desktop --smoke-test`.
- 2026-04-27: Manual target Linux Mint package validation confirmed install and
  launch without the old Kivy/SDL/GLX startup failure.
- 2026-04-27: The packaged artifact and an extracted installed package passed
  `talon-desktop --loopback-smoke`, covering server startup, token generation,
  client enrollment, and server-to-client asset sync over Reticulum TCP
  loopback.
- 2026-04-27: `python -m py_compile talon_desktop/theme.py talon_desktop/app.py
  talon_desktop/asset_page.py talon_desktop/document_page.py
  talon_desktop/mission_page.py talon_desktop/operator_page.py` passed after
  PySide6 theme polish.
- 2026-04-27: `pytest -q tests/test_desktop_shell.py` passed, 40 tests after
  centralized PySide6 dark theme and left navigation rail polish.
- 2026-04-27: `pytest -q` passed, 255 tests after PySide6 desktop theme polish.
- 2026-04-27: `python -m py_compile talon_desktop/settings.py
  talon_desktop/app.py talon_desktop/main.py tests/test_desktop_shell.py`
  passed after durable desktop settings wiring.
- 2026-04-27: `pytest -q tests/test_desktop_shell.py` passed, 41 tests after
  adding durable desktop settings for geometry, splitters, table layouts, and
  last selected section.
- 2026-04-27: `pytest -q` passed, 256 tests after durable desktop settings
  wiring.
- 2026-04-27: `python -m py_compile talon_desktop/logs.py
  talon_desktop/log_view.py talon_desktop/app.py talon_desktop/main.py
  talon_desktop/theme.py tests/test_desktop_shell.py` passed after adding the
  desktop log-view affordance.
- 2026-04-27: `pytest -q tests/test_desktop_shell.py` passed, 42 tests after
  adding the desktop session log buffer and status-bar Logs affordance.
- 2026-04-27: `pytest -q` passed, 257 tests after desktop log-view affordance
  wiring.

## PySide6 Acceptance

- Launch server mode on Linux.
- Launch client mode on Linux.
- Unlock/login and lock/revocation flow.
- Enroll client with `TOKEN:SERVER_HASH`.
- Bidirectional sync and offline outbox push.
- Assets, SITREPs, missions, chat, documents, map overlays.
- Server admin enrollment, clients, leases, revocation, audit.
- Package install and launcher run on target Linux Mint.
- Manual server and client acceptance from the packaged Linux artifact.
- Paired enrollment and sync acceptance on target Linux systems.
- Windows package validation after the Linux server/client release candidate is
  accepted.

## Automation Targets

- Core API tests stay in `talon-core`.
- Desktop adapter tests cover event to Qt signal routing.
- UI smoke tests verify navigation reaches every major function, especially
  Documents.
