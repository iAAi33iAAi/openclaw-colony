# Colony Agent Model Specification
## Full-Stack Technical Audit — Deliverable 3 of 8

---

## Agent Architecture

All 7 agents inherit from `BaseAgent` (ABC).

```python
class BaseAgent(ABC):
    name: str
    domain: str
    _ready: bool

    @abstractmethod
    async def initialize(self) -> None: ...

    @abstractmethod
    async def evaluate(self, prompt: str) -> dict: ...

    def is_ready(self) -> bool: ...
```

---

## The 7 Agents

| # | Agent | Domain | Responsibility |
|---|-------|--------|----------------|
| 1 | StrategicAgent | Strategy | Long-term alignment, mission coherence |
| 2 | TechnicalAgent | Technical | Feasibility, implementation risk |
| 3 | ResourcesAgent | Resources | MANNA allocation, physical logistics |
| 4 | CommsAgent | Communications | Clarity, accessibility, plain language |
| 5 | AnalysisAgent | Analysis | Data verification, pattern detection |
| 6 | QualityAgent | Quality | Standards compliance, test coverage |
| 7 | InnovationAgent | Innovation | Novel approaches, expansion vectors |

---

## Execution Model

```
ColonyTask (prompt + metadata)
         │
         ▼
asyncio.gather(*[agent.evaluate(prompt) for agent in agents])
         │
         ▼ agent_outputs: dict[agent_name → dict]
         │
         ▼
LoveQualityEngine.score(prompt, agent_outputs)
         │
         ▼ LQScore { composite, passed, dimensions }
         │
         ▼
AethelInterface.validate(lq_score, agent_outputs, ...)
```

**Agents run in parallel.** No sequential dependency between agents.
**LQ Engine runs after all agents complete.**
**Aethel kernel runs after LQ Engine.**

---

## Agent Output Contract

Every agent `evaluate()` must return:

```python
{
    "agent":   str,    # agent name
    "domain":  str,    # agent domain
    "summary": str,    # plain language summary
    "flags":   list,   # list of concern strings (empty if none)
    # optional additional fields per agent
}
```

---

## Love Quality Engine

### 6 Dimensions

| Dimension | Weight | What It Measures |
|-----------|--------|-----------------|
| flourishing | 0.25 | Does this help people thrive? |
| harm_reduction | 0.20 | Does this reduce harm? |
| equity | 0.20 | Is this fair to all parties? |
| regenerative | 0.15 | Does this restore rather than deplete? |
| cooperation | 0.12 | Does this build community? |
| beauty | 0.08 | Is this worthy of the world we want? |

**Weights sum to exactly 1.0** (asserted at import time).

### Scoring

```python
composite = sum(dim.raw_score * dim.weight for dim in dimensions)
passed = composite >= 0.85
```

### LQScore Output

```python
@dataclass
class LQScore:
    composite: float          # 0.0 – 1.0
    passed: bool              # composite >= 0.85
    dimensions: list[DimensionScore]
    rejection_reason: str | None
```

---

## Missing Specs (Gaps to Fill)

| Gap | Priority | Recommended Fix |
|-----|----------|----------------|
| Agents are stubs — no real LLM calls | CRITICAL | Wire to LLM API or local model |
| No agent timeout handling | HIGH | Add asyncio.wait_for() per agent |
| No agent failure isolation | HIGH | Wrap each agent in try/except |
| No agent output schema validation | HIGH | Add Pydantic models per agent |
| LQ rubric is keyword-based, not semantic | MEDIUM | Replace with embedding-based scoring |
| No agent versioning | MEDIUM | Add version field to BaseAgent |
| No agent observability | MEDIUM | Add structured logging per agent |
| Beauty dimension is subjective | LOW | Document scoring rubric explicitly |

---

## Current Agent Implementation Status

| Agent | Status | Notes |
|-------|--------|-------|
| StrategicAgent | Stub | Returns placeholder output |
| TechnicalAgent | Stub | Returns placeholder output |
| ResourcesAgent | Stub | Returns placeholder output |
| CommsAgent | Stub | Returns placeholder output |
| AnalysisAgent | Stub | Returns placeholder output |
| QualityAgent | Stub | Returns placeholder output |
| InnovationAgent | Stub | Returns placeholder output |
| LoveQualityEngine | Functional | Keyword-based rubric, real scoring |

**The agents are the primary gap in the system.**
The pipeline, gates, and chain are production-grade.
The agents that feed the pipeline are scaffolding.
This is the correct order — infrastructure first, intelligence second.
