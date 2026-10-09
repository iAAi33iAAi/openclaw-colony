"""Optional FastAPI router factory for the MVD-001 advisory endpoint.

The host application must supply authentication and authorization before
mounting this router. No execution or payment endpoint is exposed here.
"""
from __future__ import annotations
from datetime import datetime, timezone
from typing import Callable
from fastapi import APIRouter, HTTPException
from .contracts import InspectionResult, ProposalRequest
from .service import IntelligenceService

def build_router(service_factory: Callable[[], IntelligenceService]) -> APIRouter:
    router = APIRouter(prefix="/intelligence", tags=["intelligence-advisory"])
    @router.post("/propose", response_model=InspectionResult)
    async def propose(request: ProposalRequest) -> InspectionResult:
        try:
            return await service_factory().propose(request, now=datetime.now(timezone.utc))
        except Exception as exc:
            raise HTTPException(status_code=503, detail="intelligence service unavailable") from exc
    return router
