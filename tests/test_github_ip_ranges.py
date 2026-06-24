from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from autobot.db.sqlite import StateStore
from autobot.providers.github_meta import GitHubIPRangeMonitor


class GitHubIPRangeMonitorTests(unittest.TestCase):
    def test_initial_check_stores_snapshot_without_change(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "autobot.db")
            monitor = GitHubIPRangeMonitor(
                store=store,
                fetch_meta=lambda _url: ({"hooks": ["2.2.2.0/24", "1.1.1.0/24"]}, "etag-1"),
            )
            result = monitor.check()
            self.assertFalse(result.changed)
            self.assertTrue(result.initial)
            self.assertEqual(result.ranges, ["1.1.1.0/24", "2.2.2.0/24"])
            status = monitor.status()
            self.assertEqual(status["snapshot"]["ranges"], ["1.1.1.0/24", "2.2.2.0/24"])
            self.assertEqual(status["recent_changes"], [])

    def test_changed_ranges_are_recorded(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "autobot.db")
            responses = [
                ({"hooks": ["1.1.1.0/24", "2.2.2.0/24"]}, "etag-1"),
                ({"hooks": ["2.2.2.0/24", "3.3.3.0/24"]}, "etag-2"),
            ]

            def fetch(_url: str):
                return responses.pop(0)

            monitor = GitHubIPRangeMonitor(store=store, fetch_meta=fetch)
            monitor.check()
            result = monitor.check()
            self.assertTrue(result.changed)
            self.assertFalse(result.initial)
            self.assertEqual(result.added, ["3.3.3.0/24"])
            self.assertEqual(result.removed, ["1.1.1.0/24"])
            changes = monitor.status()["recent_changes"]
            self.assertEqual(len(changes), 1)
            self.assertEqual(changes[0]["added"], ["3.3.3.0/24"])
            self.assertEqual(changes[0]["removed"], ["1.1.1.0/24"])


if __name__ == "__main__":
    unittest.main()
