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
