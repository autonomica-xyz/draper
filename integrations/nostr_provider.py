#!/usr/bin/env python3
"""
Nostr Publishing Provider
Implements PublishingProvider on top of the nostr-sdk-backed pipeline.

Publishing modes (ideas adapted from the nostr-cms project):

* **Immediate (server key)** -- signs and blasts to all relays right away.
* **Sign-now-publish-later (server key)** -- when ``scheduled_at`` is in the
  future the event is signed with a future ``created_at`` and stored; the
  job queue broadcasts it when due.
* **NIP-07 extension signing** -- when no server key is configured the
  provider creates a *signing request* and returns
  ``PublishErrorCode.SIGNING_REQUIRED``. A human signs the prepared event
  with nos2x/Alby directly in the dashboard Pipeline tab; the verified,
  signed event is then scheduled and published later without the server
  ever holding an nsec.
"""

import os
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pathlib import Path

from .publishing_provider import (
    PublishingProvider,
    SocialAccount,
    PublishRequest,
    PublishResult,
    PublishErrorCode,
)

# Project root for nostr/ imports
import sys

_project_root = str(Path(__file__).parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from nostr.nostr_publisher import NostrPublisher
from nostr import signing as nostr_signing


class NostrProvider(PublishingProvider):
    """Nostr protocol implementation wrapping NostrPublisher"""

    def __init__(
        self,
        private_key: Optional[str] = None,
        data_dir: Optional[str] = None,
        relays: Optional[List[str]] = None,
        signing_service=None,
    ):
        self._private_key = private_key or os.getenv("NOSTR_PRIVATE_KEY")
        self._relays = relays
        self._publisher = None
        self._analytics = None
        self._data_dir = data_dir
        self._signing_service = signing_service

    def _get_publisher(self) -> NostrPublisher:
        """Lazy-initialize the NostrPublisher"""
        if self._publisher is None:
            self._publisher = NostrPublisher(
                private_key=self._private_key,
                relays=self._relays,
            )
        return self._publisher

    def _get_analytics(self):
        """Lazy-initialize NostrAnalytics if available"""
        if self._analytics is None:
            try:
                from nostr.nostr_analytics import NostrAnalytics

                self._analytics = NostrAnalytics(
                    data_dir=self._data_dir or str(Path(__file__).resolve().parent.parent / "data")
                )
            except ImportError:
                self._analytics = None
        return self._analytics

    def get_name(self) -> str:
        return "nostr"

    def is_configured(self) -> bool:
        """Configured when a server key exists OR extension signing is possible."""
        if self._private_key:
            return True
        key_file = Path.home() / ".nostr" / "private_key.txt"
        if key_file.exists():
            return True
        # Extension signing mode: possible whenever a signing service is wired.
        return self._signing_service is not None

    def get_accounts(self) -> List[SocialAccount]:
        """Return a SocialAccount for the Nostr identity (npub when known)."""
        if self._private_key or nostr_signing.sdk_available():
            try:
                publisher = self._get_publisher()
            except Exception:
                publisher = None
            try:
                npub = (publisher.npub if publisher else None) or nostr_signing.expected_signer_pubkey()
            except Exception:
                npub = None
            if npub:
                return [
                    SocialAccount(
                        account_id=f"nostr_{npub[:16]}",
                        platform="nostr",
                        handle=npub[:20] + "..." if len(npub) > 20 else npub,
                        display_name="Nostr Identity",
                        provider="nostr",
                        enabled=True,
                    )
                ]

        try:
            pinned = nostr_signing.expected_signer_pubkey()
        except Exception:
            pinned = None
        if pinned and nostr_signing.sdk_available():
            from nostr_sdk import PublicKey

            try:
                npub = PublicKey.parse(pinned).to_bech32()
                return [
                    SocialAccount(
                        account_id=f"nostr_{npub[:16]}",
                        platform="nostr",
                        handle=npub[:20] + "..." if len(npub) > 20 else npub,
                        display_name="Nostr Identity (extension signing)",
                        provider="nostr",
                        enabled=True,
                    )
                ]
            except Exception:
                pass

        return []

    def publish(self, request: PublishRequest) -> PublishResult:
        """Publish content to Nostr.

        Immediate publish when a server key is configured and no future
        schedule is requested; sign-now-publish-later for future schedules;
        signing-request + SIGNING_REQUIRED when only extension signing is
        available.
        """
        publisher = self._get_publisher()
        post_data = {
            "content": request.content,
            "platform": request.platform or "nostr",
            "content_type": request.content_type or "",
            "pillar": "",
            "topic": "",
        }
        scheduled_at = request.scheduled_at

        # Sign-now-publish-later: a future-dated event is signed now and
        # stored; the job queue broadcasts it when due.
        if scheduled_at is not None and self._signing_service is not None:
            if isinstance(scheduled_at, datetime):
                scheduled_iso = scheduled_at
            else:
                scheduled_iso = str(scheduled_at)
            return self._publish_via_signing_service(
                post_data,
                scheduled_iso,
                review_id=request.review_id,
                project_id=request.project_id,
            )

        if publisher.private_key:
            result = publisher.publish_from_post_data(post_data)

            if result.get("success") and not result.get("requires_manual_publish"):
                event_id = result.get("event_id")
                self._record_analytics(event_id, request.content)

                return PublishResult(
                    success=True,
                    post_id=event_id,
                    url=result.get("event_uri"),
                    provider="nostr",
                    scheduled=False,
                )

            if result.get("requires_manual_publish"):
                return PublishResult(
                    success=False,
                    error=(
                        "nostr-sdk is not installed; event prepared for manual "
                        "publishing via the nak CLI"
                    ),
                    provider="nostr",
                    error_code=PublishErrorCode.NOT_CONFIGURED,
                )

            return PublishResult(
                success=False,
                error=result.get("message", "Unknown Nostr publishing error"),
                provider="nostr",
                error_code=PublishErrorCode.PROVIDER_ERROR,
            )

        # No server key: hand off to the NIP-07 extension signing flow.
        if self._signing_service is not None:
            return self._publish_via_signing_service(
                post_data,
                scheduled_at.isoformat() if isinstance(scheduled_at, datetime) else None,
                review_id=request.review_id,
                project_id=request.project_id,
            )

        return PublishResult(
            success=False,
            error=(
                "No Nostr private key configured. Set NOSTR_PRIVATE_KEY for "
                "headless publishing, or sign approved content with a NIP-07 "
                "extension (nos2x/Alby) from the Pipeline tab."
            ),
            provider="nostr",
            error_code=PublishErrorCode.NOT_CONFIGURED,
        )

    def _publish_via_signing_service(
        self,
        post_data: Dict,
        scheduled_at,
        review_id: Optional[str],
        project_id: Optional[str] = None,
    ) -> PublishResult:
        """Create a signing request and report the required human step."""
        record = {
            "post_data": post_data,
            "review_id": review_id,
            "project_id": project_id or post_data.get("project_id"),
        }
        try:
            request_record = self._signing_service.create_request(record, scheduled_at=scheduled_at)
        except Exception as exc:
            return PublishResult(
                success=False,
                error=f"Failed to prepare Nostr signing request: {exc}",
                provider="nostr",
                error_code=PublishErrorCode.PROVIDER_ERROR,
            )

        # If a server key exists (per-project, env, or key file) the service can
        # sign immediately; otherwise the request waits for a NIP-07 signature.
        try:
            server_key = nostr_signing.load_keys(self._private_key)
            if server_key is not None:
                signed = self._signing_service.sign_request_with_server_keys(
                    request_record["request_id"], private_key=self._private_key
                )
                if signed.get("status") == "signed":
                    return PublishResult(
                        success=True,
                        post_id=signed.get("event_id"),
                        url=signed.get("event_uri"),
                        provider="nostr",
                        scheduled=True,
                    )
        except Exception as exc:
            return PublishResult(
                success=False,
                error=f"Nostr signing failed: {exc}",
                provider="nostr",
                error_code=PublishErrorCode.PROVIDER_ERROR,
            )

        return PublishResult(
            success=False,
            error=(
                "Nostr signature required: the approved post is waiting in the "
                "Pipeline tab -- click 'Sign with extension' there to sign it "
                "with your Nostr extension (nos2x/Alby). "
                f"Signing request {request_record['request_id']} is pending."
            ),
            provider="nostr",
            error_code=PublishErrorCode.SIGNING_REQUIRED,
        )

    def _record_analytics(self, event_id: Optional[str], content: str) -> None:
        analytics = self._get_analytics()
        if analytics and event_id:
            try:
                analytics.record_event(
                    event_id=event_id,
                    kind=1,
                    content=content[:200],
                    published_at=datetime.now(timezone.utc).isoformat(),
                    platform="nostr",
                    pillar="",
                )
            except Exception:
                pass

    def get_analytics(self, account_id: Optional[str] = None) -> Dict:
        """Return basic analytics from NostrAnalytics if available"""
        analytics = self._get_analytics()
        if analytics is None:
            return {
                "provider": "nostr",
                "status": "no_data",
                "message": "Nostr analytics module not available",
            }

        summary = analytics.get_analytics_summary()
        summary["provider"] = "nostr"
        return summary
