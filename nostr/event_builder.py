"""Pure-Python construction of Nostr events (no SDK required).

Ideas adapted from nostr-cms:

* Kind routing -- short posts become Kind 1 text notes, long-form content
  becomes Kind 30023 (NIP-23) with ``d``/``title``/``published_at`` tags.
* Threads use NIP-10 ``root``/``reply`` markers instead of bare ``e`` tags.
* Every published event carries a ``client`` attribution tag.
* ``parse_event_time`` mirrors ``src/lib/eventTime.ts`` -- it accepts unix
  seconds, unix milliseconds, and ISO 8601 strings.

Keeping this module SDK-free makes the event shapes easy to unit test and
lets the dashboard hand the exact same unsigned event dictionaries to a
NIP-07 browser extension (nos2x, Alby, ...) for signing.
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Optional

# Kinds used by the pipeline (mirrors the nostr-cms kind map).
KIND_NOTE = 1
KIND_PROFILE = 0
KIND_REACTION = 7
KIND_REPOST = 6
KIND_LONG_FORM = 30023
KIND_RELAY_LIST = 10002
KIND_DELETION = 5
KIND_ZAP_RECEIPT = 9735

CLIENT_TAG_NAME = "draper-pipeline"
MAX_HASHTAGS = 5

_HASHTAG_RE = re.compile(r"(?<![\w/])#([A-Za-z0-9_]+)")
_NSEC_RE = re.compile(r"nsec1[0-9a-z]{20,}", re.IGNORECASE)
_THREAD_SPLIT_RE = re.compile(r"^\s*(?:tweet|part|post)\s*(\d+)\s*[:.)\-]\s*(.*)$", re.IGNORECASE)
_THREAD_LABEL_ONLY_RE = re.compile(r"^\s*(?:tweet|part|post)\s*\d+\s*[:.)\-]?\s*$", re.IGNORECASE)


def parse_event_time(value) -> Optional[int]:
    """Tolerant timestamp parsing (stolen from nostr-cms ``eventTime.ts``).

    Accepts unix seconds, unix milliseconds, and ISO 8601 strings.
    Returns unix seconds or ``None`` when the value is unusable.
    """
    if value is None:
        return None
    if isinstance(value, (int, float)):
        numeric = int(value)
        if numeric <= 0:
            return None
        if numeric > 1_000_000_000_000:  # milliseconds
            return numeric // 1000
        return numeric

    text = str(value).strip()
    if not text:
        return None
    if text.isdigit():
        return parse_event_time(int(text))

    from datetime import datetime, timezone

    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return int(parsed.timestamp())


def extract_hashtags(content: str, limit: int = MAX_HASHTAGS) -> List[str]:
    """Extract deduplicated lowercase hashtags from note content."""
    seen: dict = {}
    for match in _HASHTAG_RE.finditer(content or ""):
        tag = match.group(1).lower()
        if len(tag) > 64:
            continue
        seen.setdefault(tag, None)
    return list(seen.keys())[:limit]


def redact_secrets(content: str) -> str:
    """Strip anything that looks like a Nostr private key from content."""
    return _NSEC_RE.sub("[redacted]", content or "")


def _base_event(kind: int, content: str, created_at: int) -> Dict:
    """Unsigned event skeleton in the shape NIP-07 ``signEvent`` expects."""
    return {
        "kind": kind,
        "content": content,
        "created_at": created_at,
        "tags": [],
        "pubkey": "",
    }


def build_note_event(
    content: str,
    *,
    hashtags: Optional[Iterable[str]] = None,
    extra_tags: Optional[List[List[str]]] = None,
    reply_to: Optional[str] = None,
    root: Optional[str] = None,
    client: str = CLIENT_TAG_NAME,
    created_at: int,
) -> Dict:
    """Build an unsigned Kind 1 text note.

    ``reply_to``/``root`` produce NIP-10 marked ``e`` tags so threads render
    correctly in Damus / nos.social / primal.
    """
    event = _base_event(KIND_NOTE, redact_secrets(content), created_at)
    tags: List[List[str]] = []

    if root:
        tags.append(["e", root, "", "root"])
    if reply_to:
        marker = "reply" if root else "root"
        tags.append(["e", reply_to, "", marker])

    merged_hashtags = list(hashtags) if hashtags is not None else extract_hashtags(content)
    for tag in merged_hashtags:
        if tag:
            tags.append(["t", str(tag).lower()])

    for tag in extra_tags or []:
        tags.append(list(tag))

    if client:
        tags.append(["client", client])

    event["tags"] = tags
    return event


def build_long_form_event(
    title: str,
    content: str,
    *,
    identifier: Optional[str] = None,
    hashtags: Optional[Iterable[str]] = None,
    client: str = CLIENT_TAG_NAME,
    created_at: int,
) -> Dict:
    """Build an unsigned Kind 30023 long-form post (NIP-23).

    ``identifier`` is the ``d`` tag; replaceable-event semantics let the same
    identifier be re-signed later to publish an edit.
    """
    event = _base_event(KIND_LONG_FORM, redact_secrets(content), created_at)
    tags: List[List[str]] = [
        ["d", identifier or f"draper-{created_at}"],
        ["title", title],
        ["published_at", str(created_at)],
    ]
    for tag in hashtags or []:
        if tag:
            tags.append(["t", str(tag).lower()])
    if client:
        tags.append(["client", client])
    event["tags"] = tags
    return event


def build_deletion_event(
    targets: Iterable[str],
    *,
    reason: str = "",
    client: str = CLIENT_TAG_NAME,
    created_at: int,
) -> Dict:
    """Build an unsigned Kind 5 deletion event for the given event ids."""
    event = _base_event(KIND_DELETION, reason or "", created_at)
    tags = [["e", target] for target in targets if target]
    if client:
        tags.append(["client", client])
    event["tags"] = tags
    return event


def split_thread(content: str) -> List[str]:
    """Split generated thread content into parts.

    Recognises the ``Tweet 2:`` / ``Part 2 -`` labels the generators emit, and
    falls back to blank-line paragraph splitting for single-label content.
    """
    lines = (content or "").splitlines()
    parts: List[str] = []
    current: List[str] = []
    saw_label = False
    for line in lines:
        match = _THREAD_SPLIT_RE.match(line)
        if match:
            saw_label = True
            if current:
                parts.append("\n".join(current).strip())
            current = []
            remainder = match.group(2).strip()
            if remainder:
                current.append(remainder)
        elif _THREAD_LABEL_ONLY_RE.match(line):
            saw_label = True
            if current:
                parts.append("\n".join(current).strip())
            current = []
        else:
            current.append(line)
    if current:
        parts.append("\n".join(current).strip())
    parts = [part for part in parts if part]
    if len(parts) <= 1 and not saw_label:
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", content or "") if p.strip()]
        if len(paragraphs) > 1:
            return paragraphs
    return parts


def build_thread_events(
    parts: List[str],
    *,
    hashtags: Optional[Iterable[str]] = None,
    client: str = CLIENT_TAG_NAME,
    created_at: int,
) -> List[Dict]:
    """Build a chain of unsigned Kind 1 notes (NIP-10 root/reply markers).

    The ``e`` tags reference the *previous* part's event id, which is only
    known after each part is signed. ``finalize_thread`` stitches them.
    """
    events = []
    for index, part in enumerate(parts):
        events.append(
            build_note_event(
                part,
                hashtags=hashtags if index == 0 else [],
                client=client,
                created_at=created_at + index,
            )
        )
    return events


def build_events_for_post_data(
    post_data: Dict,
    *,
    created_at: int,
    client: str = CLIENT_TAG_NAME,
) -> List[Dict]:
    """Convert a generator post_data dict into unsigned Nostr events.

    This is the shared shape used by both the headless publisher and the
    extension-signing flow, so what gets approved is what gets signed.
    """
    content = str(post_data.get("content", "")).strip()
    if not content:
        return []

    pillar = str(post_data.get("pillar", "") or "").strip()
    platform = str(post_data.get("platform", "") or "").strip()
    hashtags = extract_hashtags(content)
    if pillar and pillar.lower() not in hashtags and len(pillar) < 32:
        hashtags.insert(0, pillar.lower().replace(" ", "_"))
    if platform and platform.lower() not in hashtags and platform.lower() != "nostr":
        hashtags.append(platform.lower())

    content_type = str(post_data.get("content_type", "") or "").lower()
    title = str(post_data.get("title", "") or "").strip()

    # Long-form content goes out as NIP-23 (stolen from nostr-cms blog publishing).
    if content_type in {"blog", "article", "newsletter", "case_study", "press_release"} or (
        not content_type and title and len(content) > 280
    ):
        return [
            build_long_form_event(
                title or "Untitled",
                content,
                hashtags=hashtags,
                client=client,
                created_at=created_at,
            )
        ]

    thread_parts = split_thread(content)
    if len(thread_parts) > 1:
        return build_thread_events(
            thread_parts, hashtags=hashtags, client=client, created_at=created_at
        )

    return [build_note_event(content, hashtags=hashtags, client=client, created_at=created_at)]


def unsigned_event_matches(
    signed: Dict,
    unsigned: Dict,
    expected_leading_tags: Optional[List[List[str]]] = None,
) -> bool:
    """Check that a signed event still matches the unsigned event we prepared.

    Guards against a tampered/mismatched payload coming back from a signer.
    Kind, content, created_at and tags must be identical; ``pubkey`` is
    checked separately (it is filled in by the signer).

    ``expected_leading_tags`` allows the signer to prepend tags (e.g. NIP-10
    ``e`` root/reply markers in a thread) while still protecting all other
    fields. The signed event's tags are accepted if they match the unsigned
    tags either with or without the expected prefix.
    """

    def _tags_of(event: Dict) -> List[List[str]]:
        return [list(tag) for tag in event.get("tags", [])]

    signed_tags = _tags_of(signed)
    unsigned_tags = _tags_of(unsigned)
    candidates = [unsigned_tags]
    if expected_leading_tags:
        candidates.append([list(tag) for tag in expected_leading_tags] + unsigned_tags)

    return (
        signed.get("kind") == unsigned.get("kind")
        and signed.get("content") == unsigned.get("content")
        and signed.get("created_at") == unsigned.get("created_at")
        and signed_tags in candidates
    )
