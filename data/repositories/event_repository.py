from typing import Any, Dict, List, Optional

from data.repositories.base import BaseRepository


class EventRepository(BaseRepository):
    def record_event(
        self,
        category: str,
        action: str,
        *,
        project_id: Optional[str] = None,
        review_id: Optional[str] = None,
        job_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.store.record_event(
            category,
            action,
            project_id=project_id,
            review_id=review_id,
            job_id=job_id,
            payload=payload,
        )

    def list(
        self,
        *,
        category: Optional[str] = None,
        since: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        return self.store.list_events(
            category=category,
            since=since,
            project_id=project_id,
            limit=limit,
            offset=offset,
        )
