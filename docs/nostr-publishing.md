# Nostr Publishing

This module implements the pipeline's Nostr publishing with patterns adapted
from the [nostr-cms](https://github.com/bitkarrot/meetup-site) project and the
[`nostr-sdk`](https://pypi.org/project/nostr-sdk/) Python package.

## Architecture

```
Review record (approved)
    |
    v
nostr/event_builder.py        unsigned event(s): kind routing + tags
    |                             (kind 1 note / 30023 long-form / threads)
    +--> server key? ---- yes --> nostr/signing.py (nsec in env)
    |                                   |
    +--> no server key --> /nostr/sign page  (NIP-07: nos2x / Alby)
    |                               |       window.nostr.signEvent
    |                               v
    +<--------- signed event ----------
    |
    v
services/nostr_signing_service.py   verify signature + anti-tamper,
    |                                store in SQLite, enqueue job
    v                                   (status: signed)
job queue: nostr_publish_request (available_at = scheduled_at)
    |
    v
nostr/relay_client.py           blast broadcast to all relays,
    |                            per-relay results, success = >=1 relay
    v
published (status: published) --> review record mirrored
    |
    v
nostr/nostr_analytics.py        engagement from relays:
                                reactions (7), reposts (6),
                                replies (1), zaps (9735)
```

## Signing modes

### 1. NIP-07 browser extension (recommended — no nsec on the server)

1. Leave `NOSTR_PRIVATE_KEY` unset. When nostr content is approved, the
   Nostr provider returns `signing_required` and creates a *signing
   request* — the card **stays in the Pipeline tab** with an amber
   "Nostr signature required" banner and a **Sign with extension** button.
2. Click **Sign with extension** on the pipeline card (a NIP-07 extension
   such as [nos2x](https://github.com/nostafari/nos2x) or Alby must be
   installed). The dashboard calls `window.nostr.signEvent(unsignedEvent)`
   in your browser; your private key never leaves the extension.
3. The server verifies the schnorr signature, checks the signed event still
   matches the prepared one byte-for-byte (kind, content, created_at, tags),
   and only then schedules it. The card flips to "Signed — publishes <date>"
   and the event appears on the **Calendar**.
4. At `scheduled_at` the worker broadcasts the pre-signed event
   (sign-now-publish-later: the future `created_at` is part of the signature).

The standalone `/nostr/sign` page remains as a deep link for batch signing
from another device; the Pipeline is the primary flow.

Optionally pin which identity may sign (per project: Integrations → Nostr →
pubkey, or globally via `NOSTR_PUBKEY`). Signatures from any other key are
rejected server-side.

### 2. Server key (headless)

Set `NOSTR_PRIVATE_KEY` (nsec or hex) — either globally in `.env` or per
project under Settings → Integrations → Nostr. The same unsigned events are
signed by `nostr/signing.py` and scheduled/published without a human.

## Configuration

| Variable | Meaning | Default |
| --- | --- | --- |
| `NOSTR_PRIVATE_KEY` | Server signing key (nsec1… or hex). Omit for extension signing | unset |
| `NOSTR_PUBKEY` | Pin the allowed signer identity (npub or hex) | unset (any signer) |
| `NOSTR_RELAYS` | Comma-separated relay list for publish + analytics | damus, primal, nos.lol |

Per-project integration settings also accept a `pubkey` (pin) and `api_key`
(server nsec) under the `nostr` provider.

## Kinds and tags

- Short posts → **kind 1** with `t` hashtags extracted from content, plus a
  `client: draper-pipeline` attribution tag.
- Blog/article/newsletter/case-study content types (or titled long content)
  → **kind 30023** long-form with `d`, `title`, `published_at` tags.
- Threads (generated "Tweet 2:"/"Part 2" shapes) → chained kind 1 notes with
  NIP-10 `root`/`reply` markers.
- Deletion helper: `NostrPublisher.delete_events(ids, reason)` publishes
  **kind 5**.
- Anything that looks like an `nsec…` is redacted from content before
  events are built.

## Operations

```bash
# Worker drains the queue (including nostr_publish_request jobs)
draper-worker                 # or: python worker.py

# Cron-mode sweep of due signed events
draper-worker --once --kinds nostr_publish_request

# Manual sweep via the dashboard API (publisher role required)
curl -X POST $DASHBOARD/api/projects/<id>/nostr/publish-due

# Inspect / test the publisher
python nostr/nostr_publisher.py --test
python nostr/nostr_publisher.py --relays wss://relay.damus.io --note "hello"
python nostr/nostr_publisher.py --delete <event-id> --reason "typo"
```

State lives in the `nostr_signing_requests` SQLite table
(`data/sqlite_store.py`); statuses are
`pending_signature → signed → published` with `publish_failed` (after 3
attempts) and `cancelled` as exits.

## Analytics

`NostrAnalytics.sync_analytics()` now queries relays for real engagement
(kind 7 reactions, kind 6 reposts, kind 1 replies, kind 9735 zap receipts
with amounts) instead of relying on manual metric entry — the zaplytics
idea from nostr-cms. Results land in `data/nostr_metrics.json` /
`nostr_events.json` and feed `get_analytics_summary()`.

## Security notes

- Extension signatures are verified server-side (id + schnorr) **and**
  matched against the prepared unsigned event, so a signer cannot swap
  content after approval.
- `NOSTR_PUBKEY` (or the per-project pubkey) pins the accepted identity.
- The signing page is auth-gated and requires the `publisher` project role;
  all mutations go through the standard CSRF middleware.
- The server stores only signed events (public data) — never key material.
