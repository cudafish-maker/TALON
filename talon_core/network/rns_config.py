"""Reticulum config inspection and persistence helpers.

These helpers intentionally parse and write Reticulum config text without
starting Reticulum or opening network sockets.
"""
from __future__ import annotations

import dataclasses
import os
import pathlib
import shutil
import time
import typing


Mode = typing.Literal["server", "client"]


class ReticulumConfigError(RuntimeError):
    """Raised when TALON cannot inspect or persist Reticulum config."""


@dataclasses.dataclass(frozen=True)
class ReticulumConfigValidation:
    valid: bool
    errors: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class ReticulumConfigStatus:
    path: pathlib.Path
    exists: bool
    validation: ReticulumConfigValidation
    reticulum_started: bool = False

    @property
    def valid(self) -> bool:
        return self.validation.valid

    @property
    def errors(self) -> tuple[str, ...]:
        return self.validation.errors

    @property
    def warnings(self) -> tuple[str, ...]:
        return self.validation.warnings

    @property
    def needs_setup(self) -> bool:
        return (not self.exists) or (not self.valid) or bool(self.warnings)


@dataclasses.dataclass(frozen=True)
class ReticulumConfigSaveResult:
    path: pathlib.Path
    backup_path: pathlib.Path | None
    validation: ReticulumConfigValidation
    restart_required: bool = False


_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}


def reticulum_config_path(config_dir: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(config_dir) / "config"


def reticulum_config_status(
    config_dir: pathlib.Path,
    *,
    mode: Mode,
    reticulum_started: bool = False,
) -> ReticulumConfigStatus:
    path = reticulum_config_path(config_dir)
    if not path.exists():
        return ReticulumConfigStatus(
            path=path,
            exists=False,
            validation=validate_reticulum_config_text(default_reticulum_config(mode), mode=mode),
            reticulum_started=reticulum_started,
        )
    if path.is_symlink():
        return ReticulumConfigStatus(
            path=path,
            exists=True,
            validation=ReticulumConfigValidation(
                valid=False,
                errors=(f"Refusing symlinked Reticulum config: {path}",),
            ),
            reticulum_started=reticulum_started,
        )
    if not path.is_file():
        return ReticulumConfigStatus(
            path=path,
            exists=True,
            validation=ReticulumConfigValidation(
                valid=False,
                errors=(f"Reticulum config path is not a regular file: {path}",),
            ),
            reticulum_started=reticulum_started,
        )
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        validation = ReticulumConfigValidation(
            valid=False,
            errors=(f"Could not read Reticulum config: {exc}",),
        )
    else:
        validation = validate_reticulum_config_text(text, mode=mode)
    return ReticulumConfigStatus(
        path=path,
        exists=True,
        validation=validation,
        reticulum_started=reticulum_started,
    )


def load_reticulum_config_text(config_dir: pathlib.Path, *, mode: Mode) -> str:
    path = reticulum_config_path(config_dir)
    if not path.exists():
        return default_reticulum_config(mode)
    if path.is_symlink():
        raise ReticulumConfigError(f"Refusing symlinked Reticulum config: {path}")
    if not path.is_file():
        raise ReticulumConfigError(f"Reticulum config path is not a regular file: {path}")
    return path.read_text(encoding="utf-8")


def validate_reticulum_config_text(
    text: str,
    *,
    mode: Mode,
) -> ReticulumConfigValidation:
    errors: list[str] = []
    warnings: list[str] = []
    if not text.strip():
        return ReticulumConfigValidation(
            valid=False,
            errors=("Reticulum config is empty.",),
        )

    try:
        from RNS.vendor.configobj import ConfigObj

        parsed = ConfigObj(text.splitlines())
    except Exception as exc:
        return ReticulumConfigValidation(
            valid=False,
            errors=(f"Reticulum config syntax error: {exc}",),
        )

    reticulum = _section(parsed, "reticulum")
    if reticulum is None:
        errors.append("Missing [reticulum] section.")
    else:
        share_instance = reticulum.get("share_instance")
        if _as_bool(share_instance, default=False):
            warnings.append(
                "share_instance is enabled; TALON should use its own Reticulum instance."
            )
        elif share_instance is None:
            warnings.append("share_instance is not set; TALON recommends share_instance = No.")

        if mode == "server" and not _as_bool(
            reticulum.get("enable_transport"),
            default=False,
        ):
            warnings.append("Server transport is disabled; clients may not route through this node.")

    interfaces = _section(parsed, "interfaces")
    enabled_interfaces = 0
    if interfaces is None:
        warnings.append("No enabled Reticulum interfaces are configured.")
    else:
        for interface_name, interface in _iter_interface_sections(interfaces):
            if not _as_bool(interface.get("enabled"), default=False):
                continue
            enabled_interfaces += 1
            interface_type = str(interface.get("type", "")).strip()
            if interface_type == "TCPServerInterface":
                _validate_tcp_server(
                    interface_name,
                    interface,
                    warnings=warnings,
                    errors=errors,
                )
            elif interface_type == "TCPClientInterface":
                _validate_tcp_client(
                    interface_name,
                    interface,
                    warnings=warnings,
                    errors=errors,
                )
        if enabled_interfaces == 0:
            warnings.append("No enabled Reticulum interfaces are configured.")

    return ReticulumConfigValidation(
        valid=not errors,
        errors=tuple(errors),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def save_reticulum_config_text(
    config_dir: pathlib.Path,
    text: str,
    *,
    mode: Mode,
    reticulum_started: bool = False,
) -> ReticulumConfigSaveResult:
    validation = validate_reticulum_config_text(text, mode=mode)
    if not validation.valid:
        raise ReticulumConfigError("; ".join(validation.errors))

    config_dir = pathlib.Path(config_dir)
    path = reticulum_config_path(config_dir)
    if config_dir.is_symlink():
        raise ReticulumConfigError(f"Refusing symlinked Reticulum config directory: {config_dir}")
    if path.is_symlink():
        raise ReticulumConfigError(f"Refusing to overwrite symlinked Reticulum config: {path}")

    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod_private(config_dir, 0o700)

    backup_path: pathlib.Path | None = None
    if path.exists():
        if not path.is_file():
            raise ReticulumConfigError(f"Reticulum config path is not a regular file: {path}")
        backup_path = _backup_path(path)
        shutil.copy2(path, backup_path)
        _chmod_private(backup_path, 0o600)

    tmp_path = config_dir / f".config.tmp.{os.getpid()}.{time.time_ns()}"
    data = _normalise_text(text).encode("utf-8")
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, path)
        _chmod_private(path, 0o600)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise

    return ReticulumConfigSaveResult(
        path=path,
        backup_path=backup_path,
        validation=validation,
        restart_required=reticulum_started,
    )


def import_default_reticulum_config(
    config_dir: pathlib.Path,
    *,
    mode: Mode,
    reticulum_started: bool = False,
    source_path: pathlib.Path | None = None,
) -> ReticulumConfigSaveResult:
    source = source_path if source_path is not None else pathlib.Path.home() / ".reticulum" / "config"
    if not source.exists():
        raise ReticulumConfigError(f"Default Reticulum config does not exist: {source}")
    if not source.is_file():
        raise ReticulumConfigError(f"Default Reticulum config path is not a regular file: {source}")
    text = source.read_text(encoding="utf-8")
    return save_reticulum_config_text(
        config_dir,
        text,
        mode=mode,
        reticulum_started=reticulum_started,
    )


def default_reticulum_config(mode: Mode) -> str:
    return _base_config(
        mode=mode,
        interfaces=(
            "  [[TALON AutoInterface]]\n"
            "    type = AutoInterface\n"
            "    enabled = Yes\n"
        ),
    )


def auto_interface_config(mode: Mode) -> str:
    return default_reticulum_config(mode)


def tcp_server_config(*, listen_ip: str = "0.0.0.0", port: int = 4242) -> str:
    return _base_config(
        mode="server",
        interfaces=(
            "  [[TALON TCP Server]]\n"
            "    type = TCPServerInterface\n"
            "    enabled = Yes\n"
            f"    listen_ip = {listen_ip}\n"
            f"    listen_port = {int(port)}\n"
        ),
    )


def tcp_client_config(host: str, *, port: int = 4242) -> str:
    return _base_config(
        mode="client",
        interfaces=(
            "  [[TALON TCP Client]]\n"
            "    type = TCPClientInterface\n"
            "    enabled = Yes\n"
            f"    target_host = {host.strip()}\n"
            f"    target_port = {int(port)}\n"
        ),
    )


def _base_config(*, mode: Mode, interfaces: str) -> str:
    enable_transport = "True" if mode == "server" else "False"
    return (
        "[reticulum]\n"
        f"  enable_transport = {enable_transport}\n"
        "  share_instance = No\n"
        "\n"
        "[logging]\n"
        "  loglevel = 4\n"
        "\n"
        "[interfaces]\n"
        f"{interfaces}"
        "\n"
        "# TCP, Yggdrasil, I2P, and RNode interfaces are deployment-specific.\n"
    )


def _section(parsed: typing.Mapping[str, typing.Any], name: str) -> typing.Any | None:
    value = parsed.get(name)
    return value if isinstance(value, dict) or hasattr(value, "items") else None


def _iter_interface_sections(
    interfaces: typing.Any,
) -> typing.Iterator[tuple[str, typing.Mapping[str, typing.Any]]]:
    section_names = getattr(interfaces, "sections", None)
    names = section_names if isinstance(section_names, list) else list(interfaces.keys())
    for name in names:
        value = interfaces.get(name)
        if isinstance(value, dict) or hasattr(value, "items"):
            yield str(name), typing.cast(typing.Mapping[str, typing.Any], value)


def _validate_tcp_server(
    interface_name: str,
    interface: typing.Mapping[str, typing.Any],
    *,
    warnings: list[str],
    errors: list[str],
) -> None:
    listen_ip = str(interface.get("listen_ip", "")).strip().lower()
    if listen_ip in {"127.0.0.1", "localhost", "::1"}:
        warnings.append(
            f"{interface_name} listens on localhost; remote TALON clients cannot reach it."
        )
    port = interface.get("listen_port")
    if port is None:
        warnings.append(f"{interface_name} has no listen_port.")
    else:
        _validate_port(port, f"{interface_name} listen_port", errors)


def _validate_tcp_client(
    interface_name: str,
    interface: typing.Mapping[str, typing.Any],
    *,
    warnings: list[str],
    errors: list[str],
) -> None:
    target_host = str(interface.get("target_host", "")).strip().lower()
    if not target_host:
        warnings.append(f"{interface_name} has no target_host.")
    elif target_host in {"127.0.0.1", "localhost", "::1"}:
        warnings.append(
            f"{interface_name} targets localhost; use the server host for two-machine setups."
        )
    port = interface.get("target_port")
    if port is None:
        warnings.append(f"{interface_name} has no target_port.")
    else:
        _validate_port(port, f"{interface_name} target_port", errors)


def _validate_port(value: object, label: str, errors: list[str]) -> None:
    try:
        port = int(str(value).strip())
    except (TypeError, ValueError):
        errors.append(f"{label} is not a valid port.")
        return
    if port < 1 or port > 65535:
        errors.append(f"{label} must be between 1 and 65535.")


def _as_bool(value: object, *, default: bool) -> bool:
    if value is None:
        return default
    lowered = str(value).strip().lower()
    if lowered in _TRUE_VALUES:
        return True
    if lowered in _FALSE_VALUES:
        return False
    return default


def _backup_path(path: pathlib.Path) -> pathlib.Path:
    stamp = time.strftime("%Y%m%d%H%M%S")
    candidate = path.with_name(f"{path.name}.bak.{stamp}")
    counter = 1
    while candidate.exists():
        candidate = path.with_name(f"{path.name}.bak.{stamp}.{counter}")
        counter += 1
    return candidate


def _normalise_text(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def _chmod_private(path: pathlib.Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except PermissionError as exc:
        raise ReticulumConfigError(f"Could not secure Reticulum config path {path}") from exc
