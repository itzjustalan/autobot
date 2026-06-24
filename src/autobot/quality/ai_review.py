"""AI review quality gate placeholder."""

from __future__ import annotations


def ai_review_enabled(config: dict) -> bool:
    return bool(config.get("run_ai_review_before_commit", False))
