"""Job execution service for orchestration work."""

import asyncio
from typing import Any, Dict, List, Optional

from .job_queue import JobQueueService
from .generator_scoping import scoped_generator_for_project
from .observability import get_logger
from .retry_policy import categorize_exception


logger = get_logger(__name__)


class JobRunner:
    """Executes queued orchestration jobs with injected app dependencies."""

    def __init__(
        self,
        queue: JobQueueService,
        generator=None,
        feedback_manager=None,
        analytics=None,
        project_manager=None,
        content_workflow=None,
        publishing_service=None,
        review_workflow=None,
        nostr_signing=None,
    ):
        self.queue = queue
        self.generator = generator
        self.feedback_manager = feedback_manager
        self.analytics = analytics
        self.project_manager = project_manager
        self.content_workflow = content_workflow
        self.publishing_service = publishing_service
        self.review_workflow = review_workflow
        self.nostr_signing = nostr_signing

    def run_once(self, kinds: Optional[List[str]] = None) -> Optional[Dict[str, Any]]:
        job = self.queue.claim_next(kinds=kinds)
        if not job:
            return None

        from services.observability import set_job_id

        job_token = set_job_id(job.get("job_id", "-"))
        logger.info("job.claimed", extra={"job_id": job.get("job_id"), "job_kind": job.get("kind")})
        try:
            result = self.execute(job)
            completed = self.queue.complete(job["job_id"], result=result)
            logger.info(
                "job.completed",
                extra={"job_id": job.get("job_id"), "job_kind": job.get("kind")},
            )
            return {"success": True, "job": completed}
        except Exception as exc:
            category = categorize_exception(exc)
            failed = self.queue.fail_with_category(
                job["job_id"], error=str(exc), category=category,
            )
            logger.exception(
                "job.failed",
                extra={
                    "job_id": job.get("job_id"),
                    "job_kind": job.get("kind"),
                    "failure_category": category.value,
                },
            )
            return {
                "success": False,
                "job": failed,
                "error": str(exc),
                "failure_category": category.value,
            }
        finally:
            set_job_id("-", job_token)

    def execute(self, job: Dict[str, Any]) -> Dict[str, Any]:
        kind = job.get("kind")
        if kind == "generate_content":
            return self._generate_content(job)
        if kind == "fix_content":
            return self._fix_content(job)
        if kind == "sync_analytics":
            return self._sync_analytics(job)
        if kind == "sync_provider_analytics":
            return self._sync_provider_analytics(job)
        if kind == "publish_scheduled_post":
            return self._publish_scheduled_post(job)
        if kind == "nostr_publish_request":
            return self._nostr_publish_request(job)
        if kind == "generate_visual":
            return self._generate_visual(job)
        if kind == "generate_carousel":
            return self._generate_carousel(job)
        if kind == "mine_ideas":
            return self._mine_ideas(job)
        raise ValueError(f"Unknown job kind: {kind}")

    def _generate_content(self, job: Dict[str, Any]) -> Dict[str, Any]:
        if not self.generator:
            raise RuntimeError("Content generator is not configured")
        if not self.feedback_manager:
            raise RuntimeError("Feedback manager is not configured")
        if not self.project_manager:
            raise RuntimeError("Project manager is not configured")

        payload = job.get("payload") or {}
        project_id = payload.get("project_id") or job.get("project_id")
        if not project_id or not self.project_manager.get_project(project_id):
            raise ValueError("project_id is required")

        count = int(payload.get("count", 5))
        if count < 1 or count > 25:
            raise ValueError("count must be between 1 and 25")

        platform = payload.get("platform")
        platforms = [platform] if platform else None
        project = self.project_manager.get_project(project_id)
        generator = scoped_generator_for_project(self.generator, project)
        batch_result = generator.generate_batch(count=count, platforms=platforms)
        posts = batch_result.get("posts", []) if isinstance(batch_result, dict) else batch_result

        review_ids = []
        for post in posts:
            post["project_id"] = project_id
            if payload.get("content_type"):
                post["content_type"] = payload["content_type"]
            record = self.feedback_manager.post_content_for_review(
                post,
                payload.get("channel", "JOB"),
            )
            review_ids.append(record.get("review_id"))

        return {"count": len(posts), "review_ids": review_ids}

    def _sync_analytics(self, job: Dict[str, Any]) -> Dict[str, Any]:
        if not self.analytics:
            raise RuntimeError("Analytics service is not configured")
        result = self.analytics.sync_all_platforms()
        return result if isinstance(result, dict) else {"result": result}

    def _nostr_publish_request(self, job: Dict[str, Any]) -> Dict[str, Any]:
        """Broadcast a signed Nostr event whose scheduled time has arrived."""
        signing = self.nostr_signing or (
            getattr(self.publishing_service, "nostr_signing", None)
            if self.publishing_service
            else None
        )
        if signing is None:
            raise RuntimeError("Nostr signing service is not configured")
        payload = job.get("payload") or {}
        request_id = payload.get("request_id")
        if not request_id:
            raise ValueError("request_id is required")

        result = signing.publish_request(request_id)
        if not result.get("success"):
            raise RuntimeError(result.get("error") or "Nostr publish failed")
        return {
            "success": True,
            "request_id": request_id,
            "event_id": result.get("event_id"),
            "published_to": result.get("published_to", 0),
        }

    def _publish_scheduled_post(self, job: Dict[str, Any]) -> Dict[str, Any]:
        payload = job.get("payload") or {}
        post_id = payload.get("post_id")
        if not post_id:
            raise ValueError("post_id is required")

        scheduled = self.queue.store.get_scheduled_record(post_id)
        if not scheduled:
            raise ValueError(f"Scheduled post not found: {post_id}")
        if scheduled.get("status") in {"published", "cancelled", "deleted"}:
            return {"post_id": post_id, "skipped": True, "status": scheduled.get("status")}

        review_id = payload.get("review_id") or scheduled.get("review_id")
        platform = payload.get("platform") or scheduled.get("post_data", {}).get("platform")
        provider_name = payload.get("provider")

        if review_id:
            if not self.content_workflow:
                raise RuntimeError("Content workflow service is not configured")
            result = self.content_workflow.publish_review(
                review_id,
                provider_name=provider_name,
                platform=platform,
                as_draft=False,
                auto_publish=True,
            )
            if not result.get("success"):
                return self._mark_scheduled_publish_failed(
                    scheduled,
                    result.get("error", "Scheduled publish failed"),
                )
            return self._mark_scheduled_published(scheduled, result)

        if not self.publishing_service:
            raise RuntimeError("Publishing service is not configured")

        record = {
            "project_id": scheduled.get("project_id"),
            "post_data": scheduled.get("post_data", {}),
        }
        attempt = self.publishing_service.publish_record(
            record,
            provider_name=provider_name,
            platform=platform,
            as_draft=False,
            auto_publish=True,
        )
        result = attempt.result
        if not result.success:
            return self._mark_scheduled_publish_failed(
                scheduled,
                result.error or "Scheduled publish failed",
                provider=result.provider,
            )
        return self._mark_scheduled_published(
            scheduled,
            {
                "provider": result.provider,
                "draft_id": result.draft_id,
                "url": result.url,
            },
        )

    def _mark_scheduled_published(self, scheduled: Dict[str, Any], result: Dict[str, Any]) -> Dict[str, Any]:
        from datetime import datetime, timezone

        scheduled["status"] = "published"
        scheduled["published_at"] = datetime.now(timezone.utc).isoformat()
        scheduled["published_via"] = result.get("provider")
        if result.get("draft_id"):
            scheduled["draft_id"] = result["draft_id"]
        if result.get("url"):
            scheduled["draft_url"] = result["url"]
        scheduled.pop("publishing_error", None)
        self.queue.store.save_scheduled_record(scheduled)
        return {
            "post_id": scheduled["post_id"],
            "status": "published",
            "provider": result.get("provider"),
            "draft_id": result.get("draft_id"),
            "url": result.get("url"),
        }

    def _mark_scheduled_publish_failed(
        self,
        scheduled: Dict[str, Any],
        error: str,
        provider: str = None,
    ) -> Dict[str, Any]:
        scheduled["status"] = "publish_failed"
        scheduled["publishing_error"] = error
        if provider:
            scheduled["published_via"] = provider
        self.queue.store.save_scheduled_record(scheduled)
        raise RuntimeError(error)

    def _fix_content(self, job: Dict[str, Any]) -> Dict[str, Any]:
        if not self.review_workflow:
            raise RuntimeError("Review workflow service is not configured")

        payload = job.get("payload") or {}
        review_id = payload.get("review_id")
        if not review_id:
            raise ValueError("review_id is required")

        feedback = payload.get("feedback", "")
        project_id = payload.get("project_id") or job.get("project_id")

        record = self.review_workflow.feedback_manager._load_review_record(review_id)
        if record is None:
            logger.info(
                "job.fix_content.skipped_review_deleted",
                extra={"job_id": job.get("job_id"), "review_id": review_id},
            )
            return {
                "review_id": review_id,
                "skipped": True,
                "reason": "review_deleted",
            }
        post_data = record.get("post_data") or {}

        from learning.auto_fix import AutoFixEngine, AutoFixSkipped

        try:
            fix = asyncio.run(
                AutoFixEngine().fix_content(
                    post_data=post_data,
                    feedback=feedback,
                    project_id=project_id,
                )
            )
        except AutoFixSkipped as exc:
            # The engine refused to honor concrete feedback without an LLM.
            # Do NOT fabricate a fix: leave the review in needs_work and
            # record the skip so auto_fix_status doesn't dangle on "queued".
            logger.warning(
                "job.fix_content.skipped_concrete_feedback",
                extra={
                    "job_id": job.get("job_id"),
                    "review_id": review_id,
                    "reason": exc.reason,
                },
            )
            self._abandon_auto_fix(review_id, reason=exc.reason, error=str(exc))
            return {
                "review_id": review_id,
                "skipped": True,
                "reason": exc.reason,
                "detail": str(exc),
            }

        if not isinstance(fix, dict) or fix.get("skipped"):
            # Defensive: engine returned a structured skip instead of raising.
            reason = (
                fix.get("reason", "unknown")
                if isinstance(fix, dict)
                else "invalid_fix_result"
            )
            logger.warning(
                "job.fix_content.skipped_no_fix",
                extra={
                    "job_id": job.get("job_id"),
                    "review_id": review_id,
                    "reason": reason,
                },
            )
            self._abandon_auto_fix(review_id, reason=reason)
            return {
                "review_id": review_id,
                "skipped": True,
                "reason": reason,
            }

        from services.review_workflow_service import INVALID_TRANSITION, ReviewTransitionError

        try:
            self.review_workflow.complete_auto_fix(review_id, fix=fix, feedback=feedback)
        except ReviewTransitionError as exc:
            if exc.code == INVALID_TRANSITION:
                logger.info(
                    "job.fix_content.skipped_user_action_precedence",
                    extra={
                        "job_id": job.get("job_id"),
                        "review_id": review_id,
                        "current_status": exc.from_status,
                    },
                )
                return {
                    "review_id": review_id,
                    "skipped": True,
                    "reason": "user_action_precedence",
                    "current_status": exc.from_status,
                }
            raise

        return {
            "review_id": review_id,
            "status": "pending_review",
            "explanation": fix.get("explanation", ""),
        }

    def _abandon_auto_fix(self, review_id: str, reason: str, error: str = "") -> None:
        """Record an auto-fix skip on the review without changing its status.

        The review stays in needs_work; ``auto_fix_status`` moves from
        ``queued`` to ``skipped`` with the reason recorded. Never invents a
        successful fix.
        """
        try:
            self.review_workflow.fail_auto_fix(review_id, reason=reason, error=error)
        except Exception as exc:
            logger.warning(
                "job.fix_content.fail_auto_fix_error",
                extra={"review_id": review_id, "error": str(exc)},
            )

    def _generate_visual(self, job: Dict[str, Any]) -> Dict[str, Any]:
        payload = job.get("payload") or {}
        prompt = payload.get("prompt")
        if not prompt:
            raise ValueError("prompt is required")
        platform = payload.get("platform", "instagram")
        style = payload.get("style", "minimal")

        from integrations.zai_image import ZAIImageGenerator

        zai = ZAIImageGenerator()
        if not zai.is_configured():
            raise ValueError("ZAI image generation not configured")
        result = asyncio.run(
            zai.generate_social_image(
                topic=prompt, platform=platform, style=style,
            )
        )
        return {
            "success": True,
            "image_url": result.get("url"),
            "provider": "zai",
        }

    def _generate_carousel(self, job: Dict[str, Any]) -> Dict[str, Any]:
        payload = job.get("payload") or {}
        content = payload.get("content")
        if not content:
            raise ValueError("content is required")
        title = payload.get("title", "")
        num_cards = int(payload.get("num_cards", 5))
        platform = payload.get("platform", "linkedin")

        from integrations.gamma_api import GammaAPIClient

        gamma = GammaAPIClient()
        if not gamma.is_configured():
            raise ValueError("Gamma carousel generation not configured")
        result = asyncio.run(
            gamma.generate_carousel(
                content=content, title=title, num_cards=num_cards, platform=platform,
            )
        )
        return {
            "success": True,
            "carousel_id": result.get("generation_id"),
            "cards": int(result.get("cards", num_cards)),
            "provider": "gamma",
            "gamma_url": result.get("gamma_url"),
        }

    def _mine_ideas(self, job: Dict[str, Any]) -> Dict[str, Any]:
        if not self.project_manager:
            raise RuntimeError("Project manager is not configured")
        payload = job.get("payload") or {}
        project_id = payload.get("project_id") or job.get("project_id")
        if not project_id or not self.project_manager.get_project(project_id):
            raise ValueError("project_id is required")

        source_material_id = payload.get("source_material_id")
        max_ideas = int(payload.get("max_ideas", 5))

        from services.idea_lab import IdeaLabService

        idea_lab = IdeaLabService(self.queue.store)
        ideas = idea_lab.mine_ideas(
            project_id=project_id,
            source_material_id=source_material_id,
            max_ideas=max_ideas,
        )
        idea_ids = [i.get("idea_id") for i in (ideas or []) if i.get("idea_id")]
        return {"success": True, "idea_ids": idea_ids}

    def _sync_provider_analytics(self, job: Dict[str, Any]) -> Dict[str, Any]:
        if not self.analytics:
            raise RuntimeError("Analytics service is not configured")
        result = self.analytics.sync_all_platforms()
        if isinstance(result, dict):
            return {
                "success": True,
                "synced": list(
                    result.get("synced_platforms") or result.get("synced") or []
                ),
            }
        return {"success": True, "synced": []}
