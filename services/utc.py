"""Timezone-aware UTC datetime helpers.

The single source of truth for constructing UTC datetimes. Naive
``datetime`` constructor calls without an explicit timezone are a class
of bug that only surfaces when the server timezone is not UTC;
``services.utc`` makes the timezone-safe path the default.

Use :func:`utc_now` when you need a :class:`datetime.datetime` object and
:func:`utc_now_iso` when you need an ISO 8601 string (the canonical form
stored in SQLite and emitted in API responses). Both produce values whose
``isoformat()`` representation ends in ``+00:00``.
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    return utc_now().isoformat()
