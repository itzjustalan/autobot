"""Context gathering for ready jobs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .config import AppConfig
from .event_envelope import EventEnvelope
from .repo_registry import RepoRegistry
from .templates import render_template, sanitize_branch_name


@dataclass(frozen=True)
class HandlerContext:
    envelope: EventEnvelope
    repo: dict[str, Any] | None
    variables: dict[str, Any]


def build_context(
    *,
    config: AppConfig,
    envelope: EventEnvelope,
    handler_id: str,
) -> HandlerContext:
    """Build the handler context after quiet-window release."""

    registry = RepoRegistry(config.repos)
    repo = registry.get(envelope.repo_key or "")
    defaults = config.data.get("defaults", {})
    branch_template = (
        (repo.raw if repo and repo.raw else {})
        .get("branching", {})
        .get(
            "child_branch_template",
            defaults.get("branching", {}).get(
                "child_branch_template",
                "{{app_name:-autobot}}/pr-{{pr_number}}-{{handler_id}}",
            ),
        )
    )
    variables: dict[str, Any] = {
        "app_name": config.app_name,
        "handler_id": handler_id,
        "provider": envelope.provider,
        "event_name": envelope.event_name,
        "event_action": envelope.event_action,
        "repo_key": envelope.repo_key,
        "actor": envelope.actor,
        "delivery_id": envelope.delivery_id,
        "resource_key": envelope.resource_key,
        "pr_number": envelope.parent_pr_number,
        "parent_pr_number": envelope.parent_pr_number,
        "parent_branch": envelope.parent_pr_head_branch,
        "parent_pr_head_branch": envelope.parent_pr_head_branch,
        "parent_pr_base_branch": envelope.parent_pr_base_branch,
        "commit_sha": envelope.commit_sha,
    }
    child_branch = sanitize_branch_name(render_template(str(branch_template), variables))
    variables["child_branch"] = child_branch
    return HandlerContext(
        envelope=envelope,
        repo=repo.raw if repo else None,
        variables=variables,
    )
