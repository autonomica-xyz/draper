"""Pydantic payload + result envelopes for every job kind (Phase 4 plan 04-03, ARCH-05 D-4)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Type

from pydantic import BaseModel, ConfigDict, Field


class GenerateContentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str = Field(..., min_length=1, max_length=160)
    count: int = Field(default=5, ge=1, le=25)
    platform: Optional[str] = Field(default=None, max_length=40)
    content_type: Optional[str] = Field(default=None, max_length=80)
    channel: str = Field(default="API", max_length=40)


class FixContentPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    review_id: str = Field(..., min_length=1, max_length=160)
    feedback: str = Field(default="", max_length=4000)
    project_id: str = Field(..., min_length=1, max_length=160)


class GenerateVisualPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    prompt: str = Field(..., min_length=1, max_length=4000)
    platform: str = Field(default="instagram", max_length=40)
    style: str = Field(default="minimal", max_length=40)
    project_id: Optional[str] = Field(default=None, max_length=160)


class GenerateCarouselPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    content: str = Field(..., min_length=1, max_length=12000)
    title: str = Field(default="", max_length=400)
    num_cards: int = Field(default=5, ge=1, le=12)
    platform: str = Field(default="linkedin", max_length=40)
    project_id: Optional[str] = Field(default=None, max_length=160)


class MineIdeasPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: str = Field(..., min_length=1, max_length=160)
    source_material_id: Optional[str] = Field(default=None, max_length=160)
    max_ideas: int = Field(default=5, ge=1, le=20)


class SyncProviderAnalyticsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: Optional[str] = Field(default=None, max_length=160)
    provider: Optional[str] = Field(default=None, max_length=40)


class PublishScheduledPostPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    post_id: str = Field(..., min_length=1, max_length=160)
    review_id: Optional[str] = Field(default=None, max_length=160)
    provider: Optional[str] = Field(default=None, max_length=40)
    platform: Optional[str] = Field(default=None, max_length=40)


class SyncAnalyticsPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    project_id: Optional[str] = Field(default=None, max_length=160)


class NostrPublishRequestPayload(BaseModel):
    """Payload for broadcasting a signed Nostr event when due."""

    model_config = ConfigDict(extra="ignore")

    request_id: str = Field(..., min_length=1, max_length=160)
    project_id: Optional[str] = Field(default=None, max_length=160)


class JobResult(BaseModel):
    model_config = ConfigDict(extra="allow")

    success: bool = True


class GenerateContentResult(JobResult):
    count: int = 0
    review_ids: List[str] = Field(default_factory=list)


class FixContentResult(JobResult):
    review_id: str
    status: str = "pending_review"
    explanation: str = ""


class GenerateVisualResult(JobResult):
    image_url: Optional[str] = None
    provider: Optional[str] = None


class GenerateCarouselResult(JobResult):
    carousel_id: Optional[str] = None
    cards: int = 0
    provider: Optional[str] = None


class MineIdeasResult(JobResult):
    idea_ids: List[str] = Field(default_factory=list)


class SyncProviderAnalyticsResult(JobResult):
    synced: List[str] = Field(default_factory=list)


class PublishScheduledPostResult(JobResult):
    post_id: str
    status: str
    provider: Optional[str] = None
    draft_id: Optional[str] = None
    url: Optional[str] = None


class SyncAnalyticsResult(JobResult):
    synced_platforms: List[str] = Field(default_factory=list)


class NostrPublishRequestResult(JobResult):
    request_id: str
    event_id: Optional[str] = None
    published_to: int = 0


KIND_PAYLOAD_REGISTRY: Dict[str, Type[BaseModel]] = {
    "generate_content": GenerateContentPayload,
    "fix_content": FixContentPayload,
    "generate_visual": GenerateVisualPayload,
    "generate_carousel": GenerateCarouselPayload,
    "mine_ideas": MineIdeasPayload,
    "sync_provider_analytics": SyncProviderAnalyticsPayload,
    "publish_scheduled_post": PublishScheduledPostPayload,
    "sync_analytics": SyncAnalyticsPayload,
    "nostr_publish_request": NostrPublishRequestPayload,
}

KIND_RESULT_REGISTRY: Dict[str, Type[JobResult]] = {
    "generate_content": GenerateContentResult,
    "fix_content": FixContentResult,
    "generate_visual": GenerateVisualResult,
    "generate_carousel": GenerateCarouselResult,
    "mine_ideas": MineIdeasResult,
    "sync_provider_analytics": SyncProviderAnalyticsResult,
    "publish_scheduled_post": PublishScheduledPostResult,
    "sync_analytics": SyncAnalyticsResult,
    "nostr_publish_request": NostrPublishRequestResult,
}


ALL_JOB_KINDS = frozenset(KIND_PAYLOAD_REGISTRY.keys())


def validate_payload(kind: str, payload: Optional[Dict[str, Any]]) -> BaseModel:
    """Validate a payload dict against the registered model for ``kind``.

    Raises ``KeyError`` for unknown kinds. Raises ``pydantic.ValidationError``
    for malformed payloads. Returns the validated model instance on success.
    """
    if kind not in KIND_PAYLOAD_REGISTRY:
        raise KeyError(f"Unknown job kind: {kind}")
    model_cls = KIND_PAYLOAD_REGISTRY[kind]
    return model_cls.model_validate(payload or {})


__all__ = [
    "ALL_JOB_KINDS",
    "FixContentPayload",
    "FixContentResult",
    "GenerateCarouselPayload",
    "GenerateCarouselResult",
    "GenerateContentPayload",
    "GenerateContentResult",
    "GenerateVisualPayload",
    "GenerateVisualResult",
    "JobResult",
    "KIND_PAYLOAD_REGISTRY",
    "KIND_RESULT_REGISTRY",
    "MineIdeasPayload",
    "MineIdeasResult",
    "PublishScheduledPostPayload",
    "PublishScheduledPostResult",
    "SyncAnalyticsPayload",
    "SyncAnalyticsResult",
    "SyncProviderAnalyticsPayload",
    "SyncProviderAnalyticsResult",
    "validate_payload",
]
