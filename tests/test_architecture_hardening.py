import os
import tempfile
import unittest

from feedback import FeedbackManager
from integrations.publishing_provider import (
    PublishErrorCode,
    PublishingManager,
    PublishingProvider,
    PublishRequest,
    PublishResult,
    SocialAccount,
)
from projects import ProjectManager


class FakeProvider(PublishingProvider):
    def __init__(self, name, configured):
        self.name = name
        self.configured = configured
        self.requests = []

    def get_name(self):
        return self.name

    def is_configured(self):
        return self.configured

    def get_accounts(self):
        return [
            SocialAccount(
                account_id=f"{self.name}_1",
                platform="twitter",
                handle="@test",
                display_name="Test",
                provider=self.name,
            )
        ]

    def publish(self, request):
        self.requests.append(request)
        return PublishResult(
            success=True,
            provider=self.name,
            draft_id=f"{self.name}_draft_1",
            url=f"https://example.test/{self.name}/draft/1",
        )

    def get_analytics(self, account_id=None):
        return {}


class FakeGenerator:
    def generate_batch(self, count=5, platforms=None):
        platform = platforms[0] if platforms else "twitter"
        return [
            {
                "content": f"Generated post {idx + 1}",
                "platform": platform,
            }
            for idx in range(count)
        ]


class ArchitectureHardeningTests(unittest.TestCase):
    def test_project_and_review_state_use_sqlite(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(data_dir=tmp)
            project = pm.create_project("Core Tool", platforms=["twitter"])
            pm.set_current_project(project.project_id)

            self.assertTrue((pm.data_dir / "marketing_pipeline.sqlite3").exists())
            self.assertEqual(pm.get_current_project().project_id, project.project_id)

            project_data_dir = pm.get_project_data_dir(project.project_id)
            feedback = FeedbackManager(data_dir=str(project_data_dir))
            record = feedback.add_for_review(
                {
                    "content": "Ship the core tool.",
                    "platform": "twitter",
                },
                channel="TEST",
            )

            self.assertTrue(record["review_id"].startswith("review_"))
            self.assertEqual(record["project_id"], project.project_id)
            self.assertEqual(record["post_data"]["project_id"], project.project_id)
            self.assertEqual(feedback.get_stats()["pending"], 1)

            loaded = feedback._load_review_record(record["review_id"])
            self.assertEqual(loaded["project_id"], project.project_id)

    def test_data_project_manager_reads_canonical_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(data_dir=tmp)
            project = pm.create_project("Adapter Project", platforms=["twitter", "linkedin"])

            from data.project_manager import ProjectManager as DataProjectManager

            data_pm = DataProjectManager(data_dir=tmp)
            data_project = data_pm.get_project(project.project_id)

            self.assertIsNotNone(data_project)
            self.assertEqual(data_project.project_id, project.project_id)
            self.assertEqual(set(data_project.settings.platforms), {"twitter", "linkedin"})
            self.assertTrue(
                data_pm.load_content_plan(project.project_id).startswith(
                    "# Adapter Project Content Plan"
                )
            )

    def test_provider_mapping_is_canonical(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(data_dir=tmp)
            project = pm.create_project("Routing Project")

            pm.save_provider_mapping(project.project_id, {"twitter": "late"})

            self.assertEqual(pm.get_provider_mapping(project.project_id), {"twitter": "late"})
            self.assertEqual(
                pm.get_project_settings(project.project_id)["provider_mapping"],
                {"twitter": "late"},
            )

    def test_project_context_infers_provider_from_profile(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(data_dir=tmp)
            project = pm.create_project("Profile Routing", platforms=["twitter"])
            settings = pm.get_project_settings(project.project_id)
            settings["social_profiles"] = [
                {
                    "account_id": "account-456",
                    "platform": "twitter",
                    "provider": "late",
                    "enabled": True,
                }
            ]
            pm.save_project_settings(project.project_id, settings)

            from services import ProjectContextService

            context = ProjectContextService(pm)

            self.assertEqual(
                context.infer_provider_for_platform(project.project_id, "twitter"), "late"
            )
            self.assertEqual(
                context.find_enabled_account_id(project.project_id, "twitter", "late"),
                "late_account-456",
            )

    def test_verify_project_match_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(data_dir=tmp)
            target = pm.create_project("Target")

            with self.assertRaises(ValueError):
                pm.verify_project_match("", target.project_id)

            with self.assertRaises(ValueError):
                pm.verify_project_match("other", target.project_id)

    def test_publishing_manager_skips_unconfigured_primary(self):
        manager = PublishingManager()
        manager.register_provider(FakeProvider("typefully", configured=False), primary=True)
        manager.register_provider(FakeProvider("late", configured=True))

        result = manager.publish(PublishRequest(content="hello", platform="twitter"))

        self.assertTrue(result.success)
        self.assertEqual(result.provider, "late")

    def test_content_workflow_schedules_with_project_scoped_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(data_dir=tmp)
            project = pm.create_project("Workflow Project", platforms=["twitter"])
            pm.save_provider_mapping(project.project_id, {"twitter": "late"})

            settings = pm.get_project_settings(project.project_id)
            settings["social_profiles"] = [
                {
                    "account_id": "typefully_999_twitter",
                    "platform": "twitter",
                    "handle": "@wrong",
                    "display_name": "Wrong Provider",
                    "enabled": True,
                },
                {
                    "account_id": "account-123",
                    "platform": "twitter",
                    "provider": "late",
                    "handle": "@workflow",
                    "display_name": "Workflow",
                    "enabled": True,
                },
            ]
            pm.save_project_settings(project.project_id, settings)

            feedback = FeedbackManager(data_dir=str(pm.get_project_data_dir(project.project_id)))
            record = feedback.add_for_review(
                {
                    "content": "Schedule this through the project account.",
                    "platform": "twitter",
                },
                channel="TEST",
            )

            from services import (
                ContentWorkflowService,
                ProjectContextService,
                ProjectPublishingService,
            )

            provider = FakeProvider("late", configured=True)

            class StubPublishingService(ProjectPublishingService):
                def build_manager(self, project_id=None):
                    manager = PublishingManager()
                    manager.register_provider(provider, primary=True)
                    return manager

            context = ProjectContextService(pm)
            publishing = StubPublishingService(pm, data_dir=tmp, project_context=context)
            workflow = ContentWorkflowService(feedback, context, publishing)

            result = workflow.approve_and_schedule(
                record["review_id"],
                feedback="great hook",
                scheduled_date="2026-06-01T09:00:00",
                explicit_tags="campaign",
            )

            self.assertTrue(result["success"])
            self.assertTrue(result["scheduling"]["scheduled"])
            self.assertEqual(result["scheduling"]["provider"], "late")
            self.assertEqual(provider.requests[0].account_id, "late_account-123")
            self.assertEqual(provider.requests[0].platform, "twitter")
            self.assertEqual(provider.requests[0].scheduled_at.isoformat(), "2026-06-01T09:00:00")

            loaded = feedback._load_review_record(record["review_id"])
            self.assertEqual(loaded["status"], "scheduled")
            self.assertEqual(loaded["published_via"], "late")
            self.assertEqual(
                loaded["feedback_history"][0]["learning_tags"], ["campaign", "great_hook"]
            )

    def test_project_publishing_service_fails_without_enabled_account(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(data_dir=tmp)
            project = pm.create_project("No Account Project", platforms=["twitter"])
            pm.save_provider_mapping(project.project_id, {"twitter": "typefully"})

            from services import ProjectContextService, ProjectPublishingService

            provider = FakeProvider("typefully", configured=True)

            class StubPublishingService(ProjectPublishingService):
                def build_manager(self, project_id=None):
                    manager = PublishingManager()
                    manager.register_provider(provider, primary=True)
                    return manager

            publishing = StubPublishingService(
                pm,
                data_dir=tmp,
                project_context=ProjectContextService(pm),
            )

            attempt = publishing.publish_record(
                {
                    "review_id": "review-no-account",
                    "project_id": project.project_id,
                    "post_data": {
                        "project_id": project.project_id,
                        "content": "Do not publish without an account.",
                        "platform": "twitter",
                    },
                },
                provider_name="typefully",
                platform="twitter",
            )

            self.assertFalse(attempt.result.success)
            self.assertEqual(attempt.result.error_code, PublishErrorCode.ACCOUNT_NOT_FOUND)
            self.assertIsNone(attempt.account_id)
            self.assertEqual(provider.requests, [])

    def test_job_queue_persists_and_transitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(data_dir=tmp)
            project = pm.create_project("Job Project", platforms=["twitter"])

            from services import JobQueueService

            queue = JobQueueService(pm.store)
            job = queue.enqueue(
                "sync_analytics",
                project_id=project.project_id,
                payload={"project_id": project.project_id},
            )

            self.assertTrue(job["job_id"].startswith("job_"))
            self.assertEqual(job["status"], "queued")

            claimed = queue.claim_next()
            self.assertEqual(claimed["job_id"], job["job_id"])
            self.assertEqual(claimed["status"], "running")
            self.assertEqual(claimed["attempts"], 1)

            completed = queue.complete(job["job_id"], result={"ok": True})
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["result"], {"ok": True})
            self.assertEqual(queue.stats()["completed"], 1)

    def test_job_runner_generates_content_into_review_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(data_dir=tmp)
            project = pm.create_project("Runner Project", platforms=["twitter"])
            feedback = FeedbackManager(data_dir=tmp)

            from services import JobQueueService, JobRunner

            queue = JobQueueService(pm.store)
            job = queue.enqueue(
                "generate_content",
                project_id=project.project_id,
                payload={
                    "project_id": project.project_id,
                    "count": 2,
                    "platform": "twitter",
                    "content_type": "thread",
                },
            )
            runner = JobRunner(
                queue,
                generator=FakeGenerator(),
                feedback_manager=feedback,
                project_manager=pm,
            )

            result = runner.run_once()

            self.assertTrue(result["success"])
            completed = queue.get(job["job_id"])
            self.assertEqual(completed["status"], "completed")
            self.assertEqual(completed["result"]["count"], 2)

            reviews = feedback._load_reviews()
            self.assertEqual(len(reviews), 2)
            for review in reviews.values():
                self.assertEqual(review["project_id"], project.project_id)
                self.assertEqual(review["post_data"]["content_type"], "thread")

    def test_job_runner_binds_generator_to_job_project(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(data_dir=tmp)
            project = pm.create_project("Runner Scoped Project", platforms=["twitter"])
            feedback = FeedbackManager(data_dir=tmp)

            from services import JobQueueService, JobRunner

            class ProjectAwareGenerator:
                def __init__(self):
                    self.project = None
                    self.seen_projects = []

                def generate_batch(self, count=1, platforms=None):
                    self.seen_projects.append(self.project.project_id)
                    return [
                        {
                            "content": "Generated with project context",
                            "platform": platforms[0] if platforms else "twitter",
                        }
                    ]

            generator = ProjectAwareGenerator()
            queue = JobQueueService(pm.store)
            queue.enqueue(
                "generate_content",
                project_id=project.project_id,
                payload={"project_id": project.project_id, "count": 1, "platform": "twitter"},
            )
            runner = JobRunner(
                queue,
                generator=generator,
                feedback_manager=feedback,
                project_manager=pm,
            )

            result = runner.run_once()

            self.assertTrue(result["success"])
            self.assertEqual(generator.seen_projects, [project.project_id])
            self.assertIsNone(generator.project)

    def test_job_runner_publishes_scheduled_review(self):
        with tempfile.TemporaryDirectory() as tmp:
            pm = ProjectManager(data_dir=tmp)
            project = pm.create_project("Scheduled Publish Project", platforms=["twitter"])
            pm.save_provider_mapping(project.project_id, {"twitter": "late"})
            settings = pm.get_project_settings(project.project_id)
            settings["social_profiles"] = [
                {
                    "account_id": "account-789",
                    "platform": "twitter",
                    "provider": "late",
                    "enabled": True,
                }
            ]
            pm.save_project_settings(project.project_id, settings)

            feedback = FeedbackManager(data_dir=str(pm.get_project_data_dir(project.project_id)))
            review = feedback.add_for_review(
                {
                    "content": "Publish this when due.",
                    "platform": "twitter",
                },
                channel="TEST",
            )

            scheduled = pm.store.normalize_scheduled_record(
                {
                    "review_id": review["review_id"],
                    "project_id": project.project_id,
                    "post_data": review["post_data"],
                    "scheduled_at": "2026-05-29T09:00:00",
                }
            )
            pm.store.save_scheduled_record(scheduled)

            from services import (
                ContentWorkflowService,
                JobQueueService,
                JobRunner,
                ProjectContextService,
                ProjectPublishingService,
            )

            provider = FakeProvider("late", configured=True)

            class StubPublishingService(ProjectPublishingService):
                def build_manager(self, project_id=None):
                    manager = PublishingManager()
                    manager.register_provider(provider, primary=True)
                    return manager

            queue = JobQueueService(pm.store)
            job = queue.enqueue(
                "publish_scheduled_post",
                project_id=project.project_id,
                payload={
                    "post_id": scheduled["post_id"],
                    "review_id": review["review_id"],
                    "platform": "twitter",
                },
            )
            context = ProjectContextService(pm)
            publishing = StubPublishingService(pm, data_dir=tmp, project_context=context)
            workflow = ContentWorkflowService(feedback, context, publishing)
            runner = JobRunner(
                queue,
                project_manager=pm,
                content_workflow=workflow,
                publishing_service=publishing,
            )

            result = runner.run_once(kinds=["publish_scheduled_post"])

            self.assertTrue(result["success"])
            self.assertEqual(queue.get(job["job_id"])["status"], "completed")
            self.assertFalse(provider.requests[0].as_draft)
            self.assertTrue(provider.requests[0].auto_publish)
            self.assertEqual(provider.requests[0].account_id, "late_account-789")

            published_review = feedback._load_review_record(review["review_id"])
            self.assertEqual(published_review["status"], "published")

            published_scheduled = pm.store.get_scheduled_record(scheduled["post_id"])
            self.assertEqual(published_scheduled["status"], "published")
            self.assertEqual(published_scheduled["published_via"], "late")

    def test_dashboard_access_policy_requires_token_off_localhost(self):
        import unittest.mock

        from services.access_control import DashboardAccessPolicy, is_loopback_host

        self.assertTrue(is_loopback_host("127.0.0.1"))
        self.assertTrue(is_loopback_host("localhost:8000"))
        self.assertTrue(is_loopback_host("[::1]"))
        self.assertFalse(is_loopback_host("0.0.0.0"))

        DashboardAccessPolicy(
            host="127.0.0.1",
            allow_unauthenticated_local=True,
        ).validate_startup()

        # LiteLLM calls dotenv.load_dotenv() at import, so the env token
        # is always present. Patch to test the no-token safety check.
        with unittest.mock.patch.dict(
            "os.environ",
            {
                k: v
                for k, v in os.environ.items()
                if k not in ("DRAPER_DASHBOARD_TOKEN", "DASHBOARD_API_TOKEN")
            },
            clear=True,
        ):
            with self.assertRaises(RuntimeError):
                DashboardAccessPolicy(host="127.0.0.1").validate_startup()

            with self.assertRaises(RuntimeError):
                DashboardAccessPolicy(host="0.0.0.0").validate_startup()

            with self.assertRaises(RuntimeError):
                DashboardAccessPolicy(host="0.0.0.0", token="short").validate_startup()

        policy = DashboardAccessPolicy(host="0.0.0.0", token="a" * 32)
        policy.validate_startup()
        self.assertTrue(policy.is_valid_token("a" * 32))
        self.assertFalse(policy.is_valid_token("wrong"))

        bearer_headers = {"Authorization": "Bearer " + "a" * 32}
        self.assertEqual(policy.extract_token(bearer_headers, {}), "a" * 32)
        self.assertEqual(policy.extract_token({"X-API-Key": "a" * 32}, {}), "a" * 32)


if __name__ == "__main__":
    unittest.main()
