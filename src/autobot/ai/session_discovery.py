"""Discover reusable AI session IDs from git commit messages."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable


HEURISTIC_PATTERNS = [
    r"\b([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\b",
    r"(?i)\b(?:copilot|ai|agent)[-_ ]?(?:session|task)[-_ ]?(?:id)?[:= ]+([A-Za-z0-9._:-]{7,})\b",
]


@dataclass(frozen=True)
class SessionCandidate:
    provider: str
    repo_key: str
    branch: str | None
    commit_sha: str
    session_id: str
    source: str
    confidence: int
    matched_pattern: str
    recency_index: int


def session_discovery_settings(config_data: dict[str, Any], repo: dict[str, Any] | None) -> dict[str, Any]:
    defaults = (
        config_data.get("defaults", {})
        .get("ai", {})
        .get("session_discovery", {})
    )
    repo_settings = ((repo or {}).get("ai", {}) or {}).get("session_discovery", {})
    merged = {
        "enabled": False,
        "git_log_limit": 100,
        "scan_subject": True,
        "scan_body": True,
        "heuristics_enabled": False,
        "patterns": [],
    }
    merged.update(defaults)
    merged.update(repo_settings)
    return merged


def _compile_patterns(patterns: Iterable[str]) -> list[re.Pattern[str]]:
    compiled = []
    for pattern in patterns:
        regex = re.compile(pattern, re.MULTILINE)
        if regex.groups != 1:
            raise ValueError(f"session discovery pattern must have exactly one capture group: {pattern}")
        compiled.append(regex)
    return compiled


def _git_log(repo_path: Path, limit: int) -> list[tuple[str, str]]:
    separator = "\x1f"
    record = "\x1e"
    completed = subprocess.run(
        [
            "git",
            "-C",
            str(repo_path),
            "log",
            f"--max-count={limit}",
            f"--format=%H{separator}%B{record}",
        ],
        text=True,
        capture_output=True,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "git log failed")

    commits: list[tuple[str, str]] = []
    for item in completed.stdout.split(record):
        item = item.strip()
        if not item:
            continue
        if separator not in item:
            continue
        sha, message = item.split(separator, 1)
        commits.append((sha.strip(), message.strip()))
    return commits


def discover_session_candidates(
    *,
    repo_path: Path,
    repo_key: str,
    provider: str,
    branch: str | None,
    settings: dict[str, Any],
) -> list[SessionCandidate]:
    """Discover session candidates from git log according to opt-in settings."""

    if not settings.get("enabled", False):
        return []

    patterns = list(settings.get("patterns", []))
    source_by_pattern = {pattern: "configured_regex" for pattern in patterns}
    if settings.get("heuristics_enabled", False):
        for pattern in HEURISTIC_PATTERNS:
            patterns.append(pattern)
            source_by_pattern[pattern] = "heuristic"

    if not patterns:
        return []

    compiled = _compile_patterns(patterns)
    limit = int(settings.get("git_log_limit", 100))
    scan_subject = bool(settings.get("scan_subject", True))
    scan_body = bool(settings.get("scan_body", True))
    candidates: list[SessionCandidate] = []

    for recency_index, (sha, message) in enumerate(_git_log(repo_path, limit)):
        lines = message.splitlines()
        subject = lines[0] if lines else ""
        body = "\n".join(lines[1:]) if len(lines) > 1 else ""
        searchable_parts = []
        if scan_subject:
            searchable_parts.append(subject)
        if scan_body:
            searchable_parts.append(body)
        searchable = "\n".join(part for part in searchable_parts if part)
        if not searchable:
            continue

        for raw_pattern, regex in zip(patterns, compiled, strict=True):
            for match in regex.finditer(searchable):
                session_id = match.group(1).strip()
                source = source_by_pattern[raw_pattern]
                confidence = 100 if source == "configured_regex" else 50
                candidates.append(
                    SessionCandidate(
                        provider=provider,
                        repo_key=repo_key,
                        branch=branch,
                        commit_sha=sha,
                        session_id=session_id,
                        source=source,
                        confidence=confidence,
                        matched_pattern=raw_pattern,
                        recency_index=recency_index,
                    )
                )

    return candidates


def select_best_candidate(candidates: list[SessionCandidate]) -> SessionCandidate | None:
    if not candidates:
        return None
    return sorted(candidates, key=lambda item: (-item.confidence, item.recency_index))[0]
