"""Nostr signing + scheduled publishing workflow.

Implements the nostr-cms "sign now, publish later" scheduler pattern on top
of our SQLite store, with two ways to produce signatures:

* **NIP-07 browser extension** (nos2x, Alby, ...): ``create_request`` stores
  an unsigned event prepared from an approved review record. A human signs
  it directly in the dashboard Pipeline tab (``Sign with extension``);
  ``accept_signature`` verifies the signature and anti-tamper checks before
  scheduling.
* **Server keys** (headless): ``sign_request_with_server_keys`` signs the
  same unsigned event with ``NOSTR_PRIVATE_KEY`` so scheduled publishing
  needs no human in the loop.

Once signed, the request waits until ``scheduled_at`` and
``publish_due``/``publish_request`` broadcasts it to the configured relays,
mirroring the lifecycle of the nostr-cms scheduler:

    pending_signature -> signed -> published
                    \\-> cancelled        \\-> publish_failed (retries)
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.observability import get_logger

from nostr import signing as nostr_signing
from nostr.relay_client import publish_signed_event_sync, resolve_relays

logger = get_logger(__name__)

MAX_PUBLISH_ATTEMPTS = 3


class NostrSigningError(ValueError):
    """Raised for invalid signing/publishing transitions."""


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def public_request_view(record: Dict) -> Dict:
    """Signing-request view safe for templates/APIs: no signed payloads, no keys."""
    unsigned_events = record.get("unsigned_events") or []
    view = {
        "request_id": record.get("request_id"),
        "review_id": record.get("review_id"),
        "project_id": record.get("project_id"),
        "status": record.get("status"),
        "unsigned_events": unsigned_events,
        "event_id": record.get("event_id"),
        "event_uri": record.get("event_uri"),
        "relays": record.get("relays") or [],
        "scheduled_at": record.get("scheduled_at"),
        "signed_at": record.get("signed_at"),
        "published_at": record.get("published_at"),
        "publish_attempts": record.get("publish_attempts", 0),
        "last_error": record.get("last_error"),
        "created_at": record.get("created_at"),
        "parts": len(unsigned_events),
    }
    return view


def attach_pipeline_nostr_requests(
    store,
    feedback_manager,
    items: List[Dict],
    project_id: Optional[str] = None,
) -> List[Dict]:
    """Attach active nostr signing requests to pipeline card items.

    Sign-now-publish-later UX: approved nostr content that is waiting for an
    extension signature (or a publish retry) must stay visible in the
    Pipeline instead of disappearing after approval.
    """
    try:
        records = store.list_nostr_request_records(project_id=project_id)
    except AttributeError:
        return items

    active: Dict[str, Dict] = {}
    for record in records:
        if record.get("status") not in {"pending_signature", "signed", "publish_failed"}:
            continue
        review_id = record.get("review_id")
        if review_id:
            active[review_id] = public_request_view(record)
    if not active:
        return items

    seen = set()
    for item in items:
        review_id = item.get("review_id")
        seen.add(review_id)
        if review_id in active:
            item["nostr_request"] = active[review_id]

    for review_id, view in active.items():
        if review_id in seen:
            continue
        review = None
        if feedback_manager is not None:
            review = feedback_manager._load_review_record(review_id)
        if not review:
            continue
        items.append(
            {
                "review_id": review_id,
                "post_data": review.get("post_data", {}),
                "reasoning": None,
                "feedback": review.get("feedback"),
                "media": review.get("media", []),
                "status": review.get("status"),
                "nostr_request": view,
            }
        )
    return items


def _normalize_scheduled_at(value) -> Optional[str]:
    """Normalize any accepted timestamp form to UTC ISO for storage."""
    if not value:
        return None
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).isoformat()


class NostrSigningService:
    """Owns the nostr_signing_requests lifecycle."""

    def __init__(
        self,
        store,
        job_queue=None,
        feedback_manager=None,
        analytics=None,
        data_dir: Optional[str] = None,
    ):
        self.store = store
        self.job_queue = job_queue
        self.feedback_manager = feedback_manager
        self.analytics = analytics
        self.data_dir = data_dir

    # ------------------------------------------------------------------
    # Request creation
    # ------------------------------------------------------------------

    def create_request(
        self,
        review_record: Dict,
        scheduled_at=None,
        relays: Optional[List[str]] = None,
    ) -> Dict:
        """Prepare unsigned events from an approved review record.

        The unsigned events are exactly what will be signed -- no content is
        re-derived at signing or publishing time.
        """
        post_data = review_record.get("post_data", {})
        project_id = review_record.get("project_id") or post_data.get("project_id")
        review_id = review_record.get("review_id")

        from nostr.nostr_publisher import NostrPublisher

        publisher = NostrPublisher()
        unsigned_events = publisher.build_unsigned_events(post_data, scheduled_at=scheduled_at)
        if not unsigned_events:
            raise NostrSigningError("Review record has no content to publish")

        record = {
            "project_id": project_id,
            "review_id": review_id,
            "status": "pending_signature",
            "unsigned_events": unsigned_events,
            "relays": resolve_relays(relays),
            "scheduled_at": _normalize_scheduled_at(scheduled_at),
            "created_at": _utc_now_iso(),
        }
        record = self.store.normalize_nostr_request_record(record)
        self.store.save_nostr_request_record(record)
        normalized = self.store.get_nostr_request_record(record["request_id"])
        self._audit("signing_request_created", normalized)
        return normalized

    def create_request_for_review(
        self,
        review_id: str,
        scheduled_at=None,
        relays: Optional[List[str]] = None,
    ) -> Dict:
        """Load a review record by id and prepare its signing request."""
        record = self._load_review_record(review_id)
        return self.create_request(record, scheduled_at=scheduled_at, relays=relays)

    # ------------------------------------------------------------------
    # Signature acceptance (NIP-07 extension flow)
    # ------------------------------------------------------------------

    def accept_signature(
        self,
        request_id: str,
        signed_events: List[Dict],
        expected_pubkey: Optional[str] = None,
    ) -> Dict:
        """Verify and store signed events coming back from a signer.

        Every event must pass schnorr verification (via nostr-sdk), match the
        prepared unsigned event byte-for-byte on kind/content/created_at/tags,
        and be signed by ``expected_pubkey`` when one is configured. Threaded
        Kind 1 notes are allowed the NIP-10 ``e`` root/reply tags that the
        signer legitimately prepends when chaining parts.
        """
        record = self.store.get_nostr_request_record(request_id)
        if not record:
            raise NostrSigningError(f"Signing request not found: {request_id}")
        if record.get("status") not in {"pending_signature", "signed"}:
            raise NostrSigningError(
                f"Signing request is not signable (status={record.get('status')})"
            )

        unsigned_events = record.get("unsigned_events") or []
        if not signed_events or len(signed_events) != len(unsigned_events):
            raise NostrSigningError(
                f"Expected {len(unsigned_events)} signed event(s), got {len(signed_events or [])}"
            )

        try:
            pinned = nostr_signing.expected_signer_pubkey(expected_pubkey)
        except Exception as exc:
            raise NostrSigningError(f"Invalid expected signer pubkey: {exc}") from exc
        signer_pubkeys = set()
        accepted_ids: List[str] = []
        for index, (signed_event, unsigned_event) in enumerate(zip(signed_events, unsigned_events)):
            expected_extra = self._expected_thread_tags(unsigned_events, accepted_ids, index)
            ok, reason = nostr_signing.verify_signed_event(
                signed_event,
                unsigned=unsigned_event,
                expected_pubkey=pinned,
                expected_extra_tags=expected_extra,
            )
            if not ok:
                self._fail_record(record, f"Signature rejected: {reason}")
                raise NostrSigningError(f"Signature rejected: {reason}")
            signer_pubkeys.add(str(signed_event.get("pubkey")))
            accepted_ids.append(str(signed_event.get("id")))

        if len(signer_pubkeys) > 1:
            raise NostrSigningError("All events in a request must be signed by the same key")

        record["status"] = "signed"
        record["signed_events"] = signed_events
        record["event_id"] = signed_events[0].get("id")
        record["event_uri"] = nostr_signing.event_uri(
            record["event_id"], relays=record.get("relays")
        )
        record["signed_at"] = _utc_now_iso()
        record["signer_pubkey"] = signer_pubkeys.pop()
        record.pop("last_error", None)
        self.store.save_nostr_request_record(record)
        self._sync_review_status(record, "scheduled")
        self._enqueue_publish_job(record)
        self._audit("signature_accepted", record)
        return self.store.get_nostr_request_record(request_id)

    @staticmethod
    def _expected_thread_tags(unsigned_events: List[Dict], accepted_ids: List[str], index: int) -> List[List[str]]:
        """Return the NIP-10 ``e`` tags a signer may prepend to part ``index``.

        Part 0 has no thread references. For a single follow-up part, the
        expected prefix is a ``root`` marker referencing the first part. For
        deeper threads, the prefix is ``root`` (first part) followed by
        ``reply`` (immediately preceding part).
        """
        if index == 0:
            return []
        unsigned = unsigned_events[index]
        if int(unsigned.get("kind", 0)) != 1:
            return []
        root_id = accepted_ids[0]
        previous_id = accepted_ids[index - 1]
        if root_id == previous_id:
            return [["e", previous_id, "", "root"]]
        return [["e", root_id, "", "root"], ["e", previous_id, "", "reply"]]

    # ------------------------------------------------------------------
    # Headless signing (server keys)
    # ------------------------------------------------------------------

    def sign_request_with_server_keys(
        self, request_id: str, private_key: Optional[str] = None
    ) -> Dict:
        """Sign a pending request with the configured server key.

        ``private_key`` may be injected for per-project keys; otherwise the
        ``NOSTR_PRIVATE_KEY`` env / ``~/.nostr/private_key.txt`` path is used.
        Threads are stitched so each part references the previous part's
        signed id with NIP-10 root/reply markers.
        """
        record = self.store.get_nostr_request_record(request_id)
        if not record:
            raise NostrSigningError(f"Signing request not found: {request_id}")
        if record.get("status") != "pending_signature":
            raise NostrSigningError(f"Request already {record.get('status')}")

        keys = nostr_signing.load_keys(private_key)
        if keys is None:
            raise NostrSigningError(
                "No server key configured; sign the request in the dashboard Pipeline tab"
            )

        signed_events = nostr_signing.sign_event_chain(record.get("unsigned_events") or [], keys)

        return self.accept_signature(request_id, signed_events, expected_pubkey=None)

    # ------------------------------------------------------------------
    # Publishing
    # ------------------------------------------------------------------

    def publish_request(self, request_id: str) -> Dict:
        """Broadcast a signed request to its relays now."""
        record = self.store.get_nostr_request_record(request_id)
        if not record:
            raise NostrSigningError(f"Signing request not found: {request_id}")
        if record.get("status") == "published":
            return {"success": True, "skipped": True, "record": record}
        if record.get("status") != "signed":
            raise NostrSigningError(f"Request is not signed (status={record.get('status')})")
        return self._broadcast(record)

    def publish_due(
        self,
        now=None,
        limit: int = 50,
        project_id: Optional[str] = None,
    ) -> List[Dict]:
        """Publish every signed request whose scheduled time has arrived.

        ``project_id`` scopes the sweep so project A cannot broadcast
        project B's pre-signed events.
        """
        now_iso = _normalize_scheduled_at(now or datetime.now(timezone.utc))
        due = self.store.list_due_nostr_request_records(
            now_iso, limit=limit, project_id=project_id
        )
        results = []
        for record in due:
            results.append(self._broadcast(record))
        return results

    def cancel_request(self, request_id: str) -> Dict:
        record = self.store.get_nostr_request_record(request_id)
        if not record:
            raise NostrSigningError(f"Signing request not found: {request_id}")
        if record.get("status") in {"published", "cancelled"}:
            raise NostrSigningError(f"Cannot cancel a request that is {record.get('status')}")
        record["status"] = "cancelled"
        self.store.save_nostr_request_record(record)
        self._cancel_publish_job(record)
        self._audit("signing_request_cancelled", record)
        return self.store.get_nostr_request_record(request_id)

    def _broadcast(self, record: Dict) -> Dict:
        signed_events = record.get("signed_events") or []
        relays = record.get("relays") or resolve_relays()

        broadcast_results = []
        for signed_event in signed_events:
            broadcast_results.append(publish_signed_event_sync(signed_event, relays))

        successful = [r for r in broadcast_results if r.get("success")]
        attempts = int(record.get("publish_attempts", 0) or 0) + 1

        if successful:
            record["status"] = "published"
            record["published_at"] = _utc_now_iso()
            record.pop("last_error", None)
            self.store.save_nostr_request_record(record)
            self._sync_review_status(record, "published")
            self._record_analytics(record, successful[0])
            self._audit(
                "published",
                record,
                extra={
                    "relays": [r.get("url") for r in successful[0].get("relays", [])],
                },
            )
            return {
                "success": True,
                "request_id": record["request_id"],
                "event_id": successful[0].get("event_id"),
                "published_to": successful[0].get("published_to", 0),
                "record": self.store.get_nostr_request_record(record["request_id"]),
            }

        error = (
            broadcast_results[0].get("error")
            if broadcast_results
            else "no signed events to publish"
        )
        record["publish_attempts"] = attempts
        record["last_error"] = str(error)
        record["status"] = "publish_failed" if attempts >= MAX_PUBLISH_ATTEMPTS else "signed"
        self.store.save_nostr_request_record(record)
        self._audit("publish_failed", record, extra={"error": str(error)})
        return {
            "success": False,
            "request_id": record["request_id"],
            "error": str(error),
            "record": self.store.get_nostr_request_record(record["request_id"]),
        }

    # ------------------------------------------------------------------
    # Status helpers
    # ------------------------------------------------------------------

    def get_status_summary(self, project_id: Optional[str] = None) -> Dict[str, Any]:
        records = self.store.list_nostr_request_records(project_id=project_id)
        summary: Dict[str, Any] = {
            "pending_signature": 0,
            "signed": 0,
            "published": 0,
            "publish_failed": 0,
            "cancelled": 0,
        }
        for record in records:
            status = record.get("status")
            if status in summary:
                summary[status] += 1

        try:
            summary["server_key_configured"] = nostr_signing.load_keys() is not None
        except Exception:
            summary["server_key_configured"] = False

        summary["relays"] = resolve_relays()

        try:
            pinned = nostr_signing.expected_signer_pubkey()
        except Exception:
            pinned = None
        summary["expected_pubkey"] = pinned
        return summary

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _load_review_record(self, review_id: str) -> Dict:
        if self.feedback_manager is not None:
            record = self.feedback_manager._load_review_record(review_id)
            if record:
                return record
        raise NostrSigningError(f"Review record not found: {review_id}")

    def _sync_review_status(self, record: Dict, status: str) -> None:
        """Mirror request status onto the linked review record.

        Uses the public FeedbackManager API (``mark_scheduled``/
        ``mark_published``) so this service stays out of the review
        workflow's private persistence path.
        """
        review_id = record.get("review_id")
        if not review_id or self.feedback_manager is None:
            return
        try:
            if status == "scheduled":
                self.feedback_manager.mark_scheduled(
                    review_id, {"nostr_request_id": record.get("request_id")}
                )
            elif status == "published":
                self.feedback_manager.mark_published(
                    review_id,
                    extras={
                        "post_id": record.get("event_id"),
                        "draft_url": record.get("event_uri"),
                        "published_via": "nostr",
                    },
                )
        except Exception as exc:  # review mirroring is best-effort
            logger.warning("nostr review status sync failed: %s", exc)

    def _record_analytics(self, record: Dict, broadcast: Dict) -> None:
        if self.analytics is None:
            return
        try:
            self.analytics.record_event(
                event_id=broadcast.get("event_id") or "unknown",
                kind=1,
                content=(record.get("unsigned_events") or [{}])[0].get("content", "")[:200],
                published_at=_utc_now_iso(),
                platform="nostr",
                pillar="",
            )
        except Exception as exc:
            logger.warning("nostr analytics record failed: %s", exc)

    def _enqueue_publish_job(self, record: Dict) -> None:
        if self.job_queue is None:
            return
        try:
            available_at = record.get("scheduled_at") or _utc_now_iso()
            self.job_queue.enqueue(
                "nostr_publish_request",
                project_id=record.get("project_id"),
                available_at=available_at,
                payload={"request_id": record["request_id"]},
            )
        except Exception as exc:
            logger.warning("nostr publish job enqueue failed: %s", exc)

    def _cancel_publish_job(self, record: Dict) -> None:
        if self.job_queue is None:
            return
        try:
            for job in self.job_queue.list(status="queued", limit=500):
                if job.get("payload", {}).get("request_id") == record.get("request_id"):
                    self.job_queue.cancel(job["job_id"])
        except Exception as exc:
            logger.warning("nostr publish job cancel failed: %s", exc)

    def _fail_record(self, record: Dict, error: str) -> None:
        record["last_error"] = error
        self.store.save_nostr_request_record(record)

    def _audit(self, action: str, record: Dict, extra: Optional[Dict] = None) -> None:
        if not hasattr(self.store, "record_event"):
            return
        payload = {
            "request_id": record.get("request_id"),
            "review_id": record.get("review_id"),
            "status": record.get("status"),
        }
        if extra:
            payload.update(extra)
        try:
            self.store.record_event(
                category="publish",
                action=f"nostr_{action}",
                project_id=record.get("project_id"),
                review_id=record.get("review_id"),
                payload=payload,
            )
        except Exception as exc:  # audit is best-effort
            logger.warning("system_events.nostr write failed: %s", exc)
