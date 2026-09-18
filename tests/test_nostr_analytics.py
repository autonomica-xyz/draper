"""Unit tests for Nostr analytics persistence and edge cases."""

from __future__ import annotations

from nostr.nostr_analytics import NostrAnalytics


def test_refresh_engagement_preserves_metrics_on_relay_failure(tmp_path, monkeypatch):
    """M2 regression: a failed relay query must not zero stored engagement."""
    analytics = NostrAnalytics(data_dir=str(tmp_path))
    analytics.record_event(
        event_id="deadbeef" * 4,
        kind=1,
        content="hello #nostr",
        published_at="2026-01-01T00:00:00+00:00",
    )
    # Simulate a previous successful refresh.
    analytics.events[0]["metrics"]["likes"] = 5
    analytics.events[0]["metrics"]["reposts"] = 2

    monkeypatch.setattr("nostr.relay_client.fetch_engagement_sync", lambda *a, **k: None)

    result = analytics.refresh_engagement()
    assert result["refreshed"] == 0
    assert result["reason"] == "relay query failed"
    assert analytics.events[0]["metrics"]["likes"] == 5
    assert analytics.events[0]["metrics"]["reposts"] == 2


def test_refresh_engagement_does_not_overwrite_with_empty_success(tmp_path, monkeypatch):
    """A successful query that finds no engagement should not wipe existing metrics."""
    analytics = NostrAnalytics(data_dir=str(tmp_path))
    analytics.record_event(
        event_id="cafebabe" * 4,
        kind=1,
        content="hello again",
        published_at="2026-01-01T00:00:00+00:00",
    )
    analytics.events[0]["metrics"]["likes"] = 3

    monkeypatch.setattr("nostr.relay_client.fetch_engagement_sync", lambda *a, **k: {})

    result = analytics.refresh_engagement()
    assert result["refreshed"] == 0
    assert analytics.events[0]["metrics"]["likes"] == 3
