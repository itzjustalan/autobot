"""Provider interfaces."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from autobot.event_envelope import EventEnvelope


class Provider(ABC):
    """Base provider interface."""

    name: str

    @abstractmethod
    def normalize(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        payload_path: str,
    ) -> EventEnvelope:
        """Normalize a raw provider payload into an event envelope."""
