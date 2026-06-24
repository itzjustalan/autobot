from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from autobot.db.sqlite import StateStore
from autobot.event_envelope import EventEnvelope
from autobot.loop_prevention import LoopLimits, LoopState, should_process
from autobot.queue.recovery import recover_after_crash


class RecoveryTests(unittest.TestCase):
    def test_recover_in_progress_jobs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = StateStore(Path(tmp) / "autobot.db")
            envelope = EventEnvelope(
                provider="github",
                delivery_id="d1",
                event_name="pull_request",
                event_action="opened",
                repo_key="owner/repo",
                resource_type="pull_request",
                resource_id="1",
                actor="alice",
                parent_pr_number=1,
            )
            store.upsert_job(
                job_id="job-1",
                resource_key=envelope.resource_key,
                handler_id="handler",
                status="running",
                not_before=0,
                envelope=envelope,
            )
            result = recover_after_crash(store)
            self.assertEqual(result.rescheduled_jobs, 1)


class LoopPreventionTests(unittest.TestCase):
    def test_blocks_autobot_event_by_default(self) -> None:
        decision = should_process(LoopLimits(), LoopState(event_from_autobot=True))
        self.assertFalse(decision.allowed)

    def test_blocks_attempt_over_limit(self) -> None:
        decision = should_process(LoopLimits(max_attempts_per_job=3), LoopState(attempts_for_job=3))
        self.assertFalse(decision.allowed)

    def test_allows_normal_event(self) -> None:
        decision = should_process(LoopLimits(), LoopState())
        self.assertTrue(decision.allowed)


if __name__ == "__main__":
    unittest.main()
