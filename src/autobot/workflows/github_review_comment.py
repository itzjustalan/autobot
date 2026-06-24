"""GitHub review-comment workflow."""

from __future__ import annotations

from autobot.config import AppConfig
from autobot.context import HandlerContext
from autobot.db.sqlite import StateStore

from .base import WorkflowResult

WORKFLOW_NAME = "github_pr_review_comment"


def run_parent_review_comment(
    *,
    config: AppConfig,
    store: StateStore,
    job_id: str,
    context: HandlerContext,
) -> WorkflowResult:
    """Plan/create tracking for the one child PR for a parent PR review comment."""

    envelope = context.envelope
    if not envelope.repo_key or not envelope.parent_pr_number:
        return WorkflowResult("blocked", "review comment event is not linked to a parent PR")
    if not envelope.parent_pr_head_branch:
        return WorkflowResult("blocked", "parent PR head/source branch is missing")

    child_branch = context.variables["child_branch"]
    store.upsert_child_pr(
        provider=envelope.provider,
        repo_key=envelope.repo_key,
        parent_pr_number=envelope.parent_pr_number,
        parent_head_branch=envelope.parent_pr_head_branch,
        child_branch=child_branch,
        state="open",
    )
    summary = (
        f"prepared child PR branch {child_branch!r} for review-comment work "
        f"on {envelope.repo_key} PR #{envelope.parent_pr_number}"
    )
    return WorkflowResult(
        "planned",
        summary,
        {
            "child_branch": child_branch,
            "target_branch": envelope.parent_pr_head_branch,
            "workflow": WORKFLOW_NAME,
        },
    )


def run_child_pr_followup(
    *,
    config: AppConfig,
    store: StateStore,
    job_id: str,
    context: HandlerContext,
) -> WorkflowResult:
    """Handle comments on an existing autobot child PR in-place."""

    envelope = context.envelope
    summary = (
        f"planned in-place child PR follow-up for {envelope.repo_key} "
        f"delivery {envelope.delivery_id}"
    )
    return WorkflowResult("planned", summary, {"workflow": "child_pr_followup"})
