"""Content review workflow services."""

from datetime import datetime, timezone
from typing import Dict, Optional

from data.models import FeedbackRecord

from .project_context import ProjectContextService
from .publishing_service import ProjectPublishingService


class ContentWorkflowService:
    """Coordinates review state transitions with project-safe publishing."""

    def __init__(
        self,
        feedback_manager,
        project_context: ProjectContextService,
        publishing_service: ProjectPublishingService,
    ):
        self.feedback_manager = feedback_manager
        self.project_context = project_context
        self.publishing_service = publishing_service

    def approve_and_schedule(
        self,
        review_id: str,
        feedback: str = "",
        scheduled_date: str = None,
        explicit_tags: str = "",
        fallback_platform: str = "twitter",
    ) -> Dict:
        """Approve review content and schedule it through the mapped provider."""
        record = self.feedback_manager._load_review_record(review_id)
        if not record:
            return {"success": False, "error": "Record not found"}

        original_status = record.get("status", "pending_review")
        try:
            attempt = self.publishing_service.publish_record(
                record,
                fallback_platform=fallback_platform,
                scheduled_at=scheduled_date,
                schedule_next_slot=not bool(scheduled_date),
            )
            result = attempt.result

            if result.success:
                record["status"] = "scheduled"
                record["published_via"] = result.provider
                record["scheduled_at"] = (
                    attempt.scheduled_at.isoformat()
                    if attempt.scheduled_at
                    else datetime.now(timezone.utc).isoformat()
                )
                if result.draft_id:
                    record["draft_id"] = result.draft_id
                if result.url:
                    record["draft_url"] = result.url
                record.pop("scheduling_error", None)

                learning_tags = merge_tags(
                    explicit_tags,
                    extract_positive_tags(feedback) if feedback else [],
                )
                self._append_feedback_history(
                    record,
                    from_status=original_status,
                    to_status="scheduled",
                    feedback=feedback or "Approved and scheduled",
                    learning_tags=learning_tags,
                )
                self.feedback_manager._save_review_record(review_id, record)
                self._extract_patterns(record, "approved", attempt.project_id, feedback, learning_tags)
                return {
                    "success": True,
                    "review_id": review_id,
                    "status": record["status"],
                    "record": record,
                    "scheduling": {
                        "scheduled": True,
                        "provider": result.provider,
                        "draft_url": result.url,
                        "draft_id": result.draft_id,
                    },
                }

            record["status"] = original_status
            record["scheduling_error"] = result.error
            self.feedback_manager._save_review_record(review_id, record)
            return {
                "success": True,
                "review_id": review_id,
                "status": record["status"],
                "record": record,
                "scheduling": {
                    "scheduled": False,
                    "error": result.error,
                    "provider": result.provider,
                },
            }
        except Exception as exc:
            record["status"] = original_status
            record["scheduling_error"] = str(exc)
            self.feedback_manager._save_review_record(review_id, record)
            return {
                "success": True,
                "review_id": review_id,
                "status": record["status"],
                "record": record,
                "scheduling": {"scheduled": False, "error": str(exc)},
            }

    def publish_review(
        self,
        review_id: str,
        provider_name: str = None,
        platform: str = None,
        as_draft: bool = True,
        auto_publish: bool = False,
    ) -> Dict:
        """Publish a review immediately as a provider draft/post."""
        record = self.feedback_manager._load_review_record(review_id)
        if not record:
            return {"success": False, "error": "Record not found"}

        content = record.get("post_data", {}).get("content", "")
        if not content:
            return {"success": False, "error": "No content to publish"}

        try:
            attempt = self.publishing_service.publish_record(
                record,
                provider_name=provider_name,
                platform=platform,
                as_draft=as_draft,
                auto_publish=auto_publish,
            )
            result = attempt.result
            if not result.success:
                return {
                    "success": False,
                    "error": result.error,
                    "provider": result.provider,
                }

            record["published_via"] = result.provider
            record["status"] = "published"
            record["published_at"] = datetime.now(timezone.utc).isoformat()
            if result.draft_id:
                record["draft_id"] = result.draft_id
            if result.url:
                record["draft_url"] = result.url
            self.feedback_manager._save_review_record(review_id, record)

            return {
                "success": True,
                "review_id": review_id,
                "provider": result.provider,
                "draft_id": result.draft_id,
                "url": result.url,
            }
        except Exception as exc:
            return {"success": False, "error": f"Publishing failed: {str(exc)}"}

    def _append_feedback_history(
        self,
        record: Dict,
        from_status: str,
        to_status: str,
        feedback: str,
        learning_tags: Optional[list] = None,
    ):
        feedback_record = FeedbackRecord(
            timestamp=datetime.now(timezone.utc).isoformat(),
            from_status=from_status,
            to_status=to_status,
            feedback=feedback,
            learning_tags=learning_tags or [],
        )
        history = record.get("feedback_history") or []
        history.append(feedback_record.to_dict())
        record["feedback_history"] = history

    @staticmethod
    def _extract_patterns(record: Dict, outcome: str, project_id: str, feedback: str, tags: list):
        try:
            from learning.pattern_extractor import PatternExtractor

            PatternExtractor().extract_and_save_patterns(
                record["post_data"],
                outcome,
                project_id,
                feedback=feedback,
                tags=tags,
            )
        except Exception as exc:
            print(f"Warning: Could not extract learning patterns: {exc}")


def extract_negative_tags(feedback: str) -> list:
    """Extract learning tags from feedback."""
    tags = []
    feedback_lower = feedback.lower()
    patterns = {
        "weak_hook": ["hook", "opening", "intro", "weak start", "boring opening"],
        "too_generic": ["generic", "vague", "not specific", "could be anyone", "lacks detail"],
        "too_long": ["too long", "verbose", "wordy", "cut down", "shorter"],
        "ai_sounding": ["ai", "chatgpt", "robotic", "unnatural", "sounds generated"],
        "no_value": ["no value", "what's the point", "so what", "lacks insight"],
        "formatting": ["formatting", "structure", "hard to read", "layout"],
        "tone_off": ["tone", "voice", "doesn't sound like us", "wrong voice"],
        "unclear": ["unclear", "confusing", "clarify", "elaborate", "explain"],
    }
    for tag, keywords in patterns.items():
        if any(keyword in feedback_lower for keyword in keywords):
            tags.append(tag)
    return tags


def extract_positive_tags(feedback: str) -> list:
    """Extract positive learning tags from feedback."""
    tags = []
    feedback_lower = feedback.lower()
    patterns = {
        "great_hook": ["great hook", "strong hook", "good opening", "love the hook", "nice hook"],
        "good_length": ["good length", "right length", "well sized", "perfect length"],
        "on_brand": ["on brand", "brand voice", "sounds like us", "authentic"],
        "engaging": ["engaging", "compelling", "captivating", "interesting"],
        "valuable": ["valuable", "insightful", "useful", "great insight"],
        "well_structured": ["well structured", "good structure", "well organized", "flows well"],
        "clear_cta": ["clear cta", "good cta", "call to action", "strong ending"],
    }
    for tag, keywords in patterns.items():
        if any(keyword in feedback_lower for keyword in keywords):
            tags.append(tag)
    return tags


def merge_tags(explicit_tags_str: str, auto_tags: list) -> list:
    """Merge explicit UI tags with auto-extracted tags, deduplicating."""
    explicit = [t.strip() for t in explicit_tags_str.split(",") if t.strip()] if explicit_tags_str else []
    return list(dict.fromkeys(explicit + auto_tags))
