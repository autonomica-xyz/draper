"""Tests for the Nostr signing workflow (sign now, publish later).

Uses real nostr-sdk key generation (no network): signatures are produced
locally the same way a NIP-07 extension would, then verified by the
service. Relay broadcasts are faked to keep the tests offline.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import pytest

nostr_sdk = pytest.importorskip("nostr_sdk")

from nostr_sdk import Keys  # noqa: E402

from nostr import signing as nostr_signing  # noqa: E402
from services.nostr_signing_service import (  # noqa: E402
    NostrSigningError,
    NostrSigningService,
)


@pytest.fixture(autouse=True)
def _no_server_key(monkeypatch, tmp_path):
    """Keep tests in extension-signing mode (no server keys)."""
    monkeypatch.delenv("NOSTR_PRIVATE_KEY", raising=False)
    monkeypatch.delenv("NOSTR_PUBKEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))  # no ~/.nostr key file
    yield


class FakeBroadcast:
    """Offline stand-in for relay broadcasting."""

    def __init__(self):
        self.calls: List[Dict[str, Any]] = []

    def __call__(self, signed_event, relays=None, **kwargs):
        self.calls.append({"signed_event": signed_event, "relays": relays})
        return {
            "success": True,
            "event_id": signed_event.get("id"),
            "published_to": 2,
            "relays": [
                {"url": "wss://relay.example", "success": True},
                {"url": "wss://other.example", "success": True},
            ],
        }


@pytest.fixture
def broadcast(monkeypatch):
    fake = FakeBroadcast()
    monkeypatch.setattr("services.nostr_signing_service.publish_signed_event_sync", fake)
    return fake


@pytest.fixture
def service(seeded_store):
    return NostrSigningService(seeded_store)


def make_review_record(
    project_id: str = "fixture-project",
    review_id: str = "rev-1",
    content: str = "Hello nostr #fixture",
):
    return {
        "review_id": review_id,
        "project_id": project_id,
        "status": "approved",
        "post_data": {
            "content": content,
            "platform": "nostr",
            "pillar": "growth",
            "project_id": project_id,
        },
    }


def extension_sign(unsigned_events, keys) -> List[Dict]:
    """Sign exactly like window.nostr.signEvent does."""
    return nostr_signing.sign_event_chain(unsigned_events, keys)


class TestCreateRequest:
    def test_prepared_unsigned_event_matches_content(self, service, seeded_store):
        record = service.create_request(make_review_record())
        assert record["status"] == "pending_signature"
        assert len(record["unsigned_events"]) == 1
        unsigned = record["unsigned_events"][0]
        assert unsigned["content"] == "Hello nostr #fixture"
        assert ["t", "growth"] in unsigned["tags"]
        assert record["project_id"] == "fixture-project"

        stored = seeded_store.get_nostr_request_record(record["request_id"])
        assert stored["unsigned_events"][0]["content"] == "Hello nostr #fixture"

    def test_future_schedule_becomes_created_at(self, service):
        record = service.create_request(
            make_review_record(), scheduled_at="2030-01-01T00:00:00+00:00"
        )
        assert record["scheduled_at"] == "2030-01-01T00:00:00+00:00"
        assert record["unsigned_events"][0]["created_at"] == 1893456000

    def test_empty_content_rejected(self, service):
        with pytest.raises(NostrSigningError):
            service.create_request({"review_id": "r", "post_data": {"content": ""}})


class TestAcceptSignature:
    def test_valid_signature_is_verified_and_stored(self, service):
        record = service.create_request(make_review_record())
        keys = Keys.generate()
        signed = extension_sign(record["unsigned_events"], keys)

        accepted = service.accept_signature(record["request_id"], signed)

        assert accepted["status"] == "signed"
        assert accepted["event_id"] == signed[0]["id"]
        assert accepted["signer_pubkey"] == keys.public_key().to_hex()
        assert accepted["event_uri"]

    def test_tampered_content_rejected(self, service):
        record = service.create_request(make_review_record())
        keys = Keys.generate()
        signed = extension_sign(record["unsigned_events"], keys)
        signed[0] = {**signed[0], "content": "swapped"}

        with pytest.raises(NostrSigningError, match="rejected"):
            service.accept_signature(record["request_id"], signed)

    def test_wrong_event_count_rejected(self, service):
        record = service.create_request(make_review_record())
        keys = Keys.generate()
        signed = extension_sign(record["unsigned_events"], keys)

        with pytest.raises(NostrSigningError, match="Expected 1"):
            service.accept_signature(record["request_id"], signed + signed)

    def test_wrong_signer_rejected_when_pinned(self, service):
        record = service.create_request(make_review_record())
        signer = Keys.generate()
        signed = extension_sign(record["unsigned_events"], signer)

        pinned = Keys.generate().public_key().to_bech32()  # someone else
        with pytest.raises(NostrSigningError):
            service.accept_signature(record["request_id"], signed, expected_pubkey=pinned)

    def test_garbage_payload_rejected(self, service):
        record = service.create_request(make_review_record())
        with pytest.raises(NostrSigningError):
            service.accept_signature(record["request_id"], [{"kind": 1}])


class TestPublishDue:
    def test_signed_request_broadcast_and_review_mirrored(self, service, broadcast):
        review = make_review_record()
        record = service.create_request(review)
        keys = Keys.generate()
        service.accept_signature(
            record["request_id"], extension_sign(record["unsigned_events"], keys)
        )

        results = service.publish_due()
        assert len(results) == 1 and results[0]["success"]
        assert broadcast.calls, "broadcast must have been invoked"

        stored = service.store.get_nostr_request_record(record["request_id"])
        assert stored["status"] == "published"
        assert stored["published_at"]

    def test_pending_signature_not_published(self, service, broadcast):
        service.create_request(make_review_record())
        assert service.publish_due() == []
        assert broadcast.calls == []

    def test_not_yet_due_not_published(self, service, broadcast):
        record = service.create_request(
            make_review_record(), scheduled_at="2030-01-01T00:00:00+00:00"
        )
        keys = Keys.generate()
        service.accept_signature(
            record["request_id"], extension_sign(record["unsigned_events"], keys)
        )
        assert service.publish_due() == []

    def test_publish_due_is_project_scoped(self, service, broadcast):
        """Regression: publish_due used to sweep all projects."""
        rec_a = service.create_request(make_review_record(project_id="project-a"))
        rec_b = service.create_request(make_review_record(project_id="project-b"))
        keys = Keys.generate()
        service.accept_signature(
            rec_a["request_id"], extension_sign(rec_a["unsigned_events"], keys)
        )
        service.accept_signature(
            rec_b["request_id"], extension_sign(rec_b["unsigned_events"], keys)
        )

        results = service.publish_due(project_id="project-a")
        assert len(results) == 1
        assert results[0]["request_id"] == rec_a["request_id"]
        # The broadcast fixture is called once per event; only project-a was swept.
        assert len(broadcast.calls) == 1

    def test_broadcast_failure_increments_attempts(self, service, monkeypatch):
        record = service.create_request(make_review_record())
        keys = Keys.generate()
        service.accept_signature(
            record["request_id"], extension_sign(record["unsigned_events"], keys)
        )

        def failing_broadcast(signed_event, relays=None, **kwargs):
            return {
                "success": False,
                "event_id": None,
                "published_to": 0,
                "relays": [],
                "error": "all relays down",
            }

        monkeypatch.setattr(
            "services.nostr_signing_service.publish_signed_event_sync", failing_broadcast
        )
        result = service.publish_due()[0]
        assert result["success"] is False

        stored = service.store.get_nostr_request_record(record["request_id"])
        assert stored["publish_attempts"] == 1
        assert stored["status"] == "signed"  # still retriable
        assert stored["last_error"] == "all relays down"


class TestServerSideSigning:
    def test_signs_with_configured_key(self, service, monkeypatch):
        record = service.create_request(make_review_record())
        keys = Keys.generate()
        monkeypatch.setattr(nostr_signing, "load_keys", lambda *a, **k: keys)

        signed_record = service.sign_request_with_server_keys(record["request_id"])
        assert signed_record["status"] == "signed"
        assert signed_record["signer_pubkey"] == keys.public_key().to_hex()

    def test_raises_without_key(self, service):
        record = service.create_request(make_review_record())
        with pytest.raises(NostrSigningError, match="server key"):
            service.sign_request_with_server_keys(record["request_id"])

    def test_signs_thread_with_server_key(self, service):
        """Regression: server-key thread signing used to fail anti-tamper."""
        content = "Tweet 1: first part #fixture\n\nTweet 2: second part"
        record = service.create_request(make_review_record(content=content))
        keys = Keys.generate()

        signed_record = service.sign_request_with_server_keys(
            record["request_id"],
            private_key=keys.secret_key().to_bech32(),
        )
        assert signed_record["status"] == "signed"
        assert len(signed_record["signed_events"]) == 2

        # Second part must reference the first with a NIP-10 root e tag.
        part2 = signed_record["signed_events"][1]
        assert any(
            len(t) >= 4 and t[0] == "e" and t[3] == "root"
            for t in part2["tags"]
        )


class TestStatusSummary:
    def test_counts_and_config_flags(self, service):
        service.create_request(make_review_record())
        summary = service.get_status_summary("fixture-project")
        assert summary["pending_signature"] == 1
        assert summary["server_key_configured"] is False
        assert summary["relays"]


class TestNostrProviderModes:
    def test_extension_mode_returns_signing_required(self, seeded_store, monkeypatch):
        from datetime import datetime, timedelta, timezone
        from integrations.nostr_provider import NostrProvider
        from integrations.publishing_provider import (
            PublishErrorCode,
            PublishRequest,
        )

        service = NostrSigningService(seeded_store)
        provider = NostrProvider(signing_service=service)
        assert provider.is_configured() is True

        request = PublishRequest(
            content="provider note",
            platform="nostr",
            scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
        )
        result = provider.publish(request)

        assert result.success is False
        assert result.error_code == PublishErrorCode.SIGNING_REQUIRED
        assert "Pipeline tab" in result.error
        assert "Sign with extension" in result.error

        pending = seeded_store.list_nostr_request_records(status="pending_signature")
        assert len(pending) == 1
        assert pending[0]["unsigned_events"][0]["content"] == "provider note"
        # Future-dated for sign-now-publish-later.
        assert pending[0]["scheduled_at"] is not None

    def test_headless_mode_signs_and_schedules_with_project_key(self, seeded_store):
        """A per-project nsec can schedule+sign without NOSTR_PRIVATE_KEY env."""
        from integrations.nostr_provider import NostrProvider
        from integrations.publishing_provider import PublishRequest

        service = NostrSigningService(seeded_store)
        keys = Keys.generate()

        provider = NostrProvider(
            private_key=keys.secret_key().to_bech32(),
            signing_service=service,
        )
        result = provider.publish(
            PublishRequest(
                content="headless note",
                platform="nostr",
                scheduled_at=datetime.now(timezone.utc) + timedelta(hours=1),
            )
        )
        assert result.success is True
        assert result.scheduled is True
        assert result.post_id

        stored = seeded_store.list_nostr_request_records(status="signed")
        assert len(stored) == 1
        assert stored[0]["signer_pubkey"] == keys.public_key().to_hex()
