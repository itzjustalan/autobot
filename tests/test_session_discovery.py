from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile
import unittest

from autobot.ai.command import CommandAIProvider
from autobot.ai.session_discovery import (
    discover_session_candidates,
    select_best_candidate,
)


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True)


class SessionDiscoveryTests(unittest.TestCase):
    def _repo(self) -> Path:
        root = Path(tempfile.mkdtemp())
        _git(root, "init")
        _git(root, "config", "user.email", "test@example.com")
        _git(root, "config", "user.name", "Test User")
        (root / "file.txt").write_text("one\n", encoding="utf-8")
        _git(root, "add", "file.txt")
        _git(
            root,
            "commit",
            "-m",
            "initial\n\nCopilot-Session-Id: session-older",
        )
        (root / "file.txt").write_text("two\n", encoding="utf-8")
        _git(root, "add", "file.txt")
        _git(
            root,
            "commit",
            "-m",
            "update\n\nAutobot-Session-Id: session-newer",
        )
        return root

    def test_disabled_by_default(self) -> None:
        repo = self._repo()
        candidates = discover_session_candidates(
            repo_path=repo,
            repo_key="owner/repo",
            provider="copilot",
            branch="main",
            settings={"enabled": False},
        )
        self.assertEqual(candidates, [])

    def test_configured_regex_discovers_and_scores_recent_candidate(self) -> None:
        repo = self._repo()
        candidates = discover_session_candidates(
            repo_path=repo,
            repo_key="owner/repo",
            provider="copilot",
            branch="main",
            settings={
                "enabled": True,
                "git_log_limit": 20,
                "scan_subject": True,
                "scan_body": True,
                "heuristics_enabled": False,
                "patterns": [
                    r"(?i)^Copilot-Session-Id:\s*([A-Za-z0-9._:-]+)\s*$",
                    r"(?i)^Autobot-Session-Id:\s*([A-Za-z0-9._:-]+)\s*$",
                ],
            },
        )
        self.assertEqual({item.session_id for item in candidates}, {"session-older", "session-newer"})
        self.assertEqual(select_best_candidate(candidates).session_id, "session-newer")
        self.assertTrue(all(item.source == "configured_regex" for item in candidates))

    def test_heuristics_are_opt_in(self) -> None:
        repo = Path(tempfile.mkdtemp())
        _git(repo, "init")
        _git(repo, "config", "user.email", "test@example.com")
        _git(repo, "config", "user.name", "Test User")
        (repo / "file.txt").write_text("one\n", encoding="utf-8")
        _git(repo, "add", "file.txt")
        _git(repo, "commit", "-m", "session 123e4567-e89b-12d3-a456-426614174000")

        base = {
            "enabled": True,
            "git_log_limit": 20,
            "scan_subject": True,
            "scan_body": True,
            "patterns": [],
        }
        self.assertEqual(
            discover_session_candidates(
                repo_path=repo,
                repo_key="owner/repo",
                provider="copilot",
                branch="main",
                settings={**base, "heuristics_enabled": False},
            ),
            [],
        )
        candidates = discover_session_candidates(
            repo_path=repo,
            repo_key="owner/repo",
            provider="copilot",
            branch="main",
            settings={**base, "heuristics_enabled": True},
        )
        self.assertEqual(candidates[0].session_id, "123e4567-e89b-12d3-a456-426614174000")

    def test_command_provider_session_arg_is_single_argv_element(self) -> None:
        provider = CommandAIProvider(
            ["copilot", "-p", "-"],
            connect_arg_template="--connect={{session_id}}",
        )
        command = provider.build_command(session_id="abc; rm -rf /")
        self.assertEqual(command[-1], "--connect=abc; rm -rf /")
        self.assertEqual(len(command), 4)


if __name__ == "__main__":
    unittest.main()
