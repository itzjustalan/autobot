"""Repo registry backed by config."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RepoConfig:
    key: str
    provider: str
    enabled: bool
    local_path: Path | None = None
    raw: dict[str, Any] | None = None


class RepoRegistry:
    def __init__(self, repos: list[dict[str, Any]]) -> None:
        self._repos = {
            str(repo["key"]): RepoConfig(
                key=str(repo["key"]),
                provider=str(repo.get("provider", "github")),
                enabled=bool(repo.get("enabled", True)),
                local_path=Path(str(repo["local_path"])).expanduser()
                if repo.get("local_path")
                else None,
                raw=repo,
            )
            for repo in repos
            if "key" in repo
        }

    def get(self, key: str) -> RepoConfig | None:
        repo = self._repos.get(key)
        if repo and repo.enabled:
            return repo
        return None
