"""Loop and runaway-iteration prevention."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LoopLimits:
    max_attempts_per_job: int = 3
    max_attempts_per_child_pr: int = 5
    max_events_per_parent_pr_per_hour: int = 6
    max_total_tokens_per_job: int | None = None
    max_cost_usd_per_job: float | None = None


@dataclass(frozen=True)
class LoopState:
    attempts_for_job: int = 0
    attempts_for_child_pr: int = 0
    events_for_parent_pr_last_hour: int = 0
    token_estimate_for_job: int = 0
    cost_estimate_for_job: float = 0
    actor_is_bot: bool = False
    event_from_autobot: bool = False
    child_pr_followup_allowed: bool = False


@dataclass(frozen=True)
class LoopDecision:
    allowed: bool
    reason: str = ""


def should_process(limits: LoopLimits, state: LoopState) -> LoopDecision:
    if state.event_from_autobot and not state.child_pr_followup_allowed:
        return LoopDecision(False, "autobot-generated event ignored")
    if state.actor_is_bot and not state.child_pr_followup_allowed:
        return LoopDecision(False, "bot event ignored")
    if state.attempts_for_job >= limits.max_attempts_per_job:
        return LoopDecision(False, "max attempts per job reached")
    if state.attempts_for_child_pr >= limits.max_attempts_per_child_pr:
        return LoopDecision(False, "max attempts per child PR reached")
    if state.events_for_parent_pr_last_hour > limits.max_events_per_parent_pr_per_hour:
        return LoopDecision(False, "max events per parent PR per hour reached")
    if (
        limits.max_total_tokens_per_job is not None
        and state.token_estimate_for_job >= limits.max_total_tokens_per_job
    ):
        return LoopDecision(False, "token budget reached")
    if (
        limits.max_cost_usd_per_job is not None
        and state.cost_estimate_for_job >= limits.max_cost_usd_per_job
    ):
        return LoopDecision(False, "cost budget reached")
    return LoopDecision(True)
