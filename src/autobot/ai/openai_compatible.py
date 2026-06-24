"""OpenAI-compatible provider placeholder."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from .base import AIBudget, AIProvider, AIResult


class OpenAICompatibleProvider(AIProvider):
    name = "openai_compatible"

    def __init__(self, *, base_url: str, api_key: str, model: str) -> None:
        self.base_url = base_url
        self.api_key = api_key
        self.model = model

    def run(
        self,
        *,
        prompt: str,
        worktree: Path,
        context: dict[str, Any],
        budget: AIBudget,
        tools_policy: dict[str, Any] | None = None,
    ) -> AIResult:
        raise NotImplementedError("OpenAI-compatible provider is planned but not implemented")
