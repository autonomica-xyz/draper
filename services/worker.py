"""Long-running worker that drains ``JobQueueService`` via ``JobRunner``.

Per CONTEXT.md locked decision D-1 (Worker Process), the worker is a
separate process (``draper-worker`` systemd unit) that imports services
from the same ``AppContainer`` the dashboard uses. It does NOT
reimplement claim/execute/complete logic; it drives the existing
``JobRunner.run_once`` in a polling loop.
"""

from __future__ import annotations

import signal
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional

from services.observability import get_logger


@dataclass(frozen=True)
class IdleCycles:
    """Stop trigger for ``Worker.run_forever`` based on idle cycle count."""

    idle_limit: int


class Worker:
    """Polls ``JobQueueService`` via ``JobRunner`` until stopped."""

    def __init__(
        self,
        container: Any,
        *,
        poll_interval: float = 2.0,
        logger: Optional[Any] = None,
    ) -> None:
        self.container = container
        self.job_runner = container.job_runner
        self.job_queue = container.job_queue
        self.poll_interval = poll_interval
        self.logger = logger or get_logger(__name__)

        self.jobs_processed = 0
        self.jobs_failed = 0
        self.idle_cycles = 0
        self._stop = False
        self._started_at: Optional[float] = None

    def run_once(self, kinds: Optional[list] = None) -> Optional[Dict[str, Any]]:
        result = self.job_runner.run_once(kinds=kinds)
        if result is None:
            self.idle_cycles += 1
            return None
        self.idle_cycles = 0
        if result.get("success"):
            self.jobs_processed += 1
        else:
            self.jobs_failed += 1
        return result

    def run_forever(
        self,
        kinds: Optional[list] = None,
        stop_after: Optional[IdleCycles] = None,
    ) -> None:
        self._started_at = time.monotonic()
        self._stop = False

        previous_sigterm = signal.getsignal(signal.SIGTERM)
        previous_sigint = signal.getsignal(signal.SIGINT)

        def _request_stop(signum, frame):
            self._stop = True
            self.logger.info("worker.shutdown.requested")

        signal.signal(signal.SIGTERM, _request_stop)
        signal.signal(signal.SIGINT, _request_stop)

        try:
            while not self._stop:
                try:
                    result = self.run_once(kinds=kinds)
                except Exception as exc:
                    self.logger.exception(
                        "worker.run_once.error", extra={"error": str(exc)}
                    )
                    time.sleep(self.poll_interval)
                    continue
                if result is None:
                    if self._stop:
                        break
                    time.sleep(self.poll_interval)
                    if stop_after is not None and self.idle_cycles >= stop_after.idle_limit:
                        break
        except KeyboardInterrupt:
            self.logger.info("worker.shutdown.keyboard_interrupt")
            raise
        finally:
            signal.signal(signal.SIGTERM, previous_sigterm)
            signal.signal(signal.SIGINT, previous_sigint)
            self.logger.info("worker.shutdown.complete", extra=self.stats())

    def stats(self) -> Dict[str, Any]:
        return {
            "jobs_processed": self.jobs_processed,
            "jobs_failed": self.jobs_failed,
            "idle_cycles": self.idle_cycles,
            "uptime_seconds": (
                time.monotonic() - self._started_at if self._started_at else 0.0
            ),
        }


__all__ = ["Worker", "IdleCycles"]
