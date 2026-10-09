from __future__ import annotations

import asyncio
import os
import hmac
from contextlib import asynccontextmanager
from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from pydantic import ValidationError

from .aimarket import BY_CAPABILITY, CAPABILITIES, register, signed_protocol_manifest
from .engine import scan_contradictions, verify
from .models import ContradictionScanRequest, ContradictionScanResult, EvidencePack, VerificationResult, VerifyRequest
from .signing import ProviderSigner
from .store import TruthStore


def production_mode() -> bool:
    """Fail CLOSED: production unless the operator says otherwise.

    Every gate here used to switch on ``AIFACTORY_PROD`` being SET, so a deployment that
    forgot the variable — or copied an ``.env.example`` carrying ``AIFACTORY_PROD=0`` —
    ran with no actor verification and no capability authentication, silently. Now an
    explicit ``AIFACTORY_PROD=1`` always wins, and only an explicit ``AIFACTORY_DEV=1``
    turns the checks off. Unset means production.
    """
    if os.getenv("AIFACTORY_PROD", "").strip().lower() in {"1", "true", "yes"}:
        return True
    return os.getenv("AIFACTORY_DEV", "").strip().lower() not in {"1", "true", "yes"}

hub_published = 0


@lru_cache
def provider_signer() -> ProviderSigner:
    return ProviderSigner(os.getenv("PROVIDER_SIGNING_KEY_FILE", "./data/provider-signing-key.pem"))


@asynccontextmanager
async def lifespan(_: FastAPI):
    if production_mode():
        if len(os.getenv("AIMARKET_CAPABILITY_TOKEN", "")) < 32:
            raise RuntimeError("AIMARKET_CAPABILITY_TOKEN must be configured in production")
        if os.getenv("ATTESTED_PQC_ENABLED", "1").strip().lower() not in {"1", "true", "yes"}:
            raise RuntimeError("ATTESTED_PQC_ENABLED cannot be disabled in production")
        if os.getenv("ATTESTED_PQC_REQUIRE", "1").strip().lower() not in {"1", "true", "yes"}:
            raise RuntimeError("ATTESTED_PQC_REQUIRE cannot be disabled in production")
        if not (os.getenv("TRUTH_LAYER_DATABASE_URL") or os.getenv("DATABASE_URL")):
            raise RuntimeError("PostgreSQL DSN is required in production")
        provider_signer()
        store()
    async def publish() -> None:
        global hub_published
        hub_published = await register(provider_signer())

    task = asyncio.create_task(publish())
    yield
    if not task.done():
        task.cancel()
    await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Attested Memory Truth Layer", version="0.2.0", lifespan=lifespan)


def require_service_token(request: Request) -> None:
    if not production_mode():
        return
    expected = os.getenv("AIMARKET_CAPABILITY_TOKEN", "").strip()
    supplied = request.headers.get("x-aimarket-internal-token", "")
    if len(expected) < 32 or not supplied or not hmac.compare_digest(expected, supplied):
        raise HTTPException(status_code=401, detail="internal service authentication required")


@lru_cache
def store() -> TruthStore:
    return TruthStore(os.getenv("TRUTH_LAYER_DB", "./data/truth-layer.sqlite3"))


@app.get("/healthz")
def health(response: Response) -> dict:
    database_ok = True
    try:
        store().connection.execute("SELECT 1")
    except Exception:
        database_ok = False
        response.status_code = 503
    return {
        "status": "ok" if database_ok else "degraded", "service": "truth-layer", "hub_published": hub_published,
        "capabilities": len(CAPABILITIES),
        "database": {"backend": "postgresql" if store().connection.is_postgres else "sqlite", "healthy": database_ok},
        "pqc": "hybrid-ml-dsa-65" if provider_signer().pq_public_key else "classical-only",
    }


@app.post("/v1/memories/verify", response_model=VerificationResult, dependencies=[Depends(require_service_token)])
@app.post("/v1/claims/check", response_model=VerificationResult, dependencies=[Depends(require_service_token)])
def verify_claim(request: VerifyRequest) -> VerificationResult:
    pack = verify(request)
    store().save(pack)
    return pack.result


@app.post("/v1/contradictions/scan", response_model=ContradictionScanResult, dependencies=[Depends(require_service_token)])
def contradictions(request: ContradictionScanRequest) -> ContradictionScanResult:
    return scan_contradictions(request.statements)


@app.get("/v1/evidence-packs/{pack_id}", response_model=EvidencePack, dependencies=[Depends(require_service_token)])
def evidence_pack(pack_id: str) -> EvidencePack:
    try:
        return store().get(pack_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="evidence pack not found") from None


def _public_base(default_port: int) -> str:
    """Where this service can be REACHED from outside, for its own well-known.

    `AIMARKET_INVOKE_BASE` is where the co-located hub DIALS this service — a container
    hostname on a single-host deploy (`http://memory-market:8810`). Using it to describe
    ourselves handed that hostname to everyone who fetched our well-known: a manifest URL
    that resolves on exactly one machine in the world.

    One variable cannot answer both "where do I call you" and "where are you", so
    `AIMARKET_PUBLIC_BASE` answers the second and falls back to the first. A deployment that
    sets nothing behaves exactly as before.
    """
    public = os.getenv("AIMARKET_PUBLIC_BASE", "").strip()
    if public.startswith(("http://", "https://")):
        return public.rstrip("/")
    return os.getenv("AIMARKET_INVOKE_BASE", f"http://localhost:{default_port}").rstrip("/")


@app.get("/.well-known/ai-market.json")
def well_known() -> dict:
    signer = provider_signer()
    base = _public_base(8811)
    return {
        "name": "Truth Layer", "description": "Evidence-bound verification for portable memory.",
        "protocol_versions": ["v2"], "hub_version": "provider-0.2.0",
        "manifest_url": f"{base}/ai-market/v2/manifest",
        "products_count": len(CAPABILITIES), "capabilities_count": len(CAPABILITIES),
        "categories": sorted({item.category for item in CAPABILITIES}),
        "signer_public_key": signer.public_key, "pq_public_key": signer.pq_public_key,
    }


@app.get("/ai-market/v2/manifest")
def protocol_manifest() -> dict:
    return signed_protocol_manifest(provider_signer())


@app.post("/capabilities/{product_id}/{capability_id}/invoke", dependencies=[Depends(require_service_token)])
def invoke_capability(
    product_id: str, capability_id: str, body: dict, request: Request, response: Response
) -> dict:
    capability = BY_CAPABILITY.get(capability_id)
    if capability is None or capability.product_id != product_id:
        raise HTTPException(status_code=404, detail="unknown capability")
    payload = body.get("input", body)
    if not isinstance(payload, dict):
        raise HTTPException(status_code=422, detail="input must be an object")
    try:
        if capability_id in {"memory.verify@v1", "claim.check@v1"}:
            pack = verify(VerifyRequest.model_validate(payload))
            store().save(pack)
            result = pack.result.model_dump(mode="json")
        elif capability_id == "contradiction.scan@v1":
            parsed = ContradictionScanRequest.model_validate(payload)
            result = scan_contradictions(parsed.statements).model_dump(mode="json")
        else:
            result = store().get(str(payload.get("pack_id") or "")).model_dump(mode="json")
    except KeyError:
        raise HTTPException(status_code=404, detail="evidence pack not found") from None
    except ValidationError as error:
        raise HTTPException(status_code=422, detail=error.errors()) from None

    for key, value in provider_signer().response_headers(capability_id, product_id, payload, result).items():
        response.headers[key] = value
    return {
        "success": True, "result": result,
        "crypto": {"hybrid": provider_signer().pq_public_key is not None},
    }
