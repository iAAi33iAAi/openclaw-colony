"""Optional FastAPI router factory for the MVD-001 advisory endpoint.

An explicit host authentication dependency is required before the router can
be constructed. No execution or payment endpoint is exposed here.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Callable
from fastapi import APIRouter, Depends, HTTPException
from .contracts import InspectionResult, ProposalRequest
from .service import IntelligenceService

def build_router(*, service_factory: Callable[[], IntelligenceService], auth_dependency: Callable[..., Any]) -> APIRouter:
    if auth_dependency is None:
        raise ValueError("an explicit authentication dependency is required")
    router = APIRouter(
        prefix="/intelligence",
        tags=["intelligence-advisory"],
        dependencies=[Depends(auth_dependency)],
    )
    @router.post("/propose", response_model=InspectionResult)
    async def propose(request: ProposalRequest) -> InspectionResult:
        try:
            return await service_factory().propose(request, now=datetime.now(timezone.utc))
        except Exception as exc:
            # Fail closed without exposing provider secrets or internal traces.
            raise HTTPException(status_code=503, detail="intelligence service unavailable") from exc
    return router
