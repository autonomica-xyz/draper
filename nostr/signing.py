"""Signing and verification helpers backed by the ``nostr-sdk`` Python package.

Two signing modes are supported, mirroring the nostr-cms architecture where
the CMS itself never needs to hold a private key:

* **Server keys** (headless): ``NOSTR_PRIVATE_KEY`` / ``~/.nostr/private_key.txt``
  is loaded into ``nostr_sdk.Keys`` and signs events directly.
* **NIP-07 extension** (nos2x, Alby, ...): the server only prepares unsigned
  events (``nostr.event_builder``), a human signs them in the browser via
  ``window.nostr.signEvent``, and ``verify_signed_event`` validates the
  result before it is stored for later publishing.

Everything that touches ``nostr_sdk`` lives here so the rest of the pipeline
can degrade gracefully when the SDK is not installed.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from nostr_sdk import Event, EventBuilder, Keys, Kind, PublicKey, Tag, Timestamp

    SDK_AVAILABLE = True
except ImportError:  # pragma: no cover - exercised only without nostr-sdk
    SDK_AVAILABLE = False


class SigningError(ValueError):
    """Raised when key material is missing or an event fails verification."""


def sdk_available() -> bool:
    return SDK_AVAILABLE


def load_keys(private_key: Optional[str] = None) -> Optional["Keys"]:
    """Resolve server-side keys from an injected value, env, or key file.

    Accepts ``nsec1...`` bech32 or 32-byte hex. Returns ``None`` when no
    key is configured (extension signing mode).
    """
    if not SDK_AVAILABLE:
        return None

    candidate = private_key or os.getenv("NOSTR_PRIVATE_KEY")
    if not candidate:
        key_file = Path.home() / ".nostr" / "private_key.txt"
        if key_file.exists():
            candidate = key_file.read_text().strip()

    if not candidate:
        return None

    try:
        return Keys.parse(candidate)
    except Exception as exc:
        raise SigningError(f"Invalid Nostr private key: {exc}") from exc


def npub_of(keys) -> Optional[str]:
    """Return the ``npub1...`` bech32 encoding of a key pair's public key."""
    if keys is None or not SDK_AVAILABLE:
        return None
    try:
        return keys.public_key().to_bech32()
    except Exception:
        return None


def normalize_pubkey(value: str) -> Optional[str]:
    """Normalize an ``npub1...``/hex pubkey to 64-char hex."""
    if not value or not SDK_AVAILABLE:
        return None
    try:
        return PublicKey.parse(value.strip()).to_hex()
    except Exception:
        return None


def expected_signer_pubkey(explicit: Optional[str] = None) -> Optional[str]:
    """Resolve the pinned signer pubkey (hex) if one is configured.

    ``NOSTR_PUBKEY`` pins which extension identity is allowed to sign for
    this deployment, mirroring nostr-cms's master-pubkey admin gate.
    """
    candidate = explicit or os.getenv("NOSTR_PUBKEY")
    if not candidate:
        return None
    normalized = normalize_pubkey(candidate)
    if not normalized:
        raise SigningError("NOSTR_PUBKEY is set but is not a valid npub/hex pubkey")
    return normalized


def _tags_to_sdk(tags) -> list:
    """Convert ``[["t", "value"], ...]`` lists to nostr-sdk Tag objects."""
    converted = []
    for tag in tags or []:
        if isinstance(tag, Tag):
            converted.append(tag)
            continue
        converted.append(Tag.parse([str(item) for item in tag]))
    return converted


def sign_unsigned_event(unsigned: Dict, keys: "Keys"):
    """Sign an unsigned event dict with server-side keys."""
    if not SDK_AVAILABLE:
        raise SigningError("nostr-sdk is not installed; cannot sign server-side")
    try:
        builder = EventBuilder(Kind(int(unsigned["kind"])), str(unsigned.get("content", "")))
        builder = builder.tags(_tags_to_sdk(unsigned.get("tags", [])))
        created_at = int(unsigned.get("created_at", 0))
        if created_at > 0:
            builder = builder.custom_created_at(Timestamp.from_secs(created_at))
        return builder.finalize(keys)
    except SigningError:
        raise
    except Exception as exc:
        raise SigningError(f"Failed to sign event: {exc}") from exc


def sign_event_chain(unsigned_events, keys) -> list:
    """Sign a list of unsigned events, stitching thread reply tags.

    Each Kind 1 part after the first references the previous part's signed
    event id with NIP-10 ``root``/``reply`` markers, so the thread renders
    correctly in Damus / nos.social / primal. Returns signed event dicts.
    """
    signed_events = []
    root_id = None
    previous_id = None
    for unsigned in unsigned_events:
        candidate = dict(unsigned)
        if int(candidate.get("kind", 0)) == 1 and previous_id:
            tags = [list(tag) for tag in candidate.get("tags", [])]
            if root_id and root_id != previous_id:
                tags.insert(0, ["e", previous_id, "", "reply"])
                tags.insert(0, ["e", root_id, "", "root"])
            else:
                tags.insert(0, ["e", previous_id, "", "root"])
            candidate["tags"] = tags

        signed_dict = event_to_dict(sign_unsigned_event(candidate, keys))
        if root_id is None:
            root_id = signed_dict["id"]
        previous_id = signed_dict["id"]
        signed_events.append(signed_dict)
    return signed_events


def event_to_dict(event: "Event") -> Dict:
    """Convert a nostr-sdk Event to the plain dict NIP-07 flows use."""
    return {
        "id": event.id().to_hex(),
        "pubkey": event.author().to_hex(),
        "created_at": event.created_at().as_secs(),
        "kind": event.kind().as_u16(),
        "tags": [tag.to_vec() for tag in event.tags()],
        "content": event.content(),
        "sig": event.signature(),
    }


def event_from_dict(payload: Dict) -> "Event":
    """Parse a signed event dict (as POSTed from the browser) into an Event."""
    if not SDK_AVAILABLE:
        raise SigningError("nostr-sdk is not installed; cannot verify events")
    try:
        return Event.from_json(json.dumps(payload))
    except Exception as exc:
        raise SigningError(f"Malformed signed event: {exc}") from exc


def verify_signed_event(
    payload: Dict,
    *,
    unsigned: Optional[Dict] = None,
    expected_pubkey: Optional[str] = None,
    expected_extra_tags: Optional[List[List[str]]] = None,
) -> Tuple[bool, str]:
    """Verify a signed event coming back from any signer (extension or server).

    Checks, in order:

    1. Required fields are present (id, pubkey, sig, kind, content, created_at, tags).
    2. The event id matches the serialized event (``Event.verify`` recomputes it).
    3. The schnorr signature is valid for the embedded pubkey.
    4. The event still matches the unsigned event we prepared (anti-tamper),
       optionally allowing ``expected_extra_tags`` as a leading prefix.
    5. ``created_at`` is sane (within a loose 10-year bound; sign-now-publish-later
       intentionally uses future timestamps, so the anti-tamper check in (4)
       is the real guard against a signer re-dating an event).
    6. The signer is the pinned ``expected_pubkey`` when one is configured.

    Returns ``(ok, reason)``; reason is human-readable on failure.
    """
    if not SDK_AVAILABLE:
        return False, "nostr-sdk is not installed"

    for field in ("id", "pubkey", "sig", "kind", "content", "created_at", "tags"):
        if field not in payload:
            return False, f"signed event is missing '{field}'"

    from nostr.event_builder import unsigned_event_matches

    try:
        event = event_from_dict(payload)
    except SigningError as exc:
        return False, str(exc)

    try:
        if not event.verify():
            return False, "event id or signature is invalid"
    except Exception as exc:
        return False, f"verification failed: {exc}"

    created_at = int(payload.get("created_at", 0))
    if created_at > int(time.time()) + 10 * 365 * 24 * 3600:
        return False, "created_at is implausibly far in the future"

    if unsigned is not None and not unsigned_event_matches(
        payload, unsigned, expected_leading_tags=expected_extra_tags
    ):
        return False, "signed event does not match the prepared event"

    if expected_pubkey:
        signer_hex = normalize_pubkey(str(payload.get("pubkey", "")))
        pinned_hex = normalize_pubkey(expected_pubkey)
        if not signer_hex or signer_hex != pinned_hex:
            return False, "signed with an unexpected pubkey"

    return True, ""


def event_bech32_id(event_id_hex: str) -> Optional[str]:
    """``note1...`` encoding of an event id hex."""
    if not SDK_AVAILABLE or not event_id_hex:
        return None
    try:
        from nostr_sdk import EventId

        return EventId.parse(event_id_hex).to_bech32()
    except Exception:
        return None


def event_uri(event_id_hex: str, *, relays=None, author=None) -> Optional[str]:
    """NIP-21 ``nostr:nevent1...`` URI for sharing published events."""
    if not SDK_AVAILABLE or not event_id_hex:
        return None
    try:
        from nostr_sdk import EventId

        event_id = EventId.parse(event_id_hex)
        if relays or author:
            relay_urls = [str(r) for r in (relays or [])][:2]
            author_hex = normalize_pubkey(author) if author else None
            return event_id.to_nostr_uri(relays=relay_urls, author=author_hex)
        return event_id.to_nostr_uri()
    except Exception:
        return event_bech32_id(event_id_hex)
