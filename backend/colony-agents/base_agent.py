"""
OpenClaw Colony — BaseAgent
All 7 colony agents inherit from this class.
"""

from abc import ABC, abstractmethod


class BaseAgent(ABC):
    name: str = "BaseAgent"
    domain: str = "Undefined"
    _ready: bool = False

    @abstractmethod
    async def initialize(self) -> None:
        """Perform any async setup (model loading, connection checks, etc.)."""

    @abstractmethod
    async def evaluate(self, prompt: str) -> dict:
        """
        Evaluate the prompt from this agent's domain perspective.
        Must return a dict with at least: agent, domain, summary, flags.
        """

    def is_ready(self) -> bool:
        return self._ready