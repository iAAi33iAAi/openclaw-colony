"""Strict schemas for the advisory-only MVD-001 vertical slice."""
from __future__ import annotations
from datetime import datetime, timezone
from enum import Enum
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator, model_validator

Digest = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$")]
Identifier = Annotated[str, StringConstraints(min_length=1, max_length=160, pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$")]

class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True, validate_assignment=True)

class RecommendationType(str, Enum):
    INSPECT = "INSPECT"
    INVESTIGATE = "INVESTIGATE"
    REQUEST_HUMAN_REVIEW = "REQUEST_HUMAN_REVIEW"

class Decision(str, Enum):
    APPROVE_FOR_REVIEW = "APPROVE_FOR_REVIEW"
    HOLD = "HOLD"
    REJECTED = "REJECTED"

class KnowledgeContract(StrictModel):
    contract_id: Identifier
    contract_version: str = Field(min_length=1, max_length=64)
    domain: str = Field(pattern=r"^[A-Z][A-Z0-9_]{1,63}$")
    agent_id: Identifier
    approved_model_digests: set[Digest] = Field(min_length=1)
    approved_source_ids: set[Identifier] = Field(min_length=1)
    permitted_sensor_ids: set[Identifier] = Field(min_length=1)
    allowed_targets: set[Identifier] = Field(min_length=1)
    allowed_recommendations: set[RecommendationType] = Field(min_length=1)
    prohibited_actions: set[str] = Field(default_factory=set)
    max_telemetry_age_seconds: int = Field(ge=1, le=31536000)
    min_evidence_quality_micros: int = Field(ge=0, le=1000000)
    valid_until_utc: datetime
    revoked: bool = False
    policy_id: Identifier

    @field_validator("valid_until_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("valid_until_utc must include a timezone")
        return value.astimezone(timezone.utc)

class ModelManifest(StrictModel):
    model_id: Identifier
    model_version: str = Field(min_length=1, max_length=128)
    artifact_digest: Digest
    provider: str = Field(pattern=r"^local:[a-z0-9._-]+$")
    approved: bool
    evaluation_suite_id: Identifier

class SignedKnowledgeContract(StrictModel):
    contract: KnowledgeContract
    signer_key_id: Identifier
    issued_at_utc: datetime
    signature_algorithm: Literal["Ed25519"]
    signature_b64: str = Field(min_length=1, max_length=512)

    @field_validator("issued_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("issued_at_utc must include a timezone")
        return value.astimezone(timezone.utc)


class TelemetryRecord(StrictModel):
    sensor_id: Identifier
    target_id: Identifier
    observed_at_utc: datetime
    payload_digest: Digest
    signature: str = Field(min_length=1, max_length=8192)
    signer_key_id: Identifier

    @field_validator("observed_at_utc")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at_utc must include a timezone")
        return value.astimezone(timezone.utc)

class EvidenceRecord(StrictModel):
    evidence_id: Identifier
    source_id: Identifier
    source_revision: str = Field(min_length=1, max_length=128)
    approved: bool
    content_digest: Digest
    manual_reference: str | None = Field(default=None, max_length=256)
    quality_micros: int = Field(ge=0, le=1000000)

class Proposal(StrictModel):
    contract_version: str
    domain: str
    recommendation_type: RecommendationType
    target_id: Identifier
    rationale: str = Field(min_length=1, max_length=4000)
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=64)
    uncertainty_flags: list[str] = Field(default_factory=list, max_length=32)
    requires_human_review: bool = True

    @field_validator("evidence_refs")
    @classmethod
    def unique_evidence_refs(cls, value: list[str]) -> list[str]:
        if len(set(value)) != len(value):
            raise ValueError("evidence_refs must be unique")
        return value

    @model_validator(mode="after")
    def advisory_only(self) -> "Proposal":
        if not self.requires_human_review:
            raise ValueError("MVD-001 proposals must require human review")
        return self

class ProposalRequest(StrictModel):
    request_id: Identifier
    contract_id: Identifier
    model_id: Identifier
    target_id: Identifier
    prompt_context: str = Field(min_length=1, max_length=12000)
    telemetry: TelemetryRecord
    evidence_refs: list[Identifier] = Field(min_length=1, max_length=64)

class InspectionResult(StrictModel):
    request_id: Identifier
    decision: Decision
    reasons: list[str]
    proposal: Proposal | None = None
    contract_id: Identifier
    contract_version: str
    model_digest: Digest
    contract_digest: Digest
    policy_id: Identifier
    created_at_utc: datetime
    record_digest: Digest
