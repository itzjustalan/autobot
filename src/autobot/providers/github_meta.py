"""GitHub /meta monitoring for webhook source ranges."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import logging
from typing import Any, Callable

import requests

from autobot.db.sqlite import StateStore


LOG = logging.getLogger(__name__)


FetchMeta = Callable[[str], tuple[dict[str, Any], str | None]]


@dataclass(frozen=True)
class IPRangeCheckResult:
    provider: str
    range_type: str
    changed: bool
    initial: bool
    ranges: list[str]
    added: list[str] = field(default_factory=list)
    removed: list[str] = field(default_factory=list)
    checked_at: str = ""


def _default_fetch_meta(url: str) -> tuple[dict[str, Any], str | None]:
    response = requests.get(
        url,
        timeout=20,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "autobot",
        },
    )
    response.raise_for_status()
    etag = response.headers.get("ETag")
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("GitHub /meta response must be a JSON object")
    return payload, etag


def hash_ranges(ranges: list[str]) -> str:
    canonical = json.dumps(sorted(ranges), separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class GitHubIPRangeMonitor:
    """Fetch, store, and compare GitHub webhook source CIDR ranges."""

    provider = "github"
    range_type = "hooks"

    def __init__(
        self,
        *,
        store: StateStore,
        meta_url: str = "https://api.github.com/meta",
        fetch_meta: FetchMeta = _default_fetch_meta,
    ) -> None:
        self.store = store
        self.meta_url = meta_url
        self.fetch_meta = fetch_meta

    def check(self) -> IPRangeCheckResult:
        payload, etag = self.fetch_meta(self.meta_url)
        raw_ranges = payload.get(self.range_type)
        if not isinstance(raw_ranges, list) or not all(isinstance(item, str) for item in raw_ranges):
            raise ValueError("GitHub /meta response does not include a valid hooks list")

        ranges = sorted(raw_ranges)
        current_hash = hash_ranges(ranges)
        previous = self.store.get_provider_ip_ranges(
            provider=self.provider,
            range_type=self.range_type,
        )
        checked_at = datetime.now(timezone.utc).isoformat()
        if previous is None:
            self.store.upsert_provider_ip_ranges(
                provider=self.provider,
                range_type=self.range_type,
                ranges=ranges,
                source_url=self.meta_url,
                current_hash=current_hash,
                etag=etag,
            )
            LOG.info("stored initial GitHub webhook IP range snapshot (%d ranges)", len(ranges))
            return IPRangeCheckResult(
                provider=self.provider,
                range_type=self.range_type,
                changed=False,
                initial=True,
                ranges=ranges,
                checked_at=checked_at,
            )

        old_ranges = sorted(previous["ranges"])
        old_hash = str(previous["hash"])
        added = sorted(set(ranges) - set(old_ranges))
        removed = sorted(set(old_ranges) - set(ranges))
        changed = old_hash != current_hash

        self.store.upsert_provider_ip_ranges(
            provider=self.provider,
            range_type=self.range_type,
            ranges=ranges,
            source_url=self.meta_url,
            current_hash=current_hash,
            etag=etag,
        )

        if changed:
            self.store.record_provider_ip_range_change(
                provider=self.provider,
                range_type=self.range_type,
                added=added,
                removed=removed,
                previous_hash=old_hash,
                current_hash=current_hash,
            )
            LOG.warning(
                "GitHub webhook IP ranges changed: added=%s removed=%s",
                ", ".join(added) or "-",
                ", ".join(removed) or "-",
            )
        else:
            LOG.info("GitHub webhook IP ranges unchanged (%d ranges)", len(ranges))

        return IPRangeCheckResult(
            provider=self.provider,
            range_type=self.range_type,
            changed=changed,
            initial=False,
            ranges=ranges,
            added=added,
            removed=removed,
            checked_at=checked_at,
        )

    def status(self) -> dict[str, Any]:
        snapshot = self.store.get_provider_ip_ranges(
            provider=self.provider,
            range_type=self.range_type,
        )
        changes = self.store.latest_provider_ip_range_changes(
            provider=self.provider,
            range_type=self.range_type,
            limit=5,
        )
        return {
            "snapshot": snapshot,
            "recent_changes": changes,
        }
