"""Signed release manifest checking and desktop update helpers."""
from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import tarfile
import tempfile
import typing
import urllib.error
import urllib.request

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey

from talon_core.session import CorePaths
from talon_core.version import current_app_version

DEFAULT_MANIFEST_URL = (
    "https://github.com/cudafish-maker/TALON/releases/latest/download/"
    "talon-update.json"
)
DEFAULT_SIGNATURE_URL = DEFAULT_MANIFEST_URL + ".sig"
DEFAULT_VERIFY_KEY_B64 = "IC49mOp4CKj4Kr2sVpluiMlJsuMYNngEhpktRIX4630="
DEFAULT_TIMEOUT_S = 8.0

MANIFEST_SCHEMA = 1
SUPPORTED_CHANNEL = "stable"
SUPPORTED_PLATFORMS = {"linux", "windows"}
SUPPORTED_ROLES = {"client", "server"}


class UpdateError(RuntimeError):
    """Raised when update metadata, download, or staging fails."""


@dataclasses.dataclass(frozen=True)
class Version:
    parts: tuple[int, int, int]
    prerelease: tuple[str, ...] = ()


@dataclasses.dataclass(frozen=True)
class UpdateAsset:
    role: typing.Literal["client", "server"]
    platform: typing.Literal["linux", "windows"]
    filename: str
    sha256: str
    size: int
    url: str


@dataclasses.dataclass(frozen=True)
class UpdateManifest:
    schema: int
    version: str
    tag: str
    channel: str
    compat: dict[str, typing.Any]
    assets: tuple[UpdateAsset, ...]


@dataclasses.dataclass(frozen=True)
class UpdateCheckResult:
    manifest: UpdateManifest
    asset: UpdateAsset | None
    current_version: str
    latest_version: str
    update_available: bool
    compatibility_warning: str = ""


@dataclasses.dataclass(frozen=True)
class DownloadedUpdate:
    result: UpdateCheckResult
    artifact_path: pathlib.Path
    temp_root: pathlib.Path


def platform_key() -> str:
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform.startswith("win"):
        return "windows"
    return sys.platform


def update_checks_enabled(cfg: typing.Any) -> bool:
    raw = cfg.get("updates", "enabled", fallback="true").strip().lower()
    if os.environ.get("TALON_DISABLE_UPDATE_CHECK", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        return False
    return raw not in {"0", "false", "no", "off"}


def parse_version(value: str) -> Version:
    raw = value.strip()
    if raw.startswith("v"):
        raw = raw[1:]
    main, sep, suffix = raw.partition("-")
    fields = main.split(".")
    if not 1 <= len(fields) <= 3:
        raise UpdateError(f"Invalid version: {value!r}")
    parts: list[int] = []
    for field in fields:
        if not field.isdigit():
            raise UpdateError(f"Invalid version: {value!r}")
        parts.append(int(field))
    while len(parts) < 3:
        parts.append(0)
    prerelease = tuple(suffix.split(".")) if sep else ()
    return Version(tuple(parts), prerelease)


def compare_versions(left: str, right: str) -> int:
    left_v = parse_version(left)
    right_v = parse_version(right)
    if left_v.parts < right_v.parts:
        return -1
    if left_v.parts > right_v.parts:
        return 1
    if left_v.prerelease == right_v.prerelease:
        return 0
    if not left_v.prerelease:
        return 1
    if not right_v.prerelease:
        return -1
    return -1 if left_v.prerelease < right_v.prerelease else 1


def fetch_bytes(url: str, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"User-Agent": f"TALON/{current_app_version()}"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Could not fetch {url}: {exc}") from exc


def verify_manifest_signature(
    manifest_bytes: bytes,
    signature_bytes: bytes,
    public_key_b64: str,
) -> None:
    try:
        verify_key = VerifyKey(base64.b64decode(public_key_b64, validate=True))
    except Exception as exc:
        raise UpdateError("Invalid update verification key") from exc
    try:
        verify_key.verify(manifest_bytes, signature_bytes)
    except BadSignatureError as exc:
        raise UpdateError("Update manifest signature verification failed") from exc


def parse_manifest(manifest_bytes: bytes) -> UpdateManifest:
    try:
        raw = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise UpdateError(f"Invalid update manifest JSON: {exc}") from exc
    if not isinstance(raw, dict):
        raise UpdateError("Update manifest must be a JSON object")
    if raw.get("schema") != MANIFEST_SCHEMA:
        raise UpdateError(f"Unsupported update manifest schema: {raw.get('schema')!r}")
    version = _required_str(raw, "version")
    tag = _required_str(raw, "tag")
    channel = _required_str(raw, "channel")
    if channel != SUPPORTED_CHANNEL:
        raise UpdateError(f"Unsupported update channel: {channel!r}")
    parse_version(version)
    if not tag:
        raise UpdateError("Update manifest tag is required")
    compat = raw.get("compat")
    if not isinstance(compat, dict):
        raise UpdateError("Update manifest compat must be an object")
    assets_raw = raw.get("assets")
    if not isinstance(assets_raw, list):
        raise UpdateError("Update manifest assets must be a list")
    assets = tuple(_parse_asset(item) for item in assets_raw)
    return UpdateManifest(
        schema=MANIFEST_SCHEMA,
        version=version,
        tag=tag,
        channel=channel,
        compat=dict(compat),
        assets=assets,
    )


def check_for_update(
    *,
    role: typing.Literal["client", "server"],
    manifest_url: str = DEFAULT_MANIFEST_URL,
    signature_url: str | None = None,
    public_key_b64: str = DEFAULT_VERIFY_KEY_B64,
    current_version: str | None = None,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    platform: str | None = None,
) -> UpdateCheckResult:
    signature_url = signature_url or (manifest_url + ".sig")
    manifest_bytes = fetch_bytes(manifest_url, timeout_s=timeout_s)
    signature_bytes = fetch_bytes(signature_url, timeout_s=timeout_s)
    verify_manifest_signature(manifest_bytes, signature_bytes, public_key_b64)
    manifest = parse_manifest(manifest_bytes)
    local_version = current_version or current_app_version()
    target_platform = platform or platform_key()
    asset = select_asset(manifest, role=role, platform=target_platform)
    update_available = compare_versions(manifest.version, local_version) > 0
    warning = compatibility_warning(manifest, role=role, current_version=local_version)
    return UpdateCheckResult(
        manifest=manifest,
        asset=asset,
        current_version=local_version,
        latest_version=manifest.version,
        update_available=update_available,
        compatibility_warning=warning,
    )


def select_asset(
    manifest: UpdateManifest,
    *,
    role: str,
    platform: str,
) -> UpdateAsset | None:
    for asset in manifest.assets:
        if asset.role == role and asset.platform == platform:
            return asset
    return None


def compatibility_warning(
    manifest: UpdateManifest,
    *,
    role: str,
    current_version: str,
) -> str:
    key = "min_server" if role == "server" else "min_client"
    minimum = manifest.compat.get(key)
    if isinstance(minimum, str) and compare_versions(current_version, minimum) < 0:
        return (
            f"This TALON {role} version is below the release's minimum "
            f"recommended version ({minimum}). Some features may not work correctly."
        )
    return ""


def download_update(
    result: UpdateCheckResult,
    *,
    timeout_s: float = 60.0,
    temp_root: pathlib.Path | None = None,
) -> DownloadedUpdate:
    asset = result.asset
    if asset is None:
        raise UpdateError("No matching update artifact is available")
    root = temp_root or pathlib.Path(tempfile.mkdtemp(prefix="talon-update-"))
    root.mkdir(parents=True, exist_ok=True)
    artifact_path = root / asset.filename
    _download_asset(asset, artifact_path, timeout_s=timeout_s)
    return DownloadedUpdate(result=result, artifact_path=artifact_path, temp_root=root)


def spawn_installer_and_restart(
    downloaded: DownloadedUpdate,
    *,
    role: typing.Literal["client", "server"],
    paths: CorePaths,
    parent_pid: int | None = None,
    platform: str | None = None,
) -> None:
    target_platform = platform or platform_key()
    pid = parent_pid or os.getpid()
    if target_platform == "linux":
        _spawn_linux_installer(downloaded, role=role, parent_pid=pid)
        return
    if target_platform == "windows":
        _spawn_windows_installer(downloaded, role=role, paths=paths, parent_pid=pid)
        return
    raise UpdateError(f"Unsupported update platform: {target_platform!r}")


def linux_install_manifest_path(role: str) -> pathlib.Path:
    state_home = os.environ.get("XDG_STATE_HOME", "").strip()
    base = pathlib.Path(state_home) if state_home else pathlib.Path.home() / ".local" / "state"
    return base / "talon" / f"desktop-{role}.install"


def read_linux_install_manifest(role: str) -> dict[str, str]:
    path = linux_install_manifest_path(role)
    if not path.exists():
        raise UpdateError(f"Linux install manifest was not found: {path}")
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    if values.get("role") != role:
        raise UpdateError("Linux install manifest role does not match this TALON app")
    for key in ("bundle", "launcher", "config", "data", "rns", "documents"):
        if not values.get(key):
            raise UpdateError(f"Linux install manifest is missing {key!r}")
    return values


def _parse_asset(raw: object) -> UpdateAsset:
    if not isinstance(raw, dict):
        raise UpdateError("Update manifest asset must be an object")
    role = _required_str(raw, "role")
    platform = _required_str(raw, "platform")
    if role not in SUPPORTED_ROLES:
        raise UpdateError(f"Unsupported update asset role: {role!r}")
    if platform not in SUPPORTED_PLATFORMS:
        raise UpdateError(f"Unsupported update asset platform: {platform!r}")
    filename = pathlib.PurePath(_required_str(raw, "filename")).name
    if not filename:
        raise UpdateError("Update asset filename is required")
    sha256 = _required_str(raw, "sha256").lower()
    if len(sha256) != 64 or any(c not in "0123456789abcdef" for c in sha256):
        raise UpdateError(f"Invalid SHA-256 for update asset {filename!r}")
    size = raw.get("size")
    if not isinstance(size, int) or size < 0:
        raise UpdateError(f"Invalid size for update asset {filename!r}")
    url = _required_str(raw, "url")
    if not url:
        raise UpdateError(f"Update asset {filename!r} is missing its URL")
    return UpdateAsset(
        role=typing.cast(typing.Literal["client", "server"], role),
        platform=typing.cast(typing.Literal["linux", "windows"], platform),
        filename=filename,
        sha256=sha256,
        size=size,
        url=url,
    )


def _required_str(raw: dict[str, typing.Any], key: str) -> str:
    value = raw.get(key)
    if not isinstance(value, str):
        raise UpdateError(f"Update manifest field {key!r} must be a string")
    return value.strip()


def _download_asset(asset: UpdateAsset, destination: pathlib.Path, *, timeout_s: float) -> None:
    request = urllib.request.Request(
        asset.url,
        headers={"User-Agent": f"TALON/{current_app_version()}"},
    )
    digest = hashlib.sha256()
    bytes_read = 0
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            with destination.open("wb") as handle:
                while True:
                    chunk = response.read(1024 * 1024)
                    if not chunk:
                        break
                    bytes_read += len(chunk)
                    digest.update(chunk)
                    handle.write(chunk)
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise UpdateError(f"Could not download update artifact: {exc}") from exc
    actual = digest.hexdigest()
    if actual != asset.sha256:
        destination.unlink(missing_ok=True)
        raise UpdateError(
            f"Update artifact checksum mismatch: expected {asset.sha256}, got {actual}"
        )
    if asset.size and bytes_read != asset.size:
        destination.unlink(missing_ok=True)
        raise UpdateError(
            f"Update artifact size mismatch: expected {asset.size}, got {bytes_read}"
        )


def _spawn_linux_installer(
    downloaded: DownloadedUpdate,
    *,
    role: typing.Literal["client", "server"],
    parent_pid: int,
) -> None:
    manifest = read_linux_install_manifest(role)
    temp_root = downloaded.temp_root
    extract_root = temp_root / "extract"
    extract_root.mkdir(parents=True, exist_ok=True)
    try:
        with tarfile.open(downloaded.artifact_path, "r:gz") as archive:
            _safe_extract_tar(archive, extract_root)
    except (tarfile.TarError, OSError) as exc:
        raise UpdateError(f"Could not extract Linux update artifact: {exc}") from exc

    bundle_dir = extract_root / f"talon-desktop-{role}-linux"
    installer = bundle_dir / "install.sh"
    if not installer.exists():
        raise UpdateError(f"Linux update artifact is missing install.sh: {installer}")

    install_prefix = pathlib.Path(manifest["bundle"]).parent
    launcher = pathlib.Path(manifest["launcher"])
    log_path = temp_root / "install.log"
    helper = temp_root / "run-linux-update.sh"
    helper.write_text(
        "\n".join(
            [
                "#!/usr/bin/env bash",
                "set -Eeuo pipefail",
                f"parent_pid={parent_pid}",
                "while kill -0 \"$parent_pid\" 2>/dev/null; do sleep 0.2; done",
                f"cd {_sh_quote(str(bundle_dir))}",
                (
                    "bash ./install.sh --yes --no-deps "
                    f"--prefix {_sh_quote(str(install_prefix))} "
                    f"--bin-dir {_sh_quote(str(launcher.parent))} "
                    f"--config {_sh_quote(manifest['config'])} "
                    f"--data-dir {_sh_quote(manifest['data'])} "
                    f"--rns-dir {_sh_quote(manifest['rns'])} "
                    f"--documents-dir {_sh_quote(manifest['documents'])} "
                    f"{_sh_quote(str(bundle_dir))} "
                    f">> {_sh_quote(str(log_path))} 2>&1"
                ),
                (
                    f"if [ -x {_sh_quote(str(launcher))} ]; then "
                    f"nohup {_sh_quote(str(launcher))} >/dev/null 2>&1 & "
                    "fi"
                ),
                f"rm -rf {_sh_quote(str(temp_root))}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    helper.chmod(0o700)
    subprocess.Popen(
        ["bash", str(helper)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _spawn_windows_installer(
    downloaded: DownloadedUpdate,
    *,
    role: typing.Literal["client", "server"],
    paths: CorePaths,
    parent_pid: int,
) -> None:
    if not sys.platform.startswith("win"):
        raise UpdateError("Windows update staging is only available on Windows")
    install_root = pathlib.Path(sys.executable).resolve().parent
    launch = install_root / "talon-desktop.exe"
    runtime = install_root / "tools" / "talon-runtime.ps1"
    if not launch.exists():
        raise UpdateError(f"Installed TALON executable was not found: {launch}")
    if not runtime.exists():
        raise UpdateError(f"Installed TALON runtime helper was not found: {runtime}")
    script = downloaded.temp_root / "run-windows-update.ps1"
    script.write_text(
        "\n".join(
            [
                "$ErrorActionPreference = \"Stop\"",
                "Set-StrictMode -Version Latest",
                f"$ParentPid = {parent_pid}",
                f"$Installer = {_ps_quote(str(downloaded.artifact_path))}",
                f"$Role = {_ps_quote(role)}",
                f"$DataRoot = {_ps_quote(str(paths.data_dir))}",
                f"$Launch = {_ps_quote(str(launch))}",
                f"$Runtime = {_ps_quote(str(runtime))}",
                f"$TempRoot = {_ps_quote(str(downloaded.temp_root))}",
                "try { Wait-Process -Id $ParentPid -ErrorAction SilentlyContinue } catch {}",
                (
                    "$installArgs = @('/VERYSILENT', '/SUPPRESSMSGBOXES', "
                    "'/NORESTART')"
                ),
                (
                    "$process = Start-Process -FilePath $Installer "
                    "-ArgumentList $installArgs -Verb RunAs -Wait -PassThru"
                ),
                "if ($process.ExitCode -ne 0) { exit $process.ExitCode }",
                (
                    "Start-Process -FilePath 'powershell.exe' "
                    "-ArgumentList @('-NoProfile', '-ExecutionPolicy', 'Bypass', "
                    "'-File', $Runtime, '-Role', $Role, '-DataRoot', $DataRoot, "
                    "'-Launch', $Launch)"
                ),
                "Remove-Item -LiteralPath $TempRoot -Recurse -Force -ErrorAction SilentlyContinue",
                "",
            ]
        ),
        encoding="utf-8",
    )
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _safe_extract_tar(archive: tarfile.TarFile, destination: pathlib.Path) -> None:
    dest = destination.resolve()
    for member in archive.getmembers():
        member_path = (destination / member.name).resolve()
        if not str(member_path).startswith(str(dest) + os.sep):
            raise UpdateError(f"Unsafe path in update archive: {member.name}")
    archive.extractall(destination)


def _sh_quote(value: str) -> str:
    return "'" + value.replace("'", "'\"'\"'") + "'"


def _ps_quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"
