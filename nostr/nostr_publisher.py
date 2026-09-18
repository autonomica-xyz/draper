#!/usr/bin/env python3
"""
Nostr Publisher for Draper Marketing Pipeline
Publishes generated marketing content to Nostr via the ``nostr-sdk`` package.

Architecture (ideas adapted from the nostr-cms project):

* **Multi-relay blast publishing** with per-relay results -- an event is
  sent to every configured relay and succeeds when at least one accepts it.
* **Kind routing** -- notes are Kind 1, long-form content is Kind 30023
  (NIP-23), threads use NIP-10 root/reply markers.
* **Sign-now-publish-later** -- ``build_unsigned_events`` produces exactly
  what was approved; events can be signed with a future ``created_at`` and
  broadcast later (see ``services/nostr_signing_service.py``).
* **Two signing modes** -- server-side keys (``NOSTR_PRIVATE_KEY``) for
  headless operation, or a NIP-07 browser extension (nos2x, Alby) via the
  dashboard signing page so no nsec ever lives on the server.

When ``nostr-sdk`` is not installed the publisher falls back to preparing
``nak`` CLI payloads, preserving the legacy behavior.
"""

import json
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pathlib import Path

# Allow direct execution: python nostr/nostr_publisher.py
_project_root = str(Path(__file__).resolve().parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

from nostr.event_builder import (  # noqa: E402
    KIND_DELETION,
    KIND_LONG_FORM,
    KIND_NOTE,
    KIND_PROFILE,
    KIND_REACTION,
    KIND_REPOST,
    build_deletion_event,
    build_events_for_post_data,
    build_note_event,
    extract_hashtags,
    split_thread,
)
from nostr.relay_client import publish_signed_event_sync, resolve_relays  # noqa: E402
from nostr import signing as nostr_signing  # noqa: E402


class NostrPublisher:
    """Publishes content to Nostr protocol using nostr-sdk."""

    def __init__(
        self,
        private_key: Optional[str] = None,
        relays: Optional[List[str]] = None,
    ):
        # Relay set: constructor > NOSTR_RELAYS env > defaults (two-tier
        # strategy from nostr-cms: primary + redundant publishing relays).
        self.relays = resolve_relays(relays)

        # Default kind values (Nostr event types)
        self.kinds = {
            "note": KIND_NOTE,
            "profile": KIND_PROFILE,
            "reaction": KIND_REACTION,
            "repost": KIND_REPOST,
            "long_form": KIND_LONG_FORM,
            "deletion": KIND_DELETION,
        }

        self._injected_key = private_key
        self._keys = None
        self.private_key = self._load_nostr_key()

        if self.private_key:
            keys = self._get_keys()
            self.public_key = nostr_signing.npub_of(keys) or "nostr_identity"
            print("✅ Nostr keys loaded")
        else:
            self.public_key = None
            print(
                "⚠️  No Nostr server keys found. Approved nostr posts will wait for a "
                "signature in the dashboard Pipeline tab, or set NOSTR_PRIVATE_KEY "
                "for headless publishing."
            )

    # ------------------------------------------------------------------
    # Key handling
    # ------------------------------------------------------------------

    def _load_nostr_key(self) -> Optional[str]:
        """Load Nostr private key from injected value, environment, or file."""
        if self._injected_key:
            return self._injected_key

        private_key = os.getenv("NOSTR_PRIVATE_KEY")
        if private_key:
            return private_key

        key_file = Path.home() / ".nostr" / "private_key.txt"
        if key_file.exists():
            return key_file.read_text().strip()

        return None

    def _get_keys(self):
        """Return nostr-sdk Keys for the configured private key (cached)."""
        if self._keys is None:
            self._keys = nostr_signing.load_keys(self.private_key)
        return self._keys

    @property
    def npub(self) -> Optional[str]:
        """``npub1...`` identity for display (NIP-19)."""
        return nostr_signing.npub_of(self._get_keys())

    # ------------------------------------------------------------------
    # Event construction
    # ------------------------------------------------------------------

    def build_unsigned_events(
        self,
        post_data: Dict,
        scheduled_at=None,
    ) -> List[Dict]:
        """Build the unsigned events for a generated post.

        ``scheduled_at`` (anything :func:`nostr.event_builder.parse_event_time`
        accepts) becomes the event ``created_at`` -- the sign-now-publish-later
        pattern: the timestamp is part of the signature, so a future-dated
        event can be signed ahead of time and relayed when due.
        """
        from .event_builder import parse_event_time

        created_at = parse_event_time(scheduled_at) or int(datetime.now(timezone.utc).timestamp())
        return build_events_for_post_data(post_data, created_at=created_at)

    def add_platform_tags(self, platform: str, pillar: str, topic: str) -> List[Dict]:
        """Platform-specific tag dictionaries (legacy dict shape).

        Kept for orchestrator compatibility; new code should prefer the
        ``[["t", "value"]]`` list shape used by nostr-sdk.
        """
        tags = [{"t": platform}, {"t": pillar}, {"t": "draper"}]
        if topic and len(topic) < 50:
            tags.append({"t": topic.lower().replace(" ", "_")})
        return tags

    def generate_nostr_content(self, post_data: Dict) -> Dict:
        """Convert generated post to Nostr-friendly format (legacy shape)."""
        content = post_data.get("content", "")
        platform = post_data.get("platform", "")
        pillar = post_data.get("pillar", "")
        topic = post_data.get("topic", "")

        if platform == "twitter" and (
            "Tweet 2:" in content or "Tweet 3:" in content or "Part 2:" in content
        ):
            return {
                "content_type": "thread",
                "parts": split_thread(content),
                "platform": platform,
                "pillar": pillar,
                "topic": topic,
            }

        return {
            "content_type": "note",
            "content": content,
            "platform": platform,
            "pillar": pillar,
            "topic": topic,
        }

    # ------------------------------------------------------------------
    # Signing + publishing
    # ------------------------------------------------------------------

    def _sign_events(self, unsigned_events: List[Dict]) -> List[Dict]:
        """Sign events with server keys, stitching thread reply tags."""
        keys = self._get_keys()
        if keys is None:
            raise nostr_signing.SigningError("No Nostr private key configured")
        return nostr_signing.sign_event_chain(unsigned_events, keys)

    def publish_signed_events(
        self,
        signed_events: List[Dict],
        relays: Optional[List[str]] = None,
    ) -> Dict:
        """Broadcast already-signed events; returns an aggregate result."""
        results = []
        for signed_event in signed_events:
            results.append(publish_signed_event_sync(signed_event, relays or self.relays))

        successful = [r for r in results if r.get("success")]
        if successful:
            return {
                "success": True,
                "event_id": successful[0].get("event_id"),
                "event_ids": [r.get("event_id") for r in successful],
                "published_to": max(r.get("published_to", 0) for r in successful),
                "total_events": len(results),
                "relays": [relay for r in results for relay in r.get("relays", [])],
            }
        first_failure = results[0] if results else {}
        return {
            "success": False,
            "message": first_failure.get("error", "Failed to publish to all relays"),
            "event_ids": [],
            "total_events": len(results),
            "relays": [relay for r in results for relay in r.get("relays", [])],
        }

    def publish_note(
        self,
        content: str,
        tags: Optional[List[Dict]] = None,
        scheduled_at=None,
    ) -> Dict:
        """Publish a text note to Nostr.

        Args:
            content: The note content
            tags: Optional legacy tag dictionaries ``[{"t": "tag"}]``
            scheduled_at: Optional future timestamp; the note is dated then

        Returns:
            Dict with event ID, per-relay results, and status
        """
        if not self.private_key or not nostr_signing.sdk_available():
            event = build_note_event(
                content,
                extra_tags=[[key, value] for tag in (tags or []) for key, value in tag.items()],
                created_at=int(datetime.now(timezone.utc).timestamp()),
            )
            return self._prepare_for_nak(event)

        from .event_builder import parse_event_time

        created_at = parse_event_time(scheduled_at) or int(datetime.now(timezone.utc).timestamp())
        unsigned = build_note_event(
            content,
            extra_tags=[[key, value] for tag in (tags or []) for key, value in tag.items()],
            created_at=created_at,
        )
        try:
            signed_events = self._sign_events([unsigned])
        except nostr_signing.SigningError as exc:
            return {"success": False, "message": str(exc), "event_id": None}

        result = self.publish_signed_events(signed_events)
        if result.get("success"):
            result.setdefault("message", "Published successfully")
            result["event_uri"] = nostr_signing.event_uri(result.get("event_id"))
        return result

    def create_thread(self, thread_content: List[str]) -> Dict:
        """Create a Nostr thread from a list of post parts."""
        if not self.private_key or not nostr_signing.sdk_available():
            # Legacy fallback: publish each part as an independent note.
            thread_events = []
            for content in thread_content:
                thread_events.append(
                    self.publish_note(content) if self.private_key else {"success": False}
                )
            return {
                "success": False,
                "message": "No Nostr private key configured",
                "thread_events": thread_events,
                "total_events": len(thread_content),
            }

        now = int(datetime.now(timezone.utc).timestamp())
        unsigned_events = []
        for index, content in enumerate(thread_content):
            unsigned_events.append(
                build_note_event(
                    content,
                    hashtags=extract_hashtags(content) if index == 0 else [],
                    created_at=now + index,
                )
            )

        try:
            signed_events = self._sign_events(unsigned_events)
        except nostr_signing.SigningError as exc:
            return {
                "success": False,
                "message": str(exc),
                "thread_events": [],
                "total_events": len(thread_content),
            }

        result = self.publish_signed_events(signed_events)
        result["thread_events"] = [self._thread_event_summary(event) for event in signed_events]
        result["total_events"] = len(signed_events)
        return result

    @staticmethod
    def _thread_event_summary(signed_event: Dict) -> Dict:
        return {
            "success": True,
            "event_id": signed_event.get("id"),
            "message": "Signed and published",
        }

    def delete_events(self, event_ids: List[str], reason: str = "") -> Dict:
        """Publish a Kind 5 deletion request for previously published events."""
        if not self.private_key or not nostr_signing.sdk_available():
            return {
                "success": False,
                "message": "No Nostr private key configured for deletion",
            }
        unsigned = build_deletion_event(
            event_ids,
            reason=reason,
            created_at=int(datetime.now(timezone.utc).timestamp()),
        )
        try:
            signed_events = self._sign_events([unsigned])
        except nostr_signing.SigningError as exc:
            return {"success": False, "message": str(exc)}
        return self.publish_signed_events(signed_events)

    def _prepare_for_nak(self, event: Dict) -> Dict:
        """Prepare event JSON for nak CLI tool (no nostr-sdk installed)."""
        return {
            "success": True,  # Prepared successfully
            "message": (
                "Content prepared for Nostr. nostr-sdk is not installed; "
                "run with: cat event.json | nak event <relay>"
            ),
            "nak_command": {
                "kind": event["kind"],
                "content": event["content"],
                "created_at": event.get("created_at"),
                "tags": [list(tag) for tag in event.get("tags", [])],
            },
            "event_id": None,  # Will be assigned after publishing
            "requires_manual_publish": True,
        }

    def publish_from_post_data(self, post_data: Dict, scheduled_at=None) -> Dict:
        """Publish a generated post to Nostr.

        Long-form content becomes Kind 30023; thread-shaped content becomes a
        chained Kind 1 thread; everything else is a single Kind 1 note.
        """
        unsigned_events = self.build_unsigned_events(post_data, scheduled_at=scheduled_at)
        if not unsigned_events:
            return {"success": False, "message": "No content to publish", "event_id": None}

        if not self.private_key or not nostr_signing.sdk_available():
            return self._prepare_for_nak(unsigned_events[0])

        try:
            signed_events = self._sign_events(unsigned_events)
        except nostr_signing.SigningError as exc:
            return {"success": False, "message": str(exc), "event_id": None}

        result = self.publish_signed_events(signed_events)
        if result.get("success"):
            result["event_uri"] = nostr_signing.event_uri(result.get("event_id"))
            result["message"] = (
                f"Published {result.get('total_events', 1)} event(s) to "
                f"{result.get('published_to', 0)} relay(s)"
            )
        return result


def main():
    """CLI for Nostr publishing"""
    import argparse

    parser = argparse.ArgumentParser(description="Publish content to Nostr")
    parser.add_argument("--test", action="store_true", help="Test Nostr key and connection")
    parser.add_argument("--note", help="Publish a text note")
    parser.add_argument("--key", help="Nostr private key (nsec or hex)")
    parser.add_argument("--relays", help="Comma-separated relay URLs")
    parser.add_argument("--generate-key", action="store_true", help="Generate new Nostr key pair")
    parser.add_argument("--delete", help="Comma-separated event ids to delete (Kind 5)")
    parser.add_argument("--reason", default="", help="Deletion reason")

    args = parser.parse_args()

    publisher = NostrPublisher(
        private_key=args.key,
        relays=args.relays.split(",") if args.relays else None,
    )

    if args.generate_key:
        if nostr_signing.sdk_available():
            from nostr_sdk import Keys

            keys = Keys.generate()
            print("Generated new Nostr key pair:")
            print(f"  npub (public):  {keys.public_key().to_bech32()}")
            print("  nsec (private): keep secret -- set as NOSTR_PRIVATE_KEY")
            print(
                "  For extension signing instead, install nos2x/Alby and use "
                "the Pipeline tab -- no server key needed."
            )
            return 0
        print("To generate Nostr keys, install nostr-sdk (pip install nostr-sdk)")
        return 1

    if args.test:
        if publisher.private_key:
            print("✅ Nostr private key found")
            print(f"   npub: {publisher.npub or '[unavailable]'}")
        else:
            print("⚠️  No Nostr server key found -- extension signing mode")
            print("   Sign approved nostr posts in the dashboard Pipeline tab with nos2x")
            print("   or Alby (NIP-07),")
            print("   or set NOSTR_PRIVATE_KEY for headless publishing.")
        print("\nRelays configured:")
        for relay in publisher.relays:
            print(f"  - {relay}")
        return 0

    if args.note:
        result = publisher.publish_note(args.note)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("success") else 1

    if args.delete:
        result = publisher.delete_events([e.strip() for e in args.delete.split(",")], args.reason)
        print(json.dumps(result, indent=2, default=str))
        return 0 if result.get("success") else 1

    print("Usage:")
    print("  --test                     Test Nostr configuration")
    print("  --note <content>           Publish a text note")
    print("  --delete <id,id,...>       Delete published events (Kind 5)")
    print("  --generate-key             Generate new Nostr key pair")
    print("  --relays wss://a,wss://b   Override relay list")
    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
