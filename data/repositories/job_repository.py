from typing import Any, Dict, List, Optional

from data.repositories.base import BaseRepository


class JobRepository(BaseRepository):
    def enqueue(
        self,
        kind: str,
        payload: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
        priority: int = 100,
        available_at: Optional[str] = None,
        max_attempts: int = 3,
    ) -> Dict[str, Any]:
        return self.store.enqueue_job(
            kind=kind,
            payload=payload,
            project_id=project_id,
            priority=priority,
            available_at=available_at,
            max_attempts=max_attempts,
        )

    def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get_job_record(job_id)

    def list(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        return self.store.list_job_records(
            project_id=project_id, status=status, limit=limit
        )

    def claim_next(self, kinds: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        return self.store.claim_next_job(kinds=kinds)

    def complete(
        self, job_id: str, result: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        return self.store.complete_job(job_id, result=result)

    def fail(
        self,
        job_id: str,
        error: str,
        retry: bool = False,
        available_at: Optional[str] = None,
        failure_category: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        return self.store.fail_job(
            job_id,
            error=error,
            retry=retry,
            available_at=available_at,
            failure_category=failure_category,
        )

    def save(self, record: Dict[str, Any], replace: bool = True) -> None:
        return self.store.save_job_record(record, replace=replace)

    def cancel(self, job_id: str) -> Optional[Dict[str, Any]]:
        return self.store.cancel_job(job_id)

    def stats(self) -> Dict[str, int]:
        return self.store.get_job_stats()

    def recover_stuck(self, threshold_minutes: int = 30) -> List[Dict[str, Any]]:
        return self.store.recover_stuck_jobs(threshold_minutes=threshold_minutes)
