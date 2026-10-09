from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class Evidence(BaseModel):
    source_uri: str = Field(min_length=1, max_length=2048)
    excerpt_hash: str
    stance: Literal["supports", "refutes", "context"]
    quality: float = Field(default=0.5, ge=0, le=1)
    retrieved_at: str | None = None

    @field_validator("excerpt_hash")
    @classmethod
    def validate_hash(cls, value: str) -> str:
        prefix, separator, digest = value.partition(":")
        if separator != ":" or prefix != "sha256" or len(digest) != 64:
            raise ValueError("excerpt_hash must be sha256:<64 lowercase hex chars>")
        if any(character not in "0123456789abcdef" for character in digest):
            raise ValueError("excerpt_hash must use lowercase hexadecimal")
        return value

    @field_validator("source_uri", "retrieved_at")
    @classmethod
    def bound_text(cls, value: str | None) -> str | None:
        if value is not None and len(value) > 2048:
            raise ValueError("evidence text field is too long")
        return value


class VerifyRequest(BaseModel):
    memory_id: str | None = Field(default=None, max_length=80)
    claim: str = Field(min_length=3, max_length=20_000)
    evidence: list[Evidence] = Field(default_factory=list, max_length=100)


class VerificationResult(BaseModel):
    id: str
    memory_id: str | None
    claim_hash: str
    status: Literal["unverified", "supported", "contested", "rejected"]
    confidence: float
    support_weight: float
    refute_weight: float
    evidence_count: int
    evidence_pack_id: str
    method: str
    created_at: str


class EvidencePack(BaseModel):
    id: str
    memory_id: str | None
    claim: str
    claim_hash: str
    evidence: list[Evidence]
    result: VerificationResult
    pack_hash: str


class ContradictionScanRequest(BaseModel):
    statements: list[str] = Field(min_length=2, max_length=100)

    @field_validator("statements")
    @classmethod
    def bound_statements(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 5000 for value in values):
            raise ValueError("statements must be non-empty and at most 5000 characters")
        return values


class Contradiction(BaseModel):
    left_index: int
    right_index: int
    left: str
    right: str
    reason: str
    confidence: float


class ContradictionScanResult(BaseModel):
    contradictions: list[Contradiction]
    method: str
    disclaimer: str
