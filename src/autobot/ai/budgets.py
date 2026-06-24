"""Token and cost budget helpers."""

from __future__ import annotations


def rough_token_estimate(text: str) -> int:
    """Very rough model-agnostic token estimate for budgeting."""

    return max(1, len(text) // 4)
