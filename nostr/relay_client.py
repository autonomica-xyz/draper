"""Relay broadcast + engagement reads via ``nostr-sdk``.

Steals the nostr-cms two-tier relay strategy:

* A configurable relay set (``NOSTR_RELAYS`` env, per-call override, or sane
  defaults) is used for **blast publishing** -- every event goes to every
  relay and we report per-relay outcomes.
* Success means "accepted by at least one relay" (relays are best-effort),
  but full results are kept so the UI can show partial failures.
* Engagement reads (reactions, reposts, replies, zaps) are aggregated across
  the relay set the same way nostr-cms zaplytics aggregates Kind 9735 zap
  receipts -- this feeds the pipeline's learning loop with real data.
"""

from __future__ import annotations

import asyncio
import json
import os
from datetime import timedelta
from typing import Dict, Iterable, List, Optional

try:
    from nostr_sdk import Client, Event, Filter, Kind, RelayUrl, ReqTarget

    SDK_AVAILABLE = True
except ImportError:  # pragma: no cover
    SDK_AVAILABLE = False

DEFAULT_RELAYS = [
    "wss://relay.damus.io",
    "wss://relay.primal.net",
    "wss://nos.lol",
]

DEFAULT_TIMEOUT_SECS = 10.0
ENGAGEMENT_TIMEOUT_SECS = 6.0


def resolve_relays(explicit: Optional[Iterable[str]] = None) -> List[str]:
    """Resolve the relay list: explicit argument > ``NOSTR_RELAYS`` env > defaults."""
    if explicit:
        candidates = [str(relay).strip() for relay in explicit]
    else:
        env_relays = os.getenv("NOSTR_RELAYS", "")
        candidates = [relay.strip() for relay in env_relays.split(",")] if env_relays else []

    normalized: List[str] = []
    for relay in candidates:
        if not relay:
            continue
        if not relay.startswith(("ws://", "wss://")):
            relay = f"wss://{relay}"
        if relay not in normalized:
            normalized.append(relay)
    return normalized or list(DEFAULT_RELAYS)


def _event_ids_to_sdk(event_ids: Iterable[str]) -> List:
    from nostr_sdk import EventId

    ids = []
    for event_id in event_ids:
        try:
            ids.append(EventId.parse(str(event_id)))
        except Exception:
            continue
    return ids


async def publish_signed_event(
    event_payload: Dict,
    relays: Optional[List[str]] = None,
    *,
    timeout_secs: float = DEFAULT_TIMEOUT_SECS,
) -> Dict:
    """Broadcast a signed event to every configured relay.

    Returns ``{"success", "event_id", "published_to", "relays"}`` where
    ``relays`` carries per-relay success/error detail (nostr-sdk's
    ``SendEventOutput`` already aggregates acks for us).
    """
    relay_urls = resolve_relays(relays)
    if not SDK_AVAILABLE:
        return {
            "success": False,
            "event_id": event_payload.get("id"),
            "published_to": 0,
            "relays": [
                {"url": url, "success": False, "error": "nostr-sdk not installed"}
                for url in relay_urls
            ],
            "error": "nostr-sdk is not installed; cannot publish",
        }

    from nostr.signing import event_from_dict

    try:
        event = event_from_dict(event_payload)
    except Exception as exc:
        return {
            "success": False,
            "event_id": event_payload.get("id"),
            "published_to": 0,
            "relays": [],
            "error": f"invalid signed event: {exc}",
        }

    client = Client()
    try:
        for relay_url in relay_urls:
            try:
                await client.add_relay(RelayUrl.parse(relay_url), and_connect=True)
            except Exception:
                continue  # one bad relay URL must not block the broadcast

        try:
            await asyncio.wait_for(client.connect(), timeout=timeout_secs)
        except (asyncio.TimeoutError, Exception):
            pass  # connect() is idempotent; individual relays may still be up

        output = await asyncio.wait_for(client.send_event(event), timeout=timeout_secs)

        relay_results = [{"url": str(url), "success": True} for url in output.success]
        relay_results += [
            {"url": str(url), "success": False, "error": str(error)}
            for url, error in output.failed.items()
        ]
        return {
            "success": len(output.success) > 0,
            "event_id": output.id.to_hex(),
            "published_to": len(output.success),
            "relays": relay_results,
        }
    except Exception as exc:
        return {
            "success": False,
            "event_id": event_payload.get("id"),
            "published_to": 0,
            "relays": [],
            "error": f"relay broadcast failed: {exc}",
        }
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass


def publish_signed_event_sync(
    event_payload: Dict,
    relays: Optional[List[str]] = None,
    *,
    timeout_secs: float = DEFAULT_TIMEOUT_SECS,
) -> Dict:
    """Synchronous wrapper around :func:`publish_signed_event`."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(publish_signed_event(event_payload, relays, timeout_secs=timeout_secs))

    # Already inside an event loop (e.g. dashboard route): run in a thread.
    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            asyncio.run, publish_signed_event(event_payload, relays, timeout_secs=timeout_secs)
        ).result()


def _zap_amount(event: "Event") -> int:
    """Extract the zap amount (millisats) from a Kind 9735 receipt."""
    for tag in event.tags():
        vec = tag.to_vec()
        if len(vec) >= 2 and vec[0] == "bolt11":
            # Amount is reliably present in the description JSON; fall back to 0.
            break
    for tag in event.tags():
        vec = tag.to_vec()
        if len(vec) >= 2 and vec[0] == "description":
            try:
                description = json.loads(vec[1])
                amount = description.get("amount")
                if amount is not None:
                    return int(amount)
            except Exception:
                continue
    return 0


async def fetch_engagement(
    event_ids: Iterable[str],
    relays: Optional[List[str]] = None,
    *,
    author: Optional[str] = None,
    timeout_secs: float = ENGAGEMENT_TIMEOUT_SECS,
) -> Optional[Dict[str, Dict]]:
    """Fetch engagement counts for published events across relays.

    Returns ``{event_id_hex: {"reactions", "reposts", "replies", "zaps", "zaps_msat"}}``
    for events that actually had engagement data found. Returns ``None`` when the
    relay query fails entirely so callers do not overwrite previously-persisted
    metrics with zeros.

    Only events authored by ``author`` (when given) are counted, which keeps
    third-party spam out of the metrics.
    """
    ids = _event_ids_to_sdk(event_ids)
    if not ids or not SDK_AVAILABLE:
        return {}

    relay_urls = resolve_relays(relays)
    query_filter = Filter().kinds([Kind(1), Kind(6), Kind(7), Kind(9735)]).events(ids)
    if author:
        from nostr.signing import normalize_pubkey

        author_hex = normalize_pubkey(author)
        if author_hex:
            from nostr_sdk import PublicKey

            query_filter = query_filter.author(PublicKey.parse(author_hex))

    client = Client()
    stats: Dict[str, Dict] = {}
    query_ok = False
    try:
        for relay_url in relay_urls:
            try:
                await client.add_relay(RelayUrl.parse(relay_url), and_connect=True)
            except Exception:
                continue
        try:
            await asyncio.wait_for(client.connect(), timeout=timeout_secs)
        except (asyncio.TimeoutError, Exception):
            pass

        fetched = await asyncio.wait_for(
            client.fetch_events(
                ReqTarget.auto([query_filter]),
                timeout=timedelta(seconds=timeout_secs),
            ),
            timeout=timeout_secs + 5.0,
        )
        query_ok = True
        # nostr-sdk 0.45 returns a plain list of events here.
        fetched_events = fetched.to_vec() if hasattr(fetched, "to_vec") else list(fetched)
        id_set = {event_id.to_hex() for event_id in ids}
        for event in fetched_events:
            kind = event.kind().as_u16()
            referenced = None
            for tag in event.tags():
                vec = tag.to_vec()
                if len(vec) >= 2 and vec[0] == "e" and vec[1] in id_set:
                    referenced = vec[1]
                    break
            if not referenced:
                continue
            if referenced not in stats:
                stats[referenced] = {
                    "reactions": 0,
                    "reposts": 0,
                    "replies": 0,
                    "zaps": 0,
                    "zaps_msat": 0,
                }
            bucket = stats[referenced]
            if kind == 7:
                bucket["reactions"] += 1
            elif kind == 6:
                bucket["reposts"] += 1
            elif kind == 1:
                bucket["replies"] += 1
            elif kind == 9735:
                bucket["zaps"] += 1
                bucket["zaps_msat"] += _zap_amount(event)
    except Exception:
        pass  # engagement reads are best-effort; partial data still helps
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass

    return stats if query_ok else None


def fetch_engagement_sync(
    event_ids: Iterable[str],
    relays: Optional[List[str]] = None,
    *,
    author: Optional[str] = None,
    timeout_secs: float = ENGAGEMENT_TIMEOUT_SECS,
) -> Optional[Dict[str, Dict]]:
    """Synchronous wrapper around :func:`fetch_engagement`."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(
            fetch_engagement(event_ids, relays, author=author, timeout_secs=timeout_secs)
        )

    import concurrent.futures

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(
            asyncio.run,
            fetch_engagement(event_ids, relays, author=author, timeout_secs=timeout_secs),
        ).result()
