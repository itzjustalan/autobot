"""Stats helpers."""

from __future__ import annotations

from .db.sqlite import StateStore


def print_stats(store: StateStore) -> None:
    for row in store.stats_summary():
        print(row)
