from __future__ import annotations

from pathlib import Path
import json
import tempfile
import unittest

from autobot.config import load_config
from autobot.db.sqlite import StateStore
from autobot.web import WebRuntime, _redact_config, dashboard_access_urls


class WebDashboardTests(unittest.TestCase):
    def test_redacts_secret_like_config_keys(self) -> None:
        redacted = _redact_config(
            {
                "token": "abc",
                "nested": {"webhook_secret": {"env": "SECRET"}},
                "safe": "value",
            }
        )
        self.assertEqual(redacted["token"], "<redacted>")
        self.assertEqual(redacted["nested"]["webhook_secret"], "<redacted>")
        self.assertEqual(redacted["safe"], "value")

    def test_summary_reads_state_and_redacts_nothing_sensitive(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = root / "autobot.toml"
            config_path.write_text(
                f"""
[paths]
state_dir = "{root}/state"

[server]
host = "127.0.0.1"
port = 9090
webhook_path = "/hooks/github"

[web]
host = "127.0.0.1"
port = 9091
token = {{ env = "AUTOBOT_WEB_TOKEN", default = "" }}

[queue]
url = {{ env = "AUTOBOT_QUEUE_URL", default = "redis://127.0.0.1:1/0" }}
""",
                encoding="utf-8",
            )
            config = load_config(config_path)
            StateStore(config.database_path)
            runtime = WebRuntime(config, token="token", enable_actions=False)
            summary = runtime.summary()
            self.assertEqual(summary["app"], "autobot")
            self.assertFalse(summary["web"]["actions_enabled"])
            self.assertIn("queue", summary)

    def test_dashboard_access_urls_for_loopback(self) -> None:
        self.assertEqual(
            dashboard_access_urls(bind_host="127.0.0.1", port=9091, token="abc"),
            ["http://127.0.0.1:9091/?token=abc"],
        )

    def test_dashboard_access_urls_for_public_bind_are_not_zero_address(self) -> None:
        urls = dashboard_access_urls(bind_host="0.0.0.0", port=9091, token="abc")
        self.assertTrue(urls)
        self.assertTrue(all("0.0.0.0" not in url for url in urls))


if __name__ == "__main__":
    unittest.main()
