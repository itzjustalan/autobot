"""SQLite state and audit storage."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import json
import sqlite3
from typing import Any, Iterator

from autobot.event_envelope import EventEnvelope


SCHEMA = """
PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS deliveries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  delivery_id TEXT NOT NULL,
  event_name TEXT NOT NULL,
  event_action TEXT,
  signature_status TEXT NOT NULL,
  payload_path TEXT NOT NULL,
  received_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  dedupe_status TEXT NOT NULL DEFAULT 'new',
  UNIQUE(provider, delivery_id)
);

CREATE TABLE IF NOT EXISTS events (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  delivery_id TEXT NOT NULL,
  resource_key TEXT NOT NULL,
  envelope_json TEXT NOT NULL,
  routing_status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider, delivery_id)
);

CREATE TABLE IF NOT EXISTS jobs (
  id TEXT PRIMARY KEY,
  resource_key TEXT NOT NULL,
  handler_id TEXT NOT NULL,
  status TEXT NOT NULL,
  not_before REAL,
  attempts INTEGER NOT NULL DEFAULT 0,
  latest_delivery_id TEXT,
  latest_event_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT NOT NULL,
  status TEXT NOT NULL,
  ai_provider TEXT,
  ai_model TEXT,
  prompt_hash TEXT,
  token_estimate INTEGER,
  cost_estimate REAL,
  result_summary TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS child_prs (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  repo_key TEXT NOT NULL,
  parent_pr_number INTEGER NOT NULL,
  parent_head_branch TEXT NOT NULL,
  child_branch TEXT NOT NULL,
  child_pr_number INTEGER,
  child_pr_url TEXT,
  state TEXT NOT NULL DEFAULT 'open',
  cleanup_status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider, repo_key, parent_pr_number)
);

CREATE TABLE IF NOT EXISTS pull_requests (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  repo_key TEXT NOT NULL,
  pr_number INTEGER NOT NULL,
  author TEXT,
  head_branch TEXT,
  base_branch TEXT,
  latest_sha TEXT,
  state TEXT,
  metadata_json TEXT,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  UNIQUE(provider, repo_key, pr_number)
);

CREATE TABLE IF NOT EXISTS pr_stats (
  provider TEXT NOT NULL,
  repo_key TEXT NOT NULL,
  pr_number INTEGER NOT NULL,
  events_received INTEGER NOT NULL DEFAULT 0,
  jobs_created INTEGER NOT NULL DEFAULT 0,
  child_pr_count INTEGER NOT NULL DEFAULT 0,
  gate_failures INTEGER NOT NULL DEFAULT 0,
  attempts INTEGER NOT NULL DEFAULT 0,
  token_estimate INTEGER NOT NULL DEFAULT 0,
  cost_estimate REAL NOT NULL DEFAULT 0,
  updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(provider, repo_key, pr_number)
);

CREATE TABLE IF NOT EXISTS artifacts (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  kind TEXT NOT NULL,
  path TEXT NOT NULL,
  metadata_json TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS provider_ip_ranges (
  provider TEXT NOT NULL,
  range_type TEXT NOT NULL,
  ranges_json TEXT NOT NULL,
  source_url TEXT NOT NULL,
  etag TEXT,
  hash TEXT NOT NULL,
  checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY(provider, range_type)
);

CREATE TABLE IF NOT EXISTS provider_ip_range_changes (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  range_type TEXT NOT NULL,
  added_json TEXT NOT NULL,
  removed_json TEXT NOT NULL,
  previous_hash TEXT,
  current_hash TEXT NOT NULL,
  detected_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
  acknowledged_at TEXT
);

CREATE TABLE IF NOT EXISTS ai_session_candidates (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  provider TEXT NOT NULL,
  repo_key TEXT NOT NULL,
  branch TEXT,
  commit_sha TEXT,
  session_id TEXT NOT NULL,
  source TEXT NOT NULL,
  confidence INTEGER NOT NULL,
  matched_pattern TEXT,
  discovered_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ai_session_uses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  job_id TEXT,
  provider TEXT NOT NULL,
  session_id TEXT NOT NULL,
  connect_attempted INTEGER NOT NULL DEFAULT 0,
  connect_succeeded INTEGER NOT NULL DEFAULT 0,
  fallback_used INTEGER NOT NULL DEFAULT 0,
  result_summary TEXT,
  created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
"""


class StateStore:
    """SQLite-backed audit and state store."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.migrate()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        try:
            yield con
            con.commit()
        finally:
            con.close()

    def migrate(self) -> None:
        with sqlite3.connect(self.path) as con:
            con.executescript(SCHEMA)

    def record_delivery(
        self,
        *,
        provider: str,
        delivery_id: str,
        event_name: str,
        event_action: str | None,
        signature_status: str,
        payload_path: Path,
    ) -> bool:
        """Record a delivery. Returns False if it is a duplicate."""

        try:
            with self.connect() as con:
                con.execute(
                    """
                    INSERT INTO deliveries (
                      provider, delivery_id, event_name, event_action,
                      signature_status, payload_path
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        provider,
                        delivery_id,
                        event_name,
                        event_action,
                        signature_status,
                        str(payload_path),
                    ),
                )
            return True
        except sqlite3.IntegrityError:
            with self.connect() as con:
                con.execute(
                    """
                    UPDATE deliveries
                    SET dedupe_status = 'duplicate'
                    WHERE provider = ? AND delivery_id = ?
                    """,
                    (provider, delivery_id),
                )
            return False

    def record_event(self, envelope: EventEnvelope) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT OR REPLACE INTO events (
                  provider, delivery_id, resource_key, envelope_json, routing_status
                ) VALUES (?, ?, ?, ?, 'queued')
                """,
                (
                    envelope.provider,
                    envelope.delivery_id,
                    envelope.resource_key,
                    json.dumps(envelope.to_dict(), sort_keys=True),
                ),
            )
            if envelope.parent_pr_number and envelope.repo_key:
                con.execute(
                    """
                    INSERT INTO pr_stats (
                      provider, repo_key, pr_number, events_received
                    ) VALUES (?, ?, ?, 1)
                    ON CONFLICT(provider, repo_key, pr_number)
                    DO UPDATE SET
                      events_received = events_received + 1,
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    (envelope.provider, envelope.repo_key, envelope.parent_pr_number),
                )

    def upsert_job(
        self,
        *,
        job_id: str,
        resource_key: str,
        handler_id: str,
        status: str,
        not_before: float,
        envelope: EventEnvelope,
    ) -> None:
        with self.connect() as con:
            job_exists = (
                con.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone()
                is not None
            )
            con.execute(
                """
                INSERT INTO jobs (
                  id, resource_key, handler_id, status, not_before,
                  latest_delivery_id, latest_event_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id)
                DO UPDATE SET
                  status = excluded.status,
                  not_before = excluded.not_before,
                  latest_delivery_id = excluded.latest_delivery_id,
                  latest_event_json = excluded.latest_event_json,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (
                    job_id,
                    resource_key,
                    handler_id,
                    status,
                    not_before,
                    envelope.delivery_id,
                    json.dumps(envelope.to_dict(), sort_keys=True),
                ),
            )
            if envelope.parent_pr_number and envelope.repo_key:
                increment = 0 if job_exists else 1
                con.execute(
                    """
                    INSERT INTO pr_stats (
                      provider, repo_key, pr_number, jobs_created
                    ) VALUES (?, ?, ?, ?)
                    ON CONFLICT(provider, repo_key, pr_number)
                    DO UPDATE SET
                      jobs_created = jobs_created + excluded.jobs_created,
                      updated_at = CURRENT_TIMESTAMP
                    """,
                    (
                        envelope.provider,
                        envelope.repo_key,
                        envelope.parent_pr_number,
                        increment,
                    ),
                )

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT id, resource_key, handler_id, status, not_before, attempts,
                       latest_delivery_id, latest_event_json, created_at, updated_at
                FROM jobs
                WHERE id = ?
                """,
                (job_id,),
            ).fetchone()
            return dict(row) if row else None

    def mark_job_status(self, job_id: str, status: str) -> None:
        with self.connect() as con:
            con.execute(
                """
                UPDATE jobs
                SET status = ?, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (status, job_id),
            )

    def increment_job_attempts(self, job_id: str) -> int:
        with self.connect() as con:
            con.execute(
                """
                UPDATE jobs
                SET attempts = attempts + 1, updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (job_id,),
            )
            row = con.execute("SELECT attempts FROM jobs WHERE id = ?", (job_id,)).fetchone()
            return int(row["attempts"]) if row else 0

    def record_run(
        self,
        *,
        job_id: str,
        status: str,
        result_summary: str,
        ai_provider: str | None = None,
        ai_model: str | None = None,
        token_estimate: int | None = None,
        cost_estimate: float | None = None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO runs (
                  job_id, status, ai_provider, ai_model, token_estimate,
                  cost_estimate, result_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    status,
                    ai_provider,
                    ai_model,
                    token_estimate,
                    cost_estimate,
                    result_summary,
                ),
            )
            con.execute(
                """
                UPDATE pr_stats
                SET attempts = attempts + 1,
                    token_estimate = token_estimate + COALESCE(?, 0),
                    cost_estimate = cost_estimate + COALESCE(?, 0),
                    updated_at = CURRENT_TIMESTAMP
                WHERE (provider, repo_key, pr_number) IN (
                  SELECT json_extract(latest_event_json, '$.provider'),
                         json_extract(latest_event_json, '$.repo_key'),
                         json_extract(latest_event_json, '$.parent_pr_number')
                  FROM jobs
                  WHERE id = ?
                )
                """,
                (token_estimate or 0, cost_estimate or 0, job_id),
            )

    def get_child_pr(
        self,
        *,
        provider: str,
        repo_key: str,
        parent_pr_number: int,
    ) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT provider, repo_key, parent_pr_number, parent_head_branch,
                       child_branch, child_pr_number, child_pr_url, state,
                       cleanup_status, created_at, updated_at
                FROM child_prs
                WHERE provider = ? AND repo_key = ? AND parent_pr_number = ?
                """,
                (provider, repo_key, parent_pr_number),
            ).fetchone()
            return dict(row) if row else None

    def get_child_pr_by_child_number(
        self,
        *,
        provider: str,
        repo_key: str,
        child_pr_number: int,
    ) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT provider, repo_key, parent_pr_number, parent_head_branch,
                       child_branch, child_pr_number, child_pr_url, state,
                       cleanup_status, created_at, updated_at
                FROM child_prs
                WHERE provider = ? AND repo_key = ? AND child_pr_number = ?
                """,
                (provider, repo_key, child_pr_number),
            ).fetchone()
            return dict(row) if row else None

    def upsert_child_pr(
        self,
        *,
        provider: str,
        repo_key: str,
        parent_pr_number: int,
        parent_head_branch: str,
        child_branch: str,
        child_pr_number: int | None = None,
        child_pr_url: str | None = None,
        state: str = "open",
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO child_prs (
                  provider, repo_key, parent_pr_number, parent_head_branch,
                  child_branch, child_pr_number, child_pr_url, state
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, repo_key, parent_pr_number)
                DO UPDATE SET
                  parent_head_branch = excluded.parent_head_branch,
                  child_branch = excluded.child_branch,
                  child_pr_number = COALESCE(excluded.child_pr_number, child_prs.child_pr_number),
                  child_pr_url = COALESCE(excluded.child_pr_url, child_prs.child_pr_url),
                  state = excluded.state,
                  updated_at = CURRENT_TIMESTAMP
                """,
                (
                    provider,
                    repo_key,
                    parent_pr_number,
                    parent_head_branch,
                    child_branch,
                    child_pr_number,
                    child_pr_url,
                    state,
                ),
            )
            con.execute(
                """
                INSERT INTO pr_stats (
                  provider, repo_key, pr_number, child_pr_count
                ) VALUES (?, ?, ?, 1)
                ON CONFLICT(provider, repo_key, pr_number)
                DO UPDATE SET
                  child_pr_count = MAX(child_pr_count, 1),
                  updated_at = CURRENT_TIMESTAMP
                """,
                (provider, repo_key, parent_pr_number),
            )

    def mark_child_pr_cleanup(
        self,
        *,
        provider: str,
        repo_key: str,
        parent_pr_number: int,
        cleanup_status: str,
        state: str | None = None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                UPDATE child_prs
                SET cleanup_status = ?,
                    state = COALESCE(?, state),
                    updated_at = CURRENT_TIMESTAMP
                WHERE provider = ? AND repo_key = ? AND parent_pr_number = ?
                """,
                (cleanup_status, state, provider, repo_key, parent_pr_number),
            )

    def mark_child_pr_cleanup_by_child_number(
        self,
        *,
        provider: str,
        repo_key: str,
        child_pr_number: int,
        cleanup_status: str,
        state: str | None = None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                UPDATE child_prs
                SET cleanup_status = ?,
                    state = COALESCE(?, state),
                    updated_at = CURRENT_TIMESTAMP
                WHERE provider = ? AND repo_key = ? AND child_pr_number = ?
                """,
                (cleanup_status, state, provider, repo_key, child_pr_number),
            )

    def recover_in_progress_jobs(self) -> int:
        with self.connect() as con:
            cur = con.execute(
                """
                UPDATE jobs
                SET status = 'scheduled', updated_at = CURRENT_TIMESTAMP
                WHERE status IN ('running', 'locked')
                """
            )
            return int(cur.rowcount)

    def stats_summary(self) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT provider, repo_key, pr_number, events_received, jobs_created,
                       child_pr_count, gate_failures, attempts, token_estimate,
                       cost_estimate, updated_at
                FROM pr_stats
                ORDER BY updated_at DESC
                LIMIT 100
                """
            ).fetchall()
            return [dict(row) for row in rows]

    def list_deliveries(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT id, provider, delivery_id, event_name, event_action,
                       signature_status, payload_path, received_at, dedupe_status
                FROM deliveries
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT id, provider, delivery_id, resource_key, envelope_json,
                       routing_status, created_at
                FROM events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["envelope"] = json.loads(str(item.pop("envelope_json")))
                result.append(item)
            return result

    def list_jobs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT id, resource_key, handler_id, status, not_before, attempts,
                       latest_delivery_id, latest_event_json, created_at, updated_at
                FROM jobs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                latest = item.pop("latest_event_json")
                item["latest_event"] = json.loads(str(latest)) if latest else None
                result.append(item)
            return result

    def list_runs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT id, job_id, status, ai_provider, ai_model, prompt_hash,
                       token_estimate, cost_estimate, result_summary, created_at
                FROM runs
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_child_prs(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT id, provider, repo_key, parent_pr_number, parent_head_branch,
                       child_branch, child_pr_number, child_pr_url, state,
                       cleanup_status, created_at, updated_at
                FROM child_prs
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            return [dict(row) for row in rows]

    def list_pull_requests(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT id, provider, repo_key, pr_number, author, head_branch,
                       base_branch, latest_sha, state, metadata_json, updated_at
                FROM pull_requests
                ORDER BY updated_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                metadata = item.pop("metadata_json")
                item["metadata"] = json.loads(str(metadata)) if metadata else None
                result.append(item)
            return result

    def list_artifacts(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT id, job_id, kind, path, metadata_json, created_at
                FROM artifacts
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                metadata = item.pop("metadata_json")
                item["metadata"] = json.loads(str(metadata)) if metadata else None
                result.append(item)
            return result

    def get_provider_ip_ranges(
        self,
        *,
        provider: str,
        range_type: str,
    ) -> dict[str, Any] | None:
        with self.connect() as con:
            row = con.execute(
                """
                SELECT provider, range_type, ranges_json, source_url, etag, hash, checked_at
                FROM provider_ip_ranges
                WHERE provider = ? AND range_type = ?
                """,
                (provider, range_type),
            ).fetchone()
            if not row:
                return None
            result = dict(row)
            result["ranges"] = json.loads(str(result.pop("ranges_json")))
            return result

    def upsert_provider_ip_ranges(
        self,
        *,
        provider: str,
        range_type: str,
        ranges: list[str],
        source_url: str,
        current_hash: str,
        etag: str | None = None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO provider_ip_ranges (
                  provider, range_type, ranges_json, source_url, etag, hash
                ) VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, range_type)
                DO UPDATE SET
                  ranges_json = excluded.ranges_json,
                  source_url = excluded.source_url,
                  etag = excluded.etag,
                  hash = excluded.hash,
                  checked_at = CURRENT_TIMESTAMP
                """,
                (
                    provider,
                    range_type,
                    json.dumps(ranges, sort_keys=True),
                    source_url,
                    etag,
                    current_hash,
                ),
            )

    def record_provider_ip_range_change(
        self,
        *,
        provider: str,
        range_type: str,
        added: list[str],
        removed: list[str],
        previous_hash: str | None,
        current_hash: str,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO provider_ip_range_changes (
                  provider, range_type, added_json, removed_json,
                  previous_hash, current_hash
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    provider,
                    range_type,
                    json.dumps(added, sort_keys=True),
                    json.dumps(removed, sort_keys=True),
                    previous_hash,
                    current_hash,
                ),
            )

    def latest_provider_ip_range_changes(
        self,
        *,
        provider: str = "github",
        range_type: str = "hooks",
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        with self.connect() as con:
            rows = con.execute(
                """
                SELECT id, provider, range_type, added_json, removed_json,
                       previous_hash, current_hash, detected_at, acknowledged_at
                FROM provider_ip_range_changes
                WHERE provider = ? AND range_type = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (provider, range_type, limit),
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["added"] = json.loads(str(item.pop("added_json")))
                item["removed"] = json.loads(str(item.pop("removed_json")))
                result.append(item)
            return result

    def record_ai_session_candidate(
        self,
        *,
        provider: str,
        repo_key: str,
        branch: str | None,
        commit_sha: str | None,
        session_id: str,
        source: str,
        confidence: int,
        matched_pattern: str | None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO ai_session_candidates (
                  provider, repo_key, branch, commit_sha, session_id,
                  source, confidence, matched_pattern
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    provider,
                    repo_key,
                    branch,
                    commit_sha,
                    session_id,
                    source,
                    confidence,
                    matched_pattern,
                ),
            )

    def record_ai_session_use(
        self,
        *,
        provider: str,
        session_id: str,
        job_id: str | None = None,
        connect_attempted: bool = False,
        connect_succeeded: bool = False,
        fallback_used: bool = False,
        result_summary: str | None = None,
    ) -> None:
        with self.connect() as con:
            con.execute(
                """
                INSERT INTO ai_session_uses (
                  job_id, provider, session_id, connect_attempted,
                  connect_succeeded, fallback_used, result_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    provider,
                    session_id,
                    int(connect_attempted),
                    int(connect_succeeded),
                    int(fallback_used),
                    result_summary,
                ),
            )

    def latest_ai_session_candidates(
        self,
        *,
        provider: str | None = None,
        repo_key: str | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        query = """
            SELECT provider, repo_key, branch, commit_sha, session_id, source,
                   confidence, matched_pattern, discovered_at
            FROM ai_session_candidates
            WHERE (? IS NULL OR provider = ?)
              AND (? IS NULL OR repo_key = ?)
            ORDER BY id DESC
            LIMIT ?
        """
        with self.connect() as con:
            rows = con.execute(
                query,
                (provider, provider, repo_key, repo_key, limit),
            ).fetchall()
            return [dict(row) for row in rows]
