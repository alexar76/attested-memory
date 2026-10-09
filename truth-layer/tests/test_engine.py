import hashlib

from truth_layer.engine import scan_contradictions, verify
from truth_layer.models import Evidence, VerifyRequest


def evidence(stance: str, quality: float) -> Evidence:
    return Evidence(
        source_uri="https://example.test/evidence",
        excerpt_hash="sha256:" + hashlib.sha256(f"{stance}:{quality}".encode()).hexdigest(),
        stance=stance,
        quality=quality,
    )


def test_supported_pack_is_content_addressed():
    pack = verify(VerifyRequest(
        memory_id="mem_1234567890abcdef12345678",
        claim="The source reports a completed migration.",
        evidence=[evidence("supports", 0.9), evidence("context", 0.4)],
    ))
    assert pack.result.status == "supported"
    assert pack.result.support_weight == 0.9
    assert pack.pack_hash.startswith("sha256:")


def test_competing_evidence_is_contested():
    pack = verify(VerifyRequest(
        claim="The deployment is complete.",
        evidence=[evidence("supports", 0.8), evidence("refutes", 0.5)],
    ))
    assert pack.result.status == "contested"


def test_negated_near_duplicate_is_flagged():
    result = scan_contradictions([
        "The deployment is complete on the production network",
        "The deployment is not complete on the production network",
        "The weather is clear",
    ])
    assert len(result.contradictions) == 1
    assert result.contradictions[0].left_index == 0
