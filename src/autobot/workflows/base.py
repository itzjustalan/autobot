"""Workflow result types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WorkflowResult:
    status: str
    summary: str
    metadata: dict[str, Any] = field(default_factory=dict)
