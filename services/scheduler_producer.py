"""Generation-schedule producer per Phase 4 plan 04-02 (ARCH-05 D-2)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


class SchedulerProducer:
    """Enumerates projects and enqueues ``generate_content`` jobs when due."""

    def __init__(self, container: Any, *, dry_run: bool = False):
        self.container = container
        self.project_service = container.project_manager
        self.job_queue = container.job_queue
        self.store = container.store
        self.dry_run = dry_run

    def tick(self, now: Optional[datetime] = None) -> Dict[str, Any]:
        if now is None:
            now = datetime.now(timezone.utc)

        enqueued: List[str] = []
        checked = 0

        for project in self.project_service.list_projects():
            checked += 1
            project_id = getattr(project, "project_id", None)
            if not project_id:
                continue

            record = self.store.get_project_record(project_id)
            if not record:
                continue

            schedule_dict = record.get("generation_schedule") or {}
            last_gen_str = self.store.get_project_value(project_id, "last_generation_at")

            if not self._is_due(schedule_dict, last_gen_str, now, project_id):
                continue

            posts_per_batch = int(schedule_dict.get("posts_per_batch", 5) or 5)
            payload = {
                "project_id": project_id,
                "count": posts_per_batch,
                "platform": None,
                "content_type": None,
                "channel": "SCHEDULER",
            }
            self.job_queue.enqueue("generate_content", project_id=project_id, payload=payload)
            if not self.dry_run:
                self.store.set_project_value(project_id, "last_generation_at", now.isoformat())
            enqueued.append(project_id)

        return {"enqueued": enqueued, "checked": checked, "now": now.isoformat()}

    def _is_due(
        self,
        schedule_dict: Dict[str, Any],
        last_gen_str: Optional[str],
        now: datetime,
        project_id: str,
    ) -> bool:
        queued_generate = self.job_queue.list(project_id=project_id, status="queued", limit=10)
        for job in queued_generate:
            if job.get("kind") == "generate_content":
                return False

        if last_gen_str is None:
            return True

        try:
            last_gen = datetime.fromisoformat(last_gen_str)
        except (TypeError, ValueError):
            return True

        frequency = (schedule_dict.get("frequency") or "daily").lower()
        days_since = (now.date() - last_gen.date()).days

        if frequency == "weekly":
            return days_since >= 7
        if frequency == "biweekly":
            return days_since >= 14
        return days_since >= 1


__all__ = ["SchedulerProducer"]
