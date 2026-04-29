"""Reticulum config inspection and persistence helpers.

These helpers intentionally parse and write Reticulum config text without
starting Reticulum or opening network sockets.
"""
from __future__ import annotations

import dataclasses
import hashlib
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
    accepted: bool = False
    acceptance_path: pathlib.Path | None = None
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
        return (not self.exists) or (not self.valid) or (not self.accepted)


@dataclasses.dataclass(frozen=True)
class ReticulumConfigSaveResult:
    path: pathlib.Path
    backup_path: pathlib.Path | None
    validation: ReticulumConfigValidation
    restart_required: bool = False


@dataclasses.dataclass(frozen=True)
class ReticulumTransportSummary:
    method: str
    label: str
    direct_tcp_warning: bool = False
    enabled_methods: tuple[str, ...] = ()


_TRUE_VALUES = {"1", "true", "yes", "on", "enabled"}
_FALSE_VALUES = {"0", "false", "no", "off", "disabled"}
_ACCEPTANCE_MARKER_NAME = ".talon-reticulum-config.accepted"
_METHOD_LABELS = {
    "yggdrasil": "Yggdrasil",
    "i2p": "I2P",
    "tcp": "TCP",
    "lora": "LoRa",
    "auto": "AutoInterface",
    "unknown": "Unknown",
}
_METHOD_PRIORITY = ("yggdrasil", "i2p", "tcp", "lora", "auto")
_LORA_INTERFACE_TYPES = frozenset({
    "RNodeInterface",
    "RNodeMultiInterface",
    "KISSInterface",
    "AX25KISSInterface",
    "SerialInterface",
})


def reticulum_config_path(config_dir: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(config_dir) / "config"


def reticulum_acceptance_path(config_dir: pathlib.Path) -> pathlib.Path:
    return pathlib.Path(config_dir) / _ACCEPTANCE_MARKER_NAME


def reticulum_config_status(
    config_dir: pathlib.Path,
    *,
    mode: Mode,
    reticulum_started: bool = False,
) -> ReticulumConfigStatus:
    path = reticulum_config_path(config_dir)
    acceptance_path = reticulum_acceptance_path(config_dir)
    if not path.exists():
        return ReticulumConfigStatus(
            path=path,
            exists=False,
            validation=validate_reticulum_config_text(
                default_reticulum_config(mode),
                mode=mode,
            ),
            acceptance_path=acceptance_path,
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
            acceptance_path=acceptance_path,
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
            acceptance_path=acceptance_path,
            reticulum_started=reticulum_started,
        )
    accepted = False
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        validation = ReticulumConfigValidation(
            valid=False,
            errors=(f"Could not read Reticulum config: {exc}",),
        )
    else:
        validation = validate_reticulum_config_text(text, mode=mode)
        accepted = validation.valid and _is_config_accepted(config_dir, text)
    return ReticulumConfigStatus(
        path=path,
        exists=True,
        validation=validation,
        accepted=accepted,
        acceptance_path=acceptance_path,
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
            elif interface_type == "I2PInterface":
                _validate_i2p(
                    interface_name,
                    interface,
                    warnings=warnings,
                )
        if enabled_interfaces == 0:
            warnings.append("No enabled Reticulum interfaces are configured.")

    return ReticulumConfigValidation(
        valid=not errors,
        errors=tuple(errors),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def reticulum_transport_summary(
    config_dir: pathlib.Path,
    *,
    mode: Mode,
) -> ReticulumTransportSummary:
    """Return a redacted operator-facing summary of the configured RNS method."""
    text = load_reticulum_config_text(config_dir, mode=mode)
    return reticulum_transport_summary_from_text(text, mode=mode)


def reticulum_transport_summary_from_text(
    text: str,
    *,
    mode: Mode,
) -> ReticulumTransportSummary:
    """Classify enabled Reticulum interfaces without exposing addresses."""
    del mode  # Reserved for future mode-specific classification rules.
    try:
        from RNS.vendor.configobj import ConfigObj

        parsed = ConfigObj(text.splitlines())
    except Exception:
        return ReticulumTransportSummary(
            method="unknown",
            label=_METHOD_LABELS["unknown"],
        )

    interfaces = _section(parsed, "interfaces")
    if interfaces is None:
        return ReticulumTransportSummary(
            method="unknown",
            label=_METHOD_LABELS["unknown"],
        )

    methods: list[str] = []
    for interface_name, interface in _iter_interface_sections(interfaces):
        if not _as_bool(interface.get("enabled"), default=False):
            continue
        method = _classify_interface_method(interface_name, interface)
        if method is not None:
            methods.append(method)

    unique_methods = tuple(dict.fromkeys(methods))
    selected = _select_method(unique_methods)
    return ReticulumTransportSummary(
        method=selected,
        label=_METHOD_LABELS.get(selected, _METHOD_LABELS["unknown"]),
        direct_tcp_warning=(selected == "tcp"),
        enabled_methods=unique_methods,
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
        raise ReticulumConfigError(
            f"Refusing symlinked Reticulum config directory: {config_dir}"
        )
    if path.is_symlink():
        raise ReticulumConfigError(f"Refusing to overwrite symlinked Reticulum config: {path}")

    config_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    _chmod_private(config_dir, 0o700)

    backup_path: pathlib.Path | None = None
    data = _normalise_text(text)
    existing_text: str | None = None
    if path.exists():
        if not path.is_file():
            raise ReticulumConfigError(
                f"Reticulum config path is not a regular file: {path}"
            )
        existing_text = _normalise_text(path.read_text(encoding="utf-8"))
        if existing_text != data:
            backup_path = _backup_path(path)
            shutil.copy2(path, backup_path)
            _chmod_private(backup_path, 0o600)

    if existing_text != data:
        tmp_path = config_dir / f".config.tmp.{os.getpid()}.{time.time_ns()}"
        encoded = data.encode("utf-8")
        fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(encoded)
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
    else:
        _chmod_private(path, 0o600)

    _write_acceptance_marker(config_dir, data)

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
    source = (
        source_path
        if source_path is not None
        else pathlib.Path.home() / ".reticulum" / "config"
    )
    if not source.exists():
        raise ReticulumConfigError(f"Default Reticulum config does not exist: {source}")
    if not source.is_file():
        raise ReticulumConfigError(
            f"Default Reticulum config path is not a regular file: {source}"
        )
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


def yggdrasil_server_config(*, device: str = "tun0", port: int = 4343) -> str:
    return _base_config(
        mode="server",
        interfaces=(
            "  [[TALON Yggdrasil Server]]\n"
            "    type = TCPServerInterface\n"
            "    enabled = Yes\n"
            f"    device = {device.strip() or 'tun0'}\n"
            f"    listen_port = {int(port)}\n"
            "    prefer_ipv6 = Yes\n"
        ),
    )


def yggdrasil_client_config(address: str, *, port: int = 4343) -> str:
    return _base_config(
        mode="client",
        interfaces=(
            "  [[TALON Yggdrasil Client]]\n"
            "    type = TCPClientInterface\n"
            "    enabled = Yes\n"
            f"    target_host = {address.strip()}\n"
            f"    target_port = {int(port)}\n"
        ),
    )


def i2pd_server_config() -> str:
    return _base_config(
        mode="server",
        interfaces=(
            "  [[TALON i2pd Server]]\n"
            "    type = I2PInterface\n"
            "    enabled = Yes\n"
            "    connectable = Yes\n"
        ),
    )


def i2pd_client_config(peer: str) -> str:
    return _base_config(
        mode="client",
        interfaces=(
            "  [[TALON i2pd Client]]\n"
            "    type = I2PInterface\n"
            "    enabled = Yes\n"
            "    connectable = No\n"
            f"    peers = {peer.strip()}\n"
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


def _classify_interface_method(
    interface_name: str,
    interface: typing.Mapping[str, typing.Any],
) -> str | None:
    interface_type = str(interface.get("type", "")).strip()
    interface_name_lower = interface_name.lower()
    if interface_type == "I2PInterface":
        return "i2p"
    if interface_type in _LORA_INTERFACE_TYPES:
        return "lora"
    if interface_type == "AutoInterface":
        return "auto"
    if interface_type in {"TCPServerInterface", "TCPClientInterface"}:
        if _is_yggdrasil_tcp_interface(interface_name_lower, interface):
            return "yggdrasil"
        return "tcp"
    return None


def _is_yggdrasil_tcp_interface(
    interface_name_lower: str,
    interface: typing.Mapping[str, typing.Any],
) -> bool:
    if "yggdrasil" in interface_name_lower:
        return True
    if _as_bool(interface.get("prefer_ipv6"), default=False):
        return True
    if str(interface.get("device", "")).strip():
        return True
    return _is_yggdrasil_address(interface.get("target_host")) or _is_yggdrasil_address(
        interface.get("listen_ip")
    )


def _is_yggdrasil_address(value: object) -> bool:
    if value is None:
        return False
    try:
        import ipaddress

        address = ipaddress.ip_address(str(value).strip().split("%", 1)[0])
        return address in ipaddress.ip_network("200::/7")
    except ValueError:
        return False


def _select_method(methods: tuple[str, ...]) -> str:
    if not methods:
        return "unknown"
    for method in _METHOD_PRIORITY:
        if method in methods:
            return method
    return "unknown"


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


def _validate_i2p(
    interface_name: str,
    interface: typing.Mapping[str, typing.Any],
    *,
    warnings: list[str],
) -> None:
    peers = _as_list(interface.get("peers"))
    connectable = _as_bool(interface.get("connectable"), default=False)
    if not connectable and not peers:
        warnings.append(f"{interface_name} is not connectable and has no peers.")
    for peer in peers:
        if not peer.lower().endswith(".b32.i2p"):
            warnings.append(
                f"{interface_name} peer {peer!r} does not look like a .b32.i2p address."
            )


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


def _as_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [item.strip() for item in str(value).split(",") if item.strip()]


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


def _config_digest(text: str) -> str:
    return hashlib.sha256(_normalise_text(text).encode("utf-8")).hexdigest()


def _is_config_accepted(config_dir: pathlib.Path, text: str) -> bool:
    marker = reticulum_acceptance_path(config_dir)
    if marker.is_symlink() or not marker.is_file():
        return False
    try:
        marker_text = marker.read_text(encoding="utf-8")
    except OSError:
        return False
    expected = _config_digest(text)
    values: dict[str, str] = {}
    for raw_line in marker_text.splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()
    return values.get("version") == "1" and values.get("sha256") == expected


def _write_acceptance_marker(config_dir: pathlib.Path, text: str) -> None:
    marker = reticulum_acceptance_path(config_dir)
    if marker.is_symlink():
        raise ReticulumConfigError(
            f"Refusing symlinked Reticulum config acceptance marker: {marker}"
        )
    marker_text = f"version = 1\nsha256 = {_config_digest(text)}\n"
    tmp_path = config_dir / f".accepted.tmp.{os.getpid()}.{time.time_ns()}"
    fd = os.open(tmp_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(marker_text.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, marker)
        _chmod_private(marker, 0o600)
    except Exception:
        try:
            tmp_path.unlink()
        except OSError:
            pass
        raise


def _chmod_private(path: pathlib.Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except PermissionError as exc:
        raise ReticulumConfigError(f"Could not secure Reticulum config path {path}") from exc
