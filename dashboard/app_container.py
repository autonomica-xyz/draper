"""Application container that wraps ``UnifiedDashboard`` by composition.

Plan 03-01 introduces the structural target Plans 03-02 / 03-03 / 03-04 fill
in. ``AppContainer`` exposes the collaborator set wired in
``UnifiedDashboard.__init__`` so route modules can receive services via
``Depends()`` accessors instead of closing over a dashboard instance.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from dashboard.unified_dashboard import UnifiedDashboard
from services.generator_scoping import scoped_generator_for_project

if TYPE_CHECKING:
    from services.access_control import DashboardAccessPolicy


class AppContainer:
    """Holder of wired services, wrapping a ``UnifiedDashboard`` instance."""

    def __init__(self, data_dir: Optional[str] = None, *, host: str = "127.0.0.1"):
        self._dashboard = UnifiedDashboard(data_dir=data_dir)

        self.data_dir = self._dashboard.data_dir
        self.project_manager = self._dashboard.project_manager
        self.store = self._dashboard.store
        self.project_context = self._dashboard.project_context
        self.secret_service = self._dashboard.secret_service
        self.generator = self._dashboard.generator
        self.feedback_manager = self._dashboard.feedback_manager
        self.analytics = self._dashboard.analytics
        self.reasoning_tracker = self._dashboard.reasoning_tracker
        self.publishing_service = self._dashboard.publishing_service
        self.content_workflow = self._dashboard.content_workflow
        self.review_workflow = self._dashboard.review_workflow
        self.job_queue = self._dashboard.job_queue
        self.nostr_signing = self._dashboard.publishing_service.nostr_signing
        self.idea_lab = self._dashboard.idea_lab
        self.job_runner = self._dashboard.job_runner
        self.publishing_manager = self._dashboard.publishing_manager

        self.scheduled_file = self._dashboard.scheduled_file
        self.posts_history_file = self._dashboard.posts_history_file

        from services.access_control import DashboardAccessPolicy

        self.access_policy: DashboardAccessPolicy = DashboardAccessPolicy(host=host)
        self.access_policy.validate_startup()

        self.csrf: Any = None
        self.rate_limiter: Any = None
        self.login_limiter: Any = None
        self.security_headers: Any = None
        self.auth_middleware: Any = None
        self.request_id_middleware: Any = None

    @property
    def dashboard(self) -> UnifiedDashboard:
        return self._dashboard

    def get_projects(self) -> list:
        return self._dashboard.get_projects()

    def get_current_project(self, project_id: Optional[str] = None):
        return self._dashboard.get_current_project(project_id)

    def resolve_record_project_id(self, record):
        return self._dashboard.resolve_record_project_id(record)

    def get_publishing_manager(self, project_id: Optional[str] = None):
        return self._dashboard.get_publishing_manager(project_id)

    def get_generator_for_project(self, project_id: str):
        project = self.project_manager.get_project(project_id) if project_id else None
        if not project:
            raise ValueError("project_id is required")
        return scoped_generator_for_project(
            self.generator, project, secret_service=self.secret_service
        )

    def normalize_account_id(self, raw_id, platform, provider_name=None):
        return self._dashboard.normalize_account_id(raw_id, platform, provider_name)

    def get_project_social_profiles(self, project_id):
        return self._dashboard.get_project_social_profiles(project_id)

    def schedule_post(self, post_data, scheduled_at, review_id=None, job_id=None):
        return self._dashboard.schedule_post(
            post_data, scheduled_at, review_id=review_id, job_id=job_id
        )
