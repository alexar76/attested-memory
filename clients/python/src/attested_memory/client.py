"""HTTP client for the public Attested Memory API (Personal Memory product).

    actor = Actor.generate()
    client = Client(actor)
    client.start_trial()                      # 7-day personal key, bound to this actor
    unit = client.write("Supplier terms", "Net 30, EUR, signed 2026-09-01", tags=["finance"])
    client.read(unit["id"])                   # content checked against its content_hash
"""

from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

from . import __version__
from .actor import Actor

DEFAULT_BASE_URL = "https://attestedmemory.net"


class AttestedMemoryError(Exception):
    """The service refused or failed a request; ``status`` is the HTTP code (0 = network)."""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"HTTP {status}: {detail}" if status else detail)
        self.status = status
        self.detail = detail


class IntegrityError(AttestedMemoryError):
    """A memory's content does not hash to the content_hash the service reported."""


def content_hash(content: str) -> str:
    """The Memory Market's hash of a memory's text: ``sha256:`` + hex."""
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def check_integrity(unit: dict[str, Any]) -> dict[str, Any]:
    """Raise IntegrityError unless ``unit['content']`` hashes to ``unit['content_hash']``.

    This is checked here, on the client, not taken from the service. The truth and
    provenance states in the same object are what the hub reports.
    """
    if "content" in unit and unit.get("content_hash") != content_hash(unit["content"]):
        raise IntegrityError(0, f"memory {unit.get('id')}: content does not match its content_hash")
    return unit


class Client:
    def __init__(self, actor: Actor, api_key: str | None = None, *,
                 base_url: str = DEFAULT_BASE_URL, timeout: float = 20.0) -> None:
        self.actor = actor
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # --- account -------------------------------------------------------------------------
    def start_trial(self, product: str = "personal") -> dict[str, Any]:
        """Claim the free trial key for this actor (one per actor and product) and keep it."""
        result = self._request("POST", "/api/v1/trials", {"product": product}, need_key=False)
        self.api_key = result.get("api_key") or self.api_key
        return result

    def key_status(self, product: str = "personal") -> dict[str, Any]:
        return self._request("GET", "/api/v1/keys/me?" + urllib.parse.urlencode({"product": product}))

    # --- memory --------------------------------------------------------------------------
    def write(self, title: str, content: str, *, tags: Iterable[str] = (), visibility: str = "private",
              source_refs: Iterable[str] = (), parent_memory_ids: Iterable[str] = (),
              price_usdc: str | None = None) -> dict[str, Any]:
        body = {"title": title, "content": content, "tags": list(tags), "visibility": visibility,
                "source_refs": list(source_refs), "parent_memory_ids": list(parent_memory_ids),
                "price_usdc": price_usdc}
        return check_integrity(self._request("POST", "/memory/api/memories", body))

    def read(self, memory_id: str) -> dict[str, Any]:
        path = "/memory/api/memories/" + urllib.parse.quote(memory_id, safe="")
        return check_integrity(self._request("GET", path))

    def search(self, query: str = "", limit: int = 30) -> dict[str, Any]:
        params = urllib.parse.urlencode({"q": query, "limit": max(1, min(int(limit), 100))})
        return self._request("GET", "/memory/api/search?" + params)

    # --- transport -----------------------------------------------------------------------
    def _request(self, method: str, path: str, body: dict[str, Any] | None = None, *,
                 need_key: bool = True) -> Any:
        headers = {"Accept": "application/json", "User-Agent": f"attested-memory-python/{__version__}",
                   **self.actor.proof_headers()}
        if need_key:
            if not self.api_key:
                raise AttestedMemoryError(0, "no API key: call start_trial() or pass api_key")
            headers["X-SaaS-Key"] = self.api_key
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(self.base_url + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as error:
            raise AttestedMemoryError(error.code, _detail(error.read())) from None
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            raise AttestedMemoryError(0, f"cannot reach {self.base_url}: {error}") from None
        return json.loads(raw) if raw else {}


def _detail(raw: bytes) -> str:
    try:
        payload = json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")[:300]
    detail = payload.get("detail") if isinstance(payload, dict) else None
    return str(detail if detail is not None else payload)[:300]
