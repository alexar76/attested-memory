"""The signed actor identity every protected Attested Memory call carries.

Proof v2 signs an explicit destination, HTTP method/path/query and SHA-256 of the
exact request body. A proxy can relay signed targets without gaining authority
to change the operation. Nonces are persisted by the destination service.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from pathlib import Path
from urllib.parse import parse_qsl, unquote, urlsplit

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

    @staticmethod
    def target(audience: str, method: str, path: str, body: bytes = b"") -> dict:
        parsed = urlsplit(path)
        if not audience or not parsed.path.startswith("/") or parsed.scheme or parsed.netloc or parsed.fragment:
            raise ValueError("an actor target needs a destination and an absolute service path")
        return {"audience": audience, "method": method.upper(), "path": unquote(parsed.path),
                "query": [list(pair) for pair in parse_qsl(parsed.query, keep_blank_values=True)],
                "body_sha256": hashlib.sha256(body).hexdigest()}

    def proof_headers(self, *, audience: str | None = None, method: str = "GET", path: str | None = None,
                      body: bytes = b"", targets: list[dict] | None = None,
                      now: float | None = None, nonce: str | None = None) -> dict[str, str]:
        """Sign ONE explicit end-to-end operation; never emit legacy identity bearers.

        For a Team proxy, pass both the Gateway assertion target and the final
        Memory target. At most one operation may be authorized per destination.
        ``body`` is exactly the bytes sent over HTTP, including JSON whitespace.
        """
        if targets is None:
            if not audience or path is None:
                raise ValueError("actor proof v2 requires audience and path")
            targets = [self.target(audience, method, path, body)]
        if not 1 <= len(targets) <= 4 or len({target["audience"] for target in targets}) != len(targets):
            raise ValueError("actor intent needs one explicit target per destination")
        intent = _b64url(json.dumps(targets, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False).encode())
        timestamp = str(int(time.time() if now is None else now))
        nonce = nonce or secrets.token_urlsafe(24)
        message = f"attested-actor/v2\n{self.actor_id}\n{timestamp}\n{nonce}\n{intent}".encode()
        return {
            "X-Actor-Version": "2", "X-Actor-Intent": intent,
            "X-Actor-ID": self.actor_id, "X-Actor-Public-Key": self.public_key,
            "X-Actor-Timestamp": timestamp, "X-Actor-Nonce": nonce,
            "X-Actor-Signature": _b64url(self._key.sign(message)),
        }
