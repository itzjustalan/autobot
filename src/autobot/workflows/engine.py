"""Ready-job workflow dispatcher."""

from __future__ import annotations

import json

from autobot.config import AppConfig
from autobot.context import build_context
from autobot.db.sqlite import StateStore
from autobot.event_envelope import EventEnvelope
from autobot.loop_prevention import LoopLimits, LoopState, should_process

from .base import WorkflowResult
from .child_pr_cleanup import run_cleanup
from .github_check_failure import run_check_failure
from .github_review_comment import run_child_pr_followup, run_parent_review_comment


def _limits(config: AppConfig) -> LoopLimits:
    attempts = config.data.get("defaults", {}).get("attempts", {})
    ai = config.data.get("defaults", {}).get("ai", {})
    return LoopLimits(
        max_attempts_per_job=int(attempts.get("max_attempts_per_job", 3)),
        max_attempts_per_child_pr=int(attempts.get("max_attempts_per_child_pr", 5)),
        max_events_per_parent_pr_per_hour=int(
            attempts.get("max_events_per_parent_pr_per_hour", 6)
        ),
        max_total_tokens_per_job=ai.get("max_total_tokens_per_job"),
        max_cost_usd_per_job=ai.get("max_cost_usd_per_job"),
    )


def run_job(*, config: AppConfig, store: StateStore, job_id: str) -> WorkflowResult:
    job = store.get_job(job_id)
    if not job:
        return WorkflowResult("skipped", f"job {job_id!r} not found")

    attempts = store.increment_job_attempts(job_id)
    envelope = EventEnvelope.from_dict(json.loads(str(job["latest_event_json"])))
    decision = should_process(
        _limits(config),
        LoopState(
            attempts_for_job=attempts - 1,
            actor_is_bot=bool(envelope.actor and envelope.actor.endswith("[bot]")),
            event_from_autobot=bool(envelope.actor and "autobot" in envelope.actor.lower()),
            child_pr_followup_allowed=envelope.is_child_pr,
        ),
    )
    if not decision.allowed:
        store.mark_job_status(job_id, "blocked")
        store.record_run(job_id=job_id, status="blocked", result_summary=decision.reason)
        return WorkflowResult("blocked", decision.reason)

    store.mark_job_status(job_id, "running")
    context = build_context(config=config, envelope=envelope, handler_id=str(job["handler_id"]))

    if envelope.event_name == "pull_request_review_comment" and envelope.is_child_pr:
        result = run_child_pr_followup(config=config, store=store, job_id=job_id, context=context)
    elif envelope.event_name == "pull_request_review_comment":
        result = run_parent_review_comment(config=config, store=store, job_id=job_id, context=context)
    elif envelope.event_name in {"workflow_run", "check_run", "check_suite"}:
        result = run_check_failure(config=config, store=store, job_id=job_id, context=context)
    elif envelope.event_name == "pull_request" and envelope.event_action in {"closed"}:
        result = run_cleanup(config=config, store=store, job_id=job_id, context=context)
    else:
        result = WorkflowResult("skipped", f"no workflow for {envelope.event_name}")

    terminal = "done" if result.status in {"planned", "skipped"} else result.status
    store.mark_job_status(job_id, terminal)
    store.record_run(job_id=job_id, status=result.status, result_summary=result.summary)
    return result
