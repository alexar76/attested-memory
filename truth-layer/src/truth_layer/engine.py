from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from uuid import uuid4

from .models import Contradiction, ContradictionScanResult, EvidencePack, VerificationResult, VerifyRequest


def canonical_json(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def verify(request: VerifyRequest) -> EvidencePack:
    support = round(sum(item.quality for item in request.evidence if item.stance == "supports"), 6)
    refute = round(sum(item.quality for item in request.evidence if item.stance == "refutes"), 6)
    decisive = support + refute
    confidence = round(decisive / max(1.0, len(request.evidence)), 4)
    if decisive == 0:
        status = "unverified"
    elif support > 0 and refute > 0 and min(support, refute) / max(support, refute) >= 0.35:
        status = "contested"
    elif support > refute:
        status = "supported"
    else:
        status = "rejected"

    created_at = datetime.now(timezone.utc).isoformat()
    claim_hash = sha256(request.claim)
    pack_id = "pack_" + uuid4().hex[:24]
    result = VerificationResult(
        id="ver_" + uuid4().hex[:24], memory_id=request.memory_id, claim_hash=claim_hash,
        status=status, confidence=confidence, support_weight=support, refute_weight=refute,
        evidence_count=len(request.evidence), evidence_pack_id=pack_id,
        method="submitted-evidence-weight-v1", created_at=created_at,
    )
    pack_payload = {
        "memory_id": request.memory_id,
        "claim": request.claim,
        "claim_hash": claim_hash,
        "evidence": [item.model_dump(mode="json") for item in request.evidence],
        "result": result.model_dump(mode="json"),
    }
    return EvidencePack(
        id=pack_id, memory_id=request.memory_id, claim=request.claim, claim_hash=claim_hash,
        evidence=request.evidence, result=result, pack_hash=sha256(canonical_json(pack_payload)),
    )


NEGATIONS = {"not", "no", "never", "isn't", "aren't", "wasn't", "не", "нет", "никогда"}


def _signature(statement: str) -> tuple[set[str], bool]:
    words = re.findall(r"[\w'-]+", statement.casefold(), flags=re.UNICODE)
    negated = any(word in NEGATIONS for word in words)
    content = {word for word in words if word not in NEGATIONS and len(word) > 2}
    return content, negated


def scan_contradictions(statements: list[str]) -> ContradictionScanResult:
    contradictions: list[Contradiction] = []
    signatures = [_signature(statement) for statement in statements]
    for left_index, (left_words, left_negated) in enumerate(signatures):
        for right_index in range(left_index + 1, len(statements)):
            right_words, right_negated = signatures[right_index]
            union = left_words | right_words
            overlap = len(left_words & right_words) / len(union) if union else 0
            if left_negated != right_negated and overlap >= 0.6:
                contradictions.append(Contradiction(
                    left_index=left_index, right_index=right_index,
                    left=statements[left_index], right=statements[right_index],
                    reason="high lexical overlap with opposite negation",
                    confidence=round(overlap, 3),
                ))
    return ContradictionScanResult(
        contradictions=contradictions,
        method="lexical-negation-v1",
        disclaimer="Indicators only; semantic or real-world contradiction requires further verification.",
    )
