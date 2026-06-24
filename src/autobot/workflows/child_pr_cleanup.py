"""Generated child PR cleanup workflow."""

from __future__ import annotations

from autobot.config import AppConfig
from autobot.context import HandlerContext
from autobot.db.sqlite import StateStore

from .base import WorkflowResult

WORKFLOW_NAME = "child_pr_cleanup"


def run_cleanup(
    *,
    config: AppConfig,
    store: StateStore,
    job_id: str,
    context: HandlerContext,
) -> WorkflowResult:
    """Mark tracked child PR cleanup as ready/completed.

    The branch deletion itself will be implemented by the provider operation
    layer; this state transition preserves the safety rule that only tracked
    autobot branches are cleanup candidates.
    """

    envelope = context.envelope
    if not envelope.repo_key:
        return WorkflowResult("blocked", "cleanup event is missing tracked PR identity")
    child = None
    if envelope.parent_pr_number:
        child = store.get_child_pr_by_child_number(
            provider=envelope.provider,
            repo_key=envelope.repo_key,
            child_pr_number=envelope.parent_pr_number,
        )
    if not child and envelope.child_pr_number:
        child = store.get_child_pr_by_child_number(
            provider=envelope.provider,
            repo_key=envelope.repo_key,
            child_pr_number=envelope.child_pr_number,
        )
    if not child and envelope.parent_pr_number:
        child = store.get_child_pr(
            provider=envelope.provider,
            repo_key=envelope.repo_key,
            parent_pr_number=envelope.parent_pr_number,
        )
    if not child:
        return WorkflowResult("skipped", "PR is not a tracked autobot child PR")
    if child.get("child_pr_number"):
        store.mark_child_pr_cleanup_by_child_number(
            provider=envelope.provider,
            repo_key=envelope.repo_key,
            child_pr_number=int(child["child_pr_number"]),
            cleanup_status="ready",
            state="closed",
        )
    else:
        store.mark_child_pr_cleanup(
            provider=envelope.provider,
            repo_key=envelope.repo_key,
            parent_pr_number=int(child["parent_pr_number"]),
            cleanup_status="ready",
            state="closed",
        )
    return WorkflowResult(
        "planned",
        f"marked child branch {child['child_branch']!r} ready for cleanup",
        {"workflow": WORKFLOW_NAME, "child_branch": child["child_branch"]},
    )
