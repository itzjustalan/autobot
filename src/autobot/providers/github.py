"""GitHub App provider helpers."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

from autobot.event_envelope import EventEnvelope
from autobot.providers.base import Provider


class GitHubSignatureError(RuntimeError):
    """Raised when a GitHub webhook signature is invalid."""


def verify_signature(*, secret: str, body: bytes, signature: str | None) -> None:
    """Verify GitHub X-Hub-Signature-256."""

    if not signature:
        raise GitHubSignatureError("missing X-Hub-Signature-256")
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise GitHubSignatureError("invalid X-Hub-Signature-256")


def parse_json_body(body: bytes) -> dict[str, Any]:
    payload = json.loads(body.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("GitHub payload must be a JSON object")
    return payload


def _repo_key(payload: dict[str, Any]) -> str | None:
    repo = payload.get("repository")
    if isinstance(repo, dict):
        full_name = repo.get("full_name")
        return str(full_name) if full_name else None
    return None


def _actor(payload: dict[str, Any]) -> str | None:
    sender = payload.get("sender")
    if isinstance(sender, dict) and sender.get("login"):
        return str(sender["login"])
    return None


def _pr_from_payload(payload: dict[str, Any]) -> dict[str, Any] | None:
    pr = payload.get("pull_request")
    return pr if isinstance(pr, dict) else None


def _workflow_pr_number(payload: dict[str, Any]) -> int | None:
    workflow = payload.get("workflow_run")
    if isinstance(workflow, dict):
        prs = workflow.get("pull_requests") or []
        if prs and isinstance(prs[0], dict) and prs[0].get("number") is not None:
            return int(prs[0]["number"])
    return None


class GitHubProvider(Provider):
    name = "github"

    def normalize(
        self,
        *,
        headers: dict[str, str],
        payload: dict[str, Any],
        payload_path: str,
    ) -> EventEnvelope:
        event_name = headers.get("x-github-event", "unknown")
        delivery_id = headers.get("x-github-delivery", "")
        action = payload.get("action")
        repo_key = _repo_key(payload)
        actor = _actor(payload)
        pr = _pr_from_payload(payload)
        resource_type = "unknown"
        resource_id: str | None = None
        parent_pr_number: int | None = None
        parent_head: str | None = None
        parent_base: str | None = None
        head_ref: str | None = None
        base_ref: str | None = None
        commit_sha: str | None = None

        if pr:
            resource_type = "pull_request"
            parent_pr_number = int(pr["number"])
            resource_id = str(parent_pr_number)
            head = pr.get("head") if isinstance(pr.get("head"), dict) else {}
            base = pr.get("base") if isinstance(pr.get("base"), dict) else {}
            parent_head = head.get("ref")
            parent_base = base.get("ref")
            head_ref = parent_head
            base_ref = parent_base
            commit_sha = head.get("sha")
        elif event_name == "workflow_run":
            resource_type = "workflow_run"
            workflow = payload.get("workflow_run", {})
            if isinstance(workflow, dict):
                resource_id = str(workflow.get("id")) if workflow.get("id") else None
                commit_sha = workflow.get("head_sha")
                head_ref = workflow.get("head_branch")
            parent_pr_number = _workflow_pr_number(payload)
        elif "issue" in payload:
            resource_type = "issue"
            issue = payload.get("issue", {})
            if isinstance(issue, dict) and issue.get("number") is not None:
                resource_id = str(issue["number"])

        repo = payload.get("repository", {})
        default_ref = repo.get("default_branch") if isinstance(repo, dict) else None

        return EventEnvelope(
            provider=self.name,
            delivery_id=delivery_id,
            event_name=event_name,
            event_action=str(action) if action is not None else None,
            repo_key=repo_key,
            resource_type=resource_type,
            resource_id=resource_id,
            actor=actor,
            parent_pr_number=parent_pr_number,
            parent_pr_head_branch=parent_head,
            parent_pr_base_branch=parent_base,
            head_ref=head_ref,
            base_ref=base_ref,
            default_ref=default_ref,
            commit_sha=commit_sha,
            payload_path=payload_path,
        )
