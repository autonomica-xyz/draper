from typing import Dict, List, Optional

from data.repositories.base import BaseRepository


class ScheduledPostRepository(BaseRepository):
    def get(self, post_id: str) -> Optional[Dict]:
        return self.store.get_scheduled_record(post_id)

    def list(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict]:
        return self.store.list_scheduled_records(project_id=project_id, status=status)

    def save(self, record: Dict, replace: bool = True) -> None:
        return self.store.save_scheduled_record(record, replace=replace)

    def normalize(self, record: Dict) -> Dict:
        return self.store.normalize_scheduled_record(record)
