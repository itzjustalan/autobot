"""Crash-recovery helpers for queue/state reconciliation."""

from __future__ import annotations

from dataclasses import dataclass

from autobot.db.sqlite import StateStore


@dataclass(frozen=True)
class RecoveryResult:
    rescheduled_jobs: int


def recover_after_crash(store: StateStore) -> RecoveryResult:
    """Return running/locked jobs to scheduled state after daemon restart."""

    return RecoveryResult(rescheduled_jobs=store.recover_in_progress_jobs())
