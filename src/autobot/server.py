"""Built-in autobot HTTP webhook daemon."""

from __future__ import annotations

from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path
import threading
import time
from typing import Any
from uuid import uuid4

from .config import AppConfig
from .db.sqlite import StateStore
from .providers.github import GitHubProvider, GitHubSignatureError, parse_json_body, verify_signature
from .providers.github_meta import GitHubIPRangeMonitor
from .queue.redis_queue import QueueError, RedisQuietWindowQueue
from .queue.recovery import recover_after_crash


LOG = logging.getLogger(__name__)


class AutobotRuntime:
    """Runtime dependencies shared by request handlers."""

    def __init__(self, config: AppConfig) -> None:
        self.config = config
        self.state = StateStore(config.database_path)
        recover_after_crash(self.state)
        self.queue = RedisQuietWindowQueue(config.queue_url())
        self.github = GitHubProvider()
        self.payload_dir = config.payload_dir
        self.payload_dir.mkdir(parents=True, exist_ok=True)
        self._monitor_stop = threading.Event()
        self._monitor_thread: threading.Thread | None = None

    def ready(self) -> tuple[bool, str]:
        try:
            self.queue.ping()
        except Exception as exc:  # noqa: BLE001 - readiness should report dependency failures.
            return False, f"queue unavailable: {exc}"
        return True, "ready"

    def quiet_window_seconds(self) -> int:
        return int(
            self.config.data.get("defaults", {})
            .get("throttle", {})
            .get("quiet_window_seconds", 900)
        )

    def handler_for(self, event_name: str) -> str:
        for handler in self.config.data.get("handlers", []):
            if handler.get("enabled", True) and handler.get("event") == event_name:
                return str(handler["id"])
        return "noop"

    def start_ip_range_monitor(self) -> None:
        settings = (
            self.config.data.get("providers", {})
            .get("github", {})
            .get("ip_allowlist_monitor", {})
        )
        if not settings.get("enabled", True):
            return
        interval = int(settings.get("check_interval_seconds", 86400))
        meta_url = str(settings.get("meta_url", "https://api.github.com/meta"))
        monitor = GitHubIPRangeMonitor(store=self.state, meta_url=meta_url)

        def run() -> None:
            while not self._monitor_stop.is_set():
                try:
                    monitor.check()
                except Exception as exc:  # noqa: BLE001 - daemon monitor should warn, not crash.
                    LOG.warning("GitHub webhook IP range check failed: %s", exc)
                self._monitor_stop.wait(interval)

        self._monitor_thread = threading.Thread(
            target=run,
            name="github-ip-range-monitor",
            daemon=True,
        )
        self._monitor_thread.start()

    def stop_ip_range_monitor(self) -> None:
        self._monitor_stop.set()
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5)


def _headers_dict(handler: BaseHTTPRequestHandler) -> dict[str, str]:
    return {key.lower(): value for key, value in handler.headers.items()}


def _write_json(handler: BaseHTTPRequestHandler, status: HTTPStatus, body: dict[str, Any]) -> None:
    payload = json.dumps(body, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(payload)))
    handler.end_headers()
    handler.wfile.write(payload)


class AutobotRequestHandler(BaseHTTPRequestHandler):
    runtime: AutobotRuntime

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        LOG.info("%s - %s", self.client_address[0], format % args)

    def do_GET(self) -> None:  # noqa: N802
        health_path = self.runtime.config.server.get("health_path", "/healthz")
        readiness_path = self.runtime.config.server.get("readiness_path", "/readyz")
        if self.path == health_path:
            _write_json(self, HTTPStatus.OK, {"ok": True, "status": "healthy"})
            return
        if self.path == readiness_path:
            ready, message = self.runtime.ready()
            _write_json(
                self,
                HTTPStatus.OK if ready else HTTPStatus.SERVICE_UNAVAILABLE,
                {"ok": ready, "status": message},
            )
            return
        _write_json(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        if self.path != self.runtime.config.server.get("webhook_path", "/hooks/github"):
            _write_json(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return

        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        headers = _headers_dict(self)
        delivery_id = headers.get("x-github-delivery") or str(uuid4())
        event_name = headers.get("x-github-event", "unknown")

        try:
            secret = self.runtime.config.github_webhook_secret()
            verify_signature(
                secret=secret,
                body=body,
                signature=headers.get("x-hub-signature-256"),
            )
            payload = parse_json_body(body)
        except GitHubSignatureError as exc:
            _write_json(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 - malformed webhook should return 400.
            _write_json(self, HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)})
            return

        payload_path = self._write_payload(delivery_id, body)
        action = payload.get("action")
        is_new = self.runtime.state.record_delivery(
            provider="github",
            delivery_id=delivery_id,
            event_name=event_name,
            event_action=str(action) if action else None,
            signature_status="valid",
            payload_path=payload_path,
        )
        if not is_new:
            _write_json(
                self,
                HTTPStatus.ACCEPTED,
                {"ok": True, "dedupe": "duplicate", "delivery_id": delivery_id},
            )
            return

        envelope = self.runtime.github.normalize(
            headers=headers,
            payload=payload,
            payload_path=str(payload_path),
        )
        self.runtime.state.record_event(envelope)
        handler_id = self.runtime.handler_for(envelope.event_name)
        quiet_window = self.runtime.quiet_window_seconds()

        try:
            job_id, not_before = self.runtime.queue.enqueue(
                envelope=envelope,
                handler_id=handler_id,
                quiet_window_seconds=quiet_window,
            )
        except QueueError as exc:
            _write_json(self, HTTPStatus.SERVICE_UNAVAILABLE, {"ok": False, "error": str(exc)})
            return

        self.runtime.state.upsert_job(
            job_id=job_id,
            resource_key=envelope.resource_key,
            handler_id=handler_id,
            status="scheduled",
            not_before=not_before,
            envelope=envelope,
        )
        _write_json(
            self,
            HTTPStatus.ACCEPTED,
            {
                "ok": True,
                "delivery_id": delivery_id,
                "job_id": job_id,
                "not_before": not_before,
            },
        )

    def _write_payload(self, delivery_id: str, body: bytes) -> Path:
        ts = int(time.time())
        safe_delivery = "".join(ch for ch in delivery_id if ch.isalnum() or ch in "-_")
        path = self.runtime.payload_dir / f"{ts}-{safe_delivery}.json"
        path.write_bytes(body)
        return path


def serve(config: AppConfig) -> None:
    """Run the autobot HTTP server until interrupted."""

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    runtime = AutobotRuntime(config)
    runtime.start_ip_range_monitor()
    handler = type(
        "ConfiguredAutobotRequestHandler",
        (AutobotRequestHandler,),
        {"runtime": runtime},
    )
    host = str(config.server.get("host", "127.0.0.1"))
    port = int(config.server.get("port", 9090))
    httpd = ThreadingHTTPServer((host, port), handler)
    LOG.info("autobot serving on http://%s:%s", host, port)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOG.info("autobot shutdown requested")
    finally:
        runtime.stop_ip_range_monitor()
        httpd.server_close()
