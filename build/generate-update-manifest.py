#!/usr/bin/env python3
"""Generate the signed-update manifest input for TALON desktop releases."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ASSETS = (
    ("client", "linux", "talon-desktop-client-linux.tar.gz"),
    ("server", "linux", "talon-desktop-server-linux.tar.gz"),
    ("client", "windows", "talon-desktop-client-windows-setup.exe"),
    ("server", "windows", "talon-desktop-server-windows-setup.exe"),
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dist", type=Path, required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-client", default="0.1.0")
    parser.add_argument("--min-server", default="0.1.0")
    args = parser.parse_args()

    assets = []
    for role, platform, filename in ASSETS:
        path = args.dist / filename
        if not path.exists():
            raise SystemExit(f"Missing release asset: {path}")
        assets.append(
            {
                "role": role,
                "platform": platform,
                "filename": filename,
                "sha256": _sha256(path),
                "size": path.stat().st_size,
                "url": (
                    f"https://github.com/{args.repository}/releases/download/"
                    f"{args.tag}/{filename}"
                ),
            }
        )

    manifest = {
        "schema": 1,
        "version": args.version,
        "tag": args.tag,
        "channel": "stable",
        "compat": {
            "protocol": 1,
            "min_client": args.min_client,
            "min_server": args.min_server,
        },
        "assets": assets,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    raise SystemExit(main())
