"""Announce this Hub to both AIMarket and Independent AI federation roots.

An announcement creates a pending observation. It never self-approves trust.
"""

from __future__ import annotations

import json
import os
import random
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

USER_AGENT = "Attested-Memory-Federation-Bootstrap/1.0"


def _origin(value: str, require_https: bool = True) -> str:
    value = value.strip().rstrip("/")
    parsed = urlparse(value)
    schemes = {"https"} if require_https else {"http", "https"}
    if parsed.scheme not in schemes or not parsed.hostname:
        return ""
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        return ""
    return value


def _json(url: str, timeout: float) -> dict:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    with urlopen(request, timeout=timeout) as response:  # noqa: S310 - validated/configured URL
        raw = response.read(1_000_001)
    if len(raw) > 1_000_000:
        raise RuntimeError("discovery document too large")
    body = json.loads(raw)
    if not isinstance(body, dict):
        raise RuntimeError("discovery document is not an object")
    return body


def _post(url: str, payload: dict, timeout: float) -> tuple[int, dict]:
    request = Request(
        url, method="POST", data=json.dumps(payload, separators=(",", ":")).encode(),
        headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    try:
        with urlopen(request, timeout=timeout) as response:  # noqa: S310 - validated HTTPS roots
            raw, status = response.read(256_001), response.status
    except HTTPError as error:
        raw, status = error.read(256_001), error.code
    if len(raw) > 256_000:
        return status, {}
    try:
        body = json.loads(raw) if raw else {}
    except json.JSONDecodeError:
        body = {}
    return status, body if isinstance(body, dict) else {}


def _announce(root: str, public_url: str, well_known: dict, timeout: float) -> bool:
    count = int(well_known.get("capabilities_count") or 0)
    if count < 1:
        raise RuntimeError("waiting for local capability registration")
    payload = {
        "hub_url": public_url,
        "well_known_url": f"{public_url}/.well-known/ai-market.json",
        "hub_name": str(well_known.get("name") or "Attested Memory Hub")[:128],
        "capabilities_count": count,
        "signer_public_key": str(well_known.get("signer_public_key") or "")[:128],
    }
    status, body = _post(f"{root}/ai-market/v2/federation/announce", payload, timeout)
    if 200 <= status < 300 and body.get("acknowledged") is True:
        print(f"federation-bootstrap: {root} acknowledged {public_url} ({body.get('status', 'pending')})", flush=True)
        return True
    raise RuntimeError(f"{root} returned HTTP {status}: {body.get('detail') or 'no detail'}")


def main() -> int:
    public_url = _origin(os.getenv("AIMARKET_PUBLIC_HUB_URL", ""))
    if not public_url or (urlparse(public_url).hostname or "") in {"localhost", "127.0.0.1", "::1"}:
        print("federation-bootstrap: local mode; public HTTPS hub URL is required", flush=True)
        return 0
    local_url = _origin(os.getenv("AIMARKET_BOOTSTRAP_LOCAL_URL", "http://hub:9083"), require_https=False)
    roots = []
    for raw in os.getenv(
        "AIMARKET_BOOTSTRAP_HUB_URLS",
        "https://modelmarket.dev,https://independentai.network/hub",
    ).split(","):
        root = _origin(raw)
        if root and root != public_url and root not in roots:
            roots.append(root)
    if not local_url or not roots:
        raise SystemExit("invalid local Hub URL or federation roots")

    timeout = max(2.0, float(os.getenv("AIMARKET_BOOTSTRAP_TIMEOUT_S", "10")))
    delay = max(5.0, float(os.getenv("AIMARKET_BOOTSTRAP_RETRY_MIN_S", "30")))
    maximum = max(delay, float(os.getenv("AIMARKET_BOOTSTRAP_RETRY_MAX_S", "3600")))
    pending = set(roots)
    time.sleep(max(0.0, float(os.getenv("AIMARKET_BOOTSTRAP_INITIAL_DELAY_S", "5"))))
    while pending:
        try:
            well_known = _json(f"{local_url}/.well-known/ai-market.json", timeout)
            completed = set()
            for root in pending:
                try:
                    if _announce(root, public_url, well_known, timeout):
                        completed.add(root)
                except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError) as error:
                    print(f"federation-bootstrap: {error}", flush=True)
            pending -= completed
            if pending:
                wait = min(maximum, delay) * random.uniform(0.9, 1.1)
                print(f"federation-bootstrap: retrying {len(pending)} root(s) in {wait:.0f}s", flush=True)
                time.sleep(wait)
                delay = min(maximum, delay * 2)
        except (HTTPError, URLError, TimeoutError, OSError, ValueError, RuntimeError, json.JSONDecodeError) as error:
            wait = min(maximum, delay) * random.uniform(0.9, 1.1)
            print(f"federation-bootstrap: local hub not ready ({error}); retrying in {wait:.0f}s", flush=True)
            time.sleep(wait)
            delay = min(maximum, delay * 2)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
