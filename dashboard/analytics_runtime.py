"""Analytics data collection extracted from ``UnifiedDashboard``.

Plan 03-04 moves the typefully/late/unified analytics read paths out of
``dashboard.unified_dashboard.py`` so the bootstrap module stays under the
ARCH-04 300-line budget. Behavior is byte-identical to the original
``UnifiedDashboard._get_typefully_analytics`` /
``_get_late_analytics`` / ``_get_unified_analytics`` helpers.

Plan 05-03 routes the read paths through SQLite analytics_snapshots first
with a deprecated JSON file fallback (criterion #1).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict

from analytics.typefully_analytics import _read_analytics


def _get_typefully_analytics(data_dir: Any, store: Any = None) -> Dict:
    metrics_file = Path(data_dir) / "typefully_metrics.json"

    metrics_data = _read_analytics(store, metrics_file, default=None)
    if metrics_data is None:
        return {"status": "no_data", "message": "No analytics data yet"}

    posts = list(metrics_data.values())

    total_impressions = sum(p.get("metrics", {}).get("impressions", 0) for p in posts)
    total_likes = sum(p.get("metrics", {}).get("likes", 0) for p in posts)
    total_retweets = sum(p.get("metrics", {}).get("retweets", 0) for p in posts)

    avg_engagement = 0
    if posts:
        engagement_rates = [
            p.get("calculated_metrics", {}).get("engagement_rate", 0) for p in posts
        ]
        avg_engagement = (
            round(sum(engagement_rates) / len(engagement_rates), 2) if engagement_rates else 0
        )

    top_posts = sorted(
        posts,
        key=lambda x: x.get("calculated_metrics", {}).get("engagement_rate", 0),
        reverse=True,
    )[:10]

    return {
        "status": "ok",
        "total_posts": len(posts),
        "total_impressions": total_impressions,
        "total_likes": total_likes,
        "total_retweets": total_retweets,
        "avg_engagement_rate": avg_engagement,
        "top_posts": top_posts,
    }


def _get_late_analytics() -> Dict:
    return {
        "status": "placeholder",
        "message": "LinkedIn analytics coming soon via late.dev API",
    }


def _get_unified_analytics(typefully: Dict) -> Dict:
    return {
        "total_engagement": typefully.get("total_likes", 0)
        + typefully.get("total_retweets", 0),
        "best_day": "Tuesday",
        "recommendations": [
            "Post more threads - they get 3x engagement",
            "Best time: 9AM and 3PM GMT+1",
            "Industry insights performs best",
        ],
    }


def collect_analytics_data(data_dir: Any, store: Any = None) -> Dict:
    """Aggregate typefully / late / unified analytics for the dashboard.

    Reads from SQLite analytics_snapshots when ``store`` is provided; falls
    back to the legacy JSON file path otherwise. The fallback emits a
    DeprecationWarning when fired.
    """
    typefully = _get_typefully_analytics(data_dir, store=store)
    return {
        "typefully": typefully,
        "late": _get_late_analytics(),
        "unified": _get_unified_analytics(typefully),
    }
