#!/usr/bin/env python3
"""Sign TALON update manifests with an Ed25519 signing key."""
from __future__ import annotations

import argparse
import base64
import os
from pathlib import Path

from nacl.signing import SigningKey


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    parser.add_argument("signature", type=Path)
    parser.add_argument(
        "--key-env",
        default="TALON_UPDATE_SIGNING_KEY_B64",
        help="Environment variable containing a base64 Ed25519 seed.",
    )
    args = parser.parse_args()

    key_b64 = os.environ.get(args.key_env, "").strip()
    if not key_b64:
        raise SystemExit(f"Missing signing key environment variable: {args.key_env}")
    try:
        key_bytes = base64.b64decode(key_b64, validate=True)
    except Exception as exc:
        raise SystemExit(f"Signing key is not valid base64: {exc}") from exc
    if len(key_bytes) != 32:
        raise SystemExit("Signing key must be a base64-encoded 32-byte Ed25519 seed")

    signing_key = SigningKey(key_bytes)
    signature = signing_key.sign(args.manifest.read_bytes()).signature
    args.signature.parent.mkdir(parents=True, exist_ok=True)
    args.signature.write_bytes(signature)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
