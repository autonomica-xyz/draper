#!/usr/bin/env python3
"""
Typefully Analytics Collector
Retrieve and store engagement data from Typefully (Twitter/X)

API Documentation:
- https://typefully.com/docs/api
- https://support.typefully.com/en/articles/8718287-typefully-api

NOTE: Typefully API currently does NOT provide analytics metrics (impressions,
likes, retweets, etc.) via API. This implementation retrieves post data from
Typefully and requires Twitter API integration for actual analytics.
"""

import json
import os
import time
import warnings
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pathlib import Path

import httpx


_SNAPSHOT_MISSING = object()


def _read_analytics(store: Any, file_path: Path, default: Any) -> Any:
    """SQLite-first analytics reader with deprecated JSON file fallback."""
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


class TypefullyAPIError(Exception):
    """Base exception for Typefully API errors"""
    pass


class TypefullyRateLimitError(TypefullyAPIError):
    """Rate limit exceeded"""
    pass


class TypefullyAuthError(TypefullyAPIError):
    """Authentication failed"""
    pass


class TypefullyAnalytics:
    """Collect and analyze Twitter/X analytics from Typefully"""

    def __init__(
        self,
        api_key: str = None,
        data_dir: str = None,
        store: Any = None
    ):
        if data_dir is None:
            data_dir = str(Path(__file__).resolve().parent.parent / "data")
        # API key from parameter or environment. Do not use source-code defaults.
        self.api_key = api_key or os.getenv("TYPEFULLY_API_KEY")

        if not self.api_key or self.api_key == "your-typefully-key-here":
            raise ValueError(
                "TYPEFULLY_API_KEY not set. Get your API key from: "
                "https://typefully.com/settings/api\n"
                "Set it via: export TYPEFULLY_API_KEY='your-key'"
            )

        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.store = store

        # API Configuration
        self.base_url = "https://api.typefully.com/v1"
        self.timeout = 30.0
        self.max_retries = 3
        self.retry_delay = 1.0

        # Create HTTP client
        self.client = httpx.Client(
            headers={
                "X-API-KEY": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            timeout=self.timeout
        )

        # Analytics data files
        self.metrics_file = self.data_dir / "typefully_metrics.json"
        self.analytics_file = self.data_dir / "typefully_analytics.json"
        self.trends_file = self.data_dir / "typefully_trends.json"

    def __enter__(self):
        """Context manager entry"""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup HTTP client"""
        self.close()
        return False

    def close(self):
        """Close HTTP client"""
        if hasattr(self, 'client'):
            self.client.close()

    def __del__(self):
        """Destructor - ensure HTTP client is closed"""
        self.close()

    def create_draft(
        self,
        content: str,
        threadify: bool = False,
        schedule_date: str = None,
        auto_retweet_enabled: bool = False,
        auto_plug_enabled: bool = False
    ) -> Dict:
        """Create a new draft in Typefully

        Args:
            content: Tweet content (use \n\n\n\n to separate tweets in a thread)
            threadify: Auto-split content into tweets
            schedule_date: ISO date string for scheduling (e.g., "2025-01-28T09:00:00Z")
            auto_retweet_enabled: Enable auto-retweet
            auto_plug_enabled: Enable auto-plug

        Returns:
            Dict with created draft data

        Example:
            >>> analytics = TypefullyAnalytics()
            >>> draft = analytics.create_draft("Hello world!")
            >>> print(draft)
        """
        print(f"✏️ Creating draft in Typefully...")

        payload = {
            "content": content
        }

        if threadify:
            payload["threadify"] = threadify
        if schedule_date:
            payload["schedule-date"] = schedule_date
        if auto_retweet_enabled:
            payload["auto_retweet_enabled"] = auto_retweet_enabled
        if auto_plug_enabled:
            payload["auto_plug_enabled"] = auto_plug_enabled

        try:
            result = self._api_call("POST", "/drafts/", json=payload)
            print(f"✅ Draft created successfully")
            return result
        except TypefullyAPIError as e:
            print(f"❌ Failed to create draft: {e}")
            raise

    def _api_call(self, method: str, endpoint: str, **kwargs) -> Dict:
        """Make API call with retry logic

        Args:
            method: HTTP method (GET, POST, etc.)
            endpoint: API endpoint path
            **kwargs: Additional arguments for httpx

        Returns:
            Response JSON as dict

        Raises:
            TypefullyAPIError: For API errors
        """
        url = f"{self.base_url}{endpoint}"

        for attempt in range(self.max_retries):
            try:
                response = self.client.request(method, url, **kwargs)
                response.raise_for_status()
                return response.json()

            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code

                # Authentication error
                if status_code == 401:
                    raise TypefullyAuthError(
                        "Invalid Typefully API key. Get your key from: "
                        "https://typefully.com/settings/api"
                    )

                # Rate limit error
                if status_code == 429:
                    if attempt < self.max_retries - 1:
                        # Exponential backoff
                        wait_time = self.retry_delay * (2 ** attempt)
                        print(f"⏳ Rate limited. Waiting {wait_time}s...")
                        time.sleep(wait_time)
                        continue
                    else:
                        raise TypefullyRateLimitError(
                            "Typefully API rate limit exceeded. Please wait."
                        )

                # Not found
                if status_code == 404:
                    return {"error": "Resource not found", "status": 404}

                # Other HTTP errors
                raise TypefullyAPIError(
                    f"API error {status_code}: {e.response.text}"
                )

            except httpx.TimeoutException:
                if attempt < self.max_retries - 1:
                    wait_time = self.retry_delay * (2 ** attempt)
                    print(f"⏳ Timeout. Retrying in {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                else:
                    raise TypefullyAPIError("Request timed out")

            except httpx.RequestError as e:
                raise TypefullyAPIError(f"Request failed: {str(e)}")

        return {}  # Should never reach here

    def collect_post_metrics(self, post_id: str) -> Dict:
        """Collect metrics for a specific post

        NOTE: Typefully API does not currently provide analytics metrics
        (impressions, likes, retweets, etc.). This method returns post data
        from Typefully, but actual analytics require Twitter API integration.

        Args:
            post_id: Typefully draft ID or Twitter URL

        Returns:
            Dict with post data (metrics unavailable via Typefully API)

        Example:
            >>> analytics = TypefullyAnalytics()
            >>> metrics = analytics.collect_post_metrics("draft_123")
            >>> print(metrics)
        """
        print(f"📊 Fetching metrics for post: {post_id}")

        # Typefully API doesn't have a get-by-id endpoint for published posts
        # We can only get lists of scheduled/published posts
        # For now, we'll return a note about this limitation

        result = {
            "post_id": post_id,
            "platform": "twitter",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "data_source": "typefully_api",
            "note": "Typefully API does not provide analytics metrics. "
                   "Integrate Twitter API for actual engagement data.",
            "metrics": {
                "impressions": None,
                "likes": None,
                "retweets": None,
                "replies": None,
                "quotes": None,
                "bookmarks": None,
                "profile_clicks": None,
                "url_clicks": None
            },
            "calculated_metrics": {
                "engagement_rate": None,
                "total_engagements": None
            }
        }

        # Try to find the post in recent drafts
        try:
            # Check published drafts
            published = self._api_call("GET", "/drafts/recently-published/")
            if "drafts" in published:
                for draft in published["drafts"]:
                    if draft.get("id") == post_id or draft.get("share_url", "").endswith(post_id):
                        result.update({
                            "draft_id": draft.get("id"),
                            "content": draft.get("content"),
                            "scheduled_date": draft.get("scheduled_date"),
                            "created_at": draft.get("created_at"),
                            "updated_at": draft.get("updated_at"),
                            "share_url": draft.get("share_url"),
                            "auto_retweet_enabled": draft.get("auto_retweet_enabled"),
                            "auto_plug_enabled": draft.get("auto_plug_enabled"),
                            "status": "published"
                        })
                        break

            # Check scheduled drafts if not found in published
            if "status" not in result:
                scheduled = self._api_call("GET", "/drafts/recently-scheduled/")
                if "drafts" in scheduled:
                    for draft in scheduled["drafts"]:
                        if draft.get("id") == post_id:
                            result.update({
                                "draft_id": draft.get("id"),
                                "content": draft.get("content"),
                                "scheduled_date": draft.get("scheduled_date"),
                                "created_at": draft.get("created_at"),
                                "updated_at": draft.get("updated_at"),
                                "share_url": draft.get("share_url"),
                                "auto_retweet_enabled": draft.get("auto_retweet_enabled"),
                                "auto_plug_enabled": draft.get("auto_plug_enabled"),
                                "status": "scheduled"
                            })
                            break

        except TypefullyAPIError as e:
            result["error"] = str(e)
            result["api_error"] = True

        return result

    def collect_all_recent_posts(
        self,
        days: int = 7,
        limit: int = 100
    ) -> List[Dict]:
        """Collect all recent posts (published and scheduled) from Typefully

        NOTE: Typefully API provides draft/post data but NOT analytics metrics.
        This method fetches real post data from Typefully API.

        Args:
            days: Number of days back to collect (note: Typefully doesn't filter by date)
            limit: Maximum number of posts to return

        Returns:
            List of post dictionaries with real data from Typefully API

        Example:
            >>> analytics = TypefullyAnalytics()
            >>> posts = analytics.collect_all_recent_posts(days=7, limit=50)
            >>> print(f"Collected {len(posts)} posts")
        """
        print(f"📊 Collecting posts from Typefully API...")

        all_posts = []

        try:
            # Fetch published drafts
            print("  → Fetching published drafts...")
            published_response = self._api_call("GET", "/drafts/recently-published/")

            if "drafts" in published_response:
                published_drafts = published_response["drafts"]
                print(f"  ✓ Found {len(published_drafts)} published drafts")

                for draft in published_drafts[:limit]:
                    post_data = {
                        "post_id": draft.get("id"),
                        "draft_id": draft.get("id"),
                        "content": draft.get("content"),
                        "scheduled_date": draft.get("scheduled_date"),
                        "created_at": draft.get("created_at"),
                        "updated_at": draft.get("updated_at"),
                        "share_url": draft.get("share_url"),
                        "auto_retweet_enabled": draft.get("auto_retweet_enabled"),
                        "auto_plug_enabled": draft.get("auto_plug_enabled"),
                        "status": "published",
                        "platform": "twitter",
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                        "data_source": "typefully_api",
                        "note": "Analytics metrics unavailable via Typefully API. "
                               "Integrate Twitter API for engagement data.",
                        "metrics": {
                            "impressions": None,
                            "likes": None,
                            "retweets": None,
                            "replies": None,
                            "quotes": None,
                            "bookmarks": None,
                            "profile_clicks": None,
                            "url_clicks": None
                        },
                        "calculated_metrics": {
                            "engagement_rate": None,
                            "total_engagements": None
                        }
                    }
                    all_posts.append(post_data)

            # Fetch scheduled drafts
            print("  → Fetching scheduled drafts...")
            scheduled_response = self._api_call("GET", "/drafts/recently-scheduled/")

            if "drafts" in scheduled_response:
                scheduled_drafts = scheduled_response["drafts"]
                print(f"  ✓ Found {len(scheduled_drafts)} scheduled drafts")

                for draft in scheduled_drafts[:limit]:
                    post_data = {
                        "post_id": draft.get("id"),
                        "draft_id": draft.get("id"),
                        "content": draft.get("content"),
                        "scheduled_date": draft.get("scheduled_date"),
                        "created_at": draft.get("created_at"),
                        "updated_at": draft.get("updated_at"),
                        "share_url": draft.get("share_url"),
                        "auto_retweet_enabled": draft.get("auto_retweet_enabled"),
                        "auto_plug_enabled": draft.get("auto_plug_enabled"),
                        "status": "scheduled",
                        "platform": "twitter",
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                        "data_source": "typefully_api",
                        "note": "Analytics metrics unavailable via Typefully API. "
                               "Integrate Twitter API for engagement data.",
                        "metrics": {
                            "impressions": None,
                            "likes": None,
                            "retweets": None,
                            "replies": None,
                            "quotes": None,
                            "bookmarks": None,
                            "profile_clicks": None,
                            "url_clicks": None
                        },
                        "calculated_metrics": {
                            "engagement_rate": None,
                            "total_engagements": None
                        }
                    }
                    all_posts.append(post_data)

            # Apply limit
            all_posts = all_posts[:limit]

            print(f"✅ Collected {len(all_posts)} total posts from Typefully")

            # Save to metrics file
            self._save_metrics(all_posts)

            return all_posts

        except TypefullyAPIError as e:
            print(f"❌ Error collecting posts: {e}")
            raise

    def collect_engagement_trends(
        self,
        days: int = 30
    ) -> Dict:
        """Collect and analyze engagement trends

        Args:
            days: Number of days to analyze

        Returns:
            Dict with trend analysis
        """
        print(f"📈 Analyzing engagement trends over last {days} days...")

        # Load existing metrics
        metrics_data = _read_analytics(self.store, self.metrics_file, default=None)
        if metrics_data is None:
            return {
                "error": "No metrics data available"
            }

        # Convert dict to list if needed
        if isinstance(metrics_data, dict):
            metrics_list = list(metrics_data.values())
        else:
            metrics_list = metrics_data

        # Analyze trends
        trends = {
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "days_analyzed": days,
            "total_posts": len(metrics_list),
            "average_engagement_rate": 0.0,
            "top_performing_posts": [],
            "peak_hours": [],
            "pillar_performance": {},
            "hook_performance": {},
            "content_type_performance": {}
        }

        # Calculate averages
        engagement_rates = []
        for post in metrics_list:
            er = post.get("calculated_metrics", {}).get("engagement_rate", 0)
            if er > 0:
                engagement_rates.append(er)

        if engagement_rates:
            trends["average_engagement_rate"] = round(
                sum(engagement_rates) / len(engagement_rates), 2
            )

        # Find top performing posts
        sorted_posts = sorted(
            metrics_list,
            key=lambda x: x.get("calculated_metrics", {}).get("engagement_rate", 0),
            reverse=True
        )
        trends["top_performing_posts"] = sorted_posts[:10]

        # Analyze peak posting hours (placeholder)
        # In production, would extract from posted_at timestamps
        trends["peak_hours"] = [9, 12, 15, 18, 21]

        # Analyze pillar and hook performance (if metadata available)
        # In production, would join with content database

        print(f"✅ Analysis complete:")
        print(f"   Average engagement rate: {trends['average_engagement_rate']}%")
        print(f"   Top post: {trends['top_performing_posts'][0]['post_id'] if trends['top_performing_posts'] else 'N/A'}")

        # Save trends
        self._save_trends(trends)

        return trends

    def _save_metrics(self, metrics: List[Dict]):
        """Save metrics data to JSON file

        Args:
            metrics: List of post metric dictionaries
        """
        if self.metrics_file.exists():
            try:
                with open(self.metrics_file, 'r') as f:
                    existing = json.load(f)
            except (json.JSONDecodeError, IOError):
                existing = {}
        else:
            existing = {}

        # Index by post_id
        for metric in metrics:
            post_id = metric["post_id"]
            existing[post_id] = metric

        with open(self.metrics_file, 'w') as f:
            json.dump(existing, f, indent=2)

        print(f"💾 Saved {len(metrics)} metrics to {self.metrics_file}")

    def _save_trends(self, trends: Dict):
        """Save trends data"""
        with open(self.trends_file, 'w') as f:
            json.dump(trends, f, indent=2)

        print(f"💾 Saved trends to {self.trends_file}")

    def get_top_posts(self, limit: int = 10) -> List[Dict]:
        """Get top performing posts by engagement rate

        Args:
            limit: Number of top posts to return

        Returns:
            List of top posts
        """
        metrics = _read_analytics(self.store, self.metrics_file, default={})

        sorted_posts = sorted(
            list(metrics.values()),
            key=lambda x: x.get("calculated_metrics", {}).get("engagement_rate", 0),
            reverse=True
        )

        return sorted_posts[:limit]

    def get_post_by_id(self, post_id: str) -> Optional[Dict]:
        """Get metrics for a specific post

        Args:
            post_id: Post identifier

        Returns:
            Dict with post metrics or None
        """
        metrics = _read_analytics(self.store, self.metrics_file, default={})
        return metrics.get(post_id)

    def export_analytics(
        self,
        format: str = "json",
        output_path: Optional[str] = None
    ):
        """Export analytics data

        Args:
            format: Export format (json, csv)
            output_path: Optional output file path

        Returns:
            Path to exported file
        """
        data = _read_analytics(self.store, self.metrics_file, default=None)
        if data is None:
            return None

        if not output_path:
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            output_path = self.data_dir / f"typefully_analytics_{timestamp}.{format}"

        if format == "json":
            with open(output_path, 'w') as f:
                json.dump(data, f, indent=2)
        elif format == "csv":
            import csv
            import io

            # Flatten JSON to CSV
            output = io.StringIO()
            writer = None

            for post_id, post_data in data.items():
                row = {
                    "post_id": post_id,
                    "posted_at": post_data.get("posted_at", ""),
                    "impressions": post_data.get("metrics", {}).get("impressions", 0),
                    "likes": post_data.get("metrics", {}).get("likes", 0),
                    "retweets": post_data.get("metrics", {}).get("retweets", 0),
                    "replies": post_data.get("metrics", {}).get("replies", 0),
                    "bookmarks": post_data.get("metrics", {}).get("bookmarks", 0),
                    "engagement_rate": post_data.get("calculated_metrics", {}).get("engagement_rate", 0)
                }

                if writer is None:
                    writer = csv.DictWriter(output, fieldnames=row.keys())
                    writer.writeheader()

                writer.writerow(row)

            output.seek(0)
            with open(output_path, 'w') as f:
                f.write(output.getvalue())

        print(f"📤 Exported analytics to {output_path}")

        return output_path

    def sync_analytics(self) -> Dict:
        """Sync all analytics from Typefully

        NOTE: Typefully API provides post data but NOT analytics metrics.
        This sync retrieves real posts from Typefully API, but engagement
        metrics require Twitter API integration.

        Returns:
            Dict with sync results

        Example:
            >>> analytics = TypefullyAnalytics()
            >>> results = analytics.sync_analytics()
            >>> print(results)
        """
        print("\n" + "="*60)
        print("🔄 SYNCING ANALYTICS FROM TYPEFULLY")
        print("="*60 + "\n")
        print("⚠️  NOTE: Typefully API does not provide analytics metrics.")
        print("    This sync retrieves post data only.")
        print("    For engagement metrics, integrate Twitter API.\n")

        results = {
            "synced_at": datetime.now(timezone.utc).isoformat(),
            "data_source": "typefully_api",
            "posts_collected": 0,
            "published_count": 0,
            "scheduled_count": 0,
            "trends_analyzed": False,
            "analytics_available": False,
            "errors": [],
            "recommendations": [
                "Integrate Twitter API for actual analytics metrics",
                "Twitter API v2 endpoints: /2/users/:id/tweets",
                "See: https://developer.twitter.com/en/docs/twitter-api"
            ]
        }

        try:
            # Collect recent post data from Typefully
            posts = self.collect_all_recent_posts(days=7, limit=100)
            results["posts_collected"] = len(posts)

            # Count by status
            for post in posts:
                if post.get("status") == "published":
                    results["published_count"] += 1
                elif post.get("status") == "scheduled":
                    results["scheduled_count"] += 1

            # Try to analyze trends (will skip without actual metrics)
            try:
                trends = self.collect_engagement_trends(days=30)
                results["trends_analyzed"] = True
            except Exception as trend_error:
                results["errors"].append(f"Trend analysis failed: {trend_error}")

        except Exception as e:
            results["errors"].append(str(e))
            print(f"❌ Error: {e}")

        print(f"\n✅ Sync complete!")
        print(f"   Posts collected: {results['posts_collected']}")
        print(f"   - Published: {results['published_count']}")
        print(f"   - Scheduled: {results['scheduled_count']}")
        print(f"   Analytics available: ❌ (requires Twitter API)")
        if results["errors"]:
            print(f"   Errors: {len(results['errors'])}")

        # Save sync status
        sync_file = self.data_dir / "sync_status.json"
        with open(sync_file, 'w') as f:
            json.dump(results, f, indent=2)

        return results

    def get_twitter_api_note(self) -> str:
        """Get information about Twitter API integration for analytics

        Returns:
            String with Twitter API integration guidance
        """
        return """
╔══════════════════════════════════════════════════════════════════╗
║         TWITTER API INTEGRATION FOR ANALYTICS                  ║
╚══════════════════════════════════════════════════════════════════╝

Typefully API Limitation:
  ❌ Does NOT provide analytics metrics (impressions, likes, retweets, etc.)
  ✅ DOES provide draft/post data and scheduling

Solution: Integrate Twitter API v2 for Analytics
────────────────────────────────────────────────────────────────────

1. Get Twitter API Access:
   https://developer.twitter.com/en/portal/dashboard

2. Key Endpoints:
   • GET /2/users/:id/tweets - Get user's tweets
   • GET /2/tweets/:id/metrics - Get tweet metrics
   • GET /2/users/:id/tweets?tweet.fields=public_metrics

3. Metrics Available:
   • impressions (views)
   • likes
   • retweets
   • replies
   • quotes
   • bookmark_count

4. Implementation Example:
   ```python
   import tweepy

   client = tweepy.Client(
       bearer_token="YOUR_BEARER_TOKEN"
   )

   # Get tweet with metrics
   tweet = client.get_tweet(
       tweet_id,
       tweet_fields=[
           'public_metrics',
           'created_at',
           'text'
       ]
   )

   metrics = tweet.data.public_metrics
   # {
   #   'impressions': 12345,
   #   'likes': 123,
   #   'retweets': 45,
   #   'replies': 23,
   #   'quote_count': 12
   # }
   ```

5. Integration Strategy:
   a) Use Typefully API to get/schedule posts ✅
   b) Extract Twitter tweet IDs from Typefully data
   c) Call Twitter API for actual metrics
   d) Merge data for complete analytics

Resources:
  • Twitter API Docs: https://developer.twitter.com/en/docs/twitter-api
  • Python Library: https://docs.tweepy.org/
  • Metrics Guide: https://developer.twitter.com/en/docs/twitter-api/metrics

Feature Request:
  Vote for Typefully Analytics API:
  https://feedback.typefully.com/
"""


def main():
    """CLI for Typefully analytics"""
    import argparse

    parser = argparse.ArgumentParser(
        description="Typefully analytics collector - Real Typefully API Integration",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Sync all posts from Typefully
  python typefully_analytics.py --sync

  # Show Twitter API integration guide
  python typefully_analytics.py --twitter-api-info

  # Get recent posts
  python typefully_analytics.py --recent

  # Create a draft
  python typefully_analytics.py --create-draft "Hello world!"

Notes:
  • Typefully API provides post data but NOT analytics metrics
  • For engagement metrics, integrate Twitter API v2
  • Use --twitter-api-info for integration guidance
        """
    )

    parser.add_argument("--sync", action="store_true",
                        help="Sync all posts from Typefully API")
    parser.add_argument("--recent", action="store_true",
                        help="Fetch and display recent posts")
    parser.add_argument("--top", type=int, default=10,
                        help="Get top N posts by engagement (requires metrics)")
    parser.add_argument("--post", type=str,
                        help="Get data for specific post ID")
    parser.add_argument("--trends", action="store_true",
                        help="Analyze engagement trends (requires metrics)")
    parser.add_argument("--export", type=str, choices=["json", "csv"],
                        help="Export analytics data")
    parser.add_argument("--create-draft", type=str, metavar="CONTENT",
                        help="Create a new draft in Typefully")
    parser.add_argument("--twitter-api-info", action="store_true",
                        help="Show Twitter API integration guide")

    args = parser.parse_args()

    # Show Twitter API info if requested
    if args.twitter_api_info:
        analytics = TypefullyAnalytics()
        print(analytics.get_twitter_api_note())
        return

    # Create analytics instance with context manager
    try:
        with TypefullyAnalytics() as analytics:

            if args.sync:
                results = analytics.sync_analytics()
                print(json.dumps(results, indent=2))

            elif args.recent:
                posts = analytics.collect_all_recent_posts(days=7, limit=20)
                print(f"\n📝 Recent Posts from Typefully:")
                print(f"{'='*60}\n")

                for i, post in enumerate(posts, 1):
                    status = post.get("status", "unknown").upper()
                    content = post.get("content", "")[:60]
                    created = post.get("created_at", "N/A")[:10]

                    print(f"{i}. [{status}] {created}")
                    print(f"   ID: {post.get('post_id', 'N/A')}")
                    print(f"   Content: {content}...")
                    print()

            elif args.create_draft:
                result = analytics.create_draft(args.create_draft)
                print(json.dumps(result, indent=2))

            elif args.top:
                top_posts = analytics.get_top_posts(limit=args.top)
                print(f"\n🏆 Top {len(top_posts)} Posts:")
                for i, post in enumerate(top_posts, 1):
                    metrics = post.get("calculated_metrics", {})
                    engagement = metrics.get('engagement_rate', 'N/A')
                    print(f"\n{i}. {post['post_id']}")
                    print(f"   Engagement: {engagement}% (requires Twitter API for actual data)")

            elif args.post:
                metrics = analytics.collect_post_metrics(args.post)
                print(f"\n📊 Data for {args.post}:")
                print(json.dumps(metrics, indent=2))

            elif args.trends:
                print("⚠️  Trend analysis requires actual analytics metrics")
                print("    (not available via Typefully API)")
                print("\nUse --twitter-api-info for integration guidance\n")
                trends = analytics.collect_engagement_trends(days=30)
                print(f"\n📈 Data Analysis:")
                print(f"   Total posts: {trends.get('total_posts', 0)}")
                print(f"   Average engagement: {trends.get('average_engagement_rate', 0)}%")

            elif args.export:
                output_path = analytics.export_analytics(format=args.export)
                if output_path:
                    print(f"✅ Exported to {output_path}")
                else:
                    print("❌ No data to export")

            else:
                parser.print_help()

    except ValueError as e:
        print(f"❌ Configuration Error: {e}")
        return 1
    except TypefullyAuthError as e:
        print(f"❌ Authentication Error: {e}")
        return 1
    except TypefullyRateLimitError as e:
        print(f"❌ Rate Limit Error: {e}")
        return 1
    except TypefullyAPIError as e:
        print(f"❌ API Error: {e}")
        return 1
    except Exception as e:
        print(f"❌ Unexpected Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    main()
