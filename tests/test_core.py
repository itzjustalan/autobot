from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import tempfile
import unittest

from autobot.config import load_config
from autobot.providers.github import GitHubProvider, verify_signature
from autobot.templates import TemplateRenderError, render_template, sanitize_branch_name


class TemplateTests(unittest.TestCase):
    def test_render_required_and_default_values(self) -> None:
        rendered = render_template(
            "{{app_name:-autobot}}/pr-{{pr_number}}-{{handler.id}}",
            {"pr_number": 123, "handler": {"id": "fix"}},
        )
        self.assertEqual(rendered, "autobot/pr-123-fix")

    def test_missing_required_value_fails(self) -> None:
        with self.assertRaises(TemplateRenderError):
            render_template("{{missing}}", {})

    def test_branch_sanitization(self) -> None:
        self.assertEqual(sanitize_branch_name(" autobot/pr 123 fix "), "autobot/pr-123-fix")


class GitHubProviderTests(unittest.TestCase):
    def test_signature_verification(self) -> None:
        body = b'{"ok": true}'
        secret = "secret"
        signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        verify_signature(secret=secret, body=body, signature=signature)

    def test_normalize_pull_request_payload(self) -> None:
        payload = {
            "action": "opened",
            "repository": {"full_name": "owner/repo", "default_branch": "main"},
            "sender": {"login": "alice"},
            "pull_request": {
                "number": 7,
                "head": {"ref": "feature", "sha": "abc"},
                "base": {"ref": "main"},
            },
        }
        envelope = GitHubProvider().normalize(
            headers={"x-github-event": "pull_request", "x-github-delivery": "d1"},
            payload=payload,
            payload_path="/tmp/payload.json",
        )
        self.assertEqual(envelope.repo_key, "owner/repo")
        self.assertEqual(envelope.parent_pr_number, 7)
        self.assertEqual(envelope.parent_pr_head_branch, "feature")
        self.assertEqual(envelope.parent_pr_base_branch, "main")
        self.assertEqual(envelope.resource_key, "github:owner/repo:parent-pr:7")


class ConfigTests(unittest.TestCase):
    def test_loads_env_file_and_secret_refs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env_path = root / ".env"
            env_path.write_text("AUTOBOT_GITHUB_WEBHOOK_SECRET=abc\n", encoding="utf-8")
            config_path = root / "autobot.toml"
            config_path.write_text(
                f"""
[paths]
state_dir = "{root}/state"
env_file = "{env_path}"

[server]
host = "127.0.0.1"
port = 9090
webhook_path = "/hooks/github"

[providers.github]
webhook_secret = {{ env = "AUTOBOT_GITHUB_WEBHOOK_SECRET" }}
""",
                encoding="utf-8",
            )
            old = os.environ.pop("AUTOBOT_GITHUB_WEBHOOK_SECRET", None)
            try:
                config = load_config(config_path)
                self.assertEqual(config.github_webhook_secret(), "abc")
            finally:
                if old is not None:
                    os.environ["AUTOBOT_GITHUB_WEBHOOK_SECRET"] = old


if __name__ == "__main__":
    unittest.main()
