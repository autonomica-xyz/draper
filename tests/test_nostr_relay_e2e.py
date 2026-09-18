"""End-to-end Nostr tests against nostr-sdk's embedded local relay.

Runs fully offline: LocalRelay serves a real websocket relay in-process, so
sign -> broadcast -> read-back -> engagement all exercise the true code path.
"""

from __future__ import annotations

import pytest

nostr_sdk = pytest.importorskip("nostr_sdk")

from nostr_sdk import (  # noqa: E402
    Client,
    EventBuilder as SdkBuilder,
    EventId,
    Keys,
    Kind as SdkKind,
    LocalRelayBuilder,
    RelayUrl,
    Tag,
)

from nostr import relay_client, signing  # noqa: E402
from nostr.event_builder import build_note_event  # noqa: E402
from nostr.nostr_publisher import NostrPublisher  # noqa: E402


@pytest.fixture
def relay_url():
    """Start an in-process relay; yields its ws:// URL."""

    class RelayHandle:
        def __init__(self, relay, url):
            self.relay = relay
            self.url = url

    import asyncio

    async def _start():
        relay = LocalRelayBuilder().build()
        await relay.run()
        url = str(await relay.url())
        return RelayHandle(relay, url)

    handle = asyncio.run(_start())
    yield handle.url
    handle.relay.shutdown()


@pytest.fixture(autouse=True)
def _no_server_key(monkeypatch, tmp_path):
    monkeypatch.delenv("NOSTR_PRIVATE_KEY", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))


class TestPublishAndEngagement:
    def test_sign_broadcast_and_read_back(self, relay_url):
        keys = Keys.generate()
        unsigned = build_note_event("e2e note #draper", created_at=1700000000)
        signed = signing.sign_event_chain([unsigned], keys)[0]

        result = relay_client.publish_signed_event_sync(signed, [relay_url])
        assert result["success"] is True
        assert result["published_to"] >= 1

        import asyncio

        async def _read():
            client = Client()
            await client.add_relay(RelayUrl.parse(relay_url), and_connect=True)
            from nostr_sdk import Filter, ReqTarget

            events = await client.fetch_events(
                ReqTarget.auto([Filter().ids([EventId.parse(signed["id"])])]),
                timeout=None,
            )
            await client.disconnect()
            return list(events)

        found = asyncio.run(_read())
        assert any(e.id().to_hex() == signed["id"] for e in found)
        assert any(e.content() == "e2e note #draper" for e in found)

    def test_engagement_counts(self, relay_url):
        import asyncio

        keys = Keys.generate()
        unsigned = build_note_event("target", created_at=1700000001)
        signed = signing.sign_event_chain([unsigned], keys)[0]
        assert relay_client.publish_signed_event_sync(signed, [relay_url])["success"]

        fan = Keys.generate()
        etag = Tag.event(EventId.parse(signed["id"]))
        reaction = SdkBuilder(SdkKind(7), "+").tags([etag]).finalize(fan)
        reply = SdkBuilder(SdkKind(1), "nice").tags([etag]).finalize(fan)

        async def _fan_out():
            client = Client()
            await client.add_relay(RelayUrl.parse(relay_url), and_connect=True)
            await client.send_event(reaction)
            await client.send_event(reply)
            await client.disconnect()

        asyncio.run(_fan_out())

        stats = relay_client.fetch_engagement_sync([signed["id"]], [relay_url])
        assert stats[signed["id"]]["reactions"] == 1
        assert stats[signed["id"]]["replies"] == 1
        assert stats[signed["id"]]["reposts"] == 0

    def test_publisher_end_to_end_with_server_key(self, relay_url, monkeypatch):
        keys = Keys.generate()
        monkeypatch.setenv("NOSTR_PRIVATE_KEY", keys.secret_key().to_bech32())
        publisher = NostrPublisher(relays=[relay_url])
        assert publisher.npub == keys.public_key().to_bech32()

        result = publisher.publish_from_post_data(
            {"content": "hello from the pipeline #draper", "platform": "nostr"}
        )
        assert result["success"] is True
        assert result["event_id"]
        assert result["event_uri"].startswith("nostr:")
        assert result["published_to"] >= 1

    def test_thread_publishing_chains_events(self, relay_url, monkeypatch):
        keys = Keys.generate()
        monkeypatch.setenv("NOSTR_PRIVATE_KEY", keys.secret_key().to_bech32())
        publisher = NostrPublisher(relays=[relay_url])

        result = publisher.publish_from_post_data(
            {
                "content": "Tweet 1: first\n\nTweet 2: second",
                "platform": "twitter",
            }
        )
        assert result["success"] is True
        assert result["total_events"] == 2

        import asyncio

        async def _read():
            client = Client()
            await client.add_relay(RelayUrl.parse(relay_url), and_connect=True)
            from nostr_sdk import Filter, ReqTarget

            events = await client.fetch_events(
                ReqTarget.auto([Filter().authors([keys.public_key()])]),
                timeout=None,
            )
            await client.disconnect()
            return list(events)

        notes = asyncio.run(_read())
        replies = [n for n in notes if any(t.to_vec()[0] == "e" for t in n.tags())]
        assert replies, "second thread part must reference the first via an e tag"
