"""Pipeline visibility: schedule failures must not leave reviews as approved.

Mainline ``ReviewWorkflowService._apply_schedule`` restores ``original_status``
(usually ``approved``) on publish failure, which drops the item out of the
pending Pipeline list. Apply this patch at process start so failures reset to
``pending_review`` and keep ``scheduling_error`` for retry.

Live hot-patch equivalent of the one-line status change in the full RWS file
(which exceeds the GitHub MCP create_or_update_file payload limit).
"""

from __future__ import annotations

_applied = False


def apply() -> None:
    global _applied
    if _applied:
        return

    from services.review_workflow_service import ReviewWorkflowService

    _orig = ReviewWorkflowService._apply_schedule

    def _apply_schedule(self, record, *, feedback, explicit_tags, scheduled_date, provider_name, platform):
        try:
            return _orig(
                self,
                record,
                feedback=feedback,
                explicit_tags=explicit_tags,
                scheduled_date=scheduled_date,
                provider_name=provider_name,
                platform=platform,
            )
        except Exception:
            # Orig already persisted scheduling_error and raised; fix status if
            # it was restored to approved (or any non-pending state).
            if record.get("scheduling_error") and record.get("status") != "pending_review":
                record["status"] = "pending_review"
                self._persist(record.get("review_id", ""), record)
            raise

    ReviewWorkflowService._apply_schedule = _apply_schedule  # type: ignore[method-assign]
    _applied = True
