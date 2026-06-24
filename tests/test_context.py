from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from autobot.config import load_config
from autobot.context import build_context
from autobot.event_envelope import EventEnvelope


class ContextTests(unittest.TestCase):
    def test_build_context_renders_repo_branch_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "autobot.toml"
            path.write_text(
                """
[server]
host = "127.0.0.1"
port = 9090
webhook_path = "/hooks/github"

[[repos]]
key = "owner/repo"
enabled = true
provider = "github"

[repos.branching]
child_branch_template = "{{app_name:-autobot}}/{{pr_number:-pr-unknown}} fix"
""",
                encoding="utf-8",
            )
            config = load_config(path)
            envelope = EventEnvelope(
                provider="github",
                delivery_id="d1",
                event_name="pull_request_review_comment",
                event_action="created",
                repo_key="owner/repo",
                resource_type="pull_request",
                resource_id="9",
                actor="alice",
                parent_pr_number=9,
                parent_pr_head_branch="feature",
                parent_pr_base_branch="main",
            )
            context = build_context(config=config, envelope=envelope, handler_id="review")
            self.assertEqual(context.variables["child_branch"], "autobot/9-fix")


if __name__ == "__main__":
    unittest.main()
