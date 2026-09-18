#!/usr/bin/env python3
"""
Unified Analytics Collector
Collects and analyzes data from Typefully (Twitter/X) and late.dev (LinkedIn)
"""

import json
import os
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pathlib import Path

from data.atomic_io import atomic_write_json
from .analytics_optimizer import AnalyticsOptimizer
from .typefully_analytics import TypefullyAnalytics, _SNAPSHOT_MISSING, _read_analytics


def _read_unified(store: Any, file_path: Path, default: Any) -> Any:
    """SQLite-first reader for unified_analytics snapshot with JSON fallback."""
    if store is not None:
        from data.repositories.analytics_repository import AnalyticsRepository

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


class UnifiedAnalytics:
    """Collect and analyze analytics from all platforms"""

    def __init__(
        self,
        typefully_api_key: str = None,
        late_api_key: str = None,
        data_dir: str = None
    ):
        if data_dir is None:
            data_dir = str(Path(__file__).resolve().parent.parent / "data")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Use SQLite as primary store, with file fallback for legacy compat
        self.unified_file = self.data_dir / "unified_analytics.json"
        self._store = None

        try:
            self.typefully = TypefullyAnalytics(
                api_key=typefully_api_key, data_dir=data_dir, store=self.store
            )
        except ValueError as e:
            self.typefully = None
            self.typefully_error = str(e)
        self.late_api_key = late_api_key or os.getenv("LATE_API_KEY")

    @property
    def store(self):
        """Lazy-load the SQLiteStore."""
        if self._store is None:
            from data.sqlite_store import SQLiteStore
            self._store = SQLiteStore(self.data_dir)
        return self._store

    def sync_all_platforms(self) -> Dict:
        """Sync analytics from all platforms

        Returns:
            Dict with sync results from all platforms
        """
        print("\n" + "="*60)
        print("🔄 SYNCING ALL PLATFORM ANALYTICS")
        print("="*60 + "\n")

        results = {
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "platforms": {}
        }

        # Sync Typefully (Twitter/X)
        print("🐦 Syncing Typefully (Twitter/X)...")
        typefully_results = (
            self.typefully.sync_analytics()
            if self.typefully
            else {"errors": [self.typefully_error], "posts_collected": 0, "trends_analyzed": False}
        )
        results["platforms"]["twitter"] = {
            "success": len(typefully_results.get("errors", [])) == 0,
            "posts_collected": typefully_results.get("posts_collected", 0),
            "trends_analyzed": typefully_results.get("trends_analyzed", False),
            "errors": typefully_results.get("errors", [])
        }

        # Sync late.dev (LinkedIn)
        print("\n💼 Syncing late.dev (LinkedIn)...")
        late_results = {
            "success": False,
            "status": "not_configured" if not self.late_api_key else "not_implemented",
            "posts_collected": 0,
            "trends_analyzed": False,
            "errors": ["late.dev analytics sync is not implemented"]
        }
        results["platforms"]["linkedin"] = late_results

        # Create unified view
        self._create_unified_view()

        # Summary
        print("\n" + "="*60)
        print("✅ SYNC SUMMARY")
        print("="*60)

        for platform, data in results["platforms"].items():
            icon = "🐦" if platform == "twitter" else "💼"
            status = "✅" if data["success"] else "❌"
            print(f"{icon} {platform.upper()}: {status}")
            print(f"   Posts: {data['posts_collected']}")
            print(f"   Trends: {data['trends_analyzed']}")
            if data["errors"]:
                print(f"   Errors: {len(data['errors'])}")

        print("="*60)

        return results

    def _create_unified_view(self):
        """Create unified analytics view across platforms"""
        unified = {
            "last_updated": datetime.now(timezone.utc).isoformat(),
            "platforms": {
                "twitter": {},
                "linkedin": {}
            },
            "combined_metrics": {
                "total_posts": 0,
                "total_impressions": 0,
                "total_engagement": 0,
                "average_engagement_rate": 0.0,
                "best_performing_platform": None
            }
        }

        # Load Typefully data
        typefully_data = _read_analytics(
            self.store, self.data_dir / "typefully_metrics.json", default={}
        )

        if typefully_data:
            unified["platforms"]["twitter"] = {
                "post_count": len(typefully_data),
                "latest_post": self._get_latest_post(typefully_data),
                "average_engagement": self._calculate_average_engagement(typefully_data)
            }

            # Add to combined metrics
            for post_id, post in typefully_data.items():
                metrics = post.get("metrics", {})
                unified["combined_metrics"]["total_impressions"] += metrics.get("impressions", 0)
                unified["combined_metrics"]["total_engagement"] += (
                    metrics.get("likes", 0) +
                    metrics.get("retweets", 0) +
                    metrics.get("replies", 0) +
                    metrics.get("bookmarks", 0)
                )

            unified["combined_metrics"]["total_posts"] += len(typefully_data)

        from data.repositories.analytics_repository import AnalyticsRepository

        AnalyticsRepository(self.store).save_snapshot("unified_analytics.json", unified)
        atomic_write_json(self.unified_file, unified)

        print("💾 Saved unified analytics to SQLite")

    def _get_latest_post(self, posts_data: Dict) -> Optional[Dict]:
        """Get most recent post from data"""
        sorted_posts = sorted(
            list(posts_data.values()),
            key=lambda x: x.get("posted_at", ""),
            reverse=True
        )
        return sorted_posts[0] if sorted_posts else None

    def _calculate_average_engagement(self, posts_data: Dict) -> float:
        """Calculate average engagement rate"""
        total_er = 0
        count = 0

        for post in posts_data.values():
            er = post.get("calculated_metrics", {}).get("engagement_rate", 0)
            if er > 0:
                total_er += er
                count += 1

        return round(total_er / count, 2) if count > 0 else 0.0

    def get_unified_dashboard(self) -> Dict:
        """Get unified analytics dashboard

        Returns:
            Dict with all analytics data
        """
        # Primary: analytics_snapshots table
        snapshot = _read_unified(self.store, self.unified_file, default=None)
        if snapshot is not None:
            return snapshot
        # Secondary: project_kv (Phase 1 partial-migration path)
        data = self.store.get_project_value("_analytics", "unified_analytics")
        if data:
            return data
        return {
            "error": "No unified analytics available. Run sync first."
        }

    def get_top_posts_across_platforms(
        self,
        limit: int = 20,
        min_engagement_rate: float = 1.0
    ) -> List[Dict]:
        """Get top performing posts across all platforms

        Args:
            limit: Maximum number of posts
            min_engagement_rate: Minimum engagement rate threshold

        Returns:
            List of top posts with platform info
        """
        all_posts = []

        # Load Typefully posts
        typefully_data = _read_analytics(
            self.store, self.data_dir / "typefully_metrics.json", default={}
        )
        for post_id, post in typefully_data.items():
            er = post.get("calculated_metrics", {}).get("engagement_rate", 0)
            if er >= min_engagement_rate:
                all_posts.append({
                    "post_id": post_id,
                    "platform": "twitter",
                    "engagement_rate": er,
                    "metrics": post.get("metrics", {}),
                    "posted_at": post.get("posted_at", "")
                })

        # Load late posts (placeholder)
        # When late.dev integration is ready, add similar logic

        # Sort by engagement rate
        sorted_posts = sorted(all_posts, key=lambda x: x["engagement_rate"], reverse=True)

        return sorted_posts[:limit]

    def get_platform_comparison(self) -> Dict:
        """Compare performance across platforms

        Returns:
            Dict with platform comparison data
        """
        dashboard = self.get_unified_dashboard()

        if "error" in dashboard:
            return dashboard

        comparison = {
            "platforms": [],
            "best_platform": None,
            "total_impressions": 0,
            "total_engagement": 0
        }

        # Collect platform metrics
        for platform, data in dashboard["platforms"].items():
            if data:
                comparison["platforms"].append({
                    "name": platform,
                    "post_count": data.get("post_count", 0),
                    "average_engagement": data.get("average_engagement", 0.0)
                })

        # Find best performing platform
        if comparison["platforms"]:
            best = max(comparison["platforms"], key=lambda x: x["average_engagement"])
            comparison["best_platform"] = best["name"]

        # Add combined metrics
        combined = dashboard.get("combined_metrics", {})
        comparison["total_impressions"] = combined.get("total_impressions", 0)
        comparison["total_engagement"] = combined.get("total_engagement", 0)

        return comparison

    def generate_analytics_report(self) -> str:
        """Generate analytics report

        Returns:
            Formatted report string
        """
        dashboard = self.get_unified_dashboard()

        if "error" in dashboard:
            return f"❌ Error: {dashboard['error']}"

        combined = dashboard.get("combined_metrics", {})

        report = []
        report.append("\n" + "="*60)
        report.append("📊 UNIFIED ANALYTICS REPORT")
        report.append("="*60)
        report.append(f"\n📅 Generated: {dashboard['last_updated']}")
        report.append(f"\n📈 COMBINED METRICS:")
        report.append(f"   Total Posts: {combined.get('total_posts', 0)}")
        report.append(f"   Total Impressions: {combined.get('total_impressions', 0)}")
        report.append(f"   Total Engagement: {combined.get('total_engagement', 0)}")
        report.append(f"   Avg Engagement Rate: {combined.get('average_engagement_rate', 0.0)}%")

        report.append(f"\n🐦 TWITTER/X:")
        twitter = dashboard["platforms"].get("twitter", {})
        if twitter:
            report.append(f"   Posts: {twitter.get('post_count', 0)}")
            report.append(f"   Avg Engagement: {twitter.get('average_engagement', 0.0)}%")
        else:
            report.append(f"   No data available")

        report.append(f"\n💼 LINKEDIN:")
        linkedin = dashboard["platforms"].get("linkedin", {})
        if linkedin and linkedin.get("post_count", 0) > 0:
            report.append(f"   Posts: {linkedin.get('post_count', 0)}")
            report.append(f"   Avg Engagement: {linkedin.get('average_engagement', 0.0)}%")
        else:
            report.append(f"   No data available")

        report.append("\n" + "="*60 + "\n")

        return "\n".join(report)

    def export_all_data(
        self,
        format: str = "json",
        output_path: Optional[str] = None
    ) -> str:
        """Export all analytics data

        Args:
            format: Export format (json, csv)
            output_path: Optional output path

        Returns:
            Path to exported file
        """
        dashboard = self.get_unified_dashboard()

        if not output_path:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_path = self.data_dir / f"unified_analytics_{timestamp}.{format}"

        if format == "json":
            with open(output_path, 'w') as f:
                json.dump(dashboard, f, indent=2)

        elif format == "csv":
            import csv
            import io

            output = io.StringIO()
            writer = None

            # Flatten platform data for CSV
            for platform, data in dashboard.get("platforms", {}).items():
                if data and "latest_post" in data and data["latest_post"]:
                    post = data["latest_post"]
                    row = {
                        "platform": platform,
                        "post_id": post.get("post_id", ""),
                        "posted_at": post.get("posted_at", ""),
                        "engagement_rate": post.get("calculated_metrics", {}).get("engagement_rate", 0),
                        "likes": post.get("metrics", {}).get("likes", 0),
                        "retweets": post.get("metrics", {}).get("retweets", 0),
                        "replies": post.get("metrics", {}).get("replies", 0)
                    }

                    if writer is None:
                        writer = csv.DictWriter(output, fieldnames=row.keys())
                        writer.writeheader()

                    writer.writerow(row)

            output.seek(0)
            with open(output_path, 'w') as f:
                f.write(output.getvalue())

        print(f"📤 Exported all analytics to {output_path}")
        return str(output_path)

    def get_all_metrics(self) -> Dict:
        """Get all available metrics for analytics optimizer

        Returns:
            Dict with all metrics data from all platforms
        """
        all_metrics = {
            "platforms": {},
            "posts": []
        }

        # Load Typefully data
        typefully_data = _read_analytics(
            self.store, self.data_dir / "typefully_metrics.json", default={}
        )
        if typefully_data:
            all_metrics["platforms"]["twitter"] = {
                "posts": list(typefully_data.values())
            }

            # Flatten posts for analysis
            for post_id, post in typefully_data.items():
                post["platform"] = "twitter"
                all_metrics["posts"].append(post)

        # TODO: Add late.dev data when integrated

        return all_metrics

    def generate_content_recommendations(self) -> Dict:
        """Generate content recommendations based on analytics

        This method uses the AnalyticsOptimizer to analyze historical
        performance and generate actionable recommendations for content strategy.

        Returns:
            Dict with structured recommendations for pillars, hooks, platforms, etc.
        """
        print("\n" + "="*60)
        print("🧠 GENERATING CONTENT RECOMMENDATIONS")
        print("="*60 + "\n")

        # Get all metrics
        metrics = self.get_all_metrics()

        # Create optimizer and generate recommendations
        optimizer = AnalyticsOptimizer(
            analytics_data=metrics,
            preference_data={},  # Could be loaded from preferences file
            data_dir=str(self.data_dir),
            store=self.store,
        )

        recommendations = optimizer.generate_content_recommendations()

        # Save to SQLite for the generator to pick up
        self.store.set_project_value("_analytics", "content_recommendations", recommendations)
        from data.repositories.analytics_repository import AnalyticsRepository

        AnalyticsRepository(self.store).save_snapshot(
            "content_recommendations.json", recommendations
        )

        # Display summary
        self._display_recommendations_summary(recommendations)

        return recommendations

    def _display_recommendations_summary(self, recommendations: Dict):
        """Display a summary of the recommendations"""
        print("📊 RECOMMENDATIONS SUMMARY")
        print("-" * 60)

        data_quality = recommendations.get("data_quality", {})
        status_emoji = "✅" if data_quality.get("status") == "sufficient" else "⚠️"
        print(f"\n{status_emoji} Data Quality: {data_quality.get('status', 'unknown').upper()}")
        print(f"   Total Posts: {data_quality.get('total_posts', 0)}")
        if data_quality.get("message"):
            print(f"   {data_quality['message']}")

        # Pillars to increase
        if recommendations.get("pillars_to_increase"):
            print(f"\n📈 Pillars to INCREASE:")
            for item in recommendations["pillars_to_increase"][:3]:
                print(f"   • {item['pillar']}: {item['reason']}")

        # Pillars to decrease
        if recommendations.get("pillars_to_decrease"):
            print(f"\n📉 Pillars to DECREASE:")
            for item in recommendations["pillars_to_decrease"][:3]:
                print(f"   • {item['pillar']}: {item['reason']}")

        # Top hooks
        if recommendations.get("hooks_to_use"):
            print(f"\n🎣 Top Performing Hooks:")
            for item in recommendations["hooks_to_use"][:3]:
                print(f"   • {item['hook_type']}: {item['reason']}")

        # Platform focus
        if recommendations.get("platforms_to_focus"):
            print(f"\n📱 Platform Focus:")
            for item in recommendations["platforms_to_focus"]:
                print(f"   • {item['platform'].upper()}: {item['reason']}")

        print("\n" + "="*60)

    def update_preference_weights(self, preferences: Dict) -> Dict:
        """Update content preference weights based on analytics

        This method analyzes historical performance and adjusts the weights
        in the provided preferences dict to favor high-performing content.

        Args:
            preferences: Current content preferences dict

        Returns:
            Updated preferences dict with adjusted weights
        """
        print("\n🔄 Updating preference weights based on analytics...")

        # Generate recommendations
        recommendations = self.generate_content_recommendations()

        # Update pillar weights
        pillar_weights = {}
        for item in recommendations.get("pillars_to_increase", []):
            pillar_weights[item["pillar"]] = item["suggested_weight"]

        # Add default weights for pillars not in recommendations
        default_pillars = [
            "radical_transparency",
            "production_engineering",
            "educational",
            "behind_the_scenes",
            "industry_insights"
        ]

        for pillar in default_pillars:
            if pillar not in pillar_weights:
                pillar_weights[pillar] = 0.3  # Default weight

        # Normalize weights to sum to 1.0
        total_weight = sum(pillar_weights.values())
        if total_weight > 0:
            pillar_weights = {
                k: round(v / total_weight, 3)
                for k, v in pillar_weights.items()
            }

        # Update preferences
        if "pillar_weights" not in preferences:
            preferences["pillar_weights"] = {}

        preferences["pillar_weights"].update(pillar_weights)

        # Add hook preferences
        hook_preferences = []
        for item in recommendations.get("hooks_to_use", []):
            hook_preferences.append({
                "hook_type": item["hook_type"],
                "frequency": item["suggested_frequency"]
            })

        preferences["hook_preferences"] = hook_preferences

        # Add platform preferences
        platform_preferences = []
        for item in recommendations.get("platforms_to_focus", []):
            platform_preferences.append({
                "platform": item["platform"],
                "allocation": item["suggested_allocation"]
            })

        preferences["platform_preferences"] = platform_preferences

        # Save updated preferences
        preferences_file = self.data_dir / "content_preferences.json"
        with open(preferences_file, 'w') as f:
            json.dump(preferences, f, indent=2)

        print(f"✅ Updated preferences saved to {preferences_file}")
        print(f"   Pillar weights: {pillar_weights}")
        print(f"   Hook preferences: {len(hook_preferences)} hooks")
        print(f"   Platform preferences: {len(platform_preferences)} platforms")

        return preferences

    def analyze_performance_patterns(self) -> Dict:
        """Analyze performance patterns over time

        Identifies trends and patterns in content performance:
        - Which pillars are trending up/down
        - Seasonal patterns
        - Engagement rate trends

        Returns:
            Dict with performance pattern analysis
        """
        print("\n" + "="*60)
        print("📈 ANALYZING PERFORMANCE PATTERNS")
        print("="*60 + "\n")

        patterns = {
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "trends": {},
            "insights": []
        }

        # Load analytics data
        typefully_data = _read_analytics(
            self.store, self.data_dir / "typefully_metrics.json", default=None
        )
        if not typefully_data:
            patterns["insights"].append("No data available for pattern analysis")
            return patterns

        # Sort posts by date
        sorted_posts = sorted(
            typefully_data.values(),
            key=lambda x: x.get("posted_at", ""),
            reverse=True
        )

        if len(sorted_posts) < 3:
            patterns["insights"].append("Need at least 3 posts for trend analysis")
            return patterns

        # Calculate recent vs older performance
        recent_posts = sorted_posts[:max(3, len(sorted_posts) // 3)]
        older_posts = sorted_posts[len(recent_posts):]

        recent_avg_er = sum(
            p.get("calculated_metrics", {}).get("engagement_rate", 0)
            for p in recent_posts
        ) / len(recent_posts)

        older_avg_er = sum(
            p.get("calculated_metrics", {}).get("engagement_rate", 0)
            for p in older_posts
        ) / len(older_posts) if older_posts else recent_avg_er

        # Trend analysis
        if recent_avg_er > older_avg_er * 1.2:
            patterns["trends"]["overall"] = "improving"
            patterns["insights"].append(
                f"Engagement rate improving: {recent_avg_er:.2f}% (recent) vs {older_avg_er:.2f}% (older)"
            )
        elif recent_avg_er < older_avg_er * 0.8:
            patterns["trends"]["overall"] = "declining"
            patterns["insights"].append(
                f"Engagement rate declining: {recent_avg_er:.2f}% (recent) vs {older_avg_er:.2f}% (older)"
            )
        else:
            patterns["trends"]["overall"] = "stable"
            patterns["insights"].append(
                f"Engagement rate stable: {recent_avg_er:.2f}% (recent) vs {older_avg_er:.2f}% (older)"
            )

        # Pillar trends
        pillar_trends = {}
        for post in sorted_posts:
            pillar = post.get("pillar", "unknown")
            er = post.get("calculated_metrics", {}).get("engagement_rate", 0)

            if pillar not in pillar_trends:
                pillar_trends[pillar] = []

            pillar_trends[pillar].append(er)

        for pillar, er_list in pillar_trends.items():
            if len(er_list) >= 3:
                recent = sum(er_list[:len(er_list)//3]) / (len(er_list)//3)
                older = sum(er_list[len(er_list)//3:]) / (len(er_list) - len(er_list)//3)

                if recent > older * 1.1:
                    patterns["trends"][pillar] = "rising"
                    patterns["insights"].append(f"{pillar} engagement trending up")
                elif recent < older * 0.9:
                    patterns["trends"][pillar] = "falling"
                    patterns["insights"].append(f"{pillar} engagement trending down")

        print("📊 Performance Patterns:")
        for insight in patterns["insights"]:
            print(f"   • {insight}")

        print("\n" + "="*60)

        return patterns


def main():
    """CLI for unified analytics"""
    import argparse

    parser = argparse.ArgumentParser(description="Unified analytics collector")
    parser.add_argument("--sync", action="store_true", help="Sync all platforms")
    parser.add_argument("--dashboard", action="store_true", help="Show unified dashboard")
    parser.add_argument("--compare", action="store_true", help="Compare platform performance")
    parser.add_argument("--top", type=int, default=20, help="Get top N posts")
    parser.add_argument("--min-er", type=float, default=1.0, help="Minimum engagement rate")
    parser.add_argument("--report", action="store_true", help="Generate analytics report")
    parser.add_argument("--export", type=str, choices=["json", "csv"], help="Export all data")
    parser.add_argument("--recommendations", action="store_true", help="Generate content recommendations")
    parser.add_argument("--patterns", action="store_true", help="Analyze performance patterns")
    parser.add_argument("--update-weights", action="store_true", help="Update preference weights")

    args = parser.parse_args()

    analytics = UnifiedAnalytics()

    if args.sync:
        results = analytics.sync_all_platforms()
        print("\n✅ Sync complete!")

    elif args.dashboard:
        dashboard = analytics.get_unified_dashboard()
        print("\n" + "="*60)
        print("📊 UNIFIED ANALYTICS DASHBOARD")
        print("="*60)
        print(json.dumps(dashboard, indent=2))

    elif args.compare:
        comparison = analytics.get_platform_comparison()
        print("\n" + "="*60)
        print("📈 PLATFORM COMPARISON")
        print("="*60)
        print(json.dumps(comparison, indent=2))

    elif args.recommendations:
        recommendations = analytics.generate_content_recommendations()
        print("\n" + "="*60)
        print("📊 FULL RECOMMENDATIONS")
        print("="*60)
        print(json.dumps(recommendations, indent=2))

    elif args.patterns:
        patterns = analytics.analyze_performance_patterns()
        print("\n" + "="*60)
        print("📊 PERFORMANCE PATTERNS")
        print("="*60)
        print(json.dumps(patterns, indent=2))

    elif args.update_weights:
        preferences = {}
        updated = analytics.update_preference_weights(preferences)
        print("\n" + "="*60)
        print("📊 UPDATED PREFERENCES")
        print("="*60)
        print(json.dumps(updated, indent=2))

    elif args.report:
        report = analytics.generate_analytics_report()
        print(report)

    elif args.export:
        output_path = analytics.export_all_data(format=args.export)
        print(f"✅ Exported to {output_path}")

    elif args.top:
        top_posts = analytics.get_top_posts_across_platforms(
            limit=args.top,
            min_engagement_rate=args.min_er
        )

        print(f"\n🏆 Top {len(top_posts)} Posts (ER > {args.min_er}%):")
        for i, post in enumerate(top_posts, 1):
            icon = "🐦" if post["platform"] == "twitter" else "💼"
            print(f"\n{i}. {icon} {post['post_id']}")
            print(f"   Engagement Rate: {post['engagement_rate']}%")
            print(f"   Posted: {post['posted_at']}")
            print(f"   Likes: {post['metrics'].get('likes', 0)}")
            print(f"   Retweets/Shares: {post['metrics'].get('retweets', 0)}")
            print(f"   Replies: {post['metrics'].get('replies', 0)}")

    else:
        print("Usage:")
        print("  --sync           Sync analytics from all platforms")
        print("  --dashboard      Show unified dashboard")
        print("  --compare        Compare platform performance")
        print("  --top N          Get top N posts")
        print("  --report         Generate analytics report")
        print("  --export json/csv  Export all data")
        print("  --recommendations  Generate content recommendations")
        print("  --patterns       Analyze performance patterns")
        print("  --update-weights  Update preference weights")


if __name__ == "__main__":
    main()
