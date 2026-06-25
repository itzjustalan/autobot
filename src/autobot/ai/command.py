"""Command-backed AI provider."""

from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

from .base import AIBudget, AIProvider, AIResult


class CommandAIProvider(AIProvider):
    name = "command"
    supports_session_reuse = True

    def __init__(
        self,
        command: list[str],
        *,
        model: str | None = None,
        timeout: int = 3600,
        connect_arg_template: str | None = None,
    ) -> None:
        self.command = command
        self.model = model
        self.timeout = timeout
        self.connect_arg_template = connect_arg_template

    def build_command(self, *, session_id: str | None = None) -> list[str]:
        command = list(self.command)
        if session_id and self.connect_arg_template:
            command.append(self.connect_arg_template.replace("{{session_id}}", session_id))
        return command

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
        completed = subprocess.run(
            self.build_command(session_id=session_id),
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
            metadata={"returncode": completed.returncode, "session_id": session_id},
        )
