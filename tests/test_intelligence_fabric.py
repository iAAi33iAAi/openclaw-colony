from datetime import datetime, timedelta, timezone

import pytest

from intelligence_fabric.contracts import (
    Decision, EvidenceRecord, KnowledgeContract, ModelManifest, Proposal,
    ProposalRequest, RecommendationType, TelemetryRecord,
)
from intelligence_fabric.evidence import EvidenceInspector, InMemoryEvidenceRegistry
from intelligence_fabric.providers.ollama_provider import OllamaProvider
from intelligence_fabric.service import IntelligenceService

NOW = datetime(2026, 10, 9, 12, 0, tzinfo=timezone.utc)
MODEL_DIGEST = "a" * 64
TELEMETRY_DIGEST = "b" * 64
EVIDENCE_DIGEST = "c" * 64


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
    service = IntelligenceService(
        contract=contract, manifests={"factory-slm": manifest},
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
        contract=contract,
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
        contract=contract,
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
