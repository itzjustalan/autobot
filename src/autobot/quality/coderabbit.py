"""Local CodeRabbit CLI quality gate."""

from __future__ import annotations

import shutil
import subprocess


def coderabbit_available(command: str = "coderabbit") -> bool:
    return shutil.which(command) is not None


def run_coderabbit(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, text=True, capture_output=True, check=False)
