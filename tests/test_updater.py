"""Tests for signed TALON desktop update metadata."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path

import pytest
from nacl.signing import SigningKey

from talon_desktop import updater


def _signing_pair() -> tuple[SigningKey, str]:
    signing_key = SigningKey.generate()
    public_key = base64.b64encode(bytes(signing_key.verify_key)).decode("ascii")
    return signing_key, public_key


def _manifest(asset_path: Path, *, version: str = "0.2.0") -> dict:
    data = asset_path.read_bytes()
    return {
        "schema": 1,
        "version": version,
        "tag": f"v{version}",
        "channel": "stable",
        "compat": {"protocol": 1, "min_client": "0.1.0", "min_server": "0.1.0"},
        "assets": [
            {
                "role": "client",
                "platform": "linux",
                "filename": asset_path.name,
                "sha256": hashlib.sha256(data).hexdigest(),
                "size": len(data),
                "url": asset_path.as_uri(),
            }
        ],
    }


def _write_signed_manifest(tmp_path: Path, manifest: dict, signing_key: SigningKey) -> Path:
    manifest_path = tmp_path / "talon-update.json"
    manifest_bytes = json.dumps(manifest, sort_keys=True).encode("utf-8")
    manifest_path.write_bytes(manifest_bytes)
    (tmp_path / "talon-update.json.sig").write_bytes(
        signing_key.sign(manifest_bytes).signature
    )
    return manifest_path


def test_check_for_update_finds_newer_matching_asset(tmp_path: Path) -> None:
    signing_key, public_key = _signing_pair()
    asset = tmp_path / "talon-desktop-client-linux.tar.gz"
    asset.write_bytes(b"new-release")
    manifest_path = _write_signed_manifest(tmp_path, _manifest(asset), signing_key)

    result = updater.check_for_update(
        role="client",
        platform="linux",
        manifest_url=manifest_path.as_uri(),
        public_key_b64=public_key,
        current_version="0.1.0",
    )

    assert result.update_available is True
    assert result.asset is not None
    assert result.asset.filename == asset.name


def test_check_for_update_ignores_current_or_older_version(tmp_path: Path) -> None:
    signing_key, public_key = _signing_pair()
    asset = tmp_path / "talon-desktop-client-linux.tar.gz"
    asset.write_bytes(b"same-release")
    manifest_path = _write_signed_manifest(
        tmp_path,
        _manifest(asset, version="0.1.0"),
        signing_key,
    )

    result = updater.check_for_update(
        role="client",
        platform="linux",
        manifest_url=manifest_path.as_uri(),
        public_key_b64=public_key,
        current_version="0.1.0",
    )

    assert result.update_available is False


def test_check_for_update_rejects_bad_signature(tmp_path: Path) -> None:
    signing_key, _public_key = _signing_pair()
    _wrong_signing_key, wrong_public_key = _signing_pair()
    asset = tmp_path / "talon-desktop-client-linux.tar.gz"
    asset.write_bytes(b"new-release")
    manifest_path = _write_signed_manifest(tmp_path, _manifest(asset), signing_key)

    with pytest.raises(updater.UpdateError, match="signature"):
        updater.check_for_update(
            role="client",
            platform="linux",
            manifest_url=manifest_path.as_uri(),
            public_key_b64=wrong_public_key,
            current_version="0.1.0",
        )


def test_download_update_rejects_checksum_mismatch(tmp_path: Path) -> None:
    asset_path = tmp_path / "talon-desktop-client-linux.tar.gz"
    asset_path.write_bytes(b"actual")
    manifest = updater.UpdateManifest(
        schema=1,
        version="0.2.0",
        tag="v0.2.0",
        channel="stable",
        compat={},
        assets=(
            updater.UpdateAsset(
                role="client",
                platform="linux",
                filename=asset_path.name,
                sha256="0" * 64,
                size=len(b"actual"),
                url=asset_path.as_uri(),
            ),
        ),
    )
    result = updater.UpdateCheckResult(
        manifest=manifest,
        asset=manifest.assets[0],
        current_version="0.1.0",
        latest_version="0.2.0",
        update_available=True,
    )

    with pytest.raises(updater.UpdateError, match="checksum mismatch"):
        updater.download_update(result, temp_root=tmp_path / "download")


def test_check_for_update_reports_missing_same_role_asset(tmp_path: Path) -> None:
    signing_key, public_key = _signing_pair()
    asset = tmp_path / "talon-desktop-client-linux.tar.gz"
    asset.write_bytes(b"new-release")
    manifest_path = _write_signed_manifest(tmp_path, _manifest(asset), signing_key)

    result = updater.check_for_update(
        role="server",
        platform="linux",
        manifest_url=manifest_path.as_uri(),
        public_key_b64=public_key,
        current_version="0.1.0",
    )

    assert result.update_available is True
    assert result.asset is None


def test_update_config_can_disable_startup_check() -> None:
    import configparser

    cfg = configparser.ConfigParser()
    cfg["updates"] = {"enabled": "false"}

    assert updater.update_checks_enabled(cfg) is False
