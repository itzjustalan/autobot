"""GitHub check-failure workflow."""

from __future__ import annotations

from autobot.config import AppConfig
from autobot.context import HandlerContext
from autobot.db.sqlite import StateStore

from .base import WorkflowResult

WORKFLOW_NAME = "github_check_failure"


def run_check_failure(
    *,
    config: AppConfig,
    store: StateStore,
    job_id: str,
    context: HandlerContext,
) -> WorkflowResult:
    """Plan/create tracking for the one child PR for a parent PR check failure."""

    envelope = context.envelope
    if not envelope.repo_key:
        return WorkflowResult("blocked", "check failure event is not linked to a repo")
    if not envelope.parent_pr_number:
        return WorkflowResult("blocked", "check failure event is not linked to a parent PR")
    target_branch = envelope.parent_pr_head_branch or envelope.head_ref
    if not target_branch:
        return WorkflowResult("blocked", "parent PR head/source branch is missing")

    child_branch = context.variables["child_branch"]
    store.upsert_child_pr(
        provider=envelope.provider,
        repo_key=envelope.repo_key,
        parent_pr_number=envelope.parent_pr_number,
        parent_head_branch=target_branch,
        child_branch=child_branch,
        state="open",
    )
    summary = (
        f"prepared child PR branch {child_branch!r} for check-failure work "
        f"on {envelope.repo_key} PR #{envelope.parent_pr_number}"
    )
    return WorkflowResult(
        "planned",
        summary,
        {
            "child_branch": child_branch,
            "target_branch": target_branch,
            "workflow": WORKFLOW_NAME,
        },
    )
