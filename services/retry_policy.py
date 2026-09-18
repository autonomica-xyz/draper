"""Retry policy by failure category per Phase 4 plan 04-04 (ARCH-05 D-5)."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional


class FailureCategory(str, Enum):
    TRANSIENT = "transient"
    PERMANENT = "permanent"
    PROVIDER_QUOTA = "provider_quota"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RetryDecision:
    next_retry_at: str
    max_attempts: int


_TRANSIENT_BACKOFF_SECONDS = (5, 15, 60, 300)
_PROVIDER_QUOTA_BACKOFF_SECONDS = (60, 600, 3600)
_UNKNOWN_BACKOFF_SECONDS = (5, 60)
_JITTER_MAX = 1.5


class RetryPolicy:
    """Compute retry decisions by failure category."""

    def compute_retry(
        self,
        category: FailureCategory,
        attempts: int,
        *,
        now: Optional[datetime] = None,
    ) -> Optional[RetryDecision]:
        now = now or datetime.now(timezone.utc)
        if category is FailureCategory.PERMANENT:
            return None
        if category is FailureCategory.TRANSIENT:
            backoff = _TRANSIENT_BACKOFF_SECONDS
            max_attempts = 4
        elif category is FailureCategory.PROVIDER_QUOTA:
            backoff = _PROVIDER_QUOTA_BACKOFF_SECONDS
            max_attempts = 3
        else:
            backoff = _UNKNOWN_BACKOFF_SECONDS
            max_attempts = 2

        if attempts >= max_attempts:
            return None

        idx = min(attempts - 1, len(backoff) - 1)
        delay = backoff[idx] + random.uniform(0, _JITTER_MAX)
        next_dt = now + timedelta(seconds=delay)
        return RetryDecision(
            next_retry_at=next_dt.isoformat(),
            max_attempts=max_attempts,
        )


_PROVIDER_QUOTA_MARKERS = ("rate limit", "rate_limit", "quota", "429", "slow down")
_TRANSIENT_MARKERS = (
    "timeout",
    "timed out",
    "connection",
    "temporarily",
    "busy",
    "lock",
)
_PERMANENT_MARKERS = (
    "validation",
    "invalid",
    "unknown kind",
    "not found",
    "auth",
    "permission",
    "forbidden",
    "project_id is required",
    "review_id is required",
)


def categorize_exception(exc: BaseException) -> FailureCategory:
    message = str(exc).lower()
    exc_type_name = type(exc).__name__.lower()

    if any(
        t in exc_type_name
        for t in ("connecterror", "timeouterror", "connectionerror")
    ):
        return FailureCategory.TRANSIENT
    if any(t in exc_type_name for t in ("valueerror", "keyerror", "typeerror")):
        return FailureCategory.PERMANENT
    if any(t in exc_type_name for t in ("auth", "permission", "forbidden")):
        return FailureCategory.PERMANENT

    if any(m in message for m in _PROVIDER_QUOTA_MARKERS):
        return FailureCategory.PROVIDER_QUOTA
    if any(m in message for m in _TRANSIENT_MARKERS):
        return FailureCategory.TRANSIENT
    if any(m in message for m in _PERMANENT_MARKERS):
        return FailureCategory.PERMANENT

    return FailureCategory.UNKNOWN


__all__ = [
    "FailureCategory",
    "RetryDecision",
    "RetryPolicy",
    "categorize_exception",
]
