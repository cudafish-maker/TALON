"""Tests for the Linux release installer."""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest


pytestmark = pytest.mark.skipif(
    sys.platform.startswith("win") or shutil.which("bash") is None,
    reason="Linux installer tests require bash",
)

REPO_ROOT = Path(__file__).resolve().parents[1]
INSTALLER = REPO_ROOT / "build" / "install-talon.sh"
DESKTOP_INSTALLER = REPO_ROOT / "build" / "install-talon-desktop.sh"
DELETE_PHRASE = "DELETE TALON DATA"


def _fake_bundle(tmp_path: Path, talon_script: str) -> Path:
    bundle = tmp_path / "talon-linux"
    internal = bundle / "_internal"
    (internal / "kivy" / "data").mkdir(parents=True)
    (internal / "kivymd").mkdir(parents=True)
    (internal / "base_library.zip").write_bytes(b"")
    (internal / "kivy" / "data" / "style.kv").write_text("", encoding="utf-8")
    (internal / "kivymd" / "icon_definitions.py").write_text(
        "md_icons = {}\n",
        encoding="utf-8",
    )

    talon = bundle / "talon"
    talon.write_text(talon_script, encoding="utf-8")
    talon.chmod(talon.stat().st_mode | stat.S_IXUSR)
    return bundle


def _install_bundle(tmp_path: Path, bundle: Path) -> None:
    install_env = os.environ.copy()
    install_env["XDG_STATE_HOME"] = str(tmp_path / "state")

    subprocess.run(
        [
            "bash",
            str(INSTALLER),
            "--no-deps",
            "--no-desktop",
            "--mode",
            "client",
            "--prefix",
            str(tmp_path / "install"),
            "--bin-dir",
            str(tmp_path / "bin"),
            "--config",
            str(tmp_path / "config" / "talon.ini"),
            "--data-dir",
            str(tmp_path / "data"),
            str(bundle),
        ],
        check=True,
        env=install_env,
        text=True,
        capture_output=True,
    )


def test_installed_launcher_retries_with_detected_x11_visual(tmp_path):
    attempts_log = tmp_path / "attempts.log"
    bundle = _fake_bundle(
        tmp_path,
        """#!/usr/bin/env sh
printf 'visual:%s:%s\\n' "${SDL_VIDEO_X11_VISUALID:-unset}" "${SDL_VIDEO_X11_WINDOW_VISUALID:-unset}" >> "$TALON_ATTEMPTS"
if [ "${SDL_VIDEO_X11_WINDOW_VISUALID:-}" = "0x022" ]; then
  printf 'visual fallback ok\\n'
  exit 0
fi
printf '%s\\n' "sdl2 - RuntimeError: b\\"Couldn't find matching GLX visual\\"" >&2
exit 1
""",
    )
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    glxinfo = fake_bin / "glxinfo"
    glxinfo.write_text(
        """#!/usr/bin/env sh
cat <<'OUT'
GLX Visuals
  visual  x   bf lv rg d st  colorbuffer  sr ax dp st accumbuffer  ms  cav
 id dep cl sp  sz l  ci b ro  r  g  b  a F gb bf th cl  r  g  b  a ns b eat
----------------------------------------------------------------------------
0x022 24 tc  0 24  0 r  y  .  8  8  8  0 .  .  0 16  0  0  0  0  0  0 0 None
GLXFBConfigs:
OUT
""",
        encoding="utf-8",
    )
    glxinfo.chmod(glxinfo.stat().st_mode | stat.S_IXUSR)

    _install_bundle(tmp_path, bundle)

    env = os.environ.copy()
    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["TALON_ATTEMPTS"] = str(attempts_log)
    result = subprocess.run(
        [str(tmp_path / "bin" / "talon")],
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "retrying X11 with GLX visual 0x022" in result.stderr
    assert "visual fallback ok" in result.stdout
    assert attempts_log.read_text(encoding="utf-8").splitlines() == [
        "visual:unset:unset",
        "visual:0x022:0x022",
    ]


def test_installed_launcher_retries_glx_failure_with_egl(tmp_path):
    attempts_log = tmp_path / "attempts.log"
    bundle = _fake_bundle(
        tmp_path,
        """#!/usr/bin/env sh
printf 'attempt:%s\\n' "${SDL_VIDEO_X11_FORCE_EGL:-0}" >> "$TALON_ATTEMPTS"
if [ "${SDL_VIDEO_X11_FORCE_EGL:-}" = "1" ]; then
  printf 'fallback ok\\n'
  exit 0
fi
printf '%s\\n' "sdl2 - RuntimeError: b\\"Couldn't find matching GLX visual\\"" >&2
exit 1
""",
    )

    _install_bundle(tmp_path, bundle)

    env = os.environ.copy()
    env["TALON_ATTEMPTS"] = str(attempts_log)
    result = subprocess.run(
        [str(tmp_path / "bin" / "talon")],
        env=env,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0
    assert "TALON: SDL/GLX startup failed; retrying X11 with EGL." in result.stderr
    assert "fallback ok" in result.stdout
    attempts = attempts_log.read_text(encoding="utf-8").splitlines()
    assert attempts[0] == "attempt:0"
    assert attempts[-1] == "attempt:1"


def _fake_desktop_bundle(tmp_path: Path, role: str) -> Path:
    bundle = tmp_path / f"talon-desktop-{role}-linux-source"
    internal = bundle / "_internal"
    internal.mkdir(parents=True)
    (internal / "base_library.zip").write_bytes(b"")
    (bundle / ".talon-artifact-role").write_text(f"{role}\n", encoding="utf-8")

    app = bundle / "talon-desktop"
    app.write_text(
        """#!/usr/bin/env sh
printf 'desktop:%s:%s\\n' "$TALON_CONFIG" "$*"
exit 0
""",
        encoding="utf-8",
    )
    app.chmod(app.stat().st_mode | stat.S_IXUSR)
    return bundle


def _desktop_env(tmp_path: Path) -> dict[str, str]:
    env = os.environ.copy()
    env["HOME"] = str(tmp_path / "home")
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg-data")
    env["XDG_STATE_HOME"] = str(tmp_path / "xdg-state")
    return env


def _run_desktop_install(
    tmp_path: Path,
    bundle: Path,
    *extra_args: str,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    install_env = env or _desktop_env(tmp_path)
    return subprocess.run(
        [
            "bash",
            str(DESKTOP_INSTALLER),
            "--no-deps",
            "--prefix",
            str(tmp_path / "install"),
            "--bin-dir",
            str(tmp_path / "bin"),
            str(bundle),
            *extra_args,
        ],
        check=check,
        env=install_env,
        text=True,
        capture_output=True,
    )


def test_desktop_client_artifact_installs_only_client_launcher_and_entry(tmp_path):
    env = _desktop_env(tmp_path)
    _run_desktop_install(tmp_path, _fake_desktop_bundle(tmp_path, "client"), env=env)

    assert (tmp_path / "bin" / "talon-desktop-client").is_file()
    assert not (tmp_path / "bin" / "talon-desktop").exists()
    assert not (tmp_path / "bin" / "talon-desktop-server").exists()
    entry = tmp_path / "xdg-data" / "applications" / "talon-desktop-client.desktop"
    assert entry.is_file()
    text = entry.read_text(encoding="utf-8")
    assert "Name=T.A.L.O.N. Client" in text
    assert f"Exec={tmp_path / 'bin' / 'talon-desktop-client'}" in text
    assert not (tmp_path / "xdg-data" / "applications" / "talon-desktop.desktop").exists()
    assert not (tmp_path / "xdg-data" / "applications" / "talon-desktop-server.desktop").exists()
    assert (tmp_path / "home" / ".talon" / "talon.ini").is_file()
    assert "mode = client" in (tmp_path / "home" / ".talon" / "talon.ini").read_text(encoding="utf-8")
    rns_config = tmp_path / "home" / ".talon" / "reticulum" / "config"
    assert rns_config.is_file()
    rns_text = rns_config.read_text(encoding="utf-8")
    assert "enable_transport = False" in rns_text
    assert "share_instance = No" in rns_text
    launcher = (tmp_path / "bin" / "talon-desktop-client").read_text(encoding="utf-8")
    assert f"export TALON_CONFIG='{tmp_path / 'home' / '.talon' / 'talon.ini'}'" in launcher


def test_desktop_server_artifact_installs_only_server_launcher_and_entry(tmp_path):
    env = _desktop_env(tmp_path)
    _run_desktop_install(tmp_path, _fake_desktop_bundle(tmp_path, "server"), env=env)

    assert (tmp_path / "bin" / "talon-desktop-server").is_file()
    assert not (tmp_path / "bin" / "talon-desktop").exists()
    assert not (tmp_path / "bin" / "talon-desktop-client").exists()
    entry = tmp_path / "xdg-data" / "applications" / "talon-desktop-server.desktop"
    assert entry.is_file()
    text = entry.read_text(encoding="utf-8")
    assert "Name=T.A.L.O.N. Server" in text
    assert f"Exec={tmp_path / 'bin' / 'talon-desktop-server'}" in text
    assert (tmp_path / "home" / ".talon-server" / "talon.ini").is_file()
    assert "mode = server" in (tmp_path / "home" / ".talon-server" / "talon.ini").read_text(encoding="utf-8")
    rns_config = tmp_path / "home" / ".talon-server" / "reticulum" / "config"
    assert rns_config.is_file()
    rns_text = rns_config.read_text(encoding="utf-8")
    assert "enable_transport = True" in rns_text
    assert "share_instance = No" in rns_text


def test_desktop_installer_rejects_mode_option(tmp_path):
    result = _run_desktop_install(
        tmp_path,
        _fake_desktop_bundle(tmp_path, "client"),
        "--mode",
        "server",
        check=False,
    )

    assert result.returncode != 0
    assert "--mode is not supported" in result.stderr


def test_desktop_same_role_reinstall_preserves_config_without_confirmation(tmp_path):
    env = _desktop_env(tmp_path)
    bundle = _fake_desktop_bundle(tmp_path, "client")
    _run_desktop_install(tmp_path, bundle, env=env)
    config = tmp_path / "home" / ".talon" / "talon.ini"
    rns_config = tmp_path / "home" / ".talon" / "reticulum" / "config"
    config.write_text("custom-client-config\n", encoding="utf-8")
    rns_config.write_text("custom-rns-config\n", encoding="utf-8")

    _run_desktop_install(tmp_path, bundle, env=env)

    assert config.read_text(encoding="utf-8") == "custom-client-config\n"
    assert rns_config.read_text(encoding="utf-8") == "custom-rns-config\n"


def test_desktop_opposite_role_install_fails_without_confirmation(tmp_path):
    env = _desktop_env(tmp_path)
    _run_desktop_install(tmp_path, _fake_desktop_bundle(tmp_path, "client"), env=env)

    result = _run_desktop_install(
        tmp_path,
        _fake_desktop_bundle(tmp_path, "server"),
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "Destructive role switch requires" in result.stderr
    assert (tmp_path / "home" / ".talon" / "talon.ini").exists()


def test_desktop_opposite_role_install_rejects_invalid_confirmation(tmp_path):
    env = _desktop_env(tmp_path)
    _run_desktop_install(tmp_path, _fake_desktop_bundle(tmp_path, "client"), env=env)

    result = _run_desktop_install(
        tmp_path,
        _fake_desktop_bundle(tmp_path, "server"),
        "--confirm-delete",
        "yes",
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "Invalid destructive confirmation phrase" in result.stderr
    assert (tmp_path / "home" / ".talon" / "talon.ini").exists()


def test_desktop_yes_does_not_authorize_role_switch_deletion(tmp_path):
    env = _desktop_env(tmp_path)
    _run_desktop_install(tmp_path, _fake_desktop_bundle(tmp_path, "client"), env=env)

    result = _run_desktop_install(
        tmp_path,
        _fake_desktop_bundle(tmp_path, "server"),
        "--yes",
        env=env,
        check=False,
    )

    assert result.returncode != 0
    assert "Destructive role switch requires" in result.stderr
    assert (tmp_path / "home" / ".talon" / "talon.ini").exists()


def test_desktop_confirmed_role_switch_deletes_previous_talon_footprint(tmp_path):
    env = _desktop_env(tmp_path)
    _run_desktop_install(tmp_path, _fake_desktop_bundle(tmp_path, "client"), env=env)
    home = tmp_path / "home"
    state = tmp_path / "xdg-state" / "talon"
    legacy_bundle = tmp_path / "install" / "talon-desktop-linux"
    legacy_bundle.mkdir()
    legacy_launcher = tmp_path / "bin" / "talon-desktop"
    legacy_launcher.write_text("legacy\n", encoding="utf-8")
    legacy_entry = tmp_path / "xdg-data" / "applications" / "talon-desktop.desktop"
    legacy_entry.write_text("legacy\n", encoding="utf-8")
    (home / ".talon" / "talon.db").write_text("client-db\n", encoding="utf-8")
    (home / ".talon" / "reticulum" / "identity").write_text("rns\n", encoding="utf-8")
    (home / ".talon" / "documents" / "doc.txt").write_text("doc\n", encoding="utf-8")
    (state / "old.log").write_text("log\n", encoding="utf-8")

    _run_desktop_install(
        tmp_path,
        _fake_desktop_bundle(tmp_path, "server"),
        "--confirm-delete",
        DELETE_PHRASE,
        env=env,
    )

    assert not (home / ".talon").exists()
    assert not legacy_bundle.exists()
    assert not legacy_launcher.exists()
    assert not legacy_entry.exists()
    assert not (tmp_path / "bin" / "talon-desktop-client").exists()
    assert not (tmp_path / "xdg-data" / "applications" / "talon-desktop-client.desktop").exists()
    assert (tmp_path / "bin" / "talon-desktop-server").exists()
    assert (home / ".talon-server" / "talon.ini").exists()
    assert not (state / "old.log").exists()


def test_desktop_profile_and_config_permissions_are_restricted(tmp_path):
    env = _desktop_env(tmp_path)
    _run_desktop_install(tmp_path, _fake_desktop_bundle(tmp_path, "server"), env=env)

    profile = tmp_path / "home" / ".talon-server"
    config = profile / "talon.ini"
    assert stat.S_IMODE(profile.stat().st_mode) == 0o700
    assert stat.S_IMODE((profile / "reticulum").stat().st_mode) == 0o700
    assert stat.S_IMODE((profile / "documents").stat().st_mode) == 0o700
    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE((profile / "reticulum" / "config").stat().st_mode) == 0o600
