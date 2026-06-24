"""Test command quality gates."""

from __future__ import annotations

import subprocess


def run_test_commands(commands: list[str]) -> list[subprocess.CompletedProcess[str]]:
    return [
        subprocess.run(command, shell=True, text=True, capture_output=True, check=False)
        for command in commands
    ]
