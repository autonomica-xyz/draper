#!/usr/bin/env python3
"""
Analytics Feedback Loop Optimizer
Generates content recommendations based on performance analytics
"""

import json
import warnings
from typing import Any, Dict, List, Optional
from pathlib import Path
from datetime import datetime, timedelta, timezone


def _read_analytics(store: Any, file_path: Path, default: Any) -> Any:
    """SQLite-first analytics reader with deprecated JSON file fallback."""
    if store is not None:
        from data.repositories.analytics_repository import AnalyticsRepository
        from analytics.typefully_analytics import _SNAPSHOT_MISSING

        snapshot = AnalyticsRepository(store).get_snapshot(
            file_path.name, default=_SNAPSHOT_MISSING
        )
        if snapshot is not _SNAPSHOT_MISSING:
            return snapshot
    if file_path.exists():
        warnings.warn(
            f"analytics reads from {file_path.name} - SQLite snapshot missing",
            DeprecationWarning,
            stacklevel=2,
        )
        with open(file_path, "r") as handle:
            return json.load(handle)
    return default


class AnalyticsOptimizer:
    """Generate content recommendations based on performance analytics

    This class analyzes historical content performance and generates
    actionable recommendations for content strategy optimization.
    """

    def __init__(
        self,
        analytics_data: Dict,
        preference_data: Dict,
        data_dir: str = None,
        store: Any = None
    ):
        """Initialize the optimizer with analytics and preference data

        Args:
            analytics_data: Historical analytics data from unified_analytics
            preference_data: Current content preferences and strategy
            data_dir: Path to data directory
            store: Optional SQLiteStore for SQLite-first reads
        """
        if data_dir is None:
            data_dir = str(Path(__file__).resolve().parent.parent / "data")
        self.analytics = analytics_data
        self.preferences = preference_data
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = store

        # File for storing recommendations
        self.recommendations_file = self.data_dir / "content_recommendations.json"

        # Minimum data requirements for analysis
        self.min_posts_for_analysis = 5
        self.min_engagement_threshold = 1.0

    def generate_content_recommendations(self) -> Dict:
        """Generate comprehensive recommendations for next content batch

        Analyzes historical performance and generates actionable recommendations
        for:
        - Which pillars to increase/decrease
        - Which hooks perform best
        - Optimal posting times
        - Topics to explore

        Returns:
            Dict with structured recommendations
        """
        recommendations = {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "data_quality": self._assess_data_quality(),
            "pillars_to_increase": [],
            "pillars_to_decrease": [],
            "hooks_to_use": [],
            "optimal_posting_times": [],
            "topics_to_explore": [],
            "platforms_to_focus": []
        }

        # Check if we have enough data for meaningful analysis
        if not self._has_sufficient_data():
            recommendations["data_quality"]["status"] = "insufficient"
            recommendations["data_quality"]["message"] = (
                f"Need at least {self.min_posts_for_analysis} posts for analysis. "
                f"Currently have {self._count_total_posts()}. "
                "Using default recommendations."
            )
            return self._get_default_recommendations(recommendations)

        # Analyze pillar performance
        pillar_recommendations = self._analyze_pillar_performance()
        recommendations["pillars_to_increase"] = pillar_recommendations["increase"]
        recommendations["pillars_to_decrease"] = pillar_recommendations["decrease"]

        # Analyze hook effectiveness
        hook_recommendations = self._analyze_hook_performance()
        recommendations["hooks_to_use"] = hook_recommendations

        # Analyze platform performance
        platform_recommendations = self._analyze_platform_performance()
        recommendations["platforms_to_focus"] = platform_recommendations

        # Generate optimal posting times
        recommendations["optimal_posting_times"] = self._analyze_posting_times()

        # Identify topics to explore
        recommendations["topics_to_explore"] = self._identify_trending_topics()

        # Save recommendations for future reference
        self._save_recommendations(recommendations)

        return recommendations

    def _assess_data_quality(self) -> Dict:
        """Assess the quality and quantity of available data"""
        total_posts = self._count_total_posts()
        posts_with_metrics = self._count_posts_with_metrics()

        return {
            "status": "sufficient" if total_posts >= self.min_posts_for_analysis else "insufficient",
            "total_posts": total_posts,
            "posts_with_metrics": posts_with_metrics,
            "data_freshness": self._get_data_freshness()
        }

    def _has_sufficient_data(self) -> bool:
        """Check if we have enough data for meaningful analysis"""
        return self._count_total_posts() >= self.min_posts_for_analysis

    def _count_total_posts(self) -> int:
        """Count total posts across all platforms"""
        count = 0

        # Count from Typefully (Twitter)
        typefully_data = _read_analytics(
            self.store, self.data_dir / "typefully_metrics.json", default={}
        )
        count += len(typefully_data)

        # Count from late.dev (LinkedIn) - placeholder for future
        # TODO: Add late.dev data counting when integrated

        return count

    def _count_posts_with_metrics(self) -> int:
        """Count posts that have meaningful metrics"""
        count = 0

        typefully_data = _read_analytics(
            self.store, self.data_dir / "typefully_metrics.json", default={}
        )
        for post_id, post in typefully_data.items():
            metrics = post.get("metrics", {})
            if metrics.get("impressions", 0) > 0:
                count += 1

        return count

    def _get_data_freshness(self) -> str:
        """Get how recent the analytics data is"""
        if self.store is not None:
            from data.repositories.analytics_repository import AnalyticsRepository

            snapshot = AnalyticsRepository(self.store).get_snapshot(
                "typefully_metrics.json", default=None
            )
            if snapshot is None:
                return "no_data"
            return "fresh"

        typefully_file = self.data_dir / "typefully_metrics.json"

        if not typefully_file.exists():
            return "no_data"

        # Get modification time
        mtime = datetime.fromtimestamp(typefully_file.stat().st_mtime, tz=timezone.utc)
        age = datetime.now(timezone.utc) - mtime

        if age < timedelta(hours=24):
            return "fresh"
        elif age < timedelta(days=7):
            return "recent"
        else:
            return "stale"

    def _analyze_pillar_performance(self) -> Dict:
        """Analyze which content pillars perform best

        Returns:
            Dict with 'increase' and 'decrease' lists of recommendations
        """
        pillar_stats = {}

        # Load analytics data
        typefully_data = _read_analytics(
            self.store, self.data_dir / "typefully_metrics.json", default={}
        )

        # Aggregate stats by pillar
        for post_id, post in typefully_data.items():
            pillar = post.get("pillar", "unknown")
            metrics = post.get("metrics", {})
            calculated = post.get("calculated_metrics", {})

            if pillar not in pillar_stats:
                pillar_stats[pillar] = {
                    "total_posts": 0,
                    "approved": 0,
                    "total_engagement": 0,
                    "total_impressions": 0
                }

            pillar_stats[pillar]["total_posts"] += 1
            pillar_stats[pillar]["total_engagement"] += calculated.get("engagement_rate", 0)
            pillar_stats[pillar]["total_impressions"] += metrics.get("impressions", 0)

        # Calculate success rates and generate recommendations
        increase = []
        decrease = []

        for pillar, stats in pillar_stats.items():
            if stats["total_posts"] == 0:
                continue

            avg_engagement = round(
                stats["total_engagement"] / stats["total_posts"], 2
            )
            success_rate = min(100, round(avg_engagement * 10, 1))  # Normalize to 0-100

            if success_rate > 50:  # High performers
                increase.append({
                    "pillar": pillar,
                    "reason": f"High success rate ({success_rate}%)",
                    "suggested_weight": min(1.0, success_rate / 100),
                    "avg_engagement": avg_engagement,
                    "sample_size": stats["total_posts"]
                })
            elif success_rate < 20:  # Low performers
                decrease.append({
                    "pillar": pillar,
                    "reason": f"Low success rate ({success_rate}%)",
                    "suggested_weight": 0.2,
                    "avg_engagement": avg_engagement,
                    "sample_size": stats["total_posts"]
                })

        # Sort by performance
        increase.sort(key=lambda x: x["avg_engagement"], reverse=True)
        decrease.sort(key=lambda x: x["avg_engagement"])

        return {"increase": increase, "decrease": decrease}

    def _analyze_hook_performance(self) -> List[Dict]:
        """Analyze which hooks perform best

        Returns:
            List of hook recommendations sorted by effectiveness
        """
        hook_stats = {}

        # Load analytics data
        typefully_data = _read_analytics(
            self.store, self.data_dir / "typefully_metrics.json", default={}
        )

        # Aggregate stats by hook type
        for post_id, post in typefully_data.items():
            hook = post.get("hook_type", "unknown")
            calculated = post.get("calculated_metrics", {})

            if hook not in hook_stats:
                hook_stats[hook] = {
                    "total_posts": 0,
                    "total_engagement": 0
                }

            hook_stats[hook]["total_posts"] += 1
            hook_stats[hook]["total_engagement"] += calculated.get("engagement_rate", 0)

        # Calculate averages and generate recommendations
        recommendations = []

        for hook, stats in hook_stats.items():
            if stats["total_posts"] == 0:
                continue

            avg_engagement = round(
                stats["total_engagement"] / stats["total_posts"], 2
            )

            frequency = "high" if avg_engagement > 5 else "medium" if avg_engagement > 2 else "low"

            recommendations.append({
                "hook_type": hook,
                "avg_engagement": avg_engagement,
                "sample_size": stats["total_posts"],
                "reason": f"Avg engagement {avg_engagement}%",
                "suggested_frequency": frequency
            })

        # Sort by engagement
        recommendations.sort(key=lambda x: x["avg_engagement"], reverse=True)

        # Return top 5
        return recommendations[:5]

    def _analyze_platform_performance(self) -> List[Dict]:
        """Analyze which platforms perform best

        Returns:
            List of platform recommendations
        """
        platforms = []

        # Load unified analytics
        unified_data = _read_analytics(
            self.store, self.data_dir / "unified_analytics.json", default={}
        )
        for platform_name, platform_data in unified_data.get("platforms", {}).items():
            if not platform_data:
                continue

            platforms.append({
                "platform": platform_name,
                "post_count": platform_data.get("post_count", 0),
                "average_engagement": platform_data.get("average_engagement", 0),
                "reason": f"{platform_data.get('post_count', 0)} posts with {platform_data.get('average_engagement', 0)}% avg engagement",
                "suggested_allocation": "high" if platform_data.get("average_engagement", 0) > 3 else "medium"
            })

        # Sort by engagement
        platforms.sort(key=lambda x: x["average_engagement"], reverse=True)

        return platforms

    def _analyze_posting_times(self) -> List[Dict]:
        """Analyze optimal posting times

        Returns:
            List of recommended posting times
        """
        # Default recommendations based on general social media best practices
        # TODO: Replace with actual posting time analysis when time data is available

        return [
            {
                "day": "Tuesday",
                "time_range": "9:00 AM - 11:00 AM",
                "reason": "High engagement during morning commute"
            },
            {
                "day": "Wednesday",
                "time_range": "12:00 PM - 2:00 PM",
                "reason": "Mid-week engagement peak"
            },
            {
                "day": "Thursday",
                "time_range": "3:00 PM - 5:00 PM",
                "reason": "Afternoon browsing time"
            }
        ]

    def _identify_trending_topics(self) -> List[Dict]:
        """Identify topics to explore based on performance

        Returns:
            List of topic recommendations
        """
        # Load analytics data and extract top-performing content
        topics = []

        typefully_data = _read_analytics(
            self.store, self.data_dir / "typefully_metrics.json", default={}
        )

        # Get top 5 posts by engagement
        posts_by_engagement = sorted(
            [
                (post_id, post)
                for post_id, post in typefully_data.items()
                if post.get("calculated_metrics", {}).get("engagement_rate", 0) > 0
            ],
            key=lambda x: x[1].get("calculated_metrics", {}).get("engagement_rate", 0),
            reverse=True
        )[:5]

        # Extract topics from top posts
        for post_id, post in posts_by_engagement:
            topic = post.get("topic", "General AI")
            pillar = post.get("pillar", "unknown")
            engagement = post.get("calculated_metrics", {}).get("engagement_rate", 0)

            topics.append({
                "topic": topic,
                "pillar": pillar,
                "reason": f"Top performing post ({engagement}% engagement)",
                "engagement_rate": engagement
            })

        return topics

    def _get_default_recommendations(self, recommendations: Dict) -> Dict:
        """Get default recommendations when insufficient data is available"""
        recommendations["pillars_to_increase"] = [
            {
                "pillar": "educational",
                "reason": "Safe starting pillar - broad appeal",
                "suggested_weight": 0.5,
                "avg_engagement": 0,
                "sample_size": 0
            }
        ]
        recommendations["hooks_to_use"] = [
            {
                "hook_type": "value",
                "avg_engagement": 0,
                "sample_size": 0,
                "reason": "High-converting hook type",
                "suggested_frequency": "medium"
            }
        ]
        recommendations["platforms_to_focus"] = [
            {
                "platform": "twitter",
                "post_count": 0,
                "average_engagement": 0,
                "reason": "Primary platform for tech audience",
                "suggested_allocation": "high"
            }
        ]
        recommendations["optimal_posting_times"] = self._analyze_posting_times()
        recommendations["topics_to_explore"] = [
            {
                "topic": "Building AI agents",
                "pillar": "educational",
                "reason": "Core Draper topic",
                "engagement_rate": 0
            }
        ]

        return recommendations

    def _save_recommendations(self, recommendations: Dict):
        """Save recommendations to file for future reference"""
        with open(self.recommendations_file, 'w') as f:
            json.dump(recommendations, f, indent=2)

    def load_saved_recommendations(self) -> Optional[Dict]:
        """Load previously saved recommendations

        Returns:
            Dict of saved recommendations or None if not found
        """
        return _read_analytics(self.store, self.recommendations_file, default=None)


def main():
    """CLI for analytics optimizer"""
    import argparse

    parser = argparse.ArgumentParser(description="Generate content recommendations from analytics")
    parser.add_argument("--analytics", help="Path to analytics JSON file")
    parser.add_argument("--preferences", help="Path to preferences JSON file")
    parser.add_argument("--output", help="Output path for recommendations")

    args = parser.parse_args()

    # Load analytics data
    if args.analytics:
        with open(args.analytics, 'r') as f:
            analytics_data = json.load(f)
    else:
        # Use default path
        data_dir = Path(__file__).resolve().parent.parent / "data"
        analytics_data = {}

    # Load preferences
    if args.preferences:
        with open(args.preferences, 'r') as f:
            preference_data = json.load(f)
    else:
        preference_data = {}

    # Generate recommendations
    optimizer = AnalyticsOptimizer(analytics_data, preference_data)
    recommendations = optimizer.generate_content_recommendations()

    # Output
    print(json.dumps(recommendations, indent=2))

    # Save if requested
    if args.output:
        with open(args.output, 'w') as f:
            json.dump(recommendations, f, indent=2)
        print(f"\n✅ Saved recommendations to {args.output}")


if __name__ == "__main__":
    main()
