"""Configuration loading and validation."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import os
from pathlib import Path
import tomllib
from typing import Any

from .secrets import SecretResolver


DEFAULT_CONFIG_PATH = Path("~/.config/autobot/autobot.toml").expanduser()


class ConfigError(RuntimeError):
    """Raised for invalid autobot configuration."""


def _expand_path(value: str) -> Path:
    return Path(value).expanduser()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


@dataclass(frozen=True)
class AppConfig:
    """Parsed autobot configuration."""

    path: Path
    data: dict[str, Any]
    secret_resolver: SecretResolver

    @property
    def app_name(self) -> str:
        return str(self.data.get("app", {}).get("name", "autobot"))

    @property
    def state_dir(self) -> Path:
        return _expand_path(
            str(self.data.get("paths", {}).get("state_dir", "~/.local/state/autobot"))
        )

    @property
    def payload_dir(self) -> Path:
        return self.state_dir / "payloads"

    @property
    def database_path(self) -> Path:
        path_value = str(
            self.data.get("database", {}).get(
                "path", "~/.local/state/autobot/autobot.db"
            )
        )
        if path_value == "~/.local/state/autobot/autobot.db":
            return self.state_dir / "autobot.db"
        return _expand_path(path_value)

    @property
    def server(self) -> dict[str, Any]:
        return self.data.get("server", {})

    @property
    def queue(self) -> dict[str, Any]:
        return self.data.get("queue", {})

    @property
    def repos(self) -> list[dict[str, Any]]:
        repos = self.data.get("repos", [])
        return repos if isinstance(repos, list) else []

    def repo_config(self, key: str) -> dict[str, Any] | None:
        for repo in self.repos:
            if repo.get("key") == key:
                return repo
        return None

    def queue_url(self) -> str:
        ref = self.queue.get("url", {"env": "AUTOBOT_QUEUE_URL", "default": "redis://127.0.0.1:6379/0"})
        return self.secret_resolver.resolve(ref, name="queue.url")

    def github_webhook_secret(self) -> str:
        ref = self.data.get("providers", {}).get("github", {}).get("webhook_secret")
        if not ref:
            raise ConfigError("providers.github.webhook_secret is required")
        return self.secret_resolver.resolve(ref, name="providers.github.webhook_secret")

    def validate(self) -> None:
        if self.queue.get("backend", "redis") not in {"redis", "valkey"}:
            raise ConfigError("queue.backend must be 'redis' or 'valkey'")
        if not self.server.get("host"):
            raise ConfigError("server.host is required")
        if not self.server.get("port"):
            raise ConfigError("server.port is required")
        if not self.server.get("webhook_path"):
            raise ConfigError("server.webhook_path is required")


def default_config() -> dict[str, Any]:
    """Built-in defaults. User TOML overrides these."""

    return {
        "app": {"name": "autobot", "mode": "supervised", "config_version": 1},
        "paths": {
            "state_dir": "~/.local/state/autobot",
            "prompt_override_dir": "~/.config/autobot/prompts",
            "env_file": "~/.config/autobot/.env",
        },
        "server": {
            "host": "127.0.0.1",
            "port": 9090,
            "webhook_path": "/hooks/github",
            "health_path": "/healthz",
            "readiness_path": "/readyz",
        },
        "queue": {
            "backend": "redis",
            "url": {"env": "AUTOBOT_QUEUE_URL", "default": "redis://127.0.0.1:6379/0"},
            "ready_stream": "autobot:ready",
            "scheduled_zset": "autobot:scheduled",
        },
        "database": {"driver": "sqlite", "path": "~/.local/state/autobot/autobot.db"},
        "providers": {
            "github": {
                "ip_allowlist_monitor": {
                    "enabled": True,
                    "meta_url": "https://api.github.com/meta",
                    "check_interval_seconds": 86400,
                    "warn_on_change": True,
                }
            }
        },
        "defaults": {
            "throttle": {
                "quiet_window_seconds": 900,
                "max_open_child_prs_per_parent_pr": 1,
                "coalesce_by": "parent_pr",
            },
            "branching": {
                "child_branch_template": "{{app_name:-autobot}}/pr-{{pr_number}}-{{handler_id}}",
                "target": "parent_pr_head_branch",
            },
        },
    }


def load_config(path: str | Path | None = None) -> AppConfig:
    """Load config from TOML and configured .env file."""

    config_path = Path(
        path or os.environ.get("AUTOBOT_CONFIG") or DEFAULT_CONFIG_PATH
    ).expanduser()
    user_config: dict[str, Any] = {}
    if config_path.exists():
        user_config = tomllib.loads(config_path.read_text(encoding="utf-8"))
    data = _deep_merge(default_config(), user_config)
    env_file_value = data.get("paths", {}).get("env_file")
    env_file = _expand_path(str(env_file_value)) if env_file_value else None
    resolver = SecretResolver(env_file=env_file)
    resolver.load_env_file()
    app_config = AppConfig(path=config_path, data=data, secret_resolver=resolver)
    app_config.validate()
    return app_config
