"""IdeaMiningProducer due/idempotency contracts (no package side-imports)."""

from __future__ import annotations

import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

_ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "idea_mining_producer",
    _ROOT / "services" / "idea_mining_producer.py",
)
_MOD = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
_SPEC.loader.exec_module(_MOD)
IdeaMiningProducer = _MOD.IdeaMiningProducer
resolve_idea_mining_config = _MOD.resolve_idea_mining_config


def _project(pid="proj-1"):
    return SimpleNamespace(project_id=pid)


def _container(record, queued=None, last=None):
    store = MagicMock()
    store.get_project_record.return_value = record
    store.get_project_value.return_value = last
    job_queue = MagicMock()
    job_queue.list.return_value = queued or []
    pm = MagicMock()
    pm.list_projects.return_value = [_project(record.get("project_id", "proj-1"))]
    return SimpleNamespace(project_manager=pm, job_queue=job_queue, store=store)


class TestResolveConfig:
    def test_defaults_disabled(self):
        cfg = resolve_idea_mining_config({})
        assert cfg["enabled"] is False
        assert cfg["frequency"] == "weekdays"
        assert cfg["max_ideas"] == 5

    def test_clamps_max_ideas(self):
        cfg = resolve_idea_mining_config({"config": {"idea_mining": {"max_ideas": 99}}})
        assert cfg["max_ideas"] == 20
        cfg = resolve_idea_mining_config({"config": {"idea_mining": {"max_ideas": 0}}})
        assert cfg["max_ideas"] == 1


class TestIdeaMiningProducerTick:
    def test_skips_disabled(self):
        c = _container({"project_id": "proj-1", "config": {}})
        result = IdeaMiningProducer(c).tick(now=datetime(2026, 9, 15, 6, 0, tzinfo=timezone.utc))
        assert result["enqueued"] == []
        assert result["skipped"][0]["reason"] == "disabled"
        c.job_queue.enqueue.assert_not_called()

    def test_skips_weekend_for_weekdays_freq(self):
        c = _container(
            {
                "project_id": "proj-1",
                "config": {"idea_mining": {"enabled": True, "frequency": "weekdays"}},
            }
        )
        result = IdeaMiningProducer(c).tick(now=datetime(2026, 9, 19, 6, 0, tzinfo=timezone.utc))
        assert result["enqueued"] == []
        assert result["skipped"][0]["reason"] == "not_due"
        c.job_queue.enqueue.assert_not_called()

    def test_enqueues_when_due(self):
        c = _container(
            {
                "project_id": "proj-1",
                "config": {
                    "idea_mining": {"enabled": True, "frequency": "weekdays", "max_ideas": 7}
                },
            }
        )
        now = datetime(2026, 9, 15, 6, 0, tzinfo=timezone.utc)
        result = IdeaMiningProducer(c).tick(now=now)
        assert result["enqueued"] == ["proj-1"]
        c.job_queue.enqueue.assert_called_once_with(
            "mine_ideas",
            project_id="proj-1",
            payload={"project_id": "proj-1", "max_ideas": 7},
        )
        c.store.set_project_value.assert_called_once_with(
            "proj-1", "last_idea_mining_at", now.isoformat()
        )

    def test_skips_when_already_queued(self):
        c = _container(
            {
                "project_id": "proj-1",
                "config": {"idea_mining": {"enabled": True}},
            },
            queued=[{"kind": "mine_ideas", "job_id": "j1"}],
        )
        result = IdeaMiningProducer(c).tick(now=datetime(2026, 9, 15, 6, 0, tzinfo=timezone.utc))
        assert result["skipped"][0]["reason"] == "already_queued"
        c.job_queue.enqueue.assert_not_called()

    def test_force_bypasses_disabled(self):
        c = _container({"project_id": "proj-1", "config": {}})
        result = IdeaMiningProducer(c).tick(
            now=datetime(2026, 9, 19, 6, 0, tzinfo=timezone.utc),
            force_project_id="proj-1",
        )
        assert result["enqueued"] == ["proj-1"]

    def test_dry_run_does_not_write_kv(self):
        c = _container(
            {
                "project_id": "proj-1",
                "config": {"idea_mining": {"enabled": True}},
            }
        )
        IdeaMiningProducer(c, dry_run=True).tick(
            now=datetime(2026, 9, 15, 6, 0, tzinfo=timezone.utc)
        )
        c.job_queue.enqueue.assert_called_once()
        c.store.set_project_value.assert_not_called()
