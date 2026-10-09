"""AETHEL MVD-001 advisory intelligence fabric.

This package generates and inspects proposals only. It does not authorize
execution, operate actuators, or trigger financial side effects.
"""
from .contracts import Decision, EvidenceRecord, KnowledgeContract, ModelManifest, Proposal, ProposalRequest, RecommendationType, TelemetryRecord
from .service import IntelligenceService

__all__ = ["Decision", "EvidenceRecord", "IntelligenceService", "KnowledgeContract", "ModelManifest", "Proposal", "ProposalRequest", "RecommendationType", "TelemetryRecord"]
