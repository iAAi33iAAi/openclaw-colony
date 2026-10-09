import base64
from datetime import datetime, timedelta, timezone

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from intelligence_fabric.contracts import (
    Decision, EvidenceRecord, KnowledgeContract, ModelManifest, Proposal,
    ProposalRequest, RecommendationType, SignedKnowledgeContract, TelemetryRecord,
)
from intelligence_fabric.contract_trust import (
    ContractTrustError, Ed25519ContractVerifier, contract_digest, contract_signing_payload,
)
from intelligence_fabric.evidence import EvidenceInspector, InMemoryEvidenceRegistry
from intelligence_fabric.execution_firewall import MVD001ExecutionFirewall
from intelligence_fabric.verification import verify_inspection_result_integrity
from intelligence_fabric.providers.ollama_provider import OllamaProvider
from intelligence_fabric.service import IntelligenceService

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
MODEL_DIGEST = "a" * 64
TELEMETRY_DIGEST = "b" * 64
EVIDENCE_DIGEST = "c" * 64
ISSUER_KEY_ID = "factory-issuer-v1"
ISSUER_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(bytes([19]) * 32)
ISSUER_PUBLIC_KEY = ISSUER_PRIVATE_KEY.public_key().public_bytes(
    encoding=serialization.Encoding.Raw,
    format=serialization.PublicFormat.Raw,
)


def sign_contract(contract: KnowledgeContract, *, issued_at: datetime | None = None) -> SignedKnowledgeContract:
    envelope = SignedKnowledgeContract(
        contract=contract,
        signer_key_id=ISSUER_KEY_ID,
        issued_at_utc=issued_at or (NOW - timedelta(minutes=1)),
        signature_algorithm="Ed25519",
        signature_b64=base64.b64encode(bytes(64)).decode("ascii"),
    )
    signature = ISSUER_PRIVATE_KEY.sign(contract_signing_payload(envelope))
    return envelope.model_copy(update={"signature_b64": base64.b64encode(signature).decode("ascii")})


def make_contract_verifier(*, revoked_key_ids: frozenset[str] = frozenset()) -> Ed25519ContractVerifier:
    return Ed25519ContractVerifier(
        trusted_public_keys={ISSUER_KEY_ID: ISSUER_PUBLIC_KEY},
        revoked_key_ids=revoked_key_ids,
    )


class AcceptSignature:
    def verify(self, *, key_id: str, message: bytes, signature: str) -> bool:
        return key_id == "sensor-key-1" and signature == "test-valid-signature"


class FakeProvider:
    def __init__(self, proposal: dict):
        self.proposal = proposal
        self.calls = 0
        self.runtime_digests: dict[str, str] = {}
        self.swap_digest_after_generate: str | None = None

    async def verify_model_identity(self, *, model_id: str, expected_digest: str) -> bool:
        return self.runtime_digests.get(model_id) == expected_digest

    async def generate(self, *, model_id: str, prompt: str, output_schema: type[Proposal]) -> dict:
        self.calls += 1
        if self.swap_digest_after_generate is not None:
            self.runtime_digests[model_id] = self.swap_digest_after_generate
        return self.proposal


def fixture(*, age_seconds: int = 10, signature: str = "test-valid-signature",
            approved_evidence: bool = True, proposal_target: str = "PUMP-01",
            refs: list[str] | None = None, model_approved: bool = True):
    contract = KnowledgeContract(
        contract_id="KC-FACTORY-0001", contract_version="2.0.0", domain="FACTORY",
        agent_id="factory-maintenance-01", approved_model_digests={MODEL_DIGEST},
        approved_source_ids={"manual-approved-01"}, permitted_sensor_ids={"sensor-01"},
        allowed_targets={"PUMP-01"},
        allowed_recommendations={RecommendationType.INSPECT, RecommendationType.INVESTIGATE,
                                 RecommendationType.REQUEST_HUMAN_REVIEW},
        prohibited_actions={"SHUTDOWN"}, max_telemetry_age_seconds=60,
        min_evidence_quality_micros=800000, valid_until_utc=NOW + timedelta(days=1),
        revoked=False, policy_id="factory-maintenance-demo-v1",
    )
    manifest = ModelManifest(
        model_id="factory-slm", model_version="1.0.0", artifact_digest=MODEL_DIGEST,
        provider="local:ollama", approved=model_approved, evaluation_suite_id="factory-eval-v1",
    )
    telemetry = TelemetryRecord(
        sensor_id="sensor-01", target_id="PUMP-01",
        observed_at_utc=NOW - timedelta(seconds=age_seconds), payload_digest=TELEMETRY_DIGEST,
        signature=signature, signer_key_id="sensor-key-1",
    )
    evidence = EvidenceRecord(
        evidence_id="EVID-001", source_id="manual-approved-01", source_revision="rev-4",
        approved=approved_evidence, content_digest=EVIDENCE_DIGEST,
        manual_reference="MANUAL-PUMP-01", quality_micros=900000,
    )
    proposal = {
        "contract_version": "2.0.0", "domain": "FACTORY", "recommendation_type": "INSPECT",
        "target_id": proposal_target,
        "rationale": "Inspect vibration trend against the approved maintenance manual.",
        "evidence_refs": refs if refs is not None else ["EVID-001"],
        "uncertainty_flags": [], "requires_human_review": True,
    }
    provider = FakeProvider(proposal)
    provider.runtime_digests = {"factory-slm": MODEL_DIGEST}
    registry = InMemoryEvidenceRegistry({"EVID-001": evidence})
    signed_contract = sign_contract(contract)
    service = IntelligenceService(
        signed_contract=signed_contract,
        contract_verifier=make_contract_verifier(),
        manifests={"factory-slm": manifest},
        evidence_inspector=EvidenceInspector(AcceptSignature(), registry), provider=provider,
    )
    request = ProposalRequest(
        request_id="REQ-001", contract_id=contract.contract_id, model_id=manifest.model_id,
        target_id="PUMP-01", prompt_context="Assess synthetic pump vibration telemetry.",
        telemetry=telemetry, evidence_refs=["EVID-001"],
    )
    return service, request, provider


@pytest.mark.asyncio
async def test_valid_proposal_is_advisory_only():
    service, request, _ = fixture()
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.APPROVE_FOR_REVIEW
    assert result.proposal is not None and result.proposal.requires_human_review is True
    assert len(result.record_digest) == 64


@pytest.mark.asyncio
async def test_stale_telemetry_holds_before_inference():
    service, request, provider = fixture(age_seconds=61)
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.HOLD and "telemetry_stale" in result.reasons
    assert result.proposal is None and provider.calls == 0


@pytest.mark.asyncio
async def test_unverified_signature_holds_before_inference():
    service, request, provider = fixture(signature="forged")
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.HOLD and "telemetry_signature_unverified" in result.reasons
    assert result.proposal is None and provider.calls == 0


@pytest.mark.asyncio
async def test_unapproved_evidence_from_registry_holds():
    service, request, provider = fixture(approved_evidence=False)
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.HOLD
    assert "evidence_not_approved:EVID-001" in result.reasons
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_model_fabricated_evidence_reference_is_rejected():
    service, request, _ = fixture(refs=["EVID-FABRICATED"])
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.REJECTED
    assert "proposal_references_unknown_evidence" in result.reasons


@pytest.mark.asyncio
async def test_unauthorized_target_is_rejected():
    service, request, _ = fixture(proposal_target="BREAKER-99")
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.REJECTED and "target_not_allowed" in result.reasons


@pytest.mark.asyncio
async def test_unapproved_model_does_not_infer():
    service, request, provider = fixture(model_approved=False)
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.HOLD and provider.calls == 0


@pytest.mark.asyncio
async def test_unknown_model_fails_closed():
    service, request, provider = fixture()
    request = request.model_copy(update={"model_id": "unknown-model"})
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.HOLD and provider.calls == 0


def test_proposal_cannot_remove_human_review():
    with pytest.raises(ValueError):
        Proposal(
            contract_version="2.0.0", domain="FACTORY", recommendation_type="INSPECT",
            target_id="PUMP-01", rationale="Attempt to bypass review",
            evidence_refs=["EVID-001"], requires_human_review=False,
        )


@pytest.mark.asyncio
async def test_telemetry_target_must_match_request_target():
    service, request, provider = fixture()
    changed_telemetry = request.telemetry.model_copy(update={"target_id": "PUMP-OTHER"})
    request = request.model_copy(update={"telemetry": changed_telemetry})
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.REJECTED
    assert "telemetry_target_mismatch" in result.reasons
    assert provider.calls == 0


def test_ollama_provider_rejects_non_loopback_and_lookalike_hosts():
    with pytest.raises(ValueError):
        OllamaProvider("http://example.com:11434")
    with pytest.raises(ValueError):
        OllamaProvider("http://127.0.0.1.evil.example:11434")
    with pytest.raises(ValueError):
        OllamaProvider("http://localhost.evil.example:11434")


def test_ollama_provider_accepts_loopback():
    assert OllamaProvider("http://127.0.0.1:11434").base_url == "http://127.0.0.1:11434"

@pytest.mark.asyncio
async def test_approved_model_substitution_keeps_contract_permissions():
    service, request, provider = fixture()
    second_digest = "d" * 64
    second_manifest = ModelManifest(
        model_id="factory-slm-v2", model_version="2.0.0", artifact_digest=second_digest,
        provider="local:ollama", approved=True, evaluation_suite_id="factory-eval-v2",
    )
    contract = service._contract.model_copy(update={
        "approved_model_digests": {MODEL_DIGEST, second_digest},
    })
    provider.runtime_digests["factory-slm-v2"] = second_digest
    swapped_service = IntelligenceService(
        signed_contract=sign_contract(contract),
        contract_verifier=make_contract_verifier(),
        manifests={"factory-slm": service._manifests["factory-slm"], "factory-slm-v2": second_manifest},
        evidence_inspector=service._evidence_inspector,
        provider=provider,
    )
    swapped_request = request.model_copy(update={"model_id": "factory-slm-v2"})
    result = await swapped_service.propose(swapped_request, now=NOW)
    assert result.decision == Decision.APPROVE_FOR_REVIEW
    assert result.model_digest == second_digest


@pytest.mark.asyncio
async def test_substituted_model_cannot_expand_target_permissions():
    service, request, provider = fixture(proposal_target="BREAKER-99")
    second_digest = "d" * 64
    second_manifest = ModelManifest(
        model_id="factory-slm-v2", model_version="2.0.0", artifact_digest=second_digest,
        provider="local:ollama", approved=True, evaluation_suite_id="factory-eval-v2",
    )
    contract = service._contract.model_copy(update={
        "approved_model_digests": {MODEL_DIGEST, second_digest},
    })
    provider.runtime_digests["factory-slm-v2"] = second_digest
    swapped_service = IntelligenceService(
        signed_contract=sign_contract(contract),
        contract_verifier=make_contract_verifier(),
        manifests={"factory-slm": service._manifests["factory-slm"], "factory-slm-v2": second_manifest},
        evidence_inspector=service._evidence_inspector,
        provider=provider,
    )
    swapped_request = request.model_copy(update={"model_id": "factory-slm-v2"})
    result = await swapped_service.propose(swapped_request, now=NOW)
    assert result.decision == Decision.REJECTED
    assert "target_not_allowed" in result.reasons


def test_service_exposes_no_execution_method():
    service, _, _ = fixture()
    assert not hasattr(service, "execute")


@pytest.mark.asyncio
async def test_runtime_digest_mismatch_holds_before_inference():
    service, request, provider = fixture()
    provider.runtime_digests["factory-slm"] = "d" * 64
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.HOLD
    assert "model_runtime_identity_mismatch" in result.reasons
    assert result.proposal is None and provider.calls == 0


@pytest.mark.asyncio
async def test_runtime_digest_change_discards_generated_proposal():
    service, request, provider = fixture()
    provider.swap_digest_after_generate = "d" * 64
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.HOLD
    assert "model_runtime_identity_changed_during_inference" in result.reasons
    assert result.proposal is None and provider.calls == 1


@pytest.mark.asyncio
async def test_ollama_runtime_digest_must_match_exact_model_name(monkeypatch):
    import httpx

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            assert url == "http://127.0.0.1:11434/api/tags"
            return FakeResponse({"models": [
                {"name": "factory-slm:latest", "digest": MODEL_DIGEST},
                {"name": "factory-slm:prod", "digest": "d" * 64},
            ]})

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())
    provider = OllamaProvider()
    assert await provider.verify_model_identity(
        model_id="factory-slm:latest", expected_digest=MODEL_DIGEST
    )
    assert not await provider.verify_model_identity(
        model_id="factory-slm", expected_digest=MODEL_DIGEST
    )


@pytest.mark.asyncio
async def test_ollama_runtime_digest_mismatch_fails_closed(monkeypatch):
    import httpx

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"models": [{"name": "factory-slm:latest", "digest": "d" * 64}]}

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def get(self, url):
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", lambda **kwargs: FakeClient())
    provider = OllamaProvider()
    assert not await provider.verify_model_identity(
        model_id="factory-slm:latest", expected_digest=MODEL_DIGEST
    )



@pytest.mark.asyncio
async def test_decision_record_binds_verified_contract_digest():
    service, request, _ = fixture()
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.APPROVE_FOR_REVIEW
    assert result.contract_digest == contract_digest(service._contract)


@pytest.mark.asyncio
async def test_tampered_contract_signature_fails_before_inference():
    service, request, provider = fixture()
    tampered_contract = service._contract.model_copy(update={"contract_version": "2.0.1"})
    tampered_envelope = service._signed_contract.model_copy(update={"contract": tampered_contract})
    tampered_service = IntelligenceService(
        signed_contract=tampered_envelope,
        contract_verifier=make_contract_verifier(),
        manifests=service._manifests,
        evidence_inspector=service._evidence_inspector,
        provider=provider,
    )
    with pytest.raises(ContractTrustError, match="contract_signature_invalid"):
        await tampered_service.propose(request, now=NOW)
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_untrusted_contract_signer_fails_closed():
    service, request, provider = fixture()
    envelope = service._signed_contract.model_copy(update={"signer_key_id": "attacker-key"})
    untrusted_service = IntelligenceService(
        signed_contract=envelope,
        contract_verifier=make_contract_verifier(),
        manifests=service._manifests,
        evidence_inspector=service._evidence_inspector,
        provider=provider,
    )
    with pytest.raises(ContractTrustError, match="contract_signer_untrusted"):
        await untrusted_service.propose(request, now=NOW)
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_revoked_contract_signer_fails_closed():
    service, request, provider = fixture()
    revoked_service = IntelligenceService(
        signed_contract=service._signed_contract,
        contract_verifier=make_contract_verifier(revoked_key_ids=frozenset({ISSUER_KEY_ID})),
        manifests=service._manifests,
        evidence_inspector=service._evidence_inspector,
        provider=provider,
    )
    with pytest.raises(ContractTrustError, match="contract_signer_revoked"):
        await revoked_service.propose(request, now=NOW)
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_future_issued_contract_fails_closed():
    service, request, provider = fixture()
    future_envelope = sign_contract(
        service._contract, issued_at=NOW + timedelta(minutes=5)
    )
    future_service = IntelligenceService(
        signed_contract=future_envelope,
        contract_verifier=make_contract_verifier(),
        manifests=service._manifests,
        evidence_inspector=service._evidence_inspector,
        provider=provider,
    )
    with pytest.raises(ContractTrustError, match="contract_issued_in_future"):
        await future_service.propose(request, now=NOW)
    assert provider.calls == 0



@pytest.mark.asyncio
async def test_decision_record_integrity_detects_mutation():
    service, request, _ = fixture()
    result = await service.propose(request, now=NOW)
    assert verify_inspection_result_integrity(result)
    tampered = result.model_copy(update={"decision": Decision.REJECTED})
    assert not verify_inspection_result_integrity(tampered)


@pytest.mark.asyncio
async def test_execution_firewall_always_blocks_even_valid_proposal():
    service, request, _ = fixture()
    result = await service.propose(request, now=NOW)
    assert result.decision == Decision.APPROVE_FOR_REVIEW
    boundary = MVD001ExecutionFirewall().evaluate(
        inspection=result,
        requested_operation="SHUTDOWN",
        requested_target_id="PUMP-01",
    )
    assert boundary.status == "BLOCKED"
    assert boundary.execution_authorized is False
    assert "mvd001_advisory_only_no_execution_authority" in boundary.reasons


@pytest.mark.asyncio
async def test_execution_firewall_blocks_tampered_record_and_target_mismatch():
    service, request, _ = fixture()
    result = await service.propose(request, now=NOW)
    tampered = result.model_copy(update={"decision": Decision.REJECTED})
    boundary = MVD001ExecutionFirewall().evaluate(
        inspection=tampered,
        requested_operation="PAYMENT",
        requested_target_id="BREAKER-99",
    )
    assert boundary.execution_authorized is False
    assert "inspection_record_integrity_invalid" in boundary.reasons
    assert "requested_target_mismatch" in boundary.reasons
    assert "mvd001_advisory_only_no_execution_authority" in boundary.reasons



@pytest.mark.asyncio
async def test_expired_contract_holds_before_inference():
    service, request, provider = fixture()
    expired_contract = service._contract.model_copy(
        update={"valid_until_utc": NOW - timedelta(seconds=1)}
    )
    expired_service = IntelligenceService(
        signed_contract=sign_contract(expired_contract, issued_at=NOW - timedelta(minutes=2)),
        contract_verifier=make_contract_verifier(),
        manifests=service._manifests,
        evidence_inspector=service._evidence_inspector,
        provider=provider,
    )
    result = await expired_service.propose(request, now=NOW)
    assert result.decision == Decision.HOLD
    assert "contract_expired" in result.reasons
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_revoked_contract_holds_execution_and_inference():
    service, request, provider = fixture()
    revoked_contract = service._contract.model_copy(update={"revoked": True})
    revoked_service = IntelligenceService(
        signed_contract=sign_contract(revoked_contract),
        contract_verifier=make_contract_verifier(),
        manifests=service._manifests,
        evidence_inspector=service._evidence_inspector,
        provider=provider,
    )
    result = await revoked_service.propose(request, now=NOW)
    assert result.decision == Decision.REJECTED
    assert "contract_revoked" in result.reasons
    assert provider.calls == 0


@pytest.mark.asyncio
async def test_unsupported_contract_signature_algorithm_fails_closed():
    service, request, provider = fixture()
    unsupported = service._signed_contract.model_copy(update={"signature_algorithm": "RSA"})
    unsupported_service = IntelligenceService(
        signed_contract=unsupported,
        contract_verifier=make_contract_verifier(),
        manifests=service._manifests,
        evidence_inspector=service._evidence_inspector,
        provider=provider,
    )
    with pytest.raises(ContractTrustError, match="contract_signature_algorithm_unsupported"):
        await unsupported_service.propose(request, now=NOW)
    assert provider.calls == 0



@pytest.mark.asyncio
async def test_malformed_inspection_record_integrity_check_fails_closed():
    service, request, _ = fixture()
    result = await service.propose(request, now=NOW)
    malformed = result.model_copy(update={"decision": "NOT_A_DECISION"})
    assert not verify_inspection_result_integrity(malformed)
