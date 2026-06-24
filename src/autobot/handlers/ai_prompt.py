"""AI prompt handler helpers."""

from __future__ import annotations

from pathlib import Path


def load_prompt(name: str, *, override_dir: Path, default_dir: Path) -> str:
    override = override_dir / f"{name}.md"
    if override.exists():
        return override.read_text(encoding="utf-8")
    default = default_dir / f"{name}.md"
    if default.exists():
        return default.read_text(encoding="utf-8")
    raise FileNotFoundError(f"Prompt {name!r} not found")
