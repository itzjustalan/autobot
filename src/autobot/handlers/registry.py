"""Config-driven handler registry."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from autobot.event_envelope import EventEnvelope


@dataclass(frozen=True)
class HandlerSpec:
    id: str
    provider: str
    event: str
    run_type: str
    enabled: bool = True
    actions: tuple[str, ...] = ()

    @classmethod
    def from_config(cls, raw: dict[str, Any]) -> "HandlerSpec":
        return cls(
            id=str(raw["id"]),
            provider=str(raw["provider"]),
            event=str(raw["event"]),
            run_type=str(raw.get("run_type", "noop")),
            enabled=bool(raw.get("enabled", True)),
            actions=tuple(str(action) for action in raw.get("actions", [])),
        )

    def matches(self, envelope: EventEnvelope) -> bool:
        if not self.enabled:
            return False
        if self.provider != envelope.provider or self.event != envelope.event_name:
            return False
        if self.actions and envelope.event_action not in self.actions:
            return False
        return True


class HandlerRegistry:
    def __init__(self, handlers: list[dict[str, Any]]) -> None:
        self.handlers = [HandlerSpec.from_config(handler) for handler in handlers]

    def match(self, envelope: EventEnvelope) -> HandlerSpec | None:
        for handler in self.handlers:
            if handler.matches(envelope):
                return handler
        return None
