"""Redis/Valkey quiet-window queue backend."""

from __future__ import annotations

from dataclasses import dataclass
import json
import time
from typing import Any

from autobot.event_envelope import EventEnvelope


class QueueError(RuntimeError):
    """Raised when queue operations fail."""


@dataclass(frozen=True)
class QueueNames:
    events: str = "autobot:events"
    scheduled: str = "autobot:scheduled"
    ready: str = "autobot:ready"
    resource_job_prefix: str = "autobot:resource-job:"
    job_prefix: str = "autobot:job:"
    lock_prefix: str = "autobot:locks:"


class RedisQuietWindowQueue:
    """Queue events with quiet-window coalescing.

    The implementation works with Redis and Valkey because it uses Redis
    protocol primitives only.
    """

    def __init__(self, url: str, names: QueueNames | None = None) -> None:
        try:
            import redis
        except ImportError as exc:  # pragma: no cover - dependency issue.
            raise QueueError("redis package is required for Redis/Valkey backend") from exc
        self.client = redis.Redis.from_url(url, decode_responses=True)
        self.names = names or QueueNames()

    def ping(self) -> bool:
        return bool(self.client.ping())

    def enqueue(
        self,
        *,
        envelope: EventEnvelope,
        handler_id: str,
        quiet_window_seconds: int,
    ) -> tuple[str, float]:
        now = time.time()
        not_before = now + quiet_window_seconds
        resource_key = envelope.resource_key
        resource_job_key = f"{self.names.resource_job_prefix}{resource_key}"
        job_id = self.client.get(resource_job_key)
        if not job_id:
            safe_resource = resource_key.replace(":", "-").replace("/", "-")
            job_id = f"{safe_resource}:{handler_id}"
            self.client.set(resource_job_key, job_id)

        job_key = f"{self.names.job_prefix}{job_id}"
        payload = json.dumps(envelope.to_dict(), sort_keys=True)
        pipe = self.client.pipeline()
        pipe.xadd(
            self.names.events,
            {
                "job_id": job_id,
                "delivery_id": envelope.delivery_id,
                "resource_key": resource_key,
                "event": payload,
            },
        )
        pipe.hset(
            job_key,
            mapping={
                "job_id": job_id,
                "handler_id": handler_id,
                "resource_key": resource_key,
                "latest_delivery_id": envelope.delivery_id,
                "latest_event": payload,
                "last_event_at": str(now),
                "not_before": str(not_before),
                "status": "scheduled",
            },
        )
        pipe.zadd(self.names.scheduled, {job_id: not_before})
        pipe.execute()
        return job_id, not_before

    def release_ready(self, *, now: float | None = None, limit: int = 100) -> int:
        current = now or time.time()
        job_ids = self.client.zrangebyscore(self.names.scheduled, 0, current, start=0, num=limit)
        released = 0
        for job_id in job_ids:
            job_key = f"{self.names.job_prefix}{job_id}"
            job = self.client.hgetall(job_key)
            if not job:
                self.client.zrem(self.names.scheduled, job_id)
                continue
            not_before = float(job.get("not_before", "0"))
            if not_before > current:
                self.client.zadd(self.names.scheduled, {job_id: not_before})
                continue
            self.client.zrem(self.names.scheduled, job_id)
            self.client.hset(job_key, "status", "ready")
            self.client.xadd(
                self.names.ready,
                {
                    "job_id": job_id,
                    "resource_key": job.get("resource_key", ""),
                    "handler_id": job.get("handler_id", ""),
                },
            )
            released += 1
        return released

    def pop_ready(self, *, count: int = 1) -> list[dict[str, str]]:
        """Pop ready jobs from the ready stream.

        This simple implementation uses XRANGE/XDEL instead of consumer groups
        for the first daemon version. Job state remains durable in SQLite.
        """

        rows = self.client.xrange(self.names.ready, count=count)
        jobs: list[dict[str, str]] = []
        for entry_id, data in rows:
            jobs.append({"entry_id": entry_id, **{str(k): str(v) for k, v in data.items()}})
            self.client.xdel(self.names.ready, entry_id)
        return jobs

    def acquire_lock(self, resource_key: str, owner: str, ttl_seconds: int = 900) -> bool:
        return bool(
            self.client.set(
                f"{self.names.lock_prefix}{resource_key}",
                owner,
                nx=True,
                ex=ttl_seconds,
            )
        )

    def release_lock(self, resource_key: str, owner: str) -> bool:
        key = f"{self.names.lock_prefix}{resource_key}"
        if self.client.get(key) != owner:
            return False
        self.client.delete(key)
        return True
