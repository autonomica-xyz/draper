#!/usr/bin/env python3
"""Draper unified dashboard bootstrap and compatibility container."""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from dotenv import load_dotenv

_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

load_dotenv(Path(_project_root) / ".env")

try:
    from generator.llm_content_generator import LLMContentGenerator
except Exception:
    LLMContentGenerator = None
try:
    from generator.zai_content_generator import ZAIContentGenerator
except Exception:
    ZAIContentGenerator = None

from analytics.unified_analytics import UnifiedAnalytics
from feedback import FeedbackManager
from integrations.publishing_provider import PublishingManager
from projects import ProjectManager
from reasoning.content_reasoning_tracker import ContentReasoningTracker
from services import (
    ContentWorkflowService,
    IdeaLabService,
    JobQueueService,
    JobRunner,
    ProjectContextService,
    ProjectPublishingService,
    ProjectSecretService,
    configure_logging,
)
from services.generator_scoping import scoped_generator_for_project
from services.nostr_signing_service import attach_pipeline_nostr_requests as attach_nostr
from services.review_workflow_service import ReviewWorkflowService

from dashboard.analytics_runtime import collect_analytics_data
from dashboard.routes._helpers import validation_error_message as _validation_error_message
from dashboard.routes.reviews import ApproveContentRequest

__all__ = ["ApproveContentRequest", "UnifiedDashboard", "_validation_error_message", "main"]

class UnifiedDashboard:
    """Dashboard runtime container retained for test compatibility."""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = str(Path(__file__).resolve().parent.parent / "data")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        self.project_manager = ProjectManager(data_dir=data_dir)
        self.store = self.project_manager.store
        self.project_context = ProjectContextService(self.project_manager)
        self.secret_service = ProjectSecretService(self.project_manager)

        env_project_id = os.environ.get("DRAPER_PROJECT_ID")
        current_project = (
            self.project_manager.get_project(env_project_id)
            if env_project_id
            else self.project_manager.get_current_project()
        )
        if current_project and env_project_id:
            self.project_manager.set_current_project(current_project.project_id)
        if current_project:
            print(f"📁 Dashboard loading project: {current_project.name}")
        else:
            print("⚠️  No project selected - using global data directory")

        try:
            if LLMContentGenerator is None:
                raise ValueError("LLM generator dependencies are not available")
            self.generator = LLMContentGenerator(project=current_project)
            print("✅ Using LLM content generator (Anthropic/OpenAI via litellm)")
        except ValueError as e:
            print(f"⚠️  LLM generator not available: {e}")
            try:
                if ZAIContentGenerator is None:
                    raise ValueError("ZAI generator dependencies are not available")
                self.generator = ZAIContentGenerator(project=current_project)
                print("✅ Using ZAI GLM-4.7 content generator")
            except ValueError as e2:
                print(f"⚠️  ZAI generator not available: {e2}")
                self.generator = None

        self.feedback_manager = FeedbackManager(data_dir=data_dir)
        self.analytics = UnifiedAnalytics(data_dir=data_dir)
        self.reasoning_tracker = ContentReasoningTracker()
        self.job_queue = JobQueueService(self.store)
        self.publishing_service = ProjectPublishingService(
            self.project_manager, self.data_dir, self.project_context,
            feedback_manager=self.feedback_manager, job_queue=self.job_queue,
        )
        self.content_workflow = ContentWorkflowService(
            self.feedback_manager, self.project_context, self.publishing_service
        )
        self.review_workflow = ReviewWorkflowService(
            self.feedback_manager, self.project_context, self.publishing_service
        )
        self.idea_lab = IdeaLabService(self.store)
        self.job_runner = JobRunner(
            self.job_queue,
            generator=self.generator,
            feedback_manager=self.feedback_manager,
            analytics=self.analytics,
            project_manager=self.project_manager,
            content_workflow=self.content_workflow,
            publishing_service=self.publishing_service,
            review_workflow=self.review_workflow,
        )
        self.publishing_manager = self.publishing_service.build_manager(
            current_project.project_id if current_project else None
        )
        configured_providers = [
            p.get_name() for p in self.publishing_manager.providers.values() if p.is_configured()
        ]
        if configured_providers:
            print(f"📡 Publishing providers: {', '.join(configured_providers)}")
        else:
            print("⚠️  No publishing providers configured")

        self.scheduled_file = self.data_dir / "scheduled_posts.json"
        self.posts_history_file = self.data_dir / "posts_history.json"

    def get_generator_for_project(self, project_id: str):
        """Return a project-bound generator for the target project."""
        project = self.project_manager.get_project(project_id) if project_id else None
        if not project:
            raise ValueError("project_id is required")
        return scoped_generator_for_project(
            self.generator, project, secret_service=self.secret_service
        )

    def get_analytics_data(self) -> Dict:
        return collect_analytics_data(self.data_dir, store=self.store)

    def get_scheduled_posts(self, project_id: str = None) -> List[Dict]:
        now = datetime.now(timezone.utc)
        upcoming = []
        for post in self.store.list_scheduled_records(project_id=project_id):
            scheduled_at = post.get("scheduled_at")
            if not scheduled_at:
                continue
            try:
                scheduled_dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
            except (TypeError, ValueError):
                continue
            if scheduled_dt.tzinfo is None:
                scheduled_dt = scheduled_dt.replace(tzinfo=timezone.utc)
            else:
                scheduled_dt = scheduled_dt.astimezone(timezone.utc)
            if scheduled_dt > now:
                upcoming.append(post)
        return sorted(upcoming, key=lambda x: x["scheduled_at"])

    def get_content_to_evaluate(self, limit: int = 20, project_id: str = None) -> List[Dict]:
        pending = self.feedback_manager.get_pending_reviews()
        if project_id:
            pending = [
                p
                for p in pending
                if p.get("project_id") == project_id
                or p["post_data"].get("project_id") == project_id
            ]
        pending = pending[:limit]
        results = []
        for review in pending:
            post_data = review["post_data"]
            reasoning_id = post_data.get("reasoning_id")
            reasoning = (
                self.reasoning_tracker.get_reasoning_by_id(reasoning_id) if reasoning_id else None
            )
            results.append(
                {
                    "review_id": review.get("review_id"),
                    "post_data": post_data,
                    "reasoning": reasoning,
                    "feedback": review.get("feedback"),
                    "media": review.get("media", []),
                    "status": review.get("status"),
                    "scheduling_error": review.get("scheduling_error"),
                    "auto_fix_status": review.get("auto_fix_status"),
                    "auto_fix_skip_reason": review.get("auto_fix_skip_reason"),
                    "auto_fix_error": review.get("auto_fix_error"),
                }
            )
        # Nostr sign-now-publish-later: unsigned approved items stay in the Pipeline.
        return attach_nostr(self.store, self.feedback_manager, results, project_id)

    def get_projects(self) -> List:
        return self.project_context.list_projects()

    def get_current_project(self, project_id: str = None):
        return self.project_context.get_current_project(project_id)

    def resolve_record_project_id(self, record: Dict) -> Optional[str]:
        return self.project_context.resolve_record_project_id(record)

    def get_publishing_manager(self, project_id: str = None) -> PublishingManager:
        return self.publishing_service.build_manager(project_id)

    def normalize_account_id(self, raw_id: str, platform: str, provider_name: str = None) -> str:
        return self.project_context.normalize_account_id(raw_id, platform, provider_name)

    def get_project_social_profiles(self, project_id: str) -> List[Dict]:
        return self.project_context.get_social_profiles(project_id)

    def schedule_post(
        self,
        post_data: Dict,
        scheduled_at: str,
        review_id: str = None,
        job_id: str = None,
    ) -> str:
        post_data = dict(post_data)
        scheduled_post = {
            "post_id": self.store.normalize_scheduled_record({})["post_id"],
            "review_id": review_id,
            "job_id": job_id,
            "project_id": post_data.get("project_id"),
            "post_data": post_data,
            "scheduled_at": scheduled_at,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "scheduled",
        }
        self.store.save_scheduled_record(scheduled_post)
        return scheduled_post["post_id"]

def main():
    """Run the unified dashboard server (bootstrap-only)."""
    import argparse

    parser = argparse.ArgumentParser(description="Unified dashboard for Draper marketing")
    parser.add_argument("--run-server", action="store_true", help="Run web server")
    parser.add_argument("--port", type=int, default=8000, help="Server port")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host")
    parser.add_argument("--data-dir", default=None, help="Data directory (default: <repo>/data)")
    parser.add_argument("--generate", type=int, help="Generate N posts for evaluation")
    parser.add_argument("--run-jobs", action="store_true", help="Run queued orchestration jobs")
    parser.add_argument("--jobs-once", action="store_true", help="Process at most one queued job")
    parser.add_argument("--job-kind", help="Only run jobs of this kind")
    parser.add_argument("--job-sleep", type=float, default=5.0, help="Idle sleep seconds")

    args = parser.parse_args()
    configure_logging()

    from dashboard.app_container import AppContainer
    from dashboard.app_factory import build_app

    container = AppContainer(data_dir=args.data_dir or os.environ.get("DRAPER_DATA_DIR"))
    dashboard = container.dashboard

    if args.run_jobs:
        import time

        kinds = [args.job_kind] if args.job_kind else None
        while True:
            result = dashboard.job_runner.run_once(kinds=kinds)
            if result:
                job = result.get("job") or {}
                print(f"Job {job.get('job_id')} {job.get('status')}: {job.get('kind')}")
            elif args.jobs_once:
                print("No queued jobs")
            if args.jobs_once:
                return
            if not result:
                time.sleep(args.job_sleep)

    if args.generate:
        current_project = dashboard.get_current_project()
        generator = dashboard.get_generator_for_project(
            current_project.project_id if current_project else None
        )
        result = generator.generate_batch(count=args.generate)
        posts = result.get("posts", []) if isinstance(result, dict) else result
        print(f"Generated {len(posts)} posts for evaluation")
        for post in posts:
            if current_project:
                post["project_id"] = current_project.project_id
                post["project_name"] = current_project.name
            dashboard.feedback_manager.post_content_for_review(post, "DASHBOARD")
        print(f"Posted to review queue. Access at http://localhost:{args.port}")
    elif args.run_server:
        import uvicorn

        app = build_app(container, host=args.host)
        print(f"Starting unified dashboard on http://{args.host}:{args.port}")
        uvicorn.run(app, host=args.host, port=args.port)

if __name__ == "__main__":
    main()
