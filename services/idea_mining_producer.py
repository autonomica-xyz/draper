"""Idea Lab mining producer — enqueue mine_ideas jobs for enabled projects."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


DEFAULT_IDEA_MINING = {
    "enabled": False,
    "frequency": "weekdays",
    "max_ideas": 5,
    "hour_utc": 6,
}


def _clamp_max_ideas(value: Any) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = 5
    return max(1, min(n, 20))


def resolve_idea_mining_config(record: Dict[str, Any]) -> Dict[str, Any]:
    """Merge idea_mining settings from project config/settings with defaults."""
    cfg: Dict[str, Any] = dict(DEFAULT_IDEA_MINING)
    for blob in (record.get("config"), record.get("settings")):
        if not isinstance(blob, dict):
            continue
        raw = blob.get("idea_mining")
        if isinstance(raw, dict):
            cfg.update({k: v for k, v in raw.items() if v is not None})
    cfg["enabled"] = bool(cfg.get("enabled"))
    freq = str(cfg.get("frequency") or "weekdays").lower()
    if freq not in {"daily", "weekdays", "weekly"}:
        freq = "weekdays"
    cfg["frequency"] = freq
    cfg["max_ideas"] = _clamp_max_ideas(cfg.get("max_ideas", 5))
    try:
        cfg["hour_utc"] = int(cfg.get("hour_utc", 6))
    except (TypeError, ValueError):
        cfg["hour_utc"] = 6
    return cfg


class IdeaMiningProducer:
    """Enumerate projects and enqueue ``mine_ideas`` when due."""

    def __init__(self, container: Any, *, dry_run: bool = False):
        self.container = container
        self.project_manager = container.project_manager
        self.job_queue = container.job_queue
        self.store = container.store
        self.dry_run = dry_run

    def tick(
        self,
        now: Optional[datetime] = None,
        *,
        force_project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if now is None:
            now = datetime.now(timezone.utc)
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        enqueued: List[str] = []
        skipped: List[Dict[str, str]] = []
        checked = 0

        projects = list(self.project_manager.list_projects())
        for project in projects:
            checked += 1
            project_id = getattr(project, "project_id", None) or getattr(project, "id", None)
            if not project_id:
                continue

            record = self.store.get_project_record(project_id) or {}
            cfg = resolve_idea_mining_config(record)
            forced = force_project_id is not None and project_id == force_project_id
            if force_project_id and not forced:
                skipped.append({"project_id": project_id, "reason": "not_forced_target"})
                continue
            if not cfg["enabled"] and not forced:
                skipped.append({"project_id": project_id, "reason": "disabled"})
                continue

            if not forced and not self._is_due(cfg, project_id, now):
                skipped.append({"project_id": project_id, "reason": "not_due"})
                continue

            if self._has_queued_mine_job(project_id):
                skipped.append({"project_id": project_id, "reason": "already_queued"})
                continue

            payload = {
                "project_id": project_id,
                "max_ideas": cfg["max_ideas"],
            }
            self.job_queue.enqueue(
                "mine_ideas",
                project_id=project_id,
                payload=payload,
            )
            if not self.dry_run:
                self.store.set_project_value(
                    project_id, "last_idea_mining_at", now.isoformat()
                )
            enqueued.append(project_id)

        return {
            "enqueued": enqueued,
            "checked": checked,
            "skipped": skipped,
            "now": now.isoformat(),
        }

    def _has_queued_mine_job(self, project_id: str) -> bool:
        for job in self.job_queue.list(project_id=project_id, status="queued", limit=20):
            if job.get("kind") == "mine_ideas":
                return True
        return False

    def _is_due(self, cfg: Dict[str, Any], project_id: str, now: datetime) -> bool:
        frequency = cfg["frequency"]
        # Monday=0 .. Sunday=6
        if frequency == "weekdays" and now.weekday() >= 5:
            return False

        last_raw = self.store.get_project_value(project_id, "last_idea_mining_at")
        if last_raw is None:
            return True
        try:
            last = datetime.fromisoformat(str(last_raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return True
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        days_since = (now.date() - last.astimezone(timezone.utc).date()).days
        if frequency == "weekly":
            return days_since >= 7
        return days_since >= 1


__all__ = ["IdeaMiningProducer", "resolve_idea_mining_config", "DEFAULT_IDEA_MINING"]
