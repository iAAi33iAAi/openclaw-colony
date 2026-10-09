"""Independent evidence inspection for the MVD-001 advisory service."""
from __future__ import annotations
from datetime import datetime, timezone
from .contracts import EvidenceRecord, KnowledgeContract, TelemetryRecord
from .verification import SignatureVerifier, canonical_json_bytes

class EvidenceInspector:
    def __init__(self, signature_verifier: SignatureVerifier):
        self._signature_verifier = signature_verifier

    def inspect(self, *, contract: KnowledgeContract, telemetry: TelemetryRecord, evidence: list[EvidenceRecord], now: datetime) -> list[str]:
        reasons: list[str] = []
        now = _utc(now)
        if telemetry.sensor_id not in contract.permitted_sensor_ids:
            reasons.append("sensor_not_permitted")
        if telemetry.target_id not in contract.allowed_targets:
            reasons.append("telemetry_target_not_permitted")
        age_seconds = (now - telemetry.observed_at_utc).total_seconds()
        if age_seconds < -5:
            reasons.append("telemetry_timestamp_in_future")
        elif age_seconds > contract.max_telemetry_age_seconds:
            reasons.append("telemetry_stale")
        signed_payload = canonical_json_bytes({
            "sensor_id": telemetry.sensor_id,
            "target_id": telemetry.target_id,
            "observed_at_utc": telemetry.observed_at_utc.isoformat(),
            "payload_digest": telemetry.payload_digest,
            "signer_key_id": telemetry.signer_key_id,
        })
        if not self._signature_verifier.verify(key_id=telemetry.signer_key_id, message=signed_payload, signature=telemetry.signature):
            reasons.append("telemetry_signature_unverified")
        if not evidence:
            reasons.append("evidence_missing")
        for record in evidence:
            if record.source_id not in contract.approved_source_ids:
                reasons.append(f"source_not_permitted:{record.evidence_id}")
            if not record.approved:
                reasons.append(f"evidence_not_approved:{record.evidence_id}")
            if record.quality_micros < contract.min_evidence_quality_micros:
                reasons.append(f"evidence_quality_below_threshold:{record.evidence_id}")
        return reasons

def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    return value.astimezone(timezone.utc)
