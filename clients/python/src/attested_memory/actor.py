"""The signed actor identity every protected Attested Memory call carries.

Wire format (the same in the Memory Market, the SaaS gateway and the product shells):

* ``X-Actor-ID``         ``did:actor:`` + hex SHA-256 of the raw Ed25519 public key (74 chars)
* ``X-Actor-Public-Key`` the raw 32-byte public key, base64url
* ``X-Actor-Timestamp``  unix seconds; the server accepts five minutes of skew
* ``X-Actor-Nonce``      16-64 url-safe characters, good for exactly one request
* ``X-Actor-Signature``  Ed25519 over ``<actor id>\\n<timestamp>\\n<nonce>``, base64url

A captured header set therefore replays nowhere: it is bound to one nonce and expires.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _from_b64url(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class Actor:
    """An Ed25519 identity. The private key never leaves this object or its key file."""

    def __init__(self, private_key: Ed25519PrivateKey) -> None:
        self._key = private_key
        self._public = private_key.public_key().public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )

    @classmethod
    def generate(cls) -> "Actor":
        return cls(Ed25519PrivateKey.generate())

    @classmethod
    def from_seed(cls, seed_b64url: str) -> "Actor":
        seed = _from_b64url(seed_b64url)
        if len(seed) != 32:
            raise ValueError("an actor seed is 32 bytes")
        return cls(Ed25519PrivateKey.from_private_bytes(seed))

    @classmethod
    def load(cls, path: str | os.PathLike[str]) -> "Actor":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        actor = cls.from_seed(data["seed"])
        if data.get("actor_id") and data["actor_id"] != actor.actor_id:
            raise ValueError(f"{path}: actor_id does not match the stored key")
        return actor

    def save(self, path: str | os.PathLike[str]) -> Path:
        """Write the key file with mode 0600; refuses to overwrite an existing one."""
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        seed = self._key.private_bytes(
            serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()
        )
        body = json.dumps({"actor_id": self.actor_id, "seed": _b64url(seed)}, indent=2) + "\n"
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            stream.write(body)
        return target

    @property
    def public_key(self) -> str:
        return _b64url(self._public)

    @property
    def actor_id(self) -> str:
        return "did:actor:" + hashlib.sha256(self._public).hexdigest()

    def proof_headers(self, *, now: float | None = None, nonce: str | None = None) -> dict[str, str]:
        """Fresh headers for ONE request (a new nonce each call)."""
        timestamp = str(int(time.time() if now is None else now))
        nonce = nonce or secrets.token_urlsafe(24)
        message = f"{self.actor_id}\n{timestamp}\n{nonce}".encode()
        return {
            "X-Actor-ID": self.actor_id,
            "X-Actor-Public-Key": self.public_key,
            "X-Actor-Timestamp": timestamp,
            "X-Actor-Nonce": nonce,
            "X-Actor-Signature": _b64url(self._key.sign(message)),
        }
