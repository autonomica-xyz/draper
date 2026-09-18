"""Unit tests for nostr.event_builder (pure event construction)."""

from __future__ import annotations

from nostr.event_builder import (
    KIND_LONG_FORM,
    KIND_NOTE,
    build_deletion_event,
    build_events_for_post_data,
    build_long_form_event,
    build_note_event,
    build_thread_events,
    extract_hashtags,
    parse_event_time,
    redact_secrets,
    split_thread,
    unsigned_event_matches,
)


class TestParseEventTime:
    def test_unix_seconds_passthrough(self):
        assert parse_event_time(1700000000) == 1700000000

    def test_milliseconds_converted(self):
        assert parse_event_time(1700000000000) == 1700000000

    def test_numeric_string(self):
        assert parse_event_time("1700000000") == 1700000000

    def test_iso_string(self):
        value = parse_event_time("2026-02-06T14:45:16Z")
        assert value is not None
        assert abs(value - 1770389116) < 5  # tolerate clock/tz drift

    def test_garbage_returns_none(self):
        assert parse_event_time("not-a-time") is None
        assert parse_event_time("") is None
        assert parse_event_time(None) is None
        assert parse_event_time(-5) is None


class TestHashtags:
    def test_extracts_deduped_lowercase(self):
        assert extract_hashtags("Hello #Nostr and #nostr plus #AI #ai") == ["nostr", "ai"]

    def test_respects_limit(self):
        tags = extract_hashtags("#a #b #c #d #e #f #g")
        assert len(tags) == 5


class TestSplitThread:
    def test_inline_tweet_labels(self):
        content = "Tweet 1: first\nmore\n\nTweet 2: second"
        assert split_thread(content) == ["first\nmore", "second"]

    def test_label_only_lines(self):
        content = "Tweet 1\nbody one\n\nTweet 2\nbody two"
        assert split_thread(content) == ["body one", "body two"]

    def test_paragraph_fallback(self):
        assert split_thread("para one\n\npara two") == ["para one", "para two"]

    def test_single_post(self):
        assert split_thread("just one note") == ["just one note"]


class TestBuildNoteEvent:
    def test_tags_and_client_attribution(self):
        event = build_note_event("hello #draper", created_at=1700000000)
        assert event["kind"] == KIND_NOTE
        assert event["created_at"] == 1700000000
        assert ["t", "draper"] in event["tags"]
        assert ["client", "draper-pipeline"] in event["tags"]

    def test_thread_markers(self):
        event = build_note_event(
            "reply",
            created_at=1700000000,
            root="a" * 64,
            reply_to="b" * 64,
        )
        e_tags = [tag for tag in event["tags"] if tag[0] == "e"]
        assert e_tags[0] == ["e", "a" * 64, "", "root"]
        assert e_tags[1] == ["e", "b" * 64, "", "reply"]

    def test_redacts_nsec(self):
        leaked = "nsec1" + "q" * 50
        event = build_note_event(f"leak {leaked}", created_at=1)
        assert "nsec1" not in event["content"]
        assert redact_secrets(leaked) == "[redacted]"


class TestLongForm:
    def test_kind_30023_with_d_title_published_at(self):
        event = build_long_form_event("Title", "body", identifier="slug-1", created_at=1700000000)
        assert event["kind"] == KIND_LONG_FORM
        assert ["d", "slug-1"] in event["tags"]
        assert ["title", "Title"] in event["tags"]
        assert ["published_at", "1700000000"] in event["tags"]


class TestDeletion:
    def test_kind_5_e_tags(self):
        event = build_deletion_event(["a" * 64, "b" * 64], reason="typo", created_at=1)
        assert event["kind"] == 5
        assert ["e", "a" * 64] in event["tags"]
        assert ["e", "b" * 64] in event["tags"]


class TestBuildEventsForPostData:
    def test_blog_routes_to_long_form(self):
        events = build_events_for_post_data(
            {"content": "long " * 100, "content_type": "blog", "title": "Big Post"},
            created_at=1700000000,
        )
        assert len(events) == 1
        assert events[0]["kind"] == KIND_LONG_FORM

    def test_thread_routes_to_chained_notes(self):
        content = "Tweet 1: one\n\nTweet 2: two\n\nTweet 3: three"
        events = build_events_for_post_data(
            {"content": content, "platform": "twitter"}, created_at=1700000000
        )
        assert [e["kind"] for e in events] == [KIND_NOTE] * 3

    def test_plain_note(self):
        events = build_events_for_post_data({"content": "single note"}, created_at=1700000000)
        assert len(events) == 1
        assert events[0]["kind"] == KIND_NOTE

    def test_empty_content(self):
        assert build_events_for_post_data({"content": ""}, created_at=1) == []


class TestUnsignedEventMatches:
    def test_matches(self):
        unsigned = build_note_event("x", created_at=1)
        signed = dict(unsigned, pubkey="a" * 64, id="b" * 64, sig="c" * 64)
        assert unsigned_event_matches(signed, unsigned)

    def test_content_tamper_detected(self):
        unsigned = build_note_event("x", created_at=1)
        signed = dict(unsigned, content="y")
        assert not unsigned_event_matches(signed, unsigned)

    def test_tag_tamper_detected(self):
        unsigned = build_note_event("x", created_at=1)
        signed = dict(unsigned, tags=[["t", "evil"]])
        assert not unsigned_event_matches(signed, unsigned)


class TestBuildThreadEvents:
    def test_incrementing_timestamps(self):
        events = build_thread_events(["a", "b", "c"], created_at=100)
        assert [e["created_at"] for e in events] == [100, 101, 102]
        assert events[0]["tags"]  # first part keeps hashtags
