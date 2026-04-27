"""Command-line entry point for the PySide6 desktop client."""
from __future__ import annotations

import argparse
import json
import logging
import os
import pathlib
import select
import signal
import socket
import subprocess
import sys
import tempfile
import time
import typing


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="talon-desktop",
        description="Run the TALON PySide6 desktop client.",
    )
    parser.add_argument(
        "--config",
        type=pathlib.Path,
        default=None,
        help="Path to talon.ini. Defaults to TALON_CONFIG, ~/.talon/talon.ini, then ./talon.ini.",
    )
    parser.add_argument(
        "--mode",
        choices=("client", "server"),
        default=None,
        help="Override [talon] mode from config.",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Unlock without starting Reticulum sync. Useful for local UI smoke tests.",
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=(
            "Construct the PySide6 desktop shell offscreen and exit. "
            "Used by package smoke tests."
        ),
    )
    parser.add_argument(
        "--loopback-smoke",
        action="store_true",
        help=(
            "Run a packaged Reticulum TCP loopback enrollment and sync smoke "
            "test, then exit."
        ),
    )
    parser.add_argument(
        "--loopback-smoke-role",
        choices=("server", "client"),
        default=None,
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--loopback-token",
        default="",
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: typing.Sequence[str] | None = None) -> int:
    logging.basicConfig(
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        level=logging.INFO,
    )
    args = build_parser().parse_args(argv)

    if args.smoke:
        try:
            return run_package_smoke(config_path=args.config, mode=args.mode)
        except ModuleNotFoundError as exc:
            if exc.name == "PySide6":
                print(
                    "PySide6 is not installed. Install the desktop extra with "
                    "`pip install -e .[desktop]`.",
                    file=sys.stderr,
                )
                return 2
            raise

    if args.loopback_smoke:
        return run_loopback_smoke()
    if args.loopback_smoke_role == "server":
        if args.config is None:
            print("--config is required for loopback smoke server", file=sys.stderr)
            return 2
        return run_loopback_smoke_server(args.config)
    if args.loopback_smoke_role == "client":
        if args.config is None or not args.loopback_token:
            print(
                "--config and --loopback-token are required for loopback smoke client",
                file=sys.stderr,
            )
            return 2
        return run_loopback_smoke_client(args.config, args.loopback_token)

    try:
        from talon_desktop.app import run_desktop
    except ModuleNotFoundError as exc:
        if exc.name == "PySide6":
            print(
                "PySide6 is not installed. Install the desktop extra with "
                "`pip install -e .[desktop]`.",
                file=sys.stderr,
            )
            return 2
        raise

    return run_desktop(
        config_path=args.config,
        mode=args.mode,
        start_sync=not args.no_sync,
    )


def run_loopback_smoke() -> int:
    """Run a same-machine packaged Reticulum enrollment and sync smoke."""
    with tempfile.TemporaryDirectory(prefix="talon-desktop-loopback-") as temp_name:
        root = pathlib.Path(temp_name)
        port = _free_port()
        server_cfg, server_rns = _write_loopback_app_config(root, "server")
        client_cfg, client_rns = _write_loopback_app_config(root, "client")
        _write_rns_config(
            server_rns,
            _server_tcp_interface(port),
            enable_transport=True,
        )
        _write_rns_config(
            client_rns,
            _client_tcp_interface(port),
            enable_transport=False,
        )

        server = subprocess.Popen(
            [
                *_self_command(),
                "--loopback-smoke-role",
                "server",
                "--config",
                str(server_cfg),
            ],
            cwd=pathlib.Path.cwd(),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            payload = _read_server_loopback_payload(server, timeout_s=35.0)
            client = subprocess.run(
                [
                    *_self_command(),
                    "--loopback-smoke-role",
                    "client",
                    "--config",
                    str(client_cfg),
                    "--loopback-token",
                    payload["combined"],
                ],
                cwd=pathlib.Path.cwd(),
                text=True,
                capture_output=True,
                timeout=80,
                check=False,
            )
            if client.stdout:
                print(client.stdout, end="")
            if client.stderr:
                print(client.stderr, file=sys.stderr, end="")
            if client.returncode != 0:
                raise RuntimeError(f"loopback client failed with rc={client.returncode}")
            if "TALON_PACKAGE_LOOPBACK_CLIENT_OK" not in client.stdout:
                raise RuntimeError("loopback client did not report success")
            print("TALON_PACKAGE_LOOPBACK_OK")
            return 0
        except Exception as exc:
            print(f"TALON_PACKAGE_LOOPBACK_FAILED {exc}", file=sys.stderr)
            return 1
        finally:
            server.terminate()
            try:
                out, err = server.communicate(timeout=5)
            except subprocess.TimeoutExpired:
                server.kill()
                out, err = server.communicate(timeout=5)
            if out:
                print(out, end="")
            if err:
                print(err, file=sys.stderr, end="")


def run_loopback_smoke_server(config_path: pathlib.Path) -> int:
    """Run the server half of the packaged Reticulum loopback smoke."""
    from talon_core import TalonCoreSession

    stop_requested = False

    def _stop(_signum: int, _frame: object) -> None:
        nonlocal stop_requested
        stop_requested = True

    signal.signal(signal.SIGTERM, _stop)
    core = TalonCoreSession(config_path=config_path, mode="server").start()
    try:
        core.unlock_with_key(bytes(range(32)))
        core.start_sync(init_reticulum=True)
        asset = core.command(
            "assets.create",
            category="cache",
            label="Package Loopback Cache",
            description="Packaged Reticulum loopback smoke",
        )
        token = core.command("enrollment.generate_token")
        print(
            "TALON_PACKAGE_LOOPBACK_SERVER "
            + json.dumps(
                {
                    "combined": token.combined,
                    "server_hash": core.read_model("enrollment.server_hash"),
                    "asset_id": asset.asset_id,
                }
            ),
            flush=True,
        )
        while not stop_requested:
            time.sleep(0.2)
        return 0
    finally:
        core._reticulum_started = False
        core.close()


def run_loopback_smoke_client(config_path: pathlib.Path, combined: str) -> int:
    """Run the client half of the packaged Reticulum loopback smoke."""
    from talon_core import TalonCoreSession

    core = TalonCoreSession(config_path=config_path, mode="client").start()
    exit_code = 1
    try:
        core.unlock_with_key(bytes(range(32)))
        core.start_reticulum()
        operator_id = core.enroll_client(combined, "PKGSMOKE", timeout_s=30.0)
        deadline = time.time() + 45.0
        while time.time() < deadline:
            assets = core.read_model("assets.list")
            if any(
                getattr(asset, "label", "") == "Package Loopback Cache"
                for asset in assets
            ):
                print(
                    "TALON_PACKAGE_LOOPBACK_CLIENT_OK "
                    + json.dumps({"operator_id": operator_id}),
                    flush=True,
                )
                exit_code = 0
                break
            time.sleep(0.5)
        else:
            print("TALON_PACKAGE_LOOPBACK_CLIENT_TIMEOUT", file=sys.stderr)
    except Exception as exc:
        print(f"TALON_PACKAGE_LOOPBACK_CLIENT_FAILED {exc}", file=sys.stderr)
    finally:
        core._reticulum_started = False
        core.close()
        sys.stdout.flush()
        sys.stderr.flush()
        os._exit(exit_code)


def run_package_smoke(
    *,
    config_path: pathlib.Path | None = None,
    mode: typing.Literal["server", "client"] | None = None,
) -> int:
    """Construct and navigate the desktop shell without starting an event loop."""
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6 import QtCore, QtWidgets

    from talon_core import TalonCoreSession
    from talon_desktop.app import MainWindow
    from talon_desktop.logs import install_desktop_log_buffer
    from talon_desktop.navigation import navigation_items
    from talon_desktop.qt_events import CoreEventBridge
    from talon_desktop.settings import SETTINGS_PATH_ENV

    smoke_mode = mode or "server"
    temp_dir: tempfile.TemporaryDirectory[str] | None = None
    previous_settings_path = os.environ.get(SETTINGS_PATH_ENV)
    if config_path is None:
        temp_dir = tempfile.TemporaryDirectory(prefix="talon-desktop-smoke-")
        config_path = _write_smoke_config(pathlib.Path(temp_dir.name), smoke_mode)
        os.environ.setdefault(
            SETTINGS_PATH_ENV,
            str(pathlib.Path(temp_dir.name) / "desktop-settings.ini"),
        )

    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    log_buffer = install_desktop_log_buffer()
    core = TalonCoreSession(config_path=config_path, mode=smoke_mode).start()
    window: MainWindow | None = None
    try:
        core.unlock_with_key(bytes(range(32)))
        window = MainWindow(core, CoreEventBridge(), log_buffer=log_buffer)
        expected = [item.key for item in navigation_items(core.mode)]
        actual = [
            window.nav.item(index).data(QtCore.Qt.UserRole)
            for index in range(window.nav.count())
        ]
        if actual != expected:
            raise RuntimeError(f"Unexpected navigation sections: {actual!r}")
        for index, key in enumerate(expected):
            window.nav.setCurrentRow(index)
            app.processEvents()
            if window.stack.currentIndex() != index:
                raise RuntimeError(f"Could not navigate to {key!r}")
        print(f"TALON_DESKTOP_SMOKE_OK {core.mode} {'|'.join(actual)}")
        return 0
    finally:
        if window is not None:
            window.close()
        core.close()
        app.processEvents()
        if previous_settings_path is None:
            os.environ.pop(SETTINGS_PATH_ENV, None)
        else:
            os.environ[SETTINGS_PATH_ENV] = previous_settings_path
        if temp_dir is not None:
            temp_dir.cleanup()


def _write_smoke_config(root: pathlib.Path, mode: str) -> pathlib.Path:
    data_dir = root / f"{mode}-data"
    rns_dir = root / f"{mode}-rns"
    documents_dir = root / f"{mode}-documents"
    config_path = root / f"{mode}.ini"
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


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _write_loopback_app_config(
    root: pathlib.Path,
    mode: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    data_dir = root / f"{mode}-data"
    rns_dir = root / f"{mode}-rns"
    documents_dir = root / f"{mode}-documents"
    config_path = root / f"{mode}.ini"
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
                "[network]",
                "lora_mode = false",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return config_path, rns_dir


def _write_rns_config(
    rns_dir: pathlib.Path,
    stanza: str,
    *,
    enable_transport: bool,
) -> None:
    rns_dir.mkdir(parents=True, exist_ok=True)
    (rns_dir / "config").write_text(
        "[reticulum]\n"
        f"  enable_transport = {'True' if enable_transport else 'False'}\n"
        "  share_instance = No\n"
        "\n"
        "[logging]\n"
        "  loglevel = 3\n"
        "\n"
        "[interfaces]\n"
        f"{stanza}\n",
        encoding="utf-8",
    )


def _server_tcp_interface(port: int) -> str:
    return (
        "  [[TALON Package TCP Server]]\n"
        "    type = TCPServerInterface\n"
        "    enabled = yes\n"
        "    listen_ip = 127.0.0.1\n"
        f"    listen_port = {port}\n"
    )


def _client_tcp_interface(port: int) -> str:
    return (
        "  [[TALON Package TCP Client]]\n"
        "    type = TCPClientInterface\n"
        "    enabled = yes\n"
        "    target_host = 127.0.0.1\n"
        f"    target_port = {port}\n"
    )


def _self_command() -> list[str]:
    if getattr(sys, "frozen", False):
        return [sys.executable]
    return [sys.executable, "-m", "talon_desktop"]


def _read_server_loopback_payload(
    server: subprocess.Popen[str],
    *,
    timeout_s: float,
) -> dict[str, typing.Any]:
    if server.stdout is None:
        raise RuntimeError("loopback server stdout was not captured")
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if server.poll() is not None:
            stderr = server.stderr.read() if server.stderr is not None else ""
            raise RuntimeError(
                f"loopback server exited early rc={server.returncode}: {stderr}"
            )
        readable, _, _ = select.select([server.stdout], [], [], 0.2)
        if not readable:
            continue
        line = server.stdout.readline()
        if not line:
            continue
        print(line, end="")
        if line.startswith("TALON_PACKAGE_LOOPBACK_SERVER "):
            return json.loads(line[len("TALON_PACKAGE_LOOPBACK_SERVER ") :])
    raise RuntimeError("timed out waiting for loopback server token")


if __name__ == "__main__":
    raise SystemExit(main())
