#!/usr/bin/env python3
"""Generate an Ed25519 keypair for TALON update manifest signing."""
from __future__ import annotations

import base64

from nacl.signing import SigningKey


def main() -> int:
    signing_key = SigningKey.generate()
    print("TALON_UPDATE_SIGNING_KEY_B64=" + base64.b64encode(bytes(signing_key)).decode("ascii"))
    print("TALON_UPDATE_VERIFY_KEY_B64=" + base64.b64encode(bytes(signing_key.verify_key)).decode("ascii"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
