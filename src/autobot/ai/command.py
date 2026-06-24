"""Command-backed AI provider."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from .base import AIBudget, AIProvider, AIResult


class CommandAIProvider(AIProvider):
    name = "command"

    def __init__(self, command: list[str], *, model: str | None = None, timeout: int = 3600) -> None:
        self.command = command
        self.model = model
        self.timeout = timeout

    def run(
        self,
        *,
        prompt: str,
        worktree: Path,
        context: dict[str, Any],
        budget: AIBudget,
        tools_policy: dict[str, Any] | None = None,
    ) -> AIResult:
        completed = subprocess.run(
            self.command,
            input=prompt,
            text=True,
            cwd=worktree,
            capture_output=True,
            timeout=self.timeout,
            check=False,
        )
        output = completed.stdout
        if completed.stderr:
            output = f"{output}\n{completed.stderr}".strip()
        return AIResult(
            ok=completed.returncode == 0,
            output=output,
            provider=self.name,
            model=self.model,
            metadata={"returncode": completed.returncode},
        )
