"""Fail-closed execution boundary for the advisory-only MVD-001 scope.

This is a deny-all boundary, not an executor and not a replacement for the
existing Colony transaction/kernel gates. It is not mounted automatically.
"""
from __future__ import annotations

from typing import Literal

from pydantic import Field

from .contracts import Decision, Identifier, InspectionResult, StrictModel
from .verification import verify_inspection_result_integrity


class ExecutionBoundaryResult(StrictModel):
    status: Literal["BLOCKED"] = "BLOCKED"
    execution_authorized: Literal[False] = False
    request_id: Identifier
    requested_operation: str = Field(min_length=1, max_length=96)
    requested_target_id: Identifier
    inspection_record_digest: str
    reasons: list[str]


class MVD001ExecutionFirewall:
    """Always denies execution; MVD-001 only generates human-review proposals."""

    def evaluate(
        self,
        *,
        inspection: InspectionResult,
        requested_operation: str,
        requested_target_id: str,
    ) -> ExecutionBoundaryResult:
        reasons: list[str] = []
        if not verify_inspection_result_integrity(inspection):
            reasons.append("inspection_record_integrity_invalid")
        if inspection.decision != Decision.APPROVE_FOR_REVIEW:
            reasons.append("proposal_not_approved_for_review")
        if inspection.proposal is None:
            reasons.append("proposal_missing")
        elif inspection.proposal.target_id != requested_target_id:
            reasons.append("requested_target_mismatch")
        if not requested_operation.strip():
            reasons.append("requested_operation_missing")

        # Intentionally unconditional: neither model output nor this advisory
        # assessment can mint execution authority. A separately designed,
        # authenticated, audited execution control plane is not part of MVD-001.
        reasons.append("mvd001_advisory_only_no_execution_authority")
        return ExecutionBoundaryResult(
            request_id=inspection.request_id,
            requested_operation=requested_operation,
            requested_target_id=requested_target_id,
            inspection_record_digest=inspection.record_digest,
            reasons=sorted(set(reasons)),
        )
