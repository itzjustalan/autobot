"""Secret reference resolution for autobot.

TOML config must reference secrets through environment variables, files, or
systemd-style credentials. Literal secret values are intentionally unsupported.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any


class SecretResolutionError(RuntimeError):
    """Raised when a configured secret cannot be resolved."""


@dataclass(frozen=True)
class SecretResolver:
    """Resolve secret references from config."""

    env_file: Path | None = None
    credentials_dir: Path | None = None

    def load_env_file(self) -> None:
        """Load a simple KEY=VALUE .env file without overriding existing env."""

        if not self.env_file or not self.env_file.exists():
            return

        for raw_line in self.env_file.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value

    def resolve(self, ref: Any, *, name: str = "secret") -> str:
        """Resolve a secret reference.

        Supported forms:
        - {"env": "NAME"}
        - {"file": "/path/to/file"}
        - {"credential": "systemd-credential-name"}
        - {"env": "NAME", "default": "..."} for non-secret URLs/settings
        """

        if not isinstance(ref, dict):
            raise SecretResolutionError(
                f"{name} must be a secret reference object, not a literal value"
            )

        if "env" in ref:
            env_name = str(ref["env"])
            value = os.environ.get(env_name)
            if value:
                return value
            if "default" in ref:
                return str(ref["default"])
            raise SecretResolutionError(f"{name} env var {env_name!r} is not set")

        if "file" in ref:
            path = Path(str(ref["file"])).expanduser()
            if not path.exists():
                raise SecretResolutionError(f"{name} file {path} does not exist")
            return path.read_text(encoding="utf-8").strip()

        if "credential" in ref:
            credential = str(ref["credential"])
            base = self.credentials_dir or Path(
                os.environ.get("CREDENTIALS_DIRECTORY", "")
            )
            if not str(base):
                raise SecretResolutionError(
                    f"{name} credential {credential!r} requested but no credentials dir is set"
                )
            path = base / credential
            if not path.exists():
                raise SecretResolutionError(f"{name} credential {credential!r} not found")
            return path.read_text(encoding="utf-8").strip()

        raise SecretResolutionError(
            f"{name} must reference one of: env, file, credential"
        )
