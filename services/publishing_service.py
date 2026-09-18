"""Project-scoped publishing orchestration."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, Union

from integrations.late_provider import LateProvider
from integrations.nostr_provider import NostrProvider
from integrations.publishing_provider import (
    PublishErrorCode,
    PublishRequest,
    PublishResult,
    PublishingManager,
)
from integrations.typefully_provider import TypefullyProvider

from .observability import get_logger
from .project_context import ProjectContextService
from .secrets import ProjectSecretService


_logger = get_logger(__name__)


@dataclass
class PublishingAttempt:
    """A publish call plus the routing context used to make it."""

    result: PublishResult
    project_id: str
    platform: str
    provider_name: Optional[str]
    account_id: Optional[str]
    scheduled_at: Optional[datetime] = None


class ProjectPublishingService:
    """Builds project-aware providers and publishes verified review records."""

    def __init__(
        self,
        project_manager,
        data_dir: Union[str, Path],
        project_context: Optional[ProjectContextService] = None,
        store=None,
        feedback_manager=None,
        job_queue=None,
    ):
        self.project_manager = project_manager
        self.data_dir = Path(data_dir)
        self.project_context = project_context or ProjectContextService(project_manager)
        self.secret_service = ProjectSecretService(project_manager)
        self.store = store if store is not None else getattr(project_manager, "store", None)

        # Nostr signing workflow: NIP-07 extension requests + sign-now-publish-later.
        # Constructed lazily-safe: build_manager() reads it at publish time.
        from services.nostr_signing_service import NostrSigningService

        self.nostr_signing = NostrSigningService(
            self.store,
            job_queue=job_queue,
            feedback_manager=feedback_manager,
            data_dir=str(self.data_dir),
        )

    def build_manager(self, project_id: str = None) -> PublishingManager:
        """Build a publishing manager using project-scoped secrets when available."""
        manager = PublishingManager()
        typefully_key = self.secret_service.get_api_key(project_id, "typefully")
        late_key = self.secret_service.get_api_key(project_id, "late")

        manager.register_provider(TypefullyProvider(api_key=typefully_key), primary=True)
        manager.register_provider(LateProvider(api_key=late_key))
        manager.register_provider(NostrProvider(
            private_key=self.secret_service.get_api_key(project_id, "nostr"),
            data_dir=str(self.data_dir),
            signing_service=self.nostr_signing,
        ))
        return manager

    def publish_record(
        self,
        record: Dict,
        provider_name: str = None,
        platform: str = None,
        fallback_platform: str = "twitter",
        scheduled_at: Union[str, datetime, None] = None,
        content_type: str = None,
        as_draft: bool = True,
        auto_publish: bool = False,
        schedule_next_slot: bool = False,
    ) -> PublishingAttempt:
        """Publish a review record after verifying project scope and routing."""
        post_data = record.get("post_data", {})
        project_id = self.project_context.require_record_project_id(record)
        selected_platform = (
            platform
            or post_data.get("publish_channel")
            or post_data.get("platform")
            or fallback_platform
        )
        selected_provider = provider_name or self.project_context.get_provider_for_platform(
            project_id,
            selected_platform,
        ) or self.project_context.infer_provider_for_platform(project_id, selected_platform)

        # Nostr has no per-project social "account" -- the identity comes
        # from whichever key signs (server key or NIP-07 extension), so route
        # nostr always to the nostr provider and skip the account lookup.
        if selected_platform == "nostr":
            selected_provider = provider_name or "nostr"
            account_id = None
        else:
            account_id = self.project_context.find_enabled_account_id(
                project_id,
                selected_platform,
                selected_provider,
            )
        parsed_scheduled_at = self._parse_datetime(scheduled_at)

        if not selected_provider:
            return self._failed_attempt(
                project_id=project_id,
                review_id=record.get("review_id"),
                platform=selected_platform,
                provider_name=None,
                account_id=None,
                scheduled_at=parsed_scheduled_at,
                error=(
                    f"No enabled publishing provider configured for project "
                    f"{project_id} on {selected_platform}"
                ),
            )

        if not account_id and selected_platform != "nostr":
            return self._failed_attempt(
                project_id=project_id,
                review_id=record.get("review_id"),
                platform=selected_platform,
                provider_name=selected_provider,
                account_id=None,
                scheduled_at=parsed_scheduled_at,
                error=(
                    f"No enabled {selected_provider} account configured for project "
                    f"{project_id} on {selected_platform}"
                ),
            )

        publish_request = PublishRequest(
            content=post_data.get("content", ""),
            platform=selected_platform,
            account_id=account_id,
            content_type=content_type if content_type is not None else post_data.get("content_type", ""),
            as_draft=as_draft,
            auto_publish=auto_publish,
            scheduled_at=parsed_scheduled_at,
            schedule_next_slot=schedule_next_slot,
            review_id=record.get("review_id"),
            project_id=project_id,
        )

        self._emit_attempted(
            project_id=project_id,
            review_id=record.get("review_id"),
            provider=selected_provider or "",
            platform=selected_platform,
        )

        result = self.build_manager(project_id).publish(
            publish_request,
            provider_name=selected_provider,
        )

        if result.success:
            self._emit_succeeded(
                project_id=project_id,
                review_id=record.get("review_id"),
                provider=result.provider or selected_provider or "",
                platform=selected_platform,
            )
        else:
            self._emit_failed(
                project_id=project_id,
                review_id=record.get("review_id"),
                provider=result.provider or selected_provider or "",
                platform=selected_platform,
                error_code=result.error_code,
            )

        return PublishingAttempt(
            result=result,
            project_id=project_id,
            platform=selected_platform,
            provider_name=selected_provider,
            account_id=account_id,
            scheduled_at=parsed_scheduled_at,
        )

    def _failed_attempt(
        self,
        *,
        project_id: str,
        review_id: Optional[str],
        platform: str,
        provider_name: Optional[str],
        account_id: Optional[str],
        scheduled_at: Optional[datetime],
        error: str,
    ) -> PublishingAttempt:
        provider = provider_name or ""
        self._emit_attempted(
            project_id=project_id,
            review_id=review_id,
            provider=provider,
            platform=platform,
        )
        result = PublishResult(
            success=False,
            error=error,
            provider=provider or "unknown",
            error_code=PublishErrorCode.ACCOUNT_NOT_FOUND,
        )
        self._emit_failed(
            project_id=project_id,
            review_id=review_id,
            provider=provider,
            platform=platform,
            error_code=result.error_code,
        )
        return PublishingAttempt(
            result=result,
            project_id=project_id,
            platform=platform,
            provider_name=provider_name,
            account_id=account_id,
            scheduled_at=scheduled_at,
        )

    def _emit_attempted(self, *, project_id, review_id, provider, platform) -> None:
        if self.store is None or not hasattr(self.store, "record_event"):
            return
        try:
            self.store.record_event(
                category="publish",
                action="attempted",
                project_id=project_id,
                review_id=review_id,
                payload={"provider": provider, "platform": platform},
            )
        except Exception as exc:
            _logger.warning("system_events.publish.attempted failed: %s", exc)

    def _emit_succeeded(self, *, project_id, review_id, provider, platform) -> None:
        if self.store is None or not hasattr(self.store, "record_event"):
            return
        try:
            self.store.record_event(
                category="publish",
                action="succeeded",
                project_id=project_id,
                review_id=review_id,
                payload={"provider": provider, "platform": platform},
            )
        except Exception as exc:
            _logger.warning("system_events.publish.succeeded failed: %s", exc)

    def _emit_failed(self, *, project_id, review_id, provider, platform, error_code) -> None:
        if self.store is None or not hasattr(self.store, "record_event"):
            return
        payload: Dict = {"provider": provider, "platform": platform}
        if error_code is not None:
            payload["error_code"] = error_code.value
        try:
            self.store.record_event(
                category="publish",
                action="failed",
                project_id=project_id,
                review_id=review_id,
                payload=payload,
            )
        except Exception as exc:
            _logger.warning("system_events.publish.failed failed: %s", exc)

    @staticmethod
    def _parse_datetime(value: Union[str, datetime, None]) -> Optional[datetime]:
        if not value:
            return None
        if isinstance(value, datetime):
            return value
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
