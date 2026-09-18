#!/usr/bin/env python3
"""
Data models for multi-project marketing pipeline
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List


@dataclass
class PlatformConfig:
    """Platform-specific configuration"""
    enabled: bool = False
    account_handle: str = ""
    public_key: str = ""  # For Nostr


@dataclass
class SocialProfile:
    """
    Social profile configuration for a project

    Note: Profiles are fetched from Typefully API, not manually created.
    This class just stores which Typefully accounts are enabled for this project.
    """
    account_id: str = ""  # Typefully account ID or social-set-id
    platform: str = ""  # twitter, linkedin
    handle: str = ""  # Display handle (from Typefully)
    display_name: str = ""  # Display name (from Typefully)
    enabled: bool = True  # Whether this account is enabled for this project

    def to_dict(self) -> dict:
        return {
            "account_id": self.account_id,
            "platform": self.platform,
            "handle": self.handle,
            "display_name": self.display_name,
            "enabled": self.enabled
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'SocialProfile':
        return cls(
            account_id=data.get("account_id", data.get("profile_id", "")),  # Backwards compat
            platform=data.get("platform", ""),
            handle=data.get("handle", ""),
            display_name=data.get("display_name", ""),
            enabled=data.get("enabled", True)
        )


@dataclass
class PostingStrategy:
    """Posting strategy configuration"""
    frequency: str = "daily"
    posts_per_day: int = 3
    times: List[str] = field(default_factory=lambda: ["09:00", "14:00", "18:00"])
    platforms: List[str] = field(default_factory=lambda: ["twitter", "linkedin"])

    def to_dict(self) -> dict:
        return {
            "frequency": self.frequency,
            "posts_per_day": self.posts_per_day,
            "times": self.times,
            "platforms": self.platforms
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'PostingStrategy':
        return cls(
            frequency=data.get("frequency", "daily"),
            posts_per_day=data.get("posts_per_day", 3),
            times=data.get("times", ["09:00", "14:00", "18:00"]),
            platforms=data.get("platforms", ["twitter", "linkedin"])
        )


@dataclass
class TypefullyIntegration:
    """Typefully integration settings"""
    api_key: str = ""
    drafts_enabled: bool = True
    auto_schedule: bool = False
    default_schedule_id: str = ""

    def to_dict(self) -> dict:
        return {
            "api_key": self.api_key,
            "drafts_enabled": self.drafts_enabled,
            "auto_schedule": self.auto_schedule,
            "default_schedule_id": self.default_schedule_id
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'TypefullyIntegration':
        return cls(
            api_key=data.get("api_key", ""),
            drafts_enabled=data.get("drafts_enabled", True),
            auto_schedule=data.get("auto_schedule", False),
            default_schedule_id=data.get("default_schedule_id", "")
        )


@dataclass
class ProjectSettings:
    """Project settings including brand voice and content plan paths"""
    brand_voice_path: str = ""
    content_plan_path: str = ""
    typefully_api_key: str = ""
    typefully_account_id: str = ""
    platforms: Dict[str, PlatformConfig] = field(default_factory=dict)
    social_profiles: List[SocialProfile] = field(default_factory=list)
    posting_strategy: PostingStrategy = field(default_factory=PostingStrategy)
    platform_overrides: Dict[str, PostingStrategy] = field(default_factory=dict)
    integrations: Dict[str, TypefullyIntegration] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "brand_voice_path": self.brand_voice_path,
            "content_plan_path": self.content_plan_path,
            "typefully_api_key": self.typefully_api_key,
            "typefully_account_id": self.typefully_account_id,
            "platforms": {
                name: {
                    "enabled": cfg.enabled,
                    "account_handle": cfg.account_handle,
                    "public_key": cfg.public_key
                }
                for name, cfg in self.platforms.items()
            },
            "social_profiles": [p.to_dict() for p in self.social_profiles],
            "posting_strategy": self.posting_strategy.to_dict(),
            "platform_overrides": {k: v.to_dict() for k, v in self.platform_overrides.items()},
            "integrations": {k: v.to_dict() for k, v in self.integrations.items()}
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ProjectSettings':
        return cls(
            brand_voice_path=data.get("brand_voice_path", ""),
            content_plan_path=data.get("content_plan_path", ""),
            typefully_api_key=data.get("typefully_api_key", ""),
            typefully_account_id=data.get("typefully_account_id", ""),
            platforms={
                name: PlatformConfig(**cfg)
                for name, cfg in data.get("platforms", {}).items()
            },
            social_profiles=[SocialProfile.from_dict(p) for p in data.get("social_profiles", [])],
            posting_strategy=PostingStrategy.from_dict(data.get("posting_strategy", {})),
            platform_overrides={k: PostingStrategy.from_dict(v) for k, v in data.get("platform_overrides", {}).items()},
            integrations={k: TypefullyIntegration.from_dict(v) for k, v in data.get("integrations", {}).items()}
        )


@dataclass
class GenerationSchedule:
    """Content generation schedule"""
    frequency: str = "daily"  # daily, weekly, biweekly
    times: List[str] = field(default_factory=lambda: ["09:00", "14:00"])
    posts_per_batch: int = 5

    def to_dict(self) -> dict:
        return {
            "frequency": self.frequency,
            "times": self.times,
            "posts_per_batch": self.posts_per_batch
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'GenerationSchedule':
        return cls(
            frequency=data.get("frequency", "daily"),
            times=data.get("times", ["09:00", "14:00"]),
            posts_per_batch=data.get("posts_per_batch", 5)
        )


@dataclass
class Project:
    """A marketing project with its own content, brand voice, and settings"""
    project_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    slug: str = ""
    description: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    settings: ProjectSettings = field(default_factory=ProjectSettings)
    generation_schedule: GenerationSchedule = field(default_factory=GenerationSchedule)

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "name": self.name,
            "slug": self.slug,
            "description": self.description,
            "created_at": self.created_at,
            "settings": self.settings.to_dict(),
            "generation_schedule": self.generation_schedule.to_dict()
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'Project':
        return cls(
            project_id=data.get("project_id", str(uuid.uuid4())),
            name=data.get("name", ""),
            slug=data.get("slug", ""),
            description=data.get("description", ""),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            settings=ProjectSettings.from_dict(data.get("settings", {})),
            generation_schedule=GenerationSchedule.from_dict(data.get("generation_schedule", {}))
        )


@dataclass
class FeedbackRecord:
    """Feedback history entry for content"""
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    from_status: str = ""
    to_status: str = ""
    feedback: str = ""
    learning_tags: List[str] = field(default_factory=list)
    auto_fix_applied: bool = False

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "from_status": self.from_status,
            "to_status": self.to_status,
            "feedback": self.feedback,
            "learning_tags": self.learning_tags,
            "auto_fix_applied": self.auto_fix_applied
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'FeedbackRecord':
        return cls(
            timestamp=data.get("timestamp", datetime.now(timezone.utc).isoformat()),
            from_status=data.get("from_status", ""),
            to_status=data.get("to_status", ""),
            feedback=data.get("feedback", ""),
            learning_tags=data.get("learning_tags", []),
            auto_fix_applied=data.get("auto_fix_applied", False)
        )


@dataclass
class ContentMetadata:
    """Content metadata including hook type, pillar, target audience"""
    hook_type: str = ""
    pillar: str = ""
    target_audience: str = ""

    def to_dict(self) -> dict:
        return {
            "hook_type": self.hook_type,
            "pillar": self.pillar,
            "target_audience": self.target_audience
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ContentMetadata':
        return cls(
            hook_type=data.get("hook_type", ""),
            pillar=data.get("pillar", ""),
            target_audience=data.get("target_audience", "")
        )


@dataclass
class VisualAid:
    """Visual content from Gamma.app or other sources"""
    type: str = ""  # gamma_app, image, diagram
    url: str = ""
    thumbnail: str = ""
    embed_code: str = ""

    def to_dict(self) -> dict:
        return {
            "type": self.type,
            "url": self.url,
            "thumbnail": self.thumbnail,
            "embed_code": self.embed_code
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'VisualAid':
        return cls(
            type=data.get("type", ""),
            url=data.get("url", ""),
            thumbnail=data.get("thumbnail", ""),
            embed_code=data.get("embed_code", "")
        )


@dataclass
class ContentData:
    """Actual content with text and visual aids"""
    text: str = ""
    visual_aids: List[VisualAid] = field(default_factory=list)
    metadata: ContentMetadata = field(default_factory=ContentMetadata)

    def to_dict(self) -> dict:
        return {
            "text": self.text,
            "visual_aids": [va.to_dict() for va in self.visual_aids],
            "metadata": self.metadata.to_dict()
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ContentData':
        return cls(
            text=data.get("text", ""),
            visual_aids=[VisualAid.from_dict(va) for va in data.get("visual_aids", [])],
            metadata=ContentMetadata.from_dict(data.get("metadata", {}))
        )


@dataclass
class ContentReasoning:
    """Reasoning behind content generation"""
    strategy: str = ""
    target_audience: str = ""
    key_points: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "strategy": self.strategy,
            "target_audience": self.target_audience,
            "key_points": self.key_points
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ContentReasoning':
        return cls(
            strategy=data.get("strategy", ""),
            target_audience=data.get("target_audience", ""),
            key_points=data.get("key_points", [])
        )


@dataclass
class ContentItem:
    """A piece of content in the pipeline"""
    content_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str = ""
    platform: str = ""  # linkedin, twitter, nostr
    content_type: str = ""  # thread, post, carousel, document
    status: str = "pending_review"  # pending_review, approved, needs_work, declined, published
    content: ContentData = field(default_factory=ContentData)
    reasoning: ContentReasoning = field(default_factory=ContentReasoning)
    feedback_history: List[FeedbackRecord] = field(default_factory=list)
    typefully_draft_id: str = ""
    scheduled_for: str = ""
    published_at: str = ""
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "content_id": self.content_id,
            "project_id": self.project_id,
            "platform": self.platform,
            "content_type": self.content_type,
            "status": self.status,
            "content": self.content.to_dict(),
            "reasoning": self.reasoning.to_dict(),
            "feedback_history": [fb.to_dict() for fb in self.feedback_history],
            "typefully_draft_id": self.typefully_draft_id,
            "scheduled_for": self.scheduled_for,
            "published_at": self.published_at,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ContentItem':
        return cls(
            content_id=data.get("content_id", str(uuid.uuid4())),
            project_id=data.get("project_id", ""),
            platform=data.get("platform", ""),
            content_type=data.get("content_type", ""),
            status=data.get("status", "pending_review"),
            content=ContentData.from_dict(data.get("content", {})),
            reasoning=ContentReasoning.from_dict(data.get("reasoning", {})),
            feedback_history=[FeedbackRecord.from_dict(fb) for fb in data.get("feedback_history", [])],
            typefully_draft_id=data.get("typefully_draft_id", ""),
            scheduled_for=data.get("scheduled_for", ""),
            published_at=data.get("published_at", ""),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat())
        )


@dataclass
class LearningPattern:
    """A learned pattern from content feedback"""
    pattern_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str = ""
    pattern_type: str = ""  # hook_style, structure, tone, topic, call_to_action, negative_pattern
    pattern: str = ""
    effectiveness_score: float = 0.0
    sample_size: int = 0
    success_examples: List[str] = field(default_factory=list)
    failure_examples: List[str] = field(default_factory=list)
    last_updated: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    confidence: str = "low"  # low, medium, high

    def to_dict(self) -> dict:
        return {
            "pattern_id": self.pattern_id,
            "project_id": self.project_id,
            "pattern_type": self.pattern_type,
            "pattern": self.pattern,
            "effectiveness_score": self.effectiveness_score,
            "sample_size": self.sample_size,
            "success_examples": self.success_examples,
            "failure_examples": self.failure_examples,
            "last_updated": self.last_updated,
            "confidence": self.confidence
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'LearningPattern':
        return cls(
            pattern_id=data.get("pattern_id", str(uuid.uuid4())),
            project_id=data.get("project_id", ""),
            pattern_type=data.get("pattern_type", ""),
            pattern=data.get("pattern", ""),
            effectiveness_score=data.get("effectiveness_score", 0.0),
            sample_size=data.get("sample_size", 0),
            success_examples=data.get("success_examples", []),
            failure_examples=data.get("failure_examples", []),
            last_updated=data.get("last_updated", datetime.now(timezone.utc).isoformat()),
            confidence=data.get("confidence", "low")
        )


@dataclass
class SourceMaterial:
    """A source material entry for the Idea Lab — URL, text snippet, or note."""
    material_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str = ""
    material_type: str = ""  # 'url', 'text', or 'note'
    title: str = ""
    url: str = ""
    text_content: str = ""
    note: str = ""
    source_attribution: str = ""
    tags: List[str] = field(default_factory=list)
    metadata_json: Dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "material_id": self.material_id,
            "project_id": self.project_id,
            "material_type": self.material_type,
            "title": self.title,
            "url": self.url,
            "text_content": self.text_content,
            "note": self.note,
            "source_attribution": self.source_attribution,
            "tags": self.tags,
            "metadata_json": self.metadata_json,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'SourceMaterial':
        return cls(
            material_id=data.get("material_id", str(uuid.uuid4())),
            project_id=data.get("project_id", ""),
            material_type=data.get("material_type", ""),
            title=data.get("title", ""),
            url=data.get("url", ""),
            text_content=data.get("text_content", ""),
            note=data.get("note", ""),
            source_attribution=data.get("source_attribution", ""),
            tags=data.get("tags", []),
            metadata_json=data.get("metadata_json", {}),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )


@dataclass
class ContentIdea:
    """A structured pitch-card idea for content generation."""

    idea_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str = ""
    title: str = ""
    hook_angle: str = ""
    target_platforms: List[str] = field(default_factory=list)
    content_pillar: str = ""
    rationale: str = ""
    suggested_format: str = ""
    source_material_ids: List[str] = field(default_factory=list)
    status: str = "draft"
    evaluation_notes: str = ""
    tags: List[str] = field(default_factory=list)
    metadata_json: Dict = field(default_factory=dict)
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict:
        return {
            "idea_id": self.idea_id,
            "project_id": self.project_id,
            "title": self.title,
            "hook_angle": self.hook_angle,
            "target_platforms": self.target_platforms,
            "content_pillar": self.content_pillar,
            "rationale": self.rationale,
            "suggested_format": self.suggested_format,
            "source_material_ids": self.source_material_ids,
            "status": self.status,
            "evaluation_notes": self.evaluation_notes,
            "tags": self.tags,
            "metadata_json": self.metadata_json,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, data: dict) -> 'ContentIdea':
        return cls(
            idea_id=data.get("idea_id", str(uuid.uuid4())),
            project_id=data.get("project_id", ""),
            title=data.get("title", ""),
            hook_angle=data.get("hook_angle", ""),
            target_platforms=data.get("target_platforms", []),
            content_pillar=data.get("content_pillar", ""),
            rationale=data.get("rationale", ""),
            suggested_format=data.get("suggested_format", ""),
            source_material_ids=data.get("source_material_ids", []),
            status=data.get("status", "draft"),
            evaluation_notes=data.get("evaluation_notes", ""),
            tags=data.get("tags", []),
            metadata_json=data.get("metadata_json", {}),
            created_at=data.get("created_at", datetime.now(timezone.utc).isoformat()),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
        )
