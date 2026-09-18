#!/usr/bin/env python3
"""SQLite-backed state store for project, review, and scheduling data."""

import hashlib
import json
import os
import secrets
import sqlite3
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def slugify(value: str) -> str:
    slug = "".join(ch.lower() if ch.isalnum() else "-" for ch in value.strip())
    parts = [part for part in slug.split("-") if part]
    return "-".join(parts) or "project"


def new_id(prefix: str = "") -> str:
    value = uuid.uuid4().hex
    return f"{prefix}{value}" if prefix else value


def dumps(value: Any) -> str:
    return json.dumps(value if value is not None else {}, indent=None, sort_keys=True, default=str)


def loads(value: Optional[str], default: Any = None) -> Any:
    if value in (None, ""):
        return {} if default is None else default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return {} if default is None else default


@dataclass
class MigrationReport:
    """Accumulates per-type counts and per-file errors during a legacy import."""

    projects_imported: int = 0
    reviews_imported: int = 0
    scheduled_posts_imported: int = 0
    settings_imported: int = 0
    secrets_imported: int = 0
    analytics_imported: int = 0
    errors: List[Dict[str, str]] = field(default_factory=list)

    def add_error(self, file_path: str, error: str) -> None:
        self.errors.append({"file": file_path, "error": error})

    def summary(self) -> str:
        lines = [
            "Migration Report",
            "=" * 40,
            f"  Projects imported:       {self.projects_imported}",
            f"  Reviews imported:         {self.reviews_imported}",
            f"  Scheduled posts imported: {self.scheduled_posts_imported}",
            f"  Settings imported:        {self.settings_imported}",
            f"  Secrets imported:         {self.secrets_imported}",
            f"  Analytics imported:       {self.analytics_imported}",
        ]
        if self.errors:
            lines.append(f"\n  Errors ({len(self.errors)}):")
            for err in self.errors:
                lines.append(f"    - {err['file']}: {err['error']}")
        else:
            lines.append("\n  No errors.")
        return "\n".join(lines)

    @property
    def has_errors(self) -> bool:
        return len(self.errors) > 0


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


class SQLiteStore:
    """Shared SQLite persistence layer.

    The store intentionally keeps records as JSON at the boundary. Existing
    managers can keep returning their current dict/dataclass shapes while
    writes gain transactions, UUID IDs, and one canonical backing database.
    """

    def __init__(
        self,
        data_dir: Optional[str | Path] = None,
        db_path: Optional[str | Path] = None,
        migrate: bool = True,
    ):
        self.data_dir = Path(data_dir) if data_dir else Path(__file__).resolve().parent
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = Path(db_path) if db_path else self.data_dir / "marketing_pipeline.sqlite3"
        self._ensure_secure_database_file()
        self._init_schema()
        if migrate:
            self.import_legacy_files_once()

    def _ensure_secure_database_file(self) -> None:
        """Create or tighten the SQLite file so local secrets are not world-readable."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.db_path.exists():
            try:
                fd = os.open(self.db_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
                os.close(fd)
            except FileExistsError:
                pass
        try:
            self.db_path.chmod(0o600)
        except OSError:
            pass

    def _tighten_sqlite_sidecar_files(self) -> None:
        for suffix in ("-wal", "-shm"):
            path = Path(f"{self.db_path}{suffix}")
            if path.exists():
                try:
                    path.chmod(0o600)
                except OSError:
                    pass

    @contextmanager
    def connect(self) -> Iterable[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
            self._tighten_sqlite_sidecar_files()

    def _init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    slug TEXT,
                    description TEXT NOT NULL DEFAULT '',
                    config_json TEXT NOT NULL DEFAULT '{}',
                    settings_json TEXT NOT NULL DEFAULT '{}',
                    generation_schedule_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_projects_slug
                    ON projects(slug)
                    WHERE slug IS NOT NULL AND deleted_at IS NULL;

                CREATE TABLE IF NOT EXISTS current_state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS project_kv (
                    project_id TEXT NOT NULL,
                    key TEXT NOT NULL,
                    value_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(project_id, key)
                );

                CREATE TABLE IF NOT EXISTS reviews (
                    review_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    status TEXT NOT NULL,
                    channel TEXT NOT NULL DEFAULT 'CLI',
                    post_data_json TEXT NOT NULL DEFAULT '{}',
                    feedback TEXT,
                    feedback_history_json TEXT,
                    scheduling_error TEXT,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_reviews_project_status
                    ON reviews(project_id, status, created_at);

                CREATE TABLE IF NOT EXISTS scheduled_posts (
                    post_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    scheduled_at TEXT,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_scheduled_project_time
                    ON scheduled_posts(project_id, scheduled_at);

                CREATE TABLE IF NOT EXISTS nostr_signing_requests (
                    request_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    review_id TEXT,
                    status TEXT NOT NULL DEFAULT 'pending_signature',
                    unsigned_event_json TEXT,
                    signed_event_json TEXT,
                    event_id TEXT,
                    event_uri TEXT,
                    relays_json TEXT NOT NULL DEFAULT '[]',
                    scheduled_at TEXT,
                    signed_at TEXT,
                    published_at TEXT,
                    publish_attempts INTEGER NOT NULL DEFAULT 0,
                    last_error TEXT,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_nostr_requests_status
                    ON nostr_signing_requests(status, scheduled_at);

                CREATE INDEX IF NOT EXISTS idx_nostr_requests_project
                    ON nostr_signing_requests(project_id, status);

                CREATE TABLE IF NOT EXISTS jobs (
                    job_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    kind TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'queued',
                    priority INTEGER NOT NULL DEFAULT 100,
                    payload_json TEXT NOT NULL DEFAULT '{}',
                    result_json TEXT,
                    error TEXT,
                    attempts INTEGER NOT NULL DEFAULT 0,
                    max_attempts INTEGER NOT NULL DEFAULT 3,
                    available_at TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    started_at TEXT,
                    finished_at TEXT,
                    failure_category TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_jobs_status_available
                    ON jobs(status, priority, available_at, created_at);

                CREATE INDEX IF NOT EXISTS idx_jobs_project_status
                    ON jobs(project_id, status, created_at);

                CREATE TABLE IF NOT EXISTS source_material (
                    material_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    material_type TEXT NOT NULL,
                    title TEXT,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_source_material_project_type
                    ON source_material(project_id, material_type, created_at);

                CREATE TABLE IF NOT EXISTS content_ideas (
                    idea_id TEXT PRIMARY KEY,
                    project_id TEXT,
                    status TEXT NOT NULL DEFAULT 'draft',
                    content_pillar TEXT,
                    record_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_content_ideas_project_status
                    ON content_ideas(project_id, status, created_at);

                CREATE TABLE IF NOT EXISTS access_tokens (
                    token_id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    token_hash TEXT NOT NULL UNIQUE,
                    token_prefix TEXT NOT NULL,
                    is_admin INTEGER NOT NULL DEFAULT 0,
                    mcp_enabled INTEGER NOT NULL DEFAULT 0,
                    expires_at TEXT,
                    revoked_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_access_tokens_hash
                    ON access_tokens(token_hash)
                    WHERE revoked_at IS NULL;

                CREATE TABLE IF NOT EXISTS project_roles (
                    token_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(token_id, project_id),
                    FOREIGN KEY(token_id) REFERENCES access_tokens(token_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_project_roles_project
                    ON project_roles(project_id, role);

                CREATE TABLE IF NOT EXISTS analytics_snapshots (
                    source_path TEXT PRIMARY KEY,
                    data_json TEXT NOT NULL,
                    imported_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS system_events (
                    event_id TEXT PRIMARY KEY,
                    ts TEXT NOT NULL,
                    category TEXT NOT NULL,
                    action TEXT NOT NULL,
                    project_id TEXT,
                    review_id TEXT,
                    job_id TEXT,
                    payload_json TEXT NOT NULL DEFAULT '{}'
                );

                CREATE INDEX IF NOT EXISTS idx_system_events_ts_category
                    ON system_events(ts, category);

                CREATE INDEX IF NOT EXISTS idx_system_events_project_ts
                    ON system_events(project_id, ts)
                    WHERE project_id IS NOT NULL;
                """
            )

            # Migrate pre-existing databases that lack the new review columns.
            self._migrate_review_columns(conn)

            # Phase 4 plan 04-04: jobs.failure_category column. Idempotent —
            # uses PRAGMA table_info to skip if already present (preserves
            # rollback compat for databases created before this plan).
            columns = {
                row["name"] for row in conn.execute("PRAGMA table_info(jobs)").fetchall()
            }
            if "failure_category" not in columns:
                conn.execute("ALTER TABLE jobs ADD COLUMN failure_category TEXT")

    def _migrate_review_columns(self, conn: sqlite3.Connection) -> None:
        """Add feedback_history_json and scheduling_error columns if missing."""
        if self.get_meta("schema_reviews_v2") == "1":
            return
        try:
            conn.execute("ALTER TABLE reviews ADD COLUMN feedback_history_json TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        try:
            conn.execute("ALTER TABLE reviews ADD COLUMN scheduling_error TEXT")
        except sqlite3.OperationalError:
            pass  # Column already exists
        # Create partial indexes for the new columns (idempotent via IF NOT EXISTS).
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reviews_feedback_history "
            "ON reviews(review_id) WHERE feedback_history_json IS NOT NULL"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_reviews_scheduling_error "
            "ON reviews(review_id) WHERE scheduling_error IS NOT NULL"
        )
        self.set_meta("schema_reviews_v2", "1")

    def get_meta(self, key: str) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
            return row["value"] if row else None

    def set_meta(self, key: str, value: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO meta(key, value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (key, value, now),
            )

    def import_legacy_files_once(self, report: Optional["MigrationReport"] = None) -> None:
        if report is None and self.get_meta("legacy_imported") == "1":
            return

        self._import_projects_json(report=report)
        self._import_project_data_dirs(report=report)
        self._import_reviews_file(self.data_dir / "reviews.json", None, report=report)
        self._import_scheduled_posts(self.data_dir / "scheduled_posts.json", report=report)
        self._import_orchestrator_scheduled(report=report)
        self._import_analytics_files(report=report)
        if report is None:
            self.set_meta("legacy_imported", "1")

    def run_migration_report(
        self,
        dry_run: bool = True,
        data_dir: Optional[str | Path] = None,
    ) -> "MigrationReport":
        """Run legacy import and return a MigrationReport with counts and errors.

        When dry_run is True, imports against an in-memory database and discards it.
        When dry_run is False, imports against self (the real database).
        """
        target_dir = Path(data_dir) if data_dir else self.data_dir
        report = MigrationReport()

        if dry_run:
            # Use a temporary file so all connections within the store see the
            # same database.  In-memory SQLite creates a separate DB per
            # connection, which breaks the meta table lookups during init.
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                tmp_db = Path(tmp) / "dry_run.sqlite3"
                tmp_store = SQLiteStore(
                    data_dir=target_dir,
                    db_path=tmp_db,
                    migrate=False,
                )
                tmp_store.import_legacy_files_once(report=report)
            # tmp_dir is cleaned up here — no trace left on disk
        else:
            self.import_legacy_files_once(report=report)
            self.set_meta("legacy_imported", "1")

        return report

    def _import_projects_json(self, report: Optional["MigrationReport"] = None) -> None:
        path = self.data_dir / "projects.json"
        try:
            data = read_json(path, {})
        except Exception as exc:
            if report:
                report.add_error(str(path), f"Failed to read: {exc}")
            return
        if not isinstance(data, dict):
            if report:
                report.add_error(str(path), f"Expected a JSON object, got {type(data).__name__}")
            return
        for project_id, record in data.items():
            if not isinstance(record, dict):
                continue
            try:
                record = self._normalize_project_record(project_id, record)
                self.save_project_record(record, replace=False)
                if report:
                    report.projects_imported += 1
            except Exception as exc:
                if report:
                    report.add_error(str(path), f"Project {project_id}: {exc}")

    def _import_project_data_dirs(self, report: Optional["MigrationReport"] = None) -> None:
        projects_dir = self.data_dir / "projects"
        if not projects_dir.exists():
            return

        for project_dir in projects_dir.iterdir():
            if not project_dir.is_dir():
                continue

            project_id = project_dir.name
            settings_path = project_dir / "settings.json"
            secrets_path = project_dir / "secrets.json"
            provider_mapping_path = project_dir / "provider_mapping.json"
            reviews_path = project_dir / "reviews.json"

            settings = read_json(settings_path, {})
            secrets = read_json(secrets_path, {})
            provider_mapping = read_json(provider_mapping_path, {})

            # Validate settings file if it exists
            if settings_path.exists():
                try:
                    settings = json.loads(settings_path.read_text())
                    if not isinstance(settings, dict):
                        if report:
                            report.add_error(str(settings_path), "Expected a JSON object")
                        settings = {}
                except json.JSONDecodeError as exc:
                    if report:
                        report.add_error(str(settings_path), f"Malformed JSON: {exc}")
                    settings = {}

            if settings:
                try:
                    self.set_project_value(project_id, "settings", settings)
                    if report:
                        report.settings_imported += 1
                    if not self.get_project_record(project_id):
                        name = settings.get("name") or project_id
                        self.save_project_record(
                            self._normalize_project_record(
                                project_id,
                                {
                                    "project_id": project_id,
                                    "name": name,
                                    "settings": settings,
                                },
                            ),
                            replace=False,
                        )
                except Exception as exc:
                    if report:
                        report.add_error(str(settings_path), f"Settings import: {exc}")

            if secrets:
                try:
                    self.set_project_value(project_id, "secrets", secrets)
                    if report:
                        report.secrets_imported += 1
                except Exception as exc:
                    if report:
                        report.add_error(str(secrets_path), f"Secrets import: {exc}")
            if provider_mapping:
                try:
                    self.set_project_value(project_id, "provider_mapping", provider_mapping)
                except Exception as exc:
                    if report:
                        report.add_error(
                            str(provider_mapping_path), f"Provider mapping import: {exc}"
                        )
            if isinstance(settings, dict) and settings.get("provider_mapping"):
                try:
                    self.set_project_value(
                        project_id, "provider_mapping", settings["provider_mapping"]
                    )
                except Exception as exc:
                    if report:
                        report.add_error(
                            str(settings_path), f"Provider mapping from settings: {exc}"
                        )

            self._import_reviews_file(reviews_path, project_id, report=report)

    def _import_reviews_file(
        self,
        path: Path,
        project_id: Optional[str],
        report: Optional["MigrationReport"] = None,
    ) -> None:
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            if report:
                report.add_error(str(path), f"Malformed JSON: {exc}")
            return
        except Exception as exc:
            if report:
                report.add_error(str(path), f"Failed to read: {exc}")
            return

        if isinstance(data, list):
            records = data
        elif isinstance(data, dict):
            records = []
            for key, record in data.items():
                if isinstance(record, dict):
                    record.setdefault("review_id", key)
                    records.append(record)
        else:
            if report:
                report.add_error(str(path), f"Unexpected JSON type: {type(data).__name__}")
            return

        for record in records:
            if not isinstance(record, dict):
                continue
            try:
                normalized = self.normalize_review_record(record, project_id=project_id)
                self.save_review_record(normalized, replace=False)
                if report:
                    report.reviews_imported += 1
            except Exception as exc:
                if report:
                    report.add_error(str(path), f"Review import: {exc}")

    def _import_scheduled_posts(
        self, path: Path, report: Optional["MigrationReport"] = None
    ) -> None:
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            if report:
                report.add_error(str(path), f"Malformed JSON: {exc}")
            return
        except Exception as exc:
            if report:
                report.add_error(str(path), f"Failed to read: {exc}")
            return
        if not isinstance(data, list):
            if report:
                report.add_error(str(path), "Expected a JSON array")
            return
        for record in data:
            if not isinstance(record, dict):
                continue
            try:
                normalized = self.normalize_scheduled_record(record)
                self.save_scheduled_record(normalized, replace=False)
                if report:
                    report.scheduled_posts_imported += 1
            except Exception as exc:
                if report:
                    report.add_error(str(path), f"Scheduled post import: {exc}")

    def _import_orchestrator_scheduled(self, report: Optional["MigrationReport"] = None) -> None:
        """Import the dict-shaped orchestrator_scheduled.json left by SocialOrchestrator.

        Unlike scheduled_posts.json (a list), this file is keyed by post_id.
        Post-#2 migration, SocialOrchestrator writes directly to the store.
        """
        path = self.data_dir / "orchestrator_scheduled.json"
        if not path.exists():
            return
        try:
            data = json.loads(path.read_text())
        except json.JSONDecodeError as exc:
            if report:
                report.add_error(str(path), f"Malformed JSON: {exc}")
            return
        except Exception as exc:
            if report:
                report.add_error(str(path), f"Failed to read: {exc}")
            return
        iterable = data.items() if isinstance(data, dict) else enumerate(data)
        for key, record in iterable:
            if not isinstance(record, dict):
                continue
            # The dict key is the post_id; preserve it so the row is reachable by id.
            if isinstance(data, dict) and not record.get("post_id"):
                record = {**record, "post_id": key}
            try:
                normalized = self.normalize_scheduled_record(record)
                self.save_scheduled_record(normalized, replace=False)
                if report:
                    report.scheduled_posts_imported += 1
            except Exception as exc:
                if report:
                    report.add_error(str(path), f"Scheduled post import: {exc}")

    def _import_analytics_files(self, report: Optional["MigrationReport"] = None) -> None:
        """Import legacy analytics JSON artifacts into SQLite snapshots."""
        analytics_files = [
            "typefully_metrics.json",
            "typefully_analytics.json",
            "typefully_trends.json",
            "unified_analytics.json",
            "content_recommendations.json",
            "content_preferences.json",
            "sync_status.json",
            "nostr_events.json",
            "nostr_metrics.json",
            "nostr_trends.json",
        ]
        for filename in analytics_files:
            path = self.data_dir / filename
            if not path.exists():
                continue
            try:
                data = json.loads(path.read_text())
            except json.JSONDecodeError as exc:
                if report:
                    report.add_error(str(path), f"Malformed JSON: {exc}")
                continue
            except Exception as exc:
                if report:
                    report.add_error(str(path), f"Failed to read: {exc}")
                continue
            try:
                self.save_analytics_snapshot(str(path.relative_to(self.data_dir)), data)
                if report:
                    report.analytics_imported += 1
            except Exception as exc:
                if report:
                    report.add_error(str(path), f"Analytics import: {exc}")

    def _normalize_project_record(self, project_id: str, record: Dict[str, Any]) -> Dict[str, Any]:
        name = record.get("name") or project_id
        config = record.get("config") or {}
        settings = record.get("settings") or {}
        generation_schedule = record.get("generation_schedule") or {}
        slug = record.get("slug") or slugify(name)
        created_at = record.get("created_at") or utc_now()

        return {
            "project_id": record.get("project_id") or project_id,
            "name": name,
            "slug": slug,
            "description": record.get("description", ""),
            "config": config,
            "settings": settings,
            "generation_schedule": generation_schedule,
            "created_at": created_at,
        }

    def save_project_record(self, record: Dict[str, Any], replace: bool = True) -> None:
        now = utc_now()
        project_id = record["project_id"]
        params = (
            project_id,
            record.get("name", project_id),
            record.get("slug") or slugify(record.get("name", project_id)),
            record.get("description", ""),
            dumps(record.get("config", {})),
            dumps(record.get("settings", {})),
            dumps(record.get("generation_schedule", {})),
            record.get("created_at") or now,
            now,
        )
        with self.connect() as conn:
            if replace:
                conn.execute(
                    """
                    INSERT INTO projects(
                        project_id, name, slug, description, config_json, settings_json,
                        generation_schedule_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(project_id) DO UPDATE SET
                        name = excluded.name,
                        slug = excluded.slug,
                        description = excluded.description,
                        config_json = excluded.config_json,
                        settings_json = excluded.settings_json,
                        generation_schedule_json = excluded.generation_schedule_json,
                        updated_at = excluded.updated_at,
                        deleted_at = NULL
                    """,
                    params,
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO projects(
                        project_id, name, slug, description, config_json, settings_json,
                        generation_schedule_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )

    def get_project_record(self, project_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE project_id = ? AND deleted_at IS NULL",
                (project_id,),
            ).fetchone()
        return self._row_to_project(row) if row else None

    def get_project_record_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM projects
                WHERE lower(name) = lower(?) AND deleted_at IS NULL
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (name,),
            ).fetchone()
        return self._row_to_project(row) if row else None

    def get_project_record_by_slug(self, slug: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE slug = ? AND deleted_at IS NULL",
                (slug,),
            ).fetchone()
        return self._row_to_project(row) if row else None

    def list_project_records(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM projects WHERE deleted_at IS NULL ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [self._row_to_project(row) for row in rows]

    def delete_project_record(self, project_id: str) -> bool:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                "UPDATE projects SET deleted_at = ?, updated_at = ? WHERE project_id = ? AND deleted_at IS NULL",
                (now, now, project_id),
            )
            deleted = cur.rowcount > 0
            if deleted:
                conn.execute("DELETE FROM project_kv WHERE project_id = ?", (project_id,))
        if self.get_current_project_id() == project_id:
            self.clear_current_project()
        return deleted

    def _row_to_project(self, row: sqlite3.Row) -> Dict[str, Any]:
        return {
            "project_id": row["project_id"],
            "name": row["name"],
            "slug": row["slug"],
            "description": row["description"],
            "config": loads(row["config_json"], {}),
            "settings": loads(row["settings_json"], {}),
            "generation_schedule": loads(row["generation_schedule_json"], {}),
            "created_at": row["created_at"],
        }

    def set_current_project_id(self, project_id: str) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO current_state(key, value, updated_at)
                VALUES ('current_project_id', ?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
                """,
                (project_id, now),
            )

    def get_current_project_id(self) -> Optional[str]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value FROM current_state WHERE key = 'current_project_id'"
            ).fetchone()
        return row["value"] if row and row["value"] else None

    def clear_current_project(self) -> None:
        with self.connect() as conn:
            conn.execute("DELETE FROM current_state WHERE key = 'current_project_id'")

    def set_project_value(self, project_id: str, key: str, value: Any) -> None:
        now = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO project_kv(project_id, key, value_json, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id, key) DO UPDATE SET
                    value_json = excluded.value_json,
                    updated_at = excluded.updated_at
                """,
                (project_id, key, dumps(value), now),
            )

    def get_project_value(self, project_id: str, key: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT value_json FROM project_kv WHERE project_id = ? AND key = ?",
                (project_id, key),
            ).fetchone()
        if not row:
            return {} if default is None else default
        return loads(row["value_json"], default)

    def save_analytics_snapshot(self, source_path: str, data: Any) -> None:
        """Persist an imported analytics JSON artifact."""
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO analytics_snapshots(source_path, data_json, imported_at)
                VALUES (?, ?, ?)
                ON CONFLICT(source_path) DO UPDATE SET
                    data_json = excluded.data_json,
                    imported_at = excluded.imported_at
                """,
                (source_path, dumps(data), utc_now()),
            )

    def get_analytics_snapshot(self, source_path: str, default: Any = None) -> Any:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT data_json FROM analytics_snapshots WHERE source_path = ?",
                (source_path,),
            ).fetchone()
        if not row:
            return {} if default is None else default
        return loads(row["data_json"], default)

    def list_analytics_snapshots(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT source_path, data_json, imported_at FROM analytics_snapshots ORDER BY source_path"
            ).fetchall()
        return [
            {
                "source_path": row["source_path"],
                "data": loads(row["data_json"], {}),
                "imported_at": row["imported_at"],
            }
            for row in rows
        ]

    _EVENT_CATEGORIES = frozenset({"review", "publish", "job", "credential", "settings", "auth"})

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
        if category not in self._EVENT_CATEGORIES:
            raise ValueError(
                f"Unknown system_event category: {category!r}. "
                f"Expected one of {sorted(self._EVENT_CATEGORIES)}"
            )
        payload_value = payload if payload is not None else {}
        payload_json = json.dumps(payload_value, indent=None, sort_keys=True)
        event_id = new_id("evt_")
        ts = utc_now()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO system_events(
                    event_id, ts, category, action, project_id, review_id, job_id, payload_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (event_id, ts, category, action, project_id, review_id, job_id, payload_json),
            )
        return {
            "event_id": event_id,
            "ts": ts,
            "category": category,
            "action": action,
            "project_id": project_id,
            "review_id": review_id,
            "job_id": job_id,
            "payload": payload_value,
        }

    def list_events(
        self,
        *,
        category: Optional[str] = None,
        since: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        bounded_limit = max(0, min(int(limit), 1000))
        bounded_offset = max(0, int(offset))
        clauses: List[str] = []
        params: List[Any] = []
        if category:
            clauses.append("category = ?")
            params.append(category)
        if since:
            clauses.append("ts >= ?")
            params.append(since)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT event_id, ts, category, action, project_id, review_id, job_id, payload_json "
            f"FROM system_events {where} ORDER BY ts DESC LIMIT ? OFFSET ?"
        )
        params.extend([bounded_limit, bounded_offset])
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {
                "event_id": row["event_id"],
                "ts": row["ts"],
                "category": row["category"],
                "action": row["action"],
                "project_id": row["project_id"],
                "review_id": row["review_id"],
                "job_id": row["job_id"],
                "payload": loads(row["payload_json"], {}),
            }
            for row in rows
        ]


    # ------------------------------------------------------------------
    # Access-control persistence
    # ------------------------------------------------------------------

    @staticmethod
    def hash_access_token(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def create_access_token(
        self,
        label: str,
        project_roles: Optional[Dict[str, str]] = None,
        *,
        is_admin: bool = False,
        mcp_enabled: bool = False,
        expires_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = utc_now()
        raw_token = f"draper_{secrets.token_urlsafe(32)}"
        token_id = new_id("tok_")
        project_roles = project_roles or {}
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO access_tokens(
                    token_id, label, token_hash, token_prefix, is_admin,
                    mcp_enabled, expires_at, revoked_at, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)
                """,
                (
                    token_id,
                    label or "Project token",
                    self.hash_access_token(raw_token),
                    raw_token[:16],
                    1 if is_admin else 0,
                    1 if mcp_enabled else 0,
                    expires_at,
                    now,
                    now,
                ),
            )
            for project_id, role in project_roles.items():
                conn.execute(
                    """
                    INSERT INTO project_roles(token_id, project_id, role, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (token_id, project_id, role, now, now),
                )
        record = self.get_access_token(token_id) or {}
        record["token"] = raw_token
        return record

    def get_access_token(self, token_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM access_tokens WHERE token_id = ?",
                (token_id,),
            ).fetchone()
            if not row:
                return None
            roles = conn.execute(
                "SELECT project_id, role FROM project_roles WHERE token_id = ?",
                (token_id,),
            ).fetchall()
        return self._row_to_access_token(row, roles)

    def get_access_token_by_hash(self, token_hash: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM access_tokens
                WHERE token_hash = ? AND revoked_at IS NULL
                  AND (expires_at IS NULL OR expires_at > ?)
                """,
                (token_hash, utc_now()),
            ).fetchone()
            if not row:
                return None
            roles = conn.execute(
                "SELECT project_id, role FROM project_roles WHERE token_id = ?",
                (row["token_id"],),
            ).fetchall()
        return self._row_to_access_token(row, roles)

    def list_access_tokens(self, project_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            if project_id:
                rows = conn.execute(
                    """
                    SELECT DISTINCT t.*
                    FROM access_tokens t
                    JOIN project_roles r ON r.token_id = t.token_id
                    WHERE r.project_id = ?
                    ORDER BY t.created_at DESC
                    """,
                    (project_id,),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM access_tokens ORDER BY created_at DESC"
                ).fetchall()
            token_ids = [row["token_id"] for row in rows]
            role_rows = []
            if token_ids:
                placeholders = ", ".join("?" for _ in token_ids)
                role_rows = conn.execute(
                    f"SELECT token_id, project_id, role FROM project_roles "
                    f"WHERE token_id IN ({placeholders})",
                    token_ids,
                ).fetchall()
        roles_by_token: Dict[str, List[sqlite3.Row]] = {token_id: [] for token_id in token_ids}
        for role_row in role_rows:
            roles_by_token.setdefault(role_row["token_id"], []).append(role_row)
        return [
            self._row_to_access_token(row, roles_by_token.get(row["token_id"], [])) for row in rows
        ]

    def revoke_access_token(self, token_id: str) -> bool:
        now = utc_now()
        with self.connect() as conn:
            cur = conn.execute(
                """
                UPDATE access_tokens
                SET revoked_at = ?, updated_at = ?
                WHERE token_id = ? AND revoked_at IS NULL
                """,
                (now, now, token_id),
            )
            return cur.rowcount > 0

    def _row_to_access_token(
        self,
        row: sqlite3.Row,
        role_rows: Iterable[sqlite3.Row],
    ) -> Dict[str, Any]:
        return {
            "token_id": row["token_id"],
            "label": row["label"],
            "token_prefix": row["token_prefix"],
            "is_admin": bool(row["is_admin"]),
            "mcp_enabled": bool(row["mcp_enabled"]),
            "expires_at": row["expires_at"],
            "revoked_at": row["revoked_at"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "project_roles": {r["project_id"]: r["role"] for r in role_rows},
        }

    def get_project_mcp_config(self, project_id: str) -> Dict[str, Any]:
        default = {
            "enabled": False,
            "allowed_tools": [],
            "max_role": "viewer",
        }
        config = self.get_project_value(project_id, "mcp_config", default)
        if not isinstance(config, dict):
            return default
        merged = {**default, **config}
        if not isinstance(merged.get("allowed_tools"), list):
            merged["allowed_tools"] = []
        return merged

    def set_project_mcp_config(self, project_id: str, config: Dict[str, Any]) -> Dict[str, Any]:
        current = self.get_project_mcp_config(project_id)
        merged = {**current, **(config or {})}
        merged["enabled"] = bool(merged.get("enabled"))
        allowed_tools = merged.get("allowed_tools") or []
        merged["allowed_tools"] = [str(tool) for tool in allowed_tools if str(tool).strip()]
        merged["max_role"] = str(merged.get("max_role") or "viewer")
        self.set_project_value(project_id, "mcp_config", merged)
        return merged

    def normalize_review_record(
        self,
        record: Dict[str, Any],
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        post_data = dict(record.get("post_data") or {})
        resolved_project_id = project_id or record.get("project_id") or post_data.get("project_id")
        if resolved_project_id:
            post_data.setdefault("project_id", resolved_project_id)
        review_id = record.get("review_id") or post_data.get("generated_at") or new_id("review_")
        normalized = dict(record)
        normalized.update(
            {
                "review_id": str(review_id),
                "project_id": resolved_project_id,
                "post_data": post_data,
                "channel": record.get("channel", "CLI"),
                "status": record.get("status", "pending_review"),
                "created_at": record.get("created_at") or utc_now(),
                "feedback": record.get("feedback"),
                "feedback_history": record.get("feedback_history"),
                "scheduling_error": record.get("scheduling_error"),
            }
        )
        return normalized

    def save_review_record(self, record: Dict[str, Any], replace: bool = True) -> None:
        normalized = self.normalize_review_record(record)
        now = utc_now()
        feedback_history = normalized.get("feedback_history")
        feedback_history_json = dumps(feedback_history) if feedback_history else None
        params = (
            normalized["review_id"],
            normalized.get("project_id"),
            normalized.get("status", "pending_review"),
            normalized.get("channel", "CLI"),
            dumps(normalized.get("post_data", {})),
            normalized.get("feedback"),
            feedback_history_json,
            normalized.get("scheduling_error"),
            dumps(normalized),
            normalized.get("created_at") or now,
            now,
        )
        with self.connect() as conn:
            if replace:
                conn.execute(
                    """
                    INSERT INTO reviews(
                        review_id, project_id, status, channel, post_data_json,
                        feedback, feedback_history_json, scheduling_error,
                        record_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(review_id) DO UPDATE SET
                        project_id = excluded.project_id,
                        status = excluded.status,
                        channel = excluded.channel,
                        post_data_json = excluded.post_data_json,
                        feedback = excluded.feedback,
                        feedback_history_json = excluded.feedback_history_json,
                        scheduling_error = excluded.scheduling_error,
                        record_json = excluded.record_json,
                        updated_at = excluded.updated_at
                    """,
                    params,
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO reviews(
                        review_id, project_id, status, channel, post_data_json,
                        feedback, feedback_history_json, scheduling_error,
                        record_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )

    def get_review_record(self, review_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT record_json, feedback_history_json, scheduling_error "
                "FROM reviews WHERE review_id = ?",
                (review_id,),
            ).fetchone()
        if not row:
            return None
        result = loads(row["record_json"], {})
        # Merge structured columns back so they reflect any independent updates.
        if row["feedback_history_json"] is not None:
            result["feedback_history"] = loads(row["feedback_history_json"], [])
        if row["scheduling_error"] is not None:
            result["scheduling_error"] = row["scheduling_error"]
        return result

    def list_review_records(
        self,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params: List[Any] = []
        if status:
            clauses.append("status = ?")
            params.append(status)
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = (
            f"SELECT record_json, feedback_history_json, scheduling_error "
            f"FROM reviews {where} ORDER BY created_at DESC"
        )
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        results = []
        for row in rows:
            result = loads(row["record_json"], {})
            if row["feedback_history_json"] is not None:
                result["feedback_history"] = loads(row["feedback_history_json"], [])
            if row["scheduling_error"] is not None:
                result["scheduling_error"] = row["scheduling_error"]
            results.append(result)
        return results

    def normalize_scheduled_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        post_data = record.get("post_data") or {}
        project_id = record.get("project_id") or post_data.get("project_id")
        post_id = record.get("post_id") or new_id("scheduled_")
        normalized = dict(record)
        normalized.update(
            {
                "post_id": str(post_id),
                "project_id": project_id,
                "post_data": post_data,
                "status": record.get("status", "scheduled"),
                "scheduled_at": record.get("scheduled_at"),
                "created_at": record.get("created_at") or utc_now(),
            }
        )
        return normalized

    def save_scheduled_record(self, record: Dict[str, Any], replace: bool = True) -> None:
        normalized = self.normalize_scheduled_record(record)
        now = utc_now()
        params = (
            normalized["post_id"],
            normalized.get("project_id"),
            normalized.get("status", "scheduled"),
            normalized.get("scheduled_at"),
            dumps(normalized),
            normalized.get("created_at") or now,
            now,
        )
        with self.connect() as conn:
            if replace:
                conn.execute(
                    """
                    INSERT INTO scheduled_posts(
                        post_id, project_id, status, scheduled_at, record_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(post_id) DO UPDATE SET
                        project_id = excluded.project_id,
                        status = excluded.status,
                        scheduled_at = excluded.scheduled_at,
                        record_json = excluded.record_json,
                        updated_at = excluded.updated_at
                    """,
                    params,
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO scheduled_posts(
                        post_id, project_id, status, scheduled_at, record_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )

    def list_scheduled_records(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params: List[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT record_json FROM scheduled_posts {where} ORDER BY scheduled_at",
                params,
            ).fetchall()
        return [loads(row["record_json"], {}) for row in rows]

    def get_scheduled_record(self, post_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT record_json FROM scheduled_posts WHERE post_id = ?",
                (post_id,),
            ).fetchone()
        return loads(row["record_json"], {}) if row else None

    def delete_scheduled_record(self, post_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM scheduled_posts WHERE post_id = ?", (post_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Nostr signing request CRUD
    # ------------------------------------------------------------------

    NOSTR_REQUEST_STATUSES = (
        "pending_signature",
        "signed",
        "published",
        "publish_failed",
        "cancelled",
    )

    def normalize_nostr_request_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        unsigned_events = record.get("unsigned_events")
        if unsigned_events is None and record.get("unsigned_event"):
            unsigned_events = [record["unsigned_event"]]
        signed_events = record.get("signed_events")
        if signed_events is None and record.get("signed_event"):
            signed_events = [record["signed_event"]]

        normalized = dict(record)
        normalized.update(
            {
                "request_id": str(record.get("request_id") or new_id("nostr_")),
                "project_id": record.get("project_id"),
                "review_id": record.get("review_id"),
                "status": record.get("status", "pending_signature"),
                "unsigned_events": unsigned_events or [],
                "signed_events": signed_events,
                "event_id": record.get("event_id"),
                "event_uri": record.get("event_uri"),
                "relays": record.get("relays") or [],
                "scheduled_at": record.get("scheduled_at"),
                "signed_at": record.get("signed_at"),
                "published_at": record.get("published_at"),
                "publish_attempts": int(record.get("publish_attempts", 0) or 0),
                "last_error": record.get("last_error"),
                "created_at": record.get("created_at") or utc_now(),
            }
        )
        normalized.pop("unsigned_event", None)
        normalized.pop("signed_event", None)
        return normalized

    def save_nostr_request_record(self, record: Dict[str, Any], replace: bool = True) -> None:
        normalized = self.normalize_nostr_request_record(record)
        now = utc_now()
        params = (
            normalized["request_id"],
            normalized.get("project_id"),
            normalized.get("review_id"),
            normalized.get("status", "pending_signature"),
            dumps(normalized.get("unsigned_events") or []),
            dumps(normalized.get("signed_events")) if normalized.get("signed_events") else None,
            normalized.get("event_id"),
            normalized.get("event_uri"),
            dumps(normalized.get("relays") or []),
            normalized.get("scheduled_at"),
            normalized.get("signed_at"),
            normalized.get("published_at"),
            normalized.get("publish_attempts", 0),
            normalized.get("last_error"),
            dumps(normalized),
            normalized.get("created_at") or now,
            now,
        )
        with self.connect() as conn:
            if replace:
                conn.execute(
                    """
                    INSERT INTO nostr_signing_requests(
                        request_id, project_id, review_id, status,
                        unsigned_event_json, signed_event_json, event_id, event_uri,
                        relays_json, scheduled_at, signed_at, published_at,
                        publish_attempts, last_error, record_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(request_id) DO UPDATE SET
                        project_id = excluded.project_id,
                        review_id = excluded.review_id,
                        status = excluded.status,
                        unsigned_event_json = excluded.unsigned_event_json,
                        signed_event_json = excluded.signed_event_json,
                        event_id = excluded.event_id,
                        event_uri = excluded.event_uri,
                        relays_json = excluded.relays_json,
                        scheduled_at = excluded.scheduled_at,
                        signed_at = excluded.signed_at,
                        published_at = excluded.published_at,
                        publish_attempts = excluded.publish_attempts,
                        last_error = excluded.last_error,
                        record_json = excluded.record_json,
                        updated_at = excluded.updated_at
                    """,
                    params,
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO nostr_signing_requests(
                        request_id, project_id, review_id, status,
                        unsigned_event_json, signed_event_json, event_id, event_uri,
                        relays_json, scheduled_at, signed_at, published_at,
                        publish_attempts, last_error, record_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )

    def get_nostr_request_record(self, request_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT record_json FROM nostr_signing_requests WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        return loads(row["record_json"], {}) if row else None

    def list_nostr_request_records(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        review_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params: List[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if review_id:
            clauses.append("review_id = ?")
            params.append(review_id)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT record_json FROM nostr_signing_requests {where} "
                "ORDER BY COALESCE(scheduled_at, created_at)",
                params,
            ).fetchall()
        return [loads(row["record_json"], {}) for row in rows]

    def list_due_nostr_request_records(
        self,
        now_iso: str,
        limit: int = 50,
        project_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Signed requests whose scheduled time has arrived (empty = publish now)."""
        clauses = ["status = 'signed'", "(scheduled_at IS NULL OR scheduled_at <= ?)"]
        params: List[Any] = [now_iso]
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        params.append(limit)
        where = " AND ".join(clauses)
        with self.connect() as conn:
            rows = conn.execute(
                f"""
                SELECT record_json FROM nostr_signing_requests
                WHERE {where}
                ORDER BY COALESCE(scheduled_at, created_at)
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [loads(row["record_json"], {}) for row in rows]

    def delete_nostr_request_record(self, request_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute(
                "DELETE FROM nostr_signing_requests WHERE request_id = ?",
                (request_id,),
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------
    # Source material CRUD
    # ------------------------------------------------------------------

    def normalize_source_material_record(
        self,
        record: Dict[str, Any],
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        material_id = record.get("material_id") or new_id("sm_")
        resolved_project_id = project_id or record.get("project_id")
        normalized = dict(record)
        normalized.update(
            {
                "material_id": str(material_id),
                "project_id": resolved_project_id,
                "material_type": record.get("material_type", ""),
                "created_at": record.get("created_at") or utc_now(),
                "updated_at": record.get("updated_at") or utc_now(),
            }
        )
        return normalized

    def save_source_material_record(self, record: Dict[str, Any], replace: bool = True) -> None:
        normalized = self.normalize_source_material_record(record)
        now = utc_now()
        params = (
            normalized["material_id"],
            normalized.get("project_id"),
            normalized.get("material_type", ""),
            normalized.get("title"),
            dumps(normalized),
            normalized.get("created_at") or now,
            now,
        )
        with self.connect() as conn:
            if replace:
                conn.execute(
                    """
                    INSERT INTO source_material(
                        material_id, project_id, material_type, title,
                        record_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(material_id) DO UPDATE SET
                        project_id = excluded.project_id,
                        material_type = excluded.material_type,
                        title = excluded.title,
                        record_json = excluded.record_json,
                        updated_at = excluded.updated_at
                    """,
                    params,
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO source_material(
                        material_id, project_id, material_type, title,
                        record_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )

    def get_source_material_record(self, material_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT record_json FROM source_material WHERE material_id = ?",
                (material_id,),
            ).fetchone()
        return loads(row["record_json"], {}) if row else None

    def list_source_material_records(
        self,
        project_id: Optional[str] = None,
        material_type: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params: List[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if material_type:
            clauses.append("material_type = ?")
            params.append(material_type)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT record_json FROM source_material {where} ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [loads(row["record_json"], {}) for row in rows]

    def delete_source_material_record(self, material_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM source_material WHERE material_id = ?", (material_id,))
            return cur.rowcount > 0

    # -- Content Ideas CRUD --------------------------------------------------

    def normalize_content_idea_record(
        self,
        record: Dict[str, Any],
        project_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        idea_id = record.get("idea_id") or new_id("ci_")
        resolved_project_id = project_id or record.get("project_id")
        normalized = dict(record)
        normalized.update(
            {
                "idea_id": str(idea_id),
                "project_id": resolved_project_id,
                "status": record.get("status", "draft"),
                "content_pillar": record.get("content_pillar", ""),
                "created_at": record.get("created_at") or utc_now(),
                "updated_at": record.get("updated_at") or utc_now(),
            }
        )
        return normalized

    def save_content_idea_record(self, record: Dict[str, Any], replace: bool = True) -> None:
        normalized = self.normalize_content_idea_record(record)
        now = utc_now()
        params = (
            normalized["idea_id"],
            normalized.get("project_id"),
            normalized.get("status", "draft"),
            normalized.get("content_pillar", ""),
            dumps(normalized),
            normalized.get("created_at") or now,
            now,
        )
        with self.connect() as conn:
            if replace:
                conn.execute(
                    """
                    INSERT INTO content_ideas(
                        idea_id, project_id, status, content_pillar,
                        record_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(idea_id) DO UPDATE SET
                        project_id = excluded.project_id,
                        status = excluded.status,
                        content_pillar = excluded.content_pillar,
                        record_json = excluded.record_json,
                        updated_at = excluded.updated_at
                    """,
                    params,
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO content_ideas(
                        idea_id, project_id, status, content_pillar,
                        record_json, created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )

    def get_content_idea_record(self, idea_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT record_json FROM content_ideas WHERE idea_id = ?",
                (idea_id,),
            ).fetchone()
        return loads(row["record_json"], {}) if row else None

    def list_content_idea_records(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        content_pillar: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params: List[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        if content_pillar:
            clauses.append("content_pillar = ?")
            params.append(content_pillar)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        sql = f"SELECT record_json FROM content_ideas {where} ORDER BY created_at DESC"
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [loads(row["record_json"], {}) for row in rows]

    def delete_content_idea_record(self, idea_id: str) -> bool:
        with self.connect() as conn:
            cur = conn.execute("DELETE FROM content_ideas WHERE idea_id = ?", (idea_id,))
            return cur.rowcount > 0

    def normalize_job_record(self, record: Dict[str, Any]) -> Dict[str, Any]:
        payload = record.get("payload") or {}
        result = record.get("result")
        job_id = record.get("job_id") or new_id("job_")
        created_at = record.get("created_at") or utc_now()
        normalized = dict(record)
        normalized.update(
            {
                "job_id": str(job_id),
                "project_id": record.get("project_id") or payload.get("project_id"),
                "kind": record.get("kind", "generic"),
                "status": record.get("status", "queued"),
                "priority": int(record.get("priority", 100)),
                "payload": payload,
                "result": result,
                "error": record.get("error"),
                "attempts": int(record.get("attempts", 0)),
                "max_attempts": int(record.get("max_attempts", 3)),
                "available_at": record.get("available_at") or created_at,
                "created_at": created_at,
                "started_at": record.get("started_at"),
                "finished_at": record.get("finished_at"),
                "failure_category": record.get("failure_category"),
            }
        )
        return normalized

    def enqueue_job(
        self,
        kind: str,
        payload: Optional[Dict[str, Any]] = None,
        project_id: Optional[str] = None,
        priority: int = 100,
        available_at: Optional[str] = None,
        max_attempts: int = 3,
    ) -> Dict[str, Any]:
        record = self.normalize_job_record(
            {
                "kind": kind,
                "project_id": project_id,
                "payload": payload or {},
                "priority": priority,
                "available_at": available_at,
                "max_attempts": max_attempts,
            }
        )
        self.save_job_record(record)
        return record

    def save_job_record(self, record: Dict[str, Any], replace: bool = True) -> None:
        normalized = self.normalize_job_record(record)
        now = utc_now()
        normalized["updated_at"] = now
        params = (
            normalized["job_id"],
            normalized.get("project_id"),
            normalized["kind"],
            normalized["status"],
            normalized["priority"],
            dumps(normalized.get("payload", {})),
            dumps(normalized.get("result")) if normalized.get("result") is not None else None,
            normalized.get("error"),
            normalized["attempts"],
            normalized["max_attempts"],
            normalized["available_at"],
            dumps(normalized),
            normalized["created_at"],
            now,
            normalized.get("started_at"),
            normalized.get("finished_at"),
            normalized.get("failure_category"),
        )
        with self.connect() as conn:
            if replace:
                conn.execute(
                    """
                    INSERT INTO jobs(
                        job_id, project_id, kind, status, priority, payload_json,
                        result_json, error, attempts, max_attempts, available_at,
                        record_json, created_at, updated_at, started_at, finished_at,
                        failure_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(job_id) DO UPDATE SET
                        project_id = excluded.project_id,
                        kind = excluded.kind,
                        status = excluded.status,
                        priority = excluded.priority,
                        payload_json = excluded.payload_json,
                        result_json = excluded.result_json,
                        error = excluded.error,
                        attempts = excluded.attempts,
                        max_attempts = excluded.max_attempts,
                        available_at = excluded.available_at,
                        record_json = excluded.record_json,
                        updated_at = excluded.updated_at,
                        started_at = excluded.started_at,
                        finished_at = excluded.finished_at,
                        failure_category = excluded.failure_category
                    """,
                    params,
                )
            else:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO jobs(
                        job_id, project_id, kind, status, priority, payload_json,
                        result_json, error, attempts, max_attempts, available_at,
                        record_json, created_at, updated_at, started_at, finished_at,
                        failure_category
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    params,
                )

    def get_job_record(self, job_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id = ?", (job_id,)).fetchone()
        return self._row_to_job(row) if row else None

    def list_job_records(
        self,
        project_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        clauses = []
        params: List[Any] = []
        if project_id:
            clauses.append("project_id = ?")
            params.append(project_id)
        if status:
            clauses.append("status = ?")
            params.append(status)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM jobs {where} ORDER BY created_at DESC LIMIT ?",
                params,
            ).fetchall()
        return [self._row_to_job(row) for row in rows]

    def claim_next_job(self, kinds: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        now = utc_now()
        params: List[Any] = [now]
        kind_filter = ""
        if kinds:
            placeholders = ", ".join("?" for _ in kinds)
            kind_filter = f" AND kind IN ({placeholders})"
            params.extend(kinds)

        with self.connect() as conn:
            row = conn.execute(
                f"""
                SELECT * FROM jobs
                WHERE status = 'queued'
                  AND available_at <= ?
                  {kind_filter}
                ORDER BY priority ASC, available_at ASC, created_at ASC
                LIMIT 1
                """,
                params,
            ).fetchone()
            if not row:
                return None

            record = self._row_to_job(row)
            record["status"] = "running"
            record["attempts"] = int(record.get("attempts", 0)) + 1
            record["started_at"] = now
            record["updated_at"] = now
            updated = conn.execute(
                """
                UPDATE jobs
                SET status = 'running',
                    attempts = ?,
                    started_at = ?,
                    updated_at = ?,
                    record_json = ?
                WHERE job_id = ? AND status = 'queued'
                """,
                (
                    record["attempts"],
                    now,
                    now,
                    dumps(record),
                    record["job_id"],
                ),
            )
            if updated.rowcount == 0:
                return None
            return record

    def complete_job(
        self, job_id: str, result: Optional[Dict[str, Any]] = None
    ) -> Optional[Dict[str, Any]]:
        record = self.get_job_record(job_id)
        if not record:
            return None
        now = utc_now()
        record.update(
            {
                "status": "completed",
                "result": result or {},
                "error": None,
                "finished_at": now,
                "updated_at": now,
            }
        )
        self.save_job_record(record)
        return self.get_job_record(job_id)

    def fail_job(
        self,
        job_id: str,
        error: str,
        retry: bool = False,
        available_at: Optional[str] = None,
        failure_category: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        record = self.get_job_record(job_id)
        if not record:
            return None
        now = utc_now()
        can_retry = retry and int(record.get("attempts", 0)) < int(record.get("max_attempts", 0))
        record.update(
            {
                "status": "queued" if can_retry else "failed",
                "error": error,
                "available_at": available_at or now,
                "finished_at": None if can_retry else now,
                "updated_at": now,
            }
        )
        if failure_category is not None:
            record["failure_category"] = failure_category
        self.save_job_record(record)
        return self.get_job_record(job_id)

    def cancel_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        record = self.get_job_record(job_id)
        if not record:
            return None
        now = utc_now()
        record.update({"status": "cancelled", "finished_at": now, "updated_at": now})
        self.save_job_record(record)
        return self.get_job_record(job_id)

    def get_job_stats(self) -> Dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS count FROM jobs GROUP BY status"
            ).fetchall()
        stats = {"queued": 0, "running": 0, "completed": 0, "failed": 0, "cancelled": 0}
        for row in rows:
            stats[row["status"]] = row["count"]
        stats["total"] = sum(stats.values())
        return stats

    def recover_stuck_jobs(self, threshold_minutes: int = 30) -> List[Dict[str, Any]]:
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=threshold_minutes)
        cutoff_iso = cutoff.isoformat()
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT job_id, kind, payload_json FROM jobs "
                "WHERE status = 'running' AND started_at < ?",
                (cutoff_iso,),
            ).fetchall()
            recovered_ids = [row["job_id"] for row in rows]
            if not recovered_ids:
                return []
            placeholders = ", ".join("?" for _ in recovered_ids)
            conn.execute(
                f"UPDATE jobs SET status = 'failed', "
                f"failure_category = 'unknown', "
                f"error = COALESCE(error, 'stuck: timed out'), "
                f"finished_at = ?, updated_at = ? "
                f"WHERE job_id IN ({placeholders}) AND status = 'running'",
                [utc_now(), utc_now()] + recovered_ids,
            )
        for row in rows:
            if row["kind"] != "fix_content":
                continue
            payload = loads(row["payload_json"], {}) if row["payload_json"] else {}
            review_id = payload.get("review_id") if isinstance(payload, dict) else None
            if not review_id:
                continue
            self._clear_stale_auto_fix_status(review_id, row["job_id"])
        return [self.get_job_record(jid) for jid in recovered_ids if jid]

    def _clear_stale_auto_fix_status(self, review_id: str, job_id: str) -> None:
        record = self.get_review_record(review_id)
        if not record:
            return
        linked_job_id = record.get("auto_fix_job_id")
        if linked_job_id and linked_job_id != job_id:
            return
        if "auto_fix_status" not in record and "auto_fix_job_id" not in record:
            return
        record.pop("auto_fix_status", None)
        record.pop("auto_fix_job_id", None)
        self.save_review_record(record)

    def _row_to_job(self, row: sqlite3.Row) -> Dict[str, Any]:
        record = loads(row["record_json"], {})
        record.update(
            {
                "job_id": row["job_id"],
                "project_id": row["project_id"],
                "kind": row["kind"],
                "status": row["status"],
                "priority": row["priority"],
                "payload": loads(row["payload_json"], {}),
                "result": loads(row["result_json"], None) if row["result_json"] else None,
                "error": row["error"],
                "attempts": row["attempts"],
                "max_attempts": row["max_attempts"],
                "available_at": row["available_at"],
                "created_at": row["created_at"],
                "updated_at": row["updated_at"],
                "started_at": row["started_at"],
                "finished_at": row["finished_at"],
                "failure_category": dict(row).get("failure_category"),
            }
        )
        return record
