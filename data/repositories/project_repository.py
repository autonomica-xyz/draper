from typing import Any, Dict, List, Optional

from data.repositories.base import BaseRepository


class ProjectRepository(BaseRepository):
    def get(self, project_id: str) -> Optional[Dict[str, Any]]:
        return self.store.get_project_record(project_id)

    def get_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        return self.store.get_project_record_by_slug(slug)

    def get_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        return self.store.get_project_record_by_name(name)

    def list(self) -> List[Dict[str, Any]]:
        return self.store.list_project_records()

    def save(self, record: Dict[str, Any], replace: bool = True) -> None:
        return self.store.save_project_record(record, replace=replace)

    def get_value(self, project_id: str, key: str, default: Any = None) -> Any:
        return self.store.get_project_value(project_id, key, default)

    def set_value(self, project_id: str, key: str, value: Any) -> None:
        return self.store.set_project_value(project_id, key, value)

    def normalize(self, project_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
        return self.store._normalize_project_record(project_id, record)
