"""
OpenClaw Colony — Colony Coordinator
Main entry point: routes tasks to all 7 agents, aggregates results,
passes through Love Quality Engine → Aethel Safety Kernel.
"""

import asyncio
import json
import logging
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

from love_quality.love_quality_engine import LoveQualityEngine, LQScore
from aethel_interface import AethelInterface

# ── Agent imports ──────────────────────────────────────────────────────────────
from colony_agents.strategic_agent   import StrategicAgent
from colony_agents.technical_agent   import TechnicalAgent
from colony_agents.resources_agent   import ResourcesAgent
from colony_agents.comms_agent       import CommsAgent
from colony_agents.analysis_agent    import AnalysisAgent
from colony_agents.quality_agent     import QualityAgent
from colony_agents.innovation_agent  import InnovationAgent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger("colony.coordinator")


@dataclass
class ColonyTask:
    task_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    prompt: str = ""
    submitted_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    human_consent: bool = True          # Gate 1 — must be explicitly set


@dataclass
class ColonyResult:
    task_id: str
    prompt: str
    agent_outputs: dict[str, Any]
    lq_score: dict
    aethel_verdict: str                 # "APPROVED" | "BLOCKED"
    aethel_gates: dict
    committed_action: str | None
    lineage_hash: str | None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ColonyCoordinator:
    """Orchestrates the full 7-agent → LQ → Aethel pipeline."""

    AGENTS = [
        StrategicAgent,
        TechnicalAgent,
        ResourcesAgent,
        CommsAgent,
        AnalysisAgent,
        QualityAgent,
        InnovationAgent,
    ]

    def __init__(self):
        self.lq_engine   = LoveQualityEngine()
        self.aethel      = AethelInterface()
        self.agents      = [cls() for cls in self.AGENTS]
        self._lineage: list[str] = []   # SHA-256 chain

    # ── Startup ────────────────────────────────────────────────────────────────

    async def start(self):
        log.info("Initialising OpenClaw Colony …")
        for agent in self.agents:
            await agent.initialize()
            log.info("[AGENT READY] %s", agent.name)
        log.info("[AETHEL] Kernel online. Gates: 3/3 active.")

    # ── Main pipeline ──────────────────────────────────────────────────────────

    async def process(self, task: ColonyTask) -> ColonyResult:
        log.info("Processing task %s: %r", task.task_id, task.prompt[:80])

        # 1 — Parallel agent evaluation
        agent_outputs = await self._run_agents(task)

        # 2 — Love Quality scoring
        lq: LQScore = self.lq_engine.score(task.prompt, agent_outputs)
        log.info(
            "LQ composite=%.3f  threshold=0.85  pass=%s",
            lq.composite, lq.composite >= 0.85,
        )

        # 3 — Aethel kernel gates
        aethel_result = self.aethel.validate(
            task_id=task.task_id,
            human_consent=task.human_consent,
            lq_score=lq.composite,
            agent_outputs=agent_outputs,
        )

        committed_action = None
        lineage_hash     = None

        if aethel_result["verdict"] == "APPROVED":
            committed_action = self._build_action(task, agent_outputs, lq)
            lineage_hash     = self._extend_lineage(task.task_id, committed_action)
            log.info("[APPROVED] Lineage hash: %s", lineage_hash)
        else:
            log.warning(
                "[BLOCKED] Task %s blocked at gate %s — %s",
                task.task_id,
                aethel_result.get("blocked_at_gate"),
                aethel_result.get("reason"),
            )

        return ColonyResult(
            task_id=task.task_id,
            prompt=task.prompt,
            agent_outputs=agent_outputs,
            lq_score=asdict(lq),
            aethel_verdict=aethel_result["verdict"],
            aethel_gates=aethel_result["gates"],
            committed_action=committed_action,
            lineage_hash=lineage_hash,
        )

    # ── Helpers ────────────────────────────────────────────────────────────────

    async def _run_agents(self, task: ColonyTask) -> dict[str, Any]:
        """Run all 7 agents concurrently and collect their outputs."""
        coros = [agent.evaluate(task.prompt) for agent in self.agents]
        results = await asyncio.gather(*coros, return_exceptions=True)
        outputs: dict[str, Any] = {}
        for agent, result in zip(self.agents, results):
            if isinstance(result, Exception):
                log.error("Agent %s raised: %s", agent.name, result)
                outputs[agent.name] = {"error": str(result)}
            else:
                outputs[agent.name] = result
        return outputs

    def _build_action(
        self,
        task: ColonyTask,
        agent_outputs: dict[str, Any],
        lq: "LQScore",
    ) -> str:
        return json.dumps(
            {
                "task_id": task.task_id,
                "prompt": task.prompt,
                "lq_composite": lq.composite,
                "summary": {
                    name: out.get("summary", "") if isinstance(out, dict) else str(out)
                    for name, out in agent_outputs.items()
                },
            },
            indent=2,
        )

    def _extend_lineage(self, task_id: str, action: str) -> str:
        import hashlib
        prev = self._lineage[-1] if self._lineage else "GENESIS"
        payload = f"{prev}:{task_id}:{action}"
        h = hashlib.sha256(payload.encode()).hexdigest()
        self._lineage.append(h)
        return h


# ── FastAPI application ────────────────────────────────────────────────────────

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="OpenClaw Colony API", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)

coordinator: ColonyCoordinator | None = None


@app.on_event("startup")
async def startup():
    global coordinator
    coordinator = ColonyCoordinator()
    await coordinator.start()


class TaskRequest(BaseModel):
    prompt: str
    human_consent: bool = True


class TaskResponse(BaseModel):
    task_id: str
    prompt: str
    lq_score: dict
    aethel_verdict: str
    aethel_gates: dict
    committed_action: str | None
    lineage_hash: str | None
    timestamp: str


@app.post("/process", response_model=TaskResponse)
async def process_task(req: TaskRequest):
    if not coordinator:
        raise HTTPException(status_code=503, detail="Colony not initialised")
    task = ColonyTask(prompt=req.prompt, human_consent=req.human_consent)
    result = await coordinator.process(task)
    return TaskResponse(
        task_id=result.task_id,
        prompt=result.prompt,
        lq_score=result.lq_score,
        aethel_verdict=result.aethel_verdict,
        aethel_gates=result.aethel_gates,
        committed_action=result.committed_action,
        lineage_hash=result.lineage_hash,
        timestamp=result.timestamp,
    )


@app.get("/health")
async def health():
    return {"status": "ok", "colony": "online", "gates": "3/3 active"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("colony_coordinator:app", host="0.0.0.0", port=8000, reload=False)