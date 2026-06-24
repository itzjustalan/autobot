"""Shell handler support."""

from __future__ import annotations

import subprocess


class ShellHandlerDisabled(RuntimeError):
    """Raised when shell handlers are disabled by configuration."""


def run_shell(command: str, *, enabled: bool) -> subprocess.CompletedProcess[str]:
    if not enabled:
        raise ShellHandlerDisabled("shell handlers are disabled")
    return subprocess.run(
        command,
        shell=True,
        text=True,
        capture_output=True,
        check=False,
    )
