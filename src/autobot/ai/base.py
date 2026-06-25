"""AI provider interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AIBudget:
    max_prompt_tokens: int | None = None
    max_output_tokens: int | None = None
    max_total_tokens: int | None = None
    max_cost_usd: float | None = None


@dataclass(frozen=True)
class AIResult:
    ok: bool
    output: str
    provider: str
    model: str | None = None
    token_estimate: int | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class AIProvider(ABC):
    name: str
    supports_session_reuse: bool = False

    @abstractmethod
    def run(
        self,
        *,
        prompt: str,
        worktree: Path,
        context: dict[str, Any],
        budget: AIBudget,
        tools_policy: dict[str, Any] | None = None,
        session_id: str | None = None,
    ) -> AIResult:
        """Run the provider with a rendered prompt."""
