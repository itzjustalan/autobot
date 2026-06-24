"""Safe template literals used by config, prompts, and branch names."""

from __future__ import annotations

import re
from typing import Any


TEMPLATE_RE = re.compile(r"\{\{\s*([A-Za-z_][A-Za-z0-9_.-]*)(?::-(.*?))?\s*\}\}")
UNSAFE_BRANCH_CHARS = re.compile(r"[^A-Za-z0-9._/-]+")


class TemplateRenderError(RuntimeError):
    """Raised when a template cannot be rendered."""


def _lookup(context: dict[str, Any], key: str) -> Any:
    current: Any = context
    for part in key.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        else:
            raise KeyError(key)
    return current


def render_template(template: str, context: dict[str, Any]) -> str:
    """Render `{{name}}` and `{{name:-default}}` placeholders.

    No code execution, filters, loops, or function calls are supported.
    """

    def replace(match: re.Match[str]) -> str:
        key = match.group(1)
        default = match.group(2)
        try:
            value = _lookup(context, key)
        except KeyError:
            if default is not None:
                return default
            raise TemplateRenderError(f"Missing template variable: {key}") from None
        return str(value)

    return TEMPLATE_RE.sub(replace, template)


def sanitize_branch_name(value: str) -> str:
    """Sanitize a rendered branch name for common Git hosting providers."""

    cleaned = UNSAFE_BRANCH_CHARS.sub("-", value.strip())
    cleaned = re.sub(r"/+", "/", cleaned)
    cleaned = cleaned.strip("/.")
    cleaned = cleaned.replace("..", "-")
    if not cleaned:
        raise TemplateRenderError("Rendered branch name is empty after sanitization")
    return cleaned[:240]
