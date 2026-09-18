"""Durable SQLite-backed job queue service."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from data.repositories import JobRepository
from services.job_types import validate_payload
from services.observability import get_logger
from services.retry_policy import (
    FailureCategory,
    RetryPolicy,
)


_JOB_ERROR_TRUNCATE = 200
_logger = get_logger(__name__)


class JobQueueService:
    """Thin application service around durable job storage."""

    def __init__(self, store):
        self.store = store
        self.job_repo = JobRepository(store)

    def enqueue(
        self,
        kind: str,
        payload: Optional[Dict[str, Any]] = None,
        project_id: str = None,
        priority: int = 100,
        available_at: str = None,
        max_attempts: int = 3,
    ) -> Dict[str, Any]:
        validated = validate_payload(kind, payload)
        payload = validated.model_dump()
        record = self.job_repo.enqueue(
            kind=kind,
            payload=payload,
            project_id=project_id,
            priority=priority,
            available_at=available_at,
            max_attempts=max_attempts,
        )
        try:
            self.store.record_event(
                category="job",
                action="enqueued",
                job_id=record.get("job_id"),
                project_id=record.get("project_id") or project_id,
                payload={"kind": record.get("kind", kind)},
            )
        except Exception as exc:
            _logger.warning("system_events.job.enqueued failed: %s", exc)
        return record

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.job_repo.get(job_id)

    def list(
        self,
        project_id: str = None,
        status: str = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return self.job_repo.list(project_id=project_id, status=status, limit=limit)

    def claim_next(self, kinds: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        return self.job_repo.claim_next(kinds=kinds)

    def complete(self, job_id: str, result: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        record = self.job_repo.complete(job_id, result=result)
        if record is not None:
            payload: Dict[str, Any] = {"kind": record.get("kind", "")}
            duration_ms = self._duration_ms(record.get("started_at"), record.get("finished_at"))
            if duration_ms is not None:
                payload["duration_ms"] = duration_ms
            try:
                self.store.record_event(
                    category="job",
                    action="completed",
                    job_id=job_id,
                    project_id=record.get("project_id"),
                    payload=payload,
                )
            except Exception as exc:
                _logger.warning("system_events.job.completed failed: %s", exc)
        return record

    def fail(self, job_id: str, error: str, retry: bool = False) -> Optional[Dict[str, Any]]:
        return self.job_repo.fail(job_id, error=error, retry=retry)

    def fail_with_category(
        self,
        job_id: str,
        error: str,
        category: FailureCategory,
    ) -> Optional[Dict[str, Any]]:
        record = self.get(job_id)
        if not record:
            return None
        attempts = int(record.get("attempts", 0))
        decision = RetryPolicy().compute_retry(category, attempts)
        if decision is None:
            failed = self.job_repo.fail(
                job_id,
                error=error,
                retry=False,
                failure_category=category.value,
            )
            event_action = "failed"
        else:
            record["status"] = "queued"
            record["error"] = error
            record["failure_category"] = category.value
            record["available_at"] = decision.next_retry_at
            record["finished_at"] = None
            record["updated_at"] = datetime.now(timezone.utc).isoformat()
            self.job_repo.save(record)
            failed = self.job_repo.get(job_id)
            event_action = "retry_scheduled"
        payload: Dict[str, Any] = {
            "kind": record.get("kind", ""),
            "failure_category": category.value,
            "error": (error or "")[:_JOB_ERROR_TRUNCATE],
        }
        if decision is not None:
            payload["next_retry_at"] = decision.next_retry_at
        try:
            self.store.record_event(
                category="job",
                action=event_action,
                job_id=job_id,
                project_id=record.get("project_id"),
                payload=payload,
            )
        except Exception as exc:
            _logger.warning("system_events.job.%s failed: %s", event_action, exc)
        return failed

    def recover_stuck(self, threshold_minutes: int = 30) -> List[Dict[str, Any]]:
        recovered = self.job_repo.recover_stuck(threshold_minutes=threshold_minutes)
        for record in recovered:
            try:
                self.store.record_event(
                    category="job",
                    action="recovered_stuck",
                    job_id=record.get("job_id"),
                    project_id=record.get("project_id"),
                    payload={
                        "kind": record.get("kind", ""),
                        "previous_status": "running",
                        "threshold_minutes": threshold_minutes,
                    },
                )
            except Exception as exc:
                _logger.warning("system_events.job.recovered_stuck failed: %s", exc)
        return recovered

    def cancel(self, job_id: str) -> Optional[Dict[str, Any]]:
        existing = self.get(job_id)
        previous_status = existing.get("status") if existing else None
        cancelled = self.job_repo.cancel(job_id)
        if cancelled is not None:
            try:
                self.store.record_event(
                    category="job",
                    action="cancelled",
                    job_id=job_id,
                    project_id=(existing or {}).get("project_id"),
                    payload={
                        "kind": (existing or {}).get("kind", ""),
                        "previous_status": previous_status,
                    },
                )
            except Exception as exc:
                _logger.warning("system_events.job.cancelled failed: %s", exc)
        return cancelled

    def stats(self) -> Dict[str, int]:
        return self.job_repo.stats()

    @staticmethod
    def _duration_ms(started_at: Optional[str], finished_at: Optional[str]) -> Optional[int]:
        if not started_at or not finished_at:
            return None
        try:
            start = datetime.fromisoformat(started_at)
            end = datetime.fromisoformat(finished_at)
            delta = (end - start).total_seconds()
            return int(delta * 1000) if delta >= 0 else None
        except (TypeError, ValueError):
            return None

