"""Local React SPA dashboard server."""

from __future__ import annotations

from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
from importlib import resources
import json
import logging
import mimetypes
from pathlib import Path
import secrets
import socket
from typing import Any
from urllib.parse import parse_qs, urlparse

from .config import AppConfig
from .db.sqlite import StateStore
from .providers.github_meta import GitHubIPRangeMonitor
from .queue.redis_queue import RedisQuietWindowQueue


LOG = logging.getLogger(__name__)
TOKEN_COOKIE = "autobot_web_token"


def _json_response(handler: BaseHTTPRequestHandler, status: HTTPStatus, data: Any) -> None:
    body = json.dumps(data, sort_keys=True, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _redact_config(value: Any) -> Any:
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            lower = str(key).lower()
            if any(marker in lower for marker in ("secret", "token", "key", "password")):
                result[key] = "<redacted>"
            else:
                result[key] = _redact_config(item)
        return result
    if isinstance(value, list):
        return [_redact_config(item) for item in value]
    return value


class WebRuntime:
    def __init__(self, config: AppConfig, *, token: str, enable_actions: bool) -> None:
        self.config = config
        self.token = token
        self.enable_actions = enable_actions
        self.store = StateStore(config.database_path)

    def summary(self) -> dict[str, Any]:
        queue_ready = False
        queue_error = None
        try:
            queue_ready = RedisQuietWindowQueue(self.config.queue_url()).ping()
        except Exception as exc:  # noqa: BLE001 - surface status in dashboard.
            queue_error = str(exc)
        snapshot = GitHubIPRangeMonitor(store=self.store).status()["snapshot"]
        return {
            "app": self.config.app_name,
            "config_path": str(self.config.path),
            "database_path": str(self.config.database_path),
            "state_dir": str(self.config.state_dir),
            "queue": {
                "backend": self.config.queue.get("backend", "redis"),
                "ready": queue_ready,
                "error": queue_error,
            },
            "web": {
                "read_only": not self.enable_actions,
                "actions_enabled": self.enable_actions,
            },
            "github_hooks": {
                "range_count": len(snapshot["ranges"]) if snapshot else 0,
                "checked_at": snapshot["checked_at"] if snapshot else None,
            },
        }


def _static_root() -> Path:
    return Path(str(resources.files("autobot") / "web_static"))


def _read_static(path: str) -> tuple[bytes, str] | None:
    root = _static_root().resolve()
    relative = path.lstrip("/") or "index.html"
    candidate = (root / relative).resolve()
    if not str(candidate).startswith(str(root)):
        return None
    if not candidate.exists() or candidate.is_dir():
        candidate = root / "index.html"
    if not candidate.exists():
        return None
    content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    return candidate.read_bytes(), content_type


def _detected_access_hosts(bind_host: str) -> list[str]:
    """Return browser-usable hosts for the bind address."""

    if bind_host in {"0.0.0.0", "::"}:
        hosts: list[str] = []
        try:
            for item in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
                ip = item[4][0]
                if ip.startswith("127.") or ip in hosts:
                    continue
                hosts.append(ip)
        except socket.gaierror:
            pass
        if not hosts:
            try:
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.connect(("8.8.8.8", 80))
                    ip = sock.getsockname()[0]
                    if not ip.startswith("127."):
                        hosts.append(ip)
            except OSError:
                pass
        return hosts or ["<vm-ip>"]
    return [bind_host]


def dashboard_access_urls(*, bind_host: str, port: int, token: str) -> list[str]:
    return [f"http://{host}:{port}/?token={token}" for host in _detected_access_hosts(bind_host)]


class DashboardHandler(BaseHTTPRequestHandler):
    runtime: WebRuntime

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        LOG.info("%s - %s", self.client_address[0], format % args)

    def _request_token(self) -> str | None:
        parsed = urlparse(self.path)
        query_token = parse_qs(parsed.query).get("token", [None])[0]
        if query_token:
            return query_token
        auth = self.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            return auth.removeprefix("Bearer ").strip()
        header_token = self.headers.get("X-Autobot-Token")
        if header_token:
            return header_token
        cookie = SimpleCookie(self.headers.get("Cookie"))
        morsel = cookie.get(TOKEN_COOKIE)
        return morsel.value if morsel else None

    def _authorized(self) -> bool:
        token = self._request_token()
        return bool(token) and hmac.compare_digest(token, self.runtime.token)

    def _send_static(self, *, set_cookie: bool = False) -> None:
        parsed = urlparse(self.path)
        static = _read_static(parsed.path)
        if static is None:
            _json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "dashboard assets not built"})
            return
        body, content_type = static
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if set_cookie:
            self.send_header("Set-Cookie", f"{TOKEN_COOKIE}={self.runtime.token}; HttpOnly; SameSite=Strict; Path=/")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            if not self._authorized():
                _json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
                return
            self._handle_api_get(parsed.path)
            return

        if self._authorized():
            self._send_static(set_cookie=bool(parse_qs(parsed.query).get("token")))
            return
        _json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "token required"})

    def do_POST(self) -> None:  # noqa: N802
        if not self._authorized():
            _json_response(self, HTTPStatus.UNAUTHORIZED, {"ok": False, "error": "unauthorized"})
            return
        if not self.runtime.enable_actions:
            _json_response(self, HTTPStatus.FORBIDDEN, {"ok": False, "error": "dashboard actions are disabled"})
            return
        _json_response(self, HTTPStatus.NOT_IMPLEMENTED, {"ok": False, "error": "action endpoint not implemented yet"})

    def _handle_api_get(self, path: str) -> None:
        store = self.runtime.store
        routes = {
            "/api/health": lambda: {"ok": True},
            "/api/summary": self.runtime.summary,
            "/api/deliveries": store.list_deliveries,
            "/api/events": store.list_events,
            "/api/jobs": store.list_jobs,
            "/api/runs": store.list_runs,
            "/api/pull-requests": store.list_pull_requests,
            "/api/child-prs": store.list_child_prs,
            "/api/pr-stats": store.stats_summary,
            "/api/artifacts": store.list_artifacts,
            "/api/github-ip-ranges": lambda: GitHubIPRangeMonitor(store=store).status(),
            "/api/config/effective": lambda: _redact_config(self.runtime.config.data),
        }
        factory = routes.get(path)
        if not factory:
            _json_response(self, HTTPStatus.NOT_FOUND, {"ok": False, "error": "not found"})
            return
        _json_response(self, HTTPStatus.OK, {"ok": True, "data": factory()})


def web(config: AppConfig, *, host: str | None = None, port: int | None = None, token: str | None = None, enable_actions: bool | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    web_config = config.data.get("web", {})
    bind_host = host or str(web_config.get("host", "127.0.0.1"))
    bind_port = port or int(web_config.get("port", 9091))
    actions = bool(enable_actions if enable_actions is not None else web_config.get("enable_actions", False))
    access_token = token or secrets.token_urlsafe(32)
    if bind_host not in {"127.0.0.1", "localhost", "::1"}:
        LOG.warning("autobot web is binding to non-loopback host %s", bind_host)
    runtime = WebRuntime(config, token=access_token, enable_actions=actions)
    handler = type("ConfiguredDashboardHandler", (DashboardHandler,), {"runtime": runtime})
    httpd = ThreadingHTTPServer((bind_host, bind_port), handler)
    LOG.info("autobot dashboard bound to http://%s:%s", bind_host, bind_port)
    for url in dashboard_access_urls(bind_host=bind_host, port=bind_port, token=access_token):
        LOG.info("autobot dashboard URL: %s", url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        LOG.info("autobot dashboard shutdown requested")
    finally:
        httpd.server_close()
