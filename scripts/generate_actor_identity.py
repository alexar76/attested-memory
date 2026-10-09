#!/usr/bin/env python3
"""Generate a production actor identity for the Memory Market API.

The private key stays with the actor. The actor ID is the SHA-256 fingerprint
of the public key, so the server can verify the binding without a shared secret.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("actor_id", help="stable label, for example billing-agent-1")
    parser.add_argument("--private-key", type=Path, required=True, help="0600 output file for the private key")
    args = parser.parse_args()

    private = Ed25519PrivateKey.generate()
    raw_private = private.private_bytes(
        serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
    )
    raw_public = private.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    actor = "did:actor:" + hashlib.sha256(raw_public).hexdigest()
    args.private_key.parent.mkdir(parents=True, exist_ok=True)
    args.private_key.write_text(b64(raw_private) + "\n", encoding="ascii")
    args.private_key.chmod(0o600)
    print(json.dumps({"actor_id": actor, "public_key": b64(raw_public), "label": args.actor_id}, indent=2))
    print("Sign the exact actor_id string with the private key and send base64url signature in X-Actor-Signature.")


if __name__ == "__main__":
    main()
