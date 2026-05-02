"""Tests for the Linux release installer."""

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from talon_core import TalonCoreSession
from talon_core.network.rns_config import reticulum_acceptance_path


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
    env["XDG_CONFIG_HOME"] = str(tmp_path / "xdg-config")
    env["XDG_DATA_HOME"] = str(tmp_path / "xdg-data")
    env["XDG_STATE_HOME"] = str(tmp_path / "xdg-state")
    return env


def _run_desktop_install(
    tmp_path: Path,
    bundle: Path,
    *extra_args: str,
    env: dict[str, str] | None = None,
    check: bool = True,
    install_deps: bool = False,
) -> subprocess.CompletedProcess[str]:
    install_env = env or _desktop_env(tmp_path)
    dep_args = [] if install_deps else ["--no-deps"]
    return subprocess.run(
        [
            "bash",
            str(DESKTOP_INSTALLER),
            *dep_args,
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


def _run_desktop_uninstall(
    tmp_path: Path,
    *extra_args: str,
    env: dict[str, str] | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    install_env = env or _desktop_env(tmp_path)
    return subprocess.run(
        [
            "bash",
            str(DESKTOP_INSTALLER),
            "--uninstall",
            "--prefix",
            str(tmp_path / "install"),
            "--bin-dir",
            str(tmp_path / "bin"),
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
    assert "TALON AutoInterface" in rns_text
    assert "TALON i2pd Client" in rns_text
    assert "type = I2PInterface" in rns_text
    assert "enabled = No" in rns_text
    assert "connectable = No" in rns_text
    assert not reticulum_acceptance_path(rns_config.parent).exists()
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
    assert "TALON AutoInterface" in rns_text
    assert "TALON i2pd Server" in rns_text
    assert "type = I2PInterface" in rns_text
    assert "enabled = Yes" in rns_text
    assert "connectable = Yes" in rns_text
    assert not reticulum_acceptance_path(rns_config.parent).exists()


def test_desktop_client_i2p_peer_option_enables_client_stanza(tmp_path):
    env = _desktop_env(tmp_path)
    peer = "5URVJICPZI7Q3YBZTSEF4I5OW2AQ4SOKTFJ7ZEDZ53S47R54JNQQ.B32.I2P"
    _run_desktop_install(
        tmp_path,
        _fake_desktop_bundle(tmp_path, "client"),
        "--i2p-peer",
        peer,
        env=env,
    )

    rns_config = tmp_path / "home" / ".talon" / "reticulum" / "config"
    rns_text = rns_config.read_text(encoding="utf-8")
    assert "TALON i2pd Client" in rns_text
    assert "enabled = Yes" in rns_text
    assert "connectable = No" in rns_text
    assert (
        "peers = 5urvjicpzi7q3ybztsef4i5ow2aq4soktfj7zedz53s47r54jnqq.b32.i2p"
        in rns_text
    )


def test_desktop_server_rejects_i2p_peer_option(tmp_path):
    result = _run_desktop_install(
        tmp_path,
        _fake_desktop_bundle(tmp_path, "server"),
        "--i2p-peer",
        "5urvjicpzi7q3ybztsef4i5ow2aq4soktfj7zedz53s47r54jnqq.b32.i2p",
        check=False,
    )

    assert result.returncode != 0
    assert "--i2p-peer is only supported for client artifacts" in result.stderr


def test_desktop_client_rejects_invalid_i2p_peer_option(tmp_path):
    result = _run_desktop_install(
        tmp_path,
        _fake_desktop_bundle(tmp_path, "client"),
        "--i2p-peer",
        "not-a-peer",
        check=False,
    )

    assert result.returncode != 0
    assert "--i2p-peer must be a server .b32.i2p address" in result.stderr


def test_desktop_installer_configures_i2pd_sam_when_deps_enabled(tmp_path):
    env = _desktop_env(tmp_path)
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    systemctl_log = tmp_path / "systemctl.log"
    i2pd_config = tmp_path / "i2pd" / "i2pd.conf"
    i2pd_config.parent.mkdir()
    i2pd_config.write_text(
        "[http]\n"
        "enabled = false\n"
        "\n"
        "[sam]\n"
        "enabled = false\n"
        "address = 0.0.0.0\n"
        "port = 9999\n",
        encoding="utf-8",
    )

    for name in ["xdg-open", "i2pd"]:
        tool = fake_bin / name
        tool.write_text("#!/usr/bin/env sh\nexit 0\n", encoding="utf-8")
        tool.chmod(tool.stat().st_mode | stat.S_IXUSR)

    sudo = fake_bin / "sudo"
    sudo.write_text("#!/usr/bin/env sh\nexec \"$@\"\n", encoding="utf-8")
    sudo.chmod(sudo.stat().st_mode | stat.S_IXUSR)

    ldconfig = fake_bin / "ldconfig"
    ldconfig.write_text(
        "#!/usr/bin/env sh\n"
        "cat <<'OUT'\n"
        "libGL.so.1 (libc6,x86-64) => /tmp/libGL.so.1\n"
        "libEGL.so.1 (libc6,x86-64) => /tmp/libEGL.so.1\n"
        "libxkbcommon.so.0 (libc6,x86-64) => /tmp/libxkbcommon.so.0\n"
        "libxcb-cursor.so.0 (libc6,x86-64) => /tmp/libxcb-cursor.so.0\n"
        "libxcb-icccm.so.4 (libc6,x86-64) => /tmp/libxcb-icccm.so.4\n"
        "libxcb-image.so.0 (libc6,x86-64) => /tmp/libxcb-image.so.0\n"
        "libxcb-keysyms.so.1 (libc6,x86-64) => /tmp/libxcb-keysyms.so.1\n"
        "libxcb-render-util.so.0 (libc6,x86-64) => /tmp/libxcb-render-util.so.0\n"
        "libxcb-xinerama.so.0 (libc6,x86-64) => /tmp/libxcb-xinerama.so.0\n"
        "libmagic.so.1 (libc6,x86-64) => /tmp/libmagic.so.1\n"
        "libsqlcipher.so.1 (libc6,x86-64) => /tmp/libsqlcipher.so.1\n"
        "OUT\n",
        encoding="utf-8",
    )
    ldconfig.chmod(ldconfig.stat().st_mode | stat.S_IXUSR)

    systemctl = fake_bin / "systemctl"
    systemctl.write_text(
        "#!/usr/bin/env sh\n"
        "printf '%s\\n' \"$*\" >> \"$TALON_FAKE_SYSTEMCTL_LOG\"\n"
        "exit 0\n",
        encoding="utf-8",
    )
    systemctl.chmod(systemctl.stat().st_mode | stat.S_IXUSR)

    env["PATH"] = f"{fake_bin}{os.pathsep}{env['PATH']}"
    env["TALON_I2PD_CONFIG_PATH"] = str(i2pd_config)
    env["TALON_FAKE_SYSTEMCTL_LOG"] = str(systemctl_log)

    result = _run_desktop_install(
        tmp_path,
        _fake_desktop_bundle(tmp_path, "server"),
        env=env,
        install_deps=True,
    )

    text = i2pd_config.read_text(encoding="utf-8")
    assert "Runtime dependency check passed." in result.stdout
    assert "[sam]" in text
    assert "enabled = true" in text
    assert "address = 127.0.0.1" in text
    assert "port = 7656" in text
    assert list(i2pd_config.parent.glob("i2pd.conf.talon-backup.*"))
    systemctl_lines = systemctl_log.read_text(encoding="utf-8").splitlines()
    assert "enable i2pd.service" in systemctl_lines
    assert "restart i2pd.service" in systemctl_lines


def test_desktop_fresh_installer_rns_config_requires_first_launch_acceptance(tmp_path):
    env = _desktop_env(tmp_path)
    _run_desktop_install(tmp_path, _fake_desktop_bundle(tmp_path, "server"), env=env)

    config = tmp_path / "home" / ".talon-server" / "talon.ini"
    session = TalonCoreSession(config_path=config).start()
    try:
        session.unlock_with_key(bytes(range(32)))
        status = session.reticulum_config_status()
    finally:
        session.close()

    assert status.exists is True
    assert status.valid is True
    assert status.accepted is False
    assert status.needs_setup is True


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
    legacy_launcher.write_text("TALON legacy\n", encoding="utf-8")
    legacy_entry = tmp_path / "xdg-data" / "applications" / "talon-desktop.desktop"
    legacy_entry.write_text("Tactical Awareness legacy\n", encoding="utf-8")
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


def test_desktop_uninstall_requires_delete_confirmation(tmp_path):
    env = _desktop_env(tmp_path)
    _run_desktop_install(tmp_path, _fake_desktop_bundle(tmp_path, "client"), env=env)

    result = _run_desktop_uninstall(tmp_path, env=env, check=False)

    assert result.returncode != 0
    assert "Uninstalling TALON requires" in result.stderr
    assert (tmp_path / "home" / ".talon" / "talon.ini").exists()
    assert (tmp_path / "bin" / "talon-desktop-client").exists()


def test_desktop_uninstall_preserves_non_talon_named_files(tmp_path):
    env = _desktop_env(tmp_path)
    bin_dir = tmp_path / "bin"
    desktop_dir = tmp_path / "xdg-data" / "applications"
    bin_dir.mkdir(parents=True)
    desktop_dir.mkdir(parents=True)
    launcher = bin_dir / "talon"
    entry = desktop_dir / "talon.desktop"
    launcher.write_text("#!/usr/bin/env sh\necho other app\n", encoding="utf-8")
    entry.write_text("[Desktop Entry]\nName=Other App\n", encoding="utf-8")

    result = _run_desktop_uninstall(
        tmp_path,
        "--confirm-delete",
        DELETE_PHRASE,
        env=env,
    )

    assert "No local TALON desktop or legacy install paths were found" in result.stdout
    assert launcher.exists()
    assert entry.exists()


def test_desktop_confirmed_uninstall_deletes_current_legacy_and_custom_paths(tmp_path):
    env = _desktop_env(tmp_path)
    _run_desktop_install(tmp_path, _fake_desktop_bundle(tmp_path, "client"), env=env)
    home = tmp_path / "home"
    install_root = tmp_path / "install"
    bin_dir = tmp_path / "bin"
    desktop_dir = tmp_path / "xdg-data" / "applications"
    settings_dir = tmp_path / "xdg-config" / "TALON"
    state = tmp_path / "xdg-state" / "talon"
    custom_config = tmp_path / "custom config" / "talon.ini"
    custom_data = tmp_path / "custom data"
    custom_rns = tmp_path / "custom rns"
    custom_documents = tmp_path / "custom documents"

    for directory in [
        home / ".talon-server",
        install_root / "talon-linux",
        install_root / "talon-desktop-linux",
        install_root / "talon-desktop-server-linux",
        install_root / "talon-desktop-client-linux.backup.20260428010101",
        install_root / ".talon-desktop-client-linux.new.1234",
        settings_dir,
        custom_data,
        custom_rns,
        custom_documents,
    ]:
        directory.mkdir(parents=True)

    custom_config.parent.mkdir(parents=True)
    custom_config.write_text("custom\n", encoding="utf-8")
    (home / ".talon-server" / "talon.ini").write_text("server\n", encoding="utf-8")
    (settings_dir / "TALON Desktop.ini").write_text("settings\n", encoding="utf-8")
    (state / "old.log").write_text("log\n", encoding="utf-8")
    for name in ["talon", "talon-desktop", "talon-desktop-server"]:
        (bin_dir / name).write_text("TALON legacy\n", encoding="utf-8")
    for name in ["talon.desktop", "talon-desktop.desktop", "talon-desktop-server.desktop"]:
        (desktop_dir / name).write_text("Tactical Awareness legacy\n", encoding="utf-8")

    result = _run_desktop_uninstall(
        tmp_path,
        "--config",
        str(custom_config),
        "--data-dir",
        str(custom_data),
        "--rns-dir",
        str(custom_rns),
        "--documents-dir",
        str(custom_documents),
        "--confirm-delete",
        DELETE_PHRASE,
        env=env,
    )

    assert "TALON desktop uninstall complete" in result.stdout
    for path in [
        home / ".talon",
        home / ".talon-server",
        install_root / "talon-linux",
        install_root / "talon-desktop-linux",
        install_root / "talon-desktop-client-linux",
        install_root / "talon-desktop-server-linux",
        install_root / "talon-desktop-client-linux.backup.20260428010101",
        install_root / ".talon-desktop-client-linux.new.1234",
        bin_dir / "talon",
        bin_dir / "talon-desktop",
        bin_dir / "talon-desktop-client",
        bin_dir / "talon-desktop-server",
        desktop_dir / "talon.desktop",
        desktop_dir / "talon-desktop.desktop",
        desktop_dir / "talon-desktop-client.desktop",
        desktop_dir / "talon-desktop-server.desktop",
        settings_dir,
        state,
        custom_config,
        custom_data,
        custom_rns,
        custom_documents,
    ]:
        assert not path.exists()


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
