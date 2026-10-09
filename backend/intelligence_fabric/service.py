"""Advisory proposal service with no execution or payment side effects."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from pydantic import ValidationError

from .contracts import (
    Decision, InspectionResult, KnowledgeContract, ModelManifest, Proposal,
    ProposalRequest, SignedKnowledgeContract,
)
from .contract_trust import ContractTrustError, VerifiedContract
from .evidence import EvidenceInspector
from .policy import evaluate_policy
from .providers.ollama_provider import ProviderUnavailable
from .verification import canonical_json_bytes, sha256_hex


class ContractVerifier(Protocol):
    def verify(self, envelope: SignedKnowledgeContract, *, now: datetime) -> VerifiedContract: ...


class ProposalProvider(Protocol):
    async def verify_model_identity(self, *, model_id: str, expected_digest: str) -> bool: ...
    async def generate(self, *, model_id: str, prompt: str, output_schema: type[Proposal]) -> dict: ...


class IntelligenceService:
    """Advisory-only service. There is intentionally no execute method."""

    def __init__(
        self,
        *,
        signed_contract: SignedKnowledgeContract,
        contract_verifier: ContractVerifier,
        manifests: dict[str, ModelManifest],
        evidence_inspector: EvidenceInspector,
        provider: ProposalProvider,
    ):
        self._signed_contract = signed_contract
        self._contract_verifier = contract_verifier
        # Retained for diagnostics and migration tooling only. Runtime decisions use
        # the verifier-returned contract, never this unverified reference.
        self._contract = signed_contract.contract
        self._manifests = dict(manifests)
        self._evidence_inspector = evidence_inspector
        self._provider = provider

    async def propose(self, request: ProposalRequest, *, now: datetime | None = None) -> InspectionResult:
        now = _utc(now or datetime.now(timezone.utc))
        try:
            verified = self._contract_verifier.verify(self._signed_contract, now=now)
        except ContractTrustError:
            raise
        except Exception as exc:
            # An implementation error in the trust verifier is also fail-closed.
            raise ContractTrustError("contract_verifier_failed") from exc

        contract = verified.contract

        def finish(
            model_digest: str,
            decision: Decision,
            reasons: list[str],
            proposal: Proposal | None = None,
        ) -> InspectionResult:
            return self._result(
                request=request,
                contract=contract,
                contract_digest=verified.contract_digest,
                model_digest=model_digest,
                decision=decision,
                reasons=reasons,
                proposal=proposal,
                now=now,
            )

        manifest = self._manifests.get(request.model_id)
        if manifest is None:
            return finish("0" * 64, Decision.HOLD, ["model_manifest_unavailable"])
        if manifest.model_id != request.model_id:
            return finish(manifest.artifact_digest, Decision.REJECTED, ["model_id_mismatch"])
        if request.contract_id != contract.contract_id:
            return finish(manifest.artifact_digest, Decision.REJECTED, ["contract_id_mismatch"])
        if contract.revoked:
            return finish(manifest.artifact_digest, Decision.REJECTED, ["contract_revoked"])
        if now >= contract.valid_until_utc:
            return finish(manifest.artifact_digest, Decision.HOLD, ["contract_expired"])
        if not manifest.approved or manifest.artifact_digest not in contract.approved_model_digests:
            return finish(manifest.artifact_digest, Decision.HOLD, ["model_not_approved_by_contract"])
        if request.target_id not in contract.allowed_targets:
            return finish(manifest.artifact_digest, Decision.REJECTED, ["target_not_allowed"])
        if request.telemetry.target_id != request.target_id:
            return finish(manifest.artifact_digest, Decision.REJECTED, ["telemetry_target_mismatch"])

        evidence_reasons = self._evidence_inspector.inspect(
            contract=contract, telemetry=request.telemetry, evidence_refs=request.evidence_refs, now=now
        )
        # Never send stale, unauthenticated, or unapproved evidence to the model.
        if evidence_reasons:
            return finish(manifest.artifact_digest, Decision.HOLD, evidence_reasons)

        # The manifest is only a claim until the local runtime independently reports
        # the same digest. Fail closed before inference if identity cannot be verified.
        try:
            identity_matches = await self._provider.verify_model_identity(
                model_id=manifest.model_id, expected_digest=manifest.artifact_digest
            )
        except ProviderUnavailable:
            return finish(manifest.artifact_digest, Decision.HOLD, ["model_runtime_identity_unavailable"])
        except Exception:
            return finish(manifest.artifact_digest, Decision.HOLD, ["model_runtime_identity_check_failed"])
        if not identity_matches:
            return finish(manifest.artifact_digest, Decision.HOLD, ["model_runtime_identity_mismatch"])

        prompt = (
            "Generate an advisory factory-maintenance proposal. Human review is mandatory. "
            "Use only supplied evidence IDs. Never issue commands or claim authorization.\n"
            + request.prompt_context + "\nEvidence IDs: "
            + ", ".join(request.evidence_refs)
        )
        try:
            raw = await self._provider.generate(
                model_id=manifest.model_id, prompt=prompt, output_schema=Proposal
            )
        except ProviderUnavailable:
            return finish(manifest.artifact_digest, Decision.HOLD, ["provider_unavailable"])
        except Exception:
            return finish(manifest.artifact_digest, Decision.HOLD, ["provider_generation_failed"])

        # Detect tag/model replacement during inference and discard generated output.
        try:
            identity_still_matches = await self._provider.verify_model_identity(
                model_id=manifest.model_id, expected_digest=manifest.artifact_digest
            )
        except Exception:
            return finish(manifest.artifact_digest, Decision.HOLD, ["model_runtime_identity_recheck_failed"])
        if not identity_still_matches:
            return finish(
                manifest.artifact_digest, Decision.HOLD,
                ["model_runtime_identity_changed_during_inference"]
            )

        try:
            proposal = Proposal.model_validate(raw)
        except ValidationError:
            return finish(manifest.artifact_digest, Decision.HOLD, ["proposal_schema_invalid"])

        decision, reasons = evaluate_policy(
            contract=contract, manifest=manifest, request=request, proposal=proposal,
            evidence_reasons=[], now=now,
        )
        return finish(manifest.artifact_digest, decision, reasons, proposal)

    def _result(
        self,
        *,
        request: ProposalRequest,
        contract: KnowledgeContract,
        contract_digest: str,
        model_digest: str,
        decision: Decision,
        reasons: list[str],
        proposal: Proposal | None,
        now: datetime,
    ) -> InspectionResult:
        body = {
            "request_id": request.request_id,
            "decision": decision.value,
            "reasons": sorted(set(reasons)),
            "proposal": proposal.model_dump(mode="json") if proposal else None,
            "contract_id": contract.contract_id,
            "contract_version": contract.contract_version,
            "model_digest": model_digest,
            "contract_digest": contract_digest,
            "policy_id": contract.policy_id,
            "created_at_utc": now.isoformat(),
        }
        digest = sha256_hex(canonical_json_bytes(body))
        return InspectionResult(**body, record_digest=digest)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)
