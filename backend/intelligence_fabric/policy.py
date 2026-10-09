"""Provisional deterministic policy for MVD-001; not canonical SPEC-004/CPOL."""
from __future__ import annotations
from datetime import datetime, timezone
from .contracts import Decision, KnowledgeContract, ModelManifest, Proposal, ProposalRequest

def evaluate_policy(*, contract: KnowledgeContract, manifest: ModelManifest, request: ProposalRequest, proposal: Proposal, evidence_reasons: list[str], now: datetime) -> tuple[Decision, list[str]]:
    now = _utc(now)
    if contract.revoked:
        return Decision.REJECTED, ["contract_revoked"]
    if now >= contract.valid_until_utc:
        return Decision.HOLD, ["contract_expired"]
    if not manifest.approved:
        return Decision.HOLD, ["model_manifest_not_approved"]
    if manifest.artifact_digest not in contract.approved_model_digests:
        return Decision.REJECTED, ["model_digest_not_allowed"]
    if request.model_id != manifest.model_id:
        return Decision.REJECTED, ["model_id_mismatch"]
    if request.contract_id != contract.contract_id:
        return Decision.REJECTED, ["contract_id_mismatch"]
    if proposal.contract_version != contract.contract_version:
        return Decision.REJECTED, ["proposal_contract_version_mismatch"]
    if proposal.domain != contract.domain:
        return Decision.REJECTED, ["proposal_domain_mismatch"]
    if proposal.target_id != request.target_id or proposal.target_id not in contract.allowed_targets:
        return Decision.REJECTED, ["target_not_allowed"]
    if proposal.recommendation_type not in contract.allowed_recommendations:
        return Decision.REJECTED, ["recommendation_type_not_allowed"]
    if not proposal.requires_human_review:
        return Decision.REJECTED, ["human_review_required"]
    supplied_ids = set(request.evidence_refs)
    if any(ref not in supplied_ids for ref in proposal.evidence_refs):
        return Decision.REJECTED, ["proposal_references_unknown_evidence"]
    if evidence_reasons:
        return Decision.HOLD, sorted(set(evidence_reasons))
    return Decision.APPROVE_FOR_REVIEW, ["proposal_validated_for_human_review"]

def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)
