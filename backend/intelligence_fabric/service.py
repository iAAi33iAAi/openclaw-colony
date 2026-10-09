"""Advisory proposal service with no execution or payment side effects."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Protocol

from pydantic import ValidationError

from .contracts import Decision, InspectionResult, KnowledgeContract, ModelManifest, Proposal, ProposalRequest
from .evidence import EvidenceInspector
from .policy import evaluate_policy
from .providers.ollama_provider import ProviderUnavailable
from .verification import canonical_json_bytes, sha256_hex


class ProposalProvider(Protocol):
    async def verify_model_identity(self, *, model_id: str, expected_digest: str) -> bool: ...
    async def generate(self, *, model_id: str, prompt: str, output_schema: type[Proposal]) -> dict: ...


class IntelligenceService:
    """Advisory-only service. There is intentionally no execute method."""

    def __init__(
        self,
        *,
        contract: KnowledgeContract,
        manifests: dict[str, ModelManifest],
        evidence_inspector: EvidenceInspector,
        provider: ProposalProvider,
    ):
        self._contract = contract
        self._manifests = dict(manifests)
        self._evidence_inspector = evidence_inspector
        self._provider = provider

    async def propose(self, request: ProposalRequest, *, now: datetime | None = None) -> InspectionResult:
        now = _utc(now or datetime.now(timezone.utc))
        manifest = self._manifests.get(request.model_id)
        if manifest is None:
            return self._result(request, "0" * 64, Decision.HOLD, ["model_manifest_unavailable"], None, now)
        if manifest.model_id != request.model_id:
            return self._result(request, manifest.artifact_digest, Decision.REJECTED, ["model_id_mismatch"], None, now)
        if request.contract_id != self._contract.contract_id:
            return self._result(request, manifest.artifact_digest, Decision.REJECTED, ["contract_id_mismatch"], None, now)
        if self._contract.revoked:
            return self._result(request, manifest.artifact_digest, Decision.REJECTED, ["contract_revoked"], None, now)
        if now >= self._contract.valid_until_utc:
            return self._result(request, manifest.artifact_digest, Decision.HOLD, ["contract_expired"], None, now)
        if not manifest.approved or manifest.artifact_digest not in self._contract.approved_model_digests:
            return self._result(request, manifest.artifact_digest, Decision.HOLD, ["model_not_approved_by_contract"], None, now)
        if request.target_id not in self._contract.allowed_targets:
            return self._result(request, manifest.artifact_digest, Decision.REJECTED, ["target_not_allowed"], None, now)
        if request.telemetry.target_id != request.target_id:
            return self._result(request, manifest.artifact_digest, Decision.REJECTED, ["telemetry_target_mismatch"], None, now)

        evidence_reasons = self._evidence_inspector.inspect(
            contract=self._contract, telemetry=request.telemetry, evidence_refs=request.evidence_refs, now=now
        )
        # Never send stale, unauthenticated, or unapproved evidence to the model.
        if evidence_reasons:
            return self._result(request, manifest.artifact_digest, Decision.HOLD, evidence_reasons, None, now)

        # The manifest is only a claim until the local runtime independently reports
        # the same digest. Fail closed before inference if identity cannot be verified.
        try:
            identity_matches = await self._provider.verify_model_identity(
                model_id=manifest.model_id, expected_digest=manifest.artifact_digest
            )
        except ProviderUnavailable:
            return self._result(request, manifest.artifact_digest, Decision.HOLD, ["model_runtime_identity_unavailable"], None, now)
        except Exception:
            return self._result(request, manifest.artifact_digest, Decision.HOLD, ["model_runtime_identity_check_failed"], None, now)
        if not identity_matches:
            return self._result(request, manifest.artifact_digest, Decision.HOLD, ["model_runtime_identity_mismatch"], None, now)

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
            return self._result(request, manifest.artifact_digest, Decision.HOLD, ["provider_unavailable"], None, now)
        except Exception:
            return self._result(request, manifest.artifact_digest, Decision.HOLD, ["provider_generation_failed"], None, now)

        # Detect tag/model replacement during the inference window and discard the
        # untrusted output if the runtime no longer reports the approved digest.
        try:
            identity_still_matches = await self._provider.verify_model_identity(
                model_id=manifest.model_id, expected_digest=manifest.artifact_digest
            )
        except Exception:
            return self._result(request, manifest.artifact_digest, Decision.HOLD, ["model_runtime_identity_recheck_failed"], None, now)
        if not identity_still_matches:
            return self._result(request, manifest.artifact_digest, Decision.HOLD, ["model_runtime_identity_changed_during_inference"], None, now)

        try:
            proposal = Proposal.model_validate(raw)
        except ValidationError:
            return self._result(request, manifest.artifact_digest, Decision.HOLD, ["proposal_schema_invalid"], None, now)

        decision, reasons = evaluate_policy(
            contract=self._contract, manifest=manifest, request=request, proposal=proposal,
            evidence_reasons=[], now=now,
        )
        return self._result(request, manifest.artifact_digest, decision, reasons, proposal, now)

    def _result(
        self,
        request: ProposalRequest,
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
            "contract_id": self._contract.contract_id,
            "contract_version": self._contract.contract_version,
            "model_digest": model_digest,
            "policy_id": self._contract.policy_id,
            "created_at_utc": now.isoformat(),
        }
        digest = sha256_hex(canonical_json_bytes(body))
        return InspectionResult(**body, record_digest=digest)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)
