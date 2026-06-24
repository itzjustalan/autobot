"""Provider-agnostic event envelope."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class EventEnvelope:
    provider: str
    delivery_id: str
    event_name: str
    event_action: str | None
    repo_key: str | None
    resource_type: str
    resource_id: str | None
    actor: str | None
    is_child_pr: bool = False
    parent_pr_number: int | None = None
    parent_pr_head_branch: str | None = None
    parent_pr_base_branch: str | None = None
    child_pr_number: int | None = None
    head_ref: str | None = None
    base_ref: str | None = None
    default_ref: str | None = None
    commit_sha: str | None = None
    payload_path: str | None = None
    received_at: str = ""

    def __post_init__(self) -> None:
        if not self.received_at:
            object.__setattr__(
                self,
                "received_at",
                datetime.now(timezone.utc).isoformat(),
            )

    @property
    def resource_key(self) -> str:
        repo = self.repo_key or "unknown"
        if self.parent_pr_number:
            return f"{self.provider}:{repo}:parent-pr:{self.parent_pr_number}"
        if self.resource_id:
            return f"{self.provider}:{repo}:{self.resource_type}:{self.resource_id}"
        return f"{self.provider}:{repo}:{self.event_name}:{self.delivery_id}"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EventEnvelope":
        return cls(**data)
