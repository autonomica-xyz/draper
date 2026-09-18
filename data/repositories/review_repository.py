from typing import Dict, List, Optional

from data.repositories.base import BaseRepository


class ReviewRepository(BaseRepository):
    def get(self, review_id: str) -> Optional[Dict]:
        return self.store.get_review_record(review_id)

    def list(
        self,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict]:
        return self.store.list_review_records(
            status=status, project_id=project_id, limit=limit
        )

    def save(self, record: Dict, replace: bool = True) -> None:
        return self.store.save_review_record(record, replace=replace)
