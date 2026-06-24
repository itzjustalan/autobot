"""Command-line interface for autobot."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

from .config import ConfigError, load_config
from .db.sqlite import StateStore
from .queue.redis_queue import RedisQuietWindowQueue
from .server import serve
from .stats import print_stats
from .templates import render_template
from .workflows.engine import run_job


def _add_config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", help="Path to autobot.toml")


def cmd_doctor(args: argparse.Namespace) -> int:
    try:
        config = load_config(args.config)
        config.database_path.parent.mkdir(parents=True, exist_ok=True)
        config.payload_dir.mkdir(parents=True, exist_ok=True)
        print(f"config: ok ({config.path})")
        print(f"state_dir: {config.state_dir}")
        print(f"server: {config.server.get('host')}:{config.server.get('port')}")
        print(f"queue: {config.queue.get('backend')} {config.queue_url()}")
        return 0
    except Exception as exc:  # noqa: BLE001 - doctor should surface any failure.
        print(f"doctor: failed: {exc}", file=sys.stderr)
        return 1


def cmd_render(args: argparse.Namespace) -> int:
    context = json.loads(args.context or "{}")
    print(render_template(args.template, context))
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    serve(config)
    return 0


def cmd_scheduler(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    queue = RedisQuietWindowQueue(config.queue_url())
    released = queue.release_ready(limit=args.limit)
    print(f"released {released} job(s)")
    return 0


def cmd_stats(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    print_stats(StateStore(config.database_path))
    return 0


def cmd_worker(args: argparse.Namespace) -> int:
    config = load_config(args.config)
    store = StateStore(config.database_path)
    queue = RedisQuietWindowQueue(config.queue_url())
    jobs = queue.pop_ready(count=args.count)
    for job in jobs:
        result = run_job(config=config, store=store, job_id=job["job_id"])
        print(f"{job['job_id']}: {result.status}: {result.summary}")
    if not jobs:
        print("no ready jobs")
    return 0


def cmd_placeholder(name: str) -> int:
    print(f"{name}: not implemented yet")
    return 2


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="autobot")
    sub = parser.add_subparsers(dest="command", required=True)

    serve_parser = sub.add_parser("serve", help="Run the webhook HTTP daemon")
    _add_config_arg(serve_parser)
    serve_parser.set_defaults(func=cmd_serve)

    doctor = sub.add_parser("doctor", help="Validate local config and dependencies")
    _add_config_arg(doctor)
    doctor.set_defaults(func=cmd_doctor)

    render = sub.add_parser("render", help="Render a template with JSON context")
    render.add_argument("template")
    render.add_argument("--context", default="{}")
    render.set_defaults(func=cmd_render)

    worker = sub.add_parser("worker", help="Process ready jobs")
    _add_config_arg(worker)
    worker.add_argument("--count", type=int, default=1)
    worker.set_defaults(func=cmd_worker)

    for name in ["bootstrap", "cleanup"]:
        command = sub.add_parser(name)
        _add_config_arg(command)
        command.set_defaults(func=lambda _args, n=name: cmd_placeholder(n))

    scheduler = sub.add_parser("scheduler", help="Release ready quiet-window jobs")
    _add_config_arg(scheduler)
    scheduler.add_argument("--limit", type=int, default=100)
    scheduler.set_defaults(func=cmd_scheduler)

    stats = sub.add_parser("stats", help="Print tracked PR stats")
    _add_config_arg(stats)
    stats.set_defaults(func=cmd_stats)

    webhook = sub.add_parser("webhook", help="Webhook test helpers")
    webhook_sub = webhook.add_subparsers(dest="provider", required=True)
    github = webhook_sub.add_parser("github", help="Process a saved GitHub payload")
    _add_config_arg(github)
    github.add_argument("--payload", type=Path, required=True)
    github.set_defaults(func=lambda _args: cmd_placeholder("webhook github"))

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ConfigError as exc:
        print(f"config error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
