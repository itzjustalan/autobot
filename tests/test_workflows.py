from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from autobot.config import load_config
from autobot.db.sqlite import StateStore
from autobot.event_envelope import EventEnvelope
from autobot.workflows.engine import run_job


class WorkflowEngineTests(unittest.TestCase):
    def _config(self, root: Path):
        config_path = root / "autobot.toml"
        config_path.write_text(
            f"""
[paths]
state_dir = "{root}/state"

[server]
host = "127.0.0.1"
port = 9090
webhook_path = "/hooks/github"

[defaults.throttle]
quiet_window_seconds = 900

[[repos]]
key = "owner/repo"
enabled = true
provider = "github"

[repos.branching]
child_branch_template = "{{{{app_name:-autobot}}}}/{{{{pr_number:-pr-unknown}}}}-fix"
""",
            encoding="utf-8",
        )
        return load_config(config_path)

    def test_review_comment_creates_tracked_child_pr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._config(root)
            store = StateStore(config.database_path)
            envelope = EventEnvelope(
                provider="github",
                delivery_id="d1",
                event_name="pull_request_review_comment",
                event_action="created",
                repo_key="owner/repo",
                resource_type="pull_request",
                resource_id="12",
                actor="alice",
                parent_pr_number=12,
                parent_pr_head_branch="feature",
                parent_pr_base_branch="main",
            )
            store.upsert_job(
                job_id="job-1",
                resource_key=envelope.resource_key,
                handler_id="github-pr-review-comment",
                status="ready",
                not_before=0,
                envelope=envelope,
            )
            result = run_job(config=config, store=store, job_id="job-1")
            self.assertEqual(result.status, "planned")
            child = store.get_child_pr(
                provider="github", repo_key="owner/repo", parent_pr_number=12
            )
            self.assertIsNotNone(child)
            self.assertEqual(child["child_branch"], "autobot/12-fix")
            self.assertEqual(child["parent_head_branch"], "feature")

    def test_check_failure_creates_tracked_child_pr(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._config(root)
            store = StateStore(config.database_path)
            envelope = EventEnvelope(
                provider="github",
                delivery_id="d2",
                event_name="workflow_run",
                event_action="completed",
                repo_key="owner/repo",
                resource_type="workflow_run",
                resource_id="99",
                actor="alice",
                parent_pr_number=13,
                parent_pr_head_branch="feature-2",
                head_ref="feature-2",
            )
            store.upsert_job(
                job_id="job-2",
                resource_key=envelope.resource_key,
                handler_id="github-check-failure",
                status="ready",
                not_before=0,
                envelope=envelope,
            )
            result = run_job(config=config, store=store, job_id="job-2")
            self.assertEqual(result.status, "planned")
            child = store.get_child_pr(
                provider="github", repo_key="owner/repo", parent_pr_number=13
            )
            self.assertIsNotNone(child)
            self.assertEqual(child["child_branch"], "autobot/13-fix")

    def test_cleanup_matches_tracked_child_pr_number(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = self._config(root)
            store = StateStore(config.database_path)
            store.upsert_child_pr(
                provider="github",
                repo_key="owner/repo",
                parent_pr_number=14,
                parent_head_branch="feature",
                child_branch="autobot/14-fix",
                child_pr_number=55,
                child_pr_url="https://example.test/pr/55",
            )
            envelope = EventEnvelope(
                provider="github",
                delivery_id="d3",
                event_name="pull_request",
                event_action="closed",
                repo_key="owner/repo",
                resource_type="pull_request",
                resource_id="55",
                actor="alice",
                parent_pr_number=55,
            )
            store.upsert_job(
                job_id="job-3",
                resource_key=envelope.resource_key,
                handler_id="cleanup",
                status="ready",
                not_before=0,
                envelope=envelope,
            )
            result = run_job(config=config, store=store, job_id="job-3")
            self.assertEqual(result.status, "planned")
            child = store.get_child_pr(
                provider="github", repo_key="owner/repo", parent_pr_number=14
            )
            self.assertEqual(child["cleanup_status"], "ready")


if __name__ == "__main__":
    unittest.main()
