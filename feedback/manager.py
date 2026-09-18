#!/usr/bin/env python3
"""
Content Feedback Manager

Handles the review workflow: pending → approved → scheduled
"""

import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from data.sqlite_store import SQLiteStore, new_id


class FeedbackManager:
    """Manages content review workflow"""

    def __init__(self, data_dir: Optional[str] = None):
        if data_dir:
            self.data_dir = Path(data_dir)
        else:
            self.data_dir = Path(__file__).parent.parent / "data"

        self.data_dir.mkdir(parents=True, exist_ok=True)
        # Kept for path compatibility only — SQLiteStore is now the backing store
        self.reviews_file = self.data_dir / "reviews.json"
        if self.reviews_file.exists():
            warnings.warn(
                "reviews.json is deprecated; SQLiteStore is now the backing store. "
                "This file can be safely deleted.",
                DeprecationWarning,
                stacklevel=2,
            )
        self.project_id = None
        store_data_dir = self.data_dir
        if self.data_dir.parent.name == "projects":
            self.project_id = self.data_dir.name
            store_data_dir = self.data_dir.parent.parent
        self.store = SQLiteStore(store_data_dir)

    def _load_reviews(self) -> Dict:
        """Load all reviews from file"""
        records = self.store.list_review_records(project_id=self.project_id)
        return {record["review_id"]: record for record in records}

    def _save_reviews(self, reviews: Dict):
        """Save reviews to file"""
        for review_id, record in reviews.items():
            record = dict(record)
            record.setdefault("review_id", review_id)
            if self.project_id:
                record["project_id"] = self.project_id
                record.setdefault("post_data", {}).setdefault("project_id", self.project_id)
            self.store.save_review_record(record)

    def add_for_review(self, post_data: Dict, channel: str = "CLI") -> Dict:
        """
        Add generated content for review

        Args:
            post_data: Generated content from ContentGenerator
            channel: Source channel (CLI, API, etc.)

        Returns:
            Review record
        """
        review_id = post_data.get("review_id") or new_id("review_")
        post_data = dict(post_data)
        if self.project_id:
            post_data.setdefault("project_id", self.project_id)

        record = {
            "review_id": review_id,
            "project_id": post_data.get("project_id"),
            "post_data": post_data,
            "channel": channel,
            "status": "pending_review",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "feedback": None,
        }

        self.store.save_review_record(record)

        return record

    def get_pending_reviews(self, limit: int = 100) -> List[Dict]:
        """Get content pending review, plus approved items whose scheduling failed.

        Approved records carrying a non-empty scheduling_error never reached
        the scheduler; they stay visible here so they can be retried instead
        of silently disappearing from the Pipeline. Successfully scheduled
        items (no scheduling_error) are excluded.
        """
        reviews = self._load_reviews()

        def _needs_attention(r: Dict) -> bool:
            if r.get("status") == "pending_review":
                return True
            return r.get("status") == "approved" and bool(
                str(r.get("scheduling_error") or "").strip()
            )

        pending = [r for r in reviews.values() if _needs_attention(r)]

        # Sort by created_at descending
        pending.sort(key=lambda x: x.get("created_at", ""), reverse=True)

        return pending[:limit]

    def get_approved(self) -> List[Dict]:
        """Get approved content waiting to be scheduled"""
        reviews = self._load_reviews()

        return [r for r in reviews.values() if r.get("status") == "approved"]

    def get_scheduled(self) -> List[Dict]:
        """Get content that has been scheduled"""
        reviews = self._load_reviews()

        return [r for r in reviews.values() if r.get("status") == "scheduled"]

    def approve(self, review_id: str, feedback: str = "") -> bool:
        """
        Approve content for scheduling

        Args:
            review_id: Review ID
            feedback: Optional feedback text

        Returns:
            True if successful
        """
        reviews = self._load_reviews()

        if review_id not in reviews:
            return False

        reviews[review_id]["status"] = "approved"
        reviews[review_id]["approved_at"] = datetime.now(timezone.utc).isoformat()
        reviews[review_id]["feedback"] = feedback

        self._save_reviews(reviews)
        return True

    def reject(self, review_id: str, feedback: str = "") -> bool:
        """
        Reject content

        Args:
            review_id: Review ID
            feedback: Optional feedback text

        Returns:
            True if successful
        """
        reviews = self._load_reviews()

        if review_id not in reviews:
            return False

        reviews[review_id]["status"] = "rejected"
        reviews[review_id]["rejected_at"] = datetime.now(timezone.utc).isoformat()
        reviews[review_id]["feedback"] = feedback

        self._save_reviews(reviews)
        return True

    def mark_scheduled(self, review_id: str, schedule_data: Dict = None) -> bool:
        """
        Mark content as scheduled

        Args:
            review_id: Review ID
            schedule_data: Optional data from scheduling service

        Returns:
            True if successful
        """
        reviews = self._load_reviews()

        if review_id not in reviews:
            return False

        reviews[review_id]["status"] = "scheduled"
        reviews[review_id]["scheduled_at"] = datetime.now(timezone.utc).isoformat()
        reviews[review_id].pop("scheduling_error", None)
        if schedule_data:
            reviews[review_id]["schedule_data"] = schedule_data

        self._save_reviews(reviews)
        return True

    def mark_published(self, review_id: str, extras: Optional[Dict] = None) -> bool:
        """
        Mark content as published (public API for external publishers).

        Used by providers that publish outside the review workflow (e.g. the
        Nostr sign-now-publish-later scheduler) to mirror their state onto
        the review record without re-entering workflow transitions.

        Args:
            review_id: Review ID
            extras: Optional fields merged onto the record
                    (post_id, draft_url, published_via, ...)

        Returns:
            True if successful
        """
        record = self._load_review_record(review_id)
        if not record:
            return False

        record["status"] = "published"
        record["published_at"] = datetime.now(timezone.utc).isoformat()
        record.pop("scheduling_error", None)
        for key, value in (extras or {}).items():
            if value is not None:
                record[key] = value
        self._save_review_record(review_id, record)
        return True

    def get_stats(self) -> Dict:
        """Get review statistics"""
        reviews = self._load_reviews()

        stats = {
            "total": len(reviews),
            "pending": 0,
            "approved": 0,
            "rejected": 0,
            "scheduled": 0,
            "needs_work": 0,
            "declined": 0,
            "by_platform": {},
        }

        for r in reviews.values():
            status = r.get("status", "pending_review")
            if status == "pending_review":
                stats["pending"] += 1
            elif status == "approved":
                stats["approved"] += 1
            elif status == "rejected":
                stats["rejected"] += 1
            elif status == "scheduled":
                stats["scheduled"] += 1
            elif status == "needs_work":
                stats["needs_work"] += 1
            elif status == "declined":
                stats["declined"] += 1

            # Count by platform
            platform = r.get("post_data", {}).get("platform", "unknown")
            if platform not in stats["by_platform"]:
                stats["by_platform"][platform] = {
                    "pending": 0,
                    "approved": 0,
                    "scheduled": 0,
                    "needs_work": 0,
                    "declined": 0,
                }
            if status == "pending_review":
                stats["by_platform"][platform]["pending"] += 1
            elif status == "approved":
                stats["by_platform"][platform]["approved"] += 1
            elif status == "scheduled":
                stats["by_platform"][platform]["scheduled"] += 1
            elif status == "needs_work":
                stats["by_platform"][platform]["needs_work"] += 1
            elif status == "declined":
                stats["by_platform"][platform]["declined"] += 1

        return stats

    # Backwards compatibility methods
    def post_content_for_review(self, post_data: Dict, channel: str = "CLI") -> Dict:
        """Alias for add_for_review"""
        return self.add_for_review(post_data, channel)

    def get_scheduled_posts(self) -> List[Dict]:
        """Alias for get_approved (waiting to be scheduled)"""
        return self.get_approved()

    def process_feedback(self, review_id: str, action: str, feedback: str = "") -> bool:
        """Process feedback action (approve/reject/schedule)"""
        if action == "approve":
            return self.approve(review_id, feedback)
        elif action == "reject":
            return self.reject(review_id, feedback)
        elif action == "schedule":
            return self.mark_scheduled(review_id, {"feedback": feedback})
        return False

    def _load_review_record(self, review_id: str) -> Optional[Dict]:
        """Load a single review record"""
        record = self.store.get_review_record(review_id)
        if self.project_id and record and record.get("project_id") != self.project_id:
            return None
        return record

    def _save_review_record(self, review_id: str, record: Dict):
        """Save a single review record"""
        record = dict(record)
        record["review_id"] = review_id
        if self.project_id:
            record["project_id"] = self.project_id
            record.setdefault("post_data", {}).setdefault("project_id", self.project_id)
        self.store.save_review_record(record)


# Backwards compatibility alias
ContentFeedbackManager = FeedbackManager
