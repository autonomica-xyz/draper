from typing import Any, Dict, List

from data.repositories.base import BaseRepository


class AnalyticsRepository(BaseRepository):
    def save_snapshot(self, source_path: str, data: Any) -> None:
        return self.store.save_analytics_snapshot(source_path, data)

    def get_snapshot(self, source_path: str, default: Any = None) -> Any:
        return self.store.get_analytics_snapshot(source_path, default)

    def list_snapshots(self) -> List[Dict[str, Any]]:
        return self.store.list_analytics_snapshots()
