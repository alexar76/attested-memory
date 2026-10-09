from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone

import httpx

from .signing import ProviderSigner


@dataclass(frozen=True)
class Capability:
    product_id: str
    capability_id: str
    name: str
    description: str
    price_usd: float
    category: str
    input_schema: dict


CAPABILITIES = (
    Capability("memory-verify", "memory.verify@v1", "Verify Memory", "Bind a Memory Unit claim to weighted evidence and return a portable evidence-pack reference.", 0.025, "verification/evidence", {"type": "object", "required": ["claim"], "properties": {"memory_id": {"type": "string"}, "claim": {"type": "string"}, "evidence": {"type": "array"}}}),
    Capability("claim-check", "claim.check@v1", "Check Claim", "Evaluate support and refutation weights for a standalone claim.", 0.022, "verification/evidence", {"type": "object", "required": ["claim"], "properties": {"claim": {"type": "string"}, "evidence": {"type": "array"}}}),
    Capability("contradiction-scan", "contradiction.scan@v1", "Scan Contradictions", "Find deterministic lexical-negation conflict indicators across statements.", 0.009, "verification/contradiction", {"type": "object", "required": ["statements"], "properties": {"statements": {"type": "array", "minItems": 2}}}),
    Capability("evidence-pack", "evidence.pack@v1", "Read Evidence Pack", "Return a content-addressed evidence pack by identifier.", 0.006, "verification/evidence", {"type": "object", "required": ["pack_id"], "properties": {"pack_id": {"type": "string"}}}),
)
BY_CAPABILITY = {item.capability_id: item for item in CAPABILITIES}


def payout_address() -> str:
    """Where a buyer paying a check per call in USDC (the hub's x402 "exact" rail) pays it.

    Without one, the hub can sell these checks only on its credits rail: a stranger, or another
    company's agent hiring them per call with no prepaid account, gets "this listing names no
    payout address". Attested's own wallet (PAYMENT_RECIPIENT in the stack's .env)."""
    value = os.getenv("AIMARKET_PAYOUT_ADDRESS", "").strip()
    return value if re.fullmatch(r"0x[0-9a-fA-F]{40}", value) else ""


def manifest(capability: Capability, signer: ProviderSigner) -> dict:
    base = os.getenv("AIMARKET_INVOKE_BASE", "http://truth-layer:8811").rstrip("/")
    publisher = os.getenv("AIMARKET_PUBLISHER_ID", "truth-layer")
    payout = payout_address()
    return {
        "product_id": capability.product_id, "capability_id": capability.capability_id,
        "name": capability.name, "version": "v1", "description": capability.description,
        "invoke_url": f"{base}/capabilities/{capability.product_id}/{capability.capability_id}/invoke",
        "price_per_call_usd": capability.price_usd, "publisher": publisher,
        "publisher_id": publisher, "provider_pubkey": signer.public_key,
        "input_schema": capability.input_schema,
        "output_schema": {"type": "object", "additionalProperties": True},
        "category": capability.category, "p50_latency_ms": 35, "success_rate_30d": 0.99,
        **({"payout_address": payout} if payout else {}),
    }


def signed_protocol_manifest(signer: ProviderSigner) -> dict:
    payload = {"protocol_version": "v2", "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"), "base_url": os.getenv("AIMARKET_INVOKE_BASE", "http://truth-layer:8811").rstrip("/"), "products_count": len(CAPABILITIES), "capabilities_count": len(CAPABILITIES), "tools": [manifest(item, signer) for item in CAPABILITIES]}
    tools_hash = hashlib.sha256(json.dumps(payload["tools"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    canonical = f"capabilities_count:{len(CAPABILITIES)}|generated_at:{payload['generated_at']}|protocol_version:v2|tools_hash:{tools_hash}|by_hub_hash:{hashlib.sha256(b'{}').hexdigest()}"
    payload["signature"] = signer.sign(canonical)
    return payload


async def register(signer: ProviderSigner) -> int:
    hub, token = os.getenv("AIMARKET_HUB_URL", "").rstrip("/"), os.getenv("AIMARKET_PUBLISHER_TOKEN", "")
    if not hub or not token:
        return 0
    async with httpx.AsyncClient(timeout=5) as client:
        for attempt in range(18):
            try:
                if (await client.get(f"{hub}/ai-market/v2/health")).status_code == 200:
                    break
            except httpx.HTTPError:
                pass
            await asyncio.sleep(min(2 + attempt, 8))
        else:
            return 0
        published = 0
        for capability in CAPABILITIES:
            try:
                response = await client.post(f"{hub}/ai-market/v2/supply/register", json=manifest(capability, signer), headers={"Authorization": f"Bearer {token}"})
                response.raise_for_status()
                published += 1
            except httpx.HTTPError:
                continue
        return published
