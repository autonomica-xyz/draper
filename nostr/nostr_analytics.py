#!/usr/bin/env python3
"""
Nostr Analytics Collector
Retrieve and store engagement data from Nostr
"""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional
from pathlib import Path


class NostrAnalytics:
    """Collect and analyze Nostr engagement data"""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = str(Path(__file__).resolve().parent.parent / "data")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Nostr analytics files
        self.metrics_file = self.data_dir / "nostr_metrics.json"
        self.events_file = self.data_dir / "nostr_events.json"
        self.trends_file = self.data_dir / "nostr_trends.json"

        # Default relays for analytics
        self.relays = [
            "wss://relay.damus.io",
            "wss://relay.primal.net",
            "wss://relay.nostr.band",
        ]

        # Load existing data
        self._load_data()

    def _load_data(self):
        """Load existing analytics data"""
        if self.events_file.exists():
            with open(self.events_file, "r") as f:
                self.events = json.load(f)
        else:
            self.events = []

        if self.metrics_file.exists():
            with open(self.metrics_file, "r") as f:
                self.metrics = json.load(f)
        else:
            self.metrics = {}

    def _save_data(self):
        """Save analytics data"""
        with open(self.events_file, "w") as f:
            json.dump(self.events, f, indent=2)

        with open(self.metrics_file, "w") as f:
            json.dump(self.metrics, f, indent=2)

    def record_event(
        self,
        event_id: str,
        kind: int,
        content: str,
        published_at: str,
        platform: str = "nostr",
        pillar: str = "",
    ) -> Dict:
        """Record a published Nostr event

        Args:
            event_id: Nostr event ID
            kind: Event kind (1 for text note)
            content: Event content
            published_at: ISO timestamp
            platform: Source platform
            pillar: Content pillar

        Returns:
            Dict with recorded event
        """
        event_record = {
            "event_id": event_id,
            "kind": kind,
            "content": content[:200],  # Store preview
            "published_at": published_at,
            "platform": platform,
            "pillar": pillar,
            "metrics": {
                "impressions": 0,
                "likes": 0,
                "reposts": 0,
                "replies": 0,
                "zaps": 0,
                "zaps_msat": 0,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            },
        }

        self.events.append(event_record)
        self._save_data()

        return event_record

    def update_event_metrics(
        self,
        event_id: str,
        likes: Optional[int] = None,
        reposts: Optional[int] = None,
        replies: Optional[int] = None,
    ) -> Dict:
        """Update metrics for a specific event

        Args:
            event_id: Nostr event ID
            likes: Number of likes/reactions
            reposts: Number of reposts
            replies: Number of replies

        Returns:
            Dict with updated metrics
        """
        # Find event
        for event in self.events:
            if event["event_id"] == event_id:
                if likes is not None:
                    event["metrics"]["likes"] = likes
                if reposts is not None:
                    event["metrics"]["reposts"] = reposts
                if replies is not None:
                    event["metrics"]["replies"] = replies
                event["metrics"]["last_updated"] = datetime.now(timezone.utc).isoformat()

                self._save_data()

                # Calculate engagement rate
                impressions = event["metrics"].get("impressions", 1)
                total_engagements = (
                    event["metrics"]["likes"]
                    + event["metrics"]["reposts"]
                    + event["metrics"]["replies"]
                )
                event["metrics"]["engagement_rate"] = (
                    round((total_engagements / impressions) * 100, 2) if impressions > 0 else 0
                )

                return event["metrics"]

        return None

    def get_top_posts(self, limit: int = 10, metric: str = "engagement_rate") -> List[Dict]:
        """Get top performing posts by metric

        Args:
            limit: Number of posts to return
            metric: Metric to sort by (likes, reposts, replies, engagement_rate)

        Returns:
            List of top posts
        """
        # Sort by metric
        sorted_events = sorted(self.events, key=lambda x: x["metrics"].get(metric, 0), reverse=True)

        return sorted_events[:limit]

    def get_analytics_summary(self) -> Dict:
        """Get summary analytics for Nostr

        Returns:
            Dict with summary statistics
        """
        if not self.events:
            return {"status": "no_data", "message": "No Nostr events recorded yet"}

        # Calculate totals
        total_events = len(self.events)
        total_likes = sum(e["metrics"].get("likes", 0) for e in self.events)
        total_reposts = sum(e["metrics"].get("reposts", 0) for e in self.events)
        total_replies = sum(e["metrics"].get("replies", 0) for e in self.events)
        total_zaps = sum(e["metrics"].get("zaps", 0) for e in self.events)
        total_zaps_msat = sum(e["metrics"].get("zaps_msat", 0) for e in self.events)

        # Calculate average engagement rate
        engagement_rates = [
            e["metrics"].get("engagement_rate", 0)
            for e in self.events
            if e["metrics"].get("engagement_rate", 0) > 0
        ]
        avg_engagement_rate = (
            round(sum(engagement_rates) / len(engagement_rates), 2) if engagement_rates else 0
        )

        # Calculate by pillar
        pillar_stats = {}
        for event in self.events:
            pillar = event.get("pillar", "unknown")
            if pillar not in pillar_stats:
                pillar_stats[pillar] = {
                    "count": 0,
                    "total_likes": 0,
                    "total_reposts": 0,
                    "total_replies": 0,
                }
            pillar_stats[pillar]["count"] += 1
            pillar_stats[pillar]["total_likes"] += event["metrics"].get("likes", 0)
            pillar_stats[pillar]["total_reposts"] += event["metrics"].get("reposts", 0)
            pillar_stats[pillar]["total_replies"] += event["metrics"].get("replies", 0)

        # Calculate pillar success rates
        for pillar, stats in pillar_stats.items():
            total_engagements = (
                stats["total_likes"] + stats["total_reposts"] + stats["total_replies"]
            )
            stats["avg_engagement_per_post"] = round(total_engagements / stats["count"], 2)

        return {
            "status": "ok",
            "total_events": total_events,
            "total_likes": total_likes,
            "total_reposts": total_reposts,
            "total_replies": total_replies,
            "total_zaps": total_zaps,
            "total_zaps_msat": total_zaps_msat,
            "average_engagement_rate": avg_engagement_rate,
            "pillar_performance": pillar_stats,
            "top_posts": self.get_top_posts(limit=5),
        }

    def sync_analytics(self) -> Dict:
        """Sync analytics from Nostr relays (reactions/reposts/replies/zaps).

        Steals the nostr-cms zaplytics idea: engagement is read directly
        from the configured relays instead of being entered manually.

        Returns:
            Dict with sync results
        """
        refresh_result = self.refresh_engagement()
        summary = self.get_analytics_summary()

        print("\n" + "=" * 60)
        print("🔄 NOSTR ANALYTICS SYNC")
        print("=" * 60 + "\n")

        print(f"Events refreshed: {refresh_result.get('refreshed', 0)}")
        print(f"Total events tracked: {summary.get('total_events', 0)}")
        print(f"Total likes: {summary.get('total_likes', 0)}")
        print(f"Total reposts: {summary.get('total_reposts', 0)}")
        print(f"Total replies: {summary.get('total_replies', 0)}")
        print(
            f"Total zaps: {summary.get('total_zaps', 0)} "
            f"({summary.get('total_zaps_msat', 0) / 1000:.0f} sats)"
        )
        print(f"Avg engagement rate: {summary.get('average_engagement_rate', 0)}%")

        print("\n📊 Pillar Performance:")
        for pillar, stats in summary.get("pillar_performance", {}).items():
            print(f"\n  {pillar.replace('_', ' ').title()}:")
            print(f"    Posts: {stats['count']}")
            print(f"    Avg engagement/post: {stats['avg_engagement_per_post']}")

        print("\n" + "=" * 60)
        print("✅ Sync complete")

        summary["refresh"] = refresh_result
        return summary

    def refresh_engagement(self, limit: int = 50) -> Dict:
        """Fetch real engagement counts for tracked events from relays.

        For each recorded event id, counts Kind 7 reactions, Kind 6 reposts,
        Kind 1 replies, and Kind 9735 zap receipts (with amounts) across the
        configured relay set, then updates local metrics.
        """
        from .relay_client import fetch_engagement_sync, resolve_relays

        candidates = [e for e in self.events if e.get("event_id")][:limit]
        if not candidates:
            return {"refreshed": 0, "reason": "no tracked events"}

        event_ids = [e["event_id"] for e in candidates]
        stats = fetch_engagement_sync(
            event_ids,
            self.relays or resolve_relays(),
        )

        if stats is None:
            return {"refreshed": 0, "reason": "relay query failed"}

        refreshed = 0
        for event in candidates:
            bucket = stats.get(event["event_id"])
            if not bucket:
                continue
            event.setdefault("metrics", {})
            event["metrics"].update(
                {
                    "likes": bucket.get("reactions", 0),
                    "reposts": bucket.get("reposts", 0),
                    "replies": bucket.get("replies", 0),
                    "zaps": bucket.get("zaps", 0),
                    "zaps_msat": bucket.get("zaps_msat", 0),
                    "last_updated": datetime.now(timezone.utc).isoformat(),
                }
            )
            engagements = (
                event["metrics"]["likes"]
                + event["metrics"]["reposts"]
                + event["metrics"]["replies"]
                + event["metrics"]["zaps"]
            )
            event["metrics"]["engagement_rate"] = engagements  # absolute count
            refreshed += 1

        if refreshed:
            self._save_data()
        return {"refreshed": refreshed, "queried": len(event_ids)}


def main():
    """CLI for Nostr analytics"""
    import argparse

    parser = argparse.ArgumentParser(description="Nostr analytics collector")
    parser.add_argument("--sync", action="store_true", help="Sync analytics from Nostr")
    parser.add_argument("--top", type=int, default=10, help="Get top N posts")
    parser.add_argument("--summary", action="store_true", help="Show analytics summary")
    parser.add_argument(
        "--metric",
        choices=["likes", "reposts", "replies", "engagement_rate"],
        default="engagement_rate",
        help="Metric for sorting",
    )

    args = parser.parse_args()

    analytics = NostrAnalytics()

    if args.sync:
        result = analytics.sync_analytics()
        print(json.dumps(result, indent=2))

    elif args.summary:
        summary = analytics.get_analytics_summary()
        print("\n" + "=" * 60)
        print("📊 NOSTR ANALYTICS SUMMARY")
        print("=" * 60 + "\n")
        print(json.dumps(summary, indent=2))

    elif args.top:
        top_posts = analytics.get_top_posts(limit=args.top, metric=args.metric)
        print(f"\n🏆 Top {len(top_posts)} Posts (by {args.metric}):")
        for i, post in enumerate(top_posts, 1):
            print(f"\n{i}. Event ID: {post['event_id'][:20]}...")
            print(f"   Published: {post['published_at'][:10]}")
            print(f"   Content: {post['content']}")
            print(f"   {args.metric}: {post['metrics'][args.metric]}")

    else:
        print("Usage:")
        print("  --sync              Sync analytics from Nostr")
        print("  --summary            Show analytics summary")
        print("  --top N             Show top N posts")
        print("  --metric [metric]   Sort by metric (likes, reposts, replies, engagement_rate)")


if __name__ == "__main__":
    main()
