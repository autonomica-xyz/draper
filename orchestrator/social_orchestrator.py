#!/usr/bin/env python3
"""
Social Media Orchestrator
Manages posting to Twitter/X, LinkedIn (via late.dev), and Nostr
"""

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from data.sqlite_store import SQLiteStore  # ponytail: scheduled_posts table replaces orchestrator_scheduled.json
from nostr.nostr_analytics import NostrAnalytics
from nostr.nostr_publisher import NostrPublisher


class SocialOrchestrator:
    """Orchestrates posting to social media platforms"""

    def __init__(self, data_dir: str = None):
        if data_dir is None:
            data_dir = str(Path(__file__).resolve().parent.parent / "data")
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

        # Backing store for scheduled posts (replaces orchestrator_scheduled.json)
        self.store = SQLiteStore(self.data_dir)

        # Initialize platform publishers
        self.nostr_publisher = NostrPublisher()
        self.nostr_analytics = NostrAnalytics(data_dir=data_dir)

        self.late_api_key = os.getenv("LATE_API_KEY")

        # Initialize late.dev HTTP client
        if self.late_api_key:
            try:
                self.late_client = httpx.Client(
                    base_url="https://getlate.dev/api/v1",
                    headers={"Authorization": f"Bearer {self.late_api_key}"},
                    timeout=30.0
                )
                print("✅ late.dev API client initialized")
            except Exception as e:
                print(f"⚠️  Failed to initialize late.dev client: {e}")
                self.late_client = None
        else:
            print("⚠️  LATE_API_KEY not set - scheduling is disabled")
            self.late_client = None

        # Platform-specific posting cadence
        self.cadence = {
            "twitter": {
                "daily_limit": 5,
                "min_interval_hours": 2,
                "optimal_times": ["09:00", "12:00", "15:00", "18:00", "21:00"]
            },
            "linkedin": {
                "daily_limit": 1,
                "min_interval_hours": 24,
                "optimal_days": ["Tuesday", "Wednesday", "Thursday"],
                "optimal_times": ["08:00", "12:00", "17:00"]
            },
            "nostr": {
                "daily_limit": 5,
                "min_interval_hours": 2,
                "optimal_times": ["09:00", "12:00", "15:00", "18:00", "21:00"]
            }
        }

    def schedule_post(
        self,
        post_data: Dict,
        platform: str,
        scheduled_at: Optional[datetime] = None,
        immediate: bool = False
    ) -> Dict:
        """Schedule a post to a platform

        Args:
            post_data: Post content from ContentGenerator
            platform: "twitter", "linkedin", or "nostr"
            scheduled_at: When to post (default: calculate optimal time)
            immediate: Post immediately if True

        Returns:
            Dict with scheduling result and post ID
        """
        if platform not in ["twitter", "linkedin", "nostr"]:
            return {
                "success": False,
                "error": f"Unsupported platform: {platform}"
            }

        # Calculate optimal time if not specified
        if not scheduled_at:
            scheduled_at = self._calculate_optimal_time(platform, immediate)

        # Prepare platform-specific payload
        if platform == "nostr":
            result = self._schedule_nostr(post_data, scheduled_at, immediate)
        elif platform == "twitter":
            result = self._schedule_twitter(post_data, scheduled_at, immediate)
        else:  # linkedin
            result = self._schedule_linkedin(post_data, scheduled_at, immediate)

        # Save to database
        if result.get("success"):
            self._save_scheduled_post(
                post_data=post_data,
                platform=platform,
                scheduled_at=scheduled_at,
                platform_post_id=result.get("post_id"),
                status="scheduled" if not immediate else "posted"
            )

        return result

    def _placeholder_schedule(
        self,
        platform: str,
        post_data: Dict,
        scheduled_at: datetime,
        immediate: bool
    ) -> Dict:
        """Fail closed when API client is unavailable."""
        print(f"⚠️  Scheduling disabled for {platform} - Late API client not initialized")
        return {
            "success": False,
            "platform": platform,
            "scheduled_at": scheduled_at.isoformat(),
            "immediate": immediate,
            "status": "not_configured",
            "error": "Late API client not initialized. Set LATE_API_KEY environment variable."
        }

    def _get_platform_account(self, platform: str) -> Optional[str]:
        """Get the first connected account ID for a platform

        Args:
            platform: Platform name (e.g., "twitter", "linkedin")

        Returns:
            Account ID if found, None otherwise
        """
        if not self.late_client:
            return None

        try:
            response = self.late_client.get("/accounts")
            response.raise_for_status()

            data = response.json()
            accounts = data.get("accounts", [])

            # Find first account for the specified platform
            for account in accounts:
                if account.get("platform") == platform:
                    account_id = account.get("_id")
                    print(f"✅ Found {platform} account: {account_id}")
                    return account_id

            print(f"⚠️  No {platform} account found")
            return None

        except httpx.HTTPStatusError as e:
            print(f"❌ Error fetching accounts: {e.response.status_code}")
            if e.response.status_code == 401:
                print("❌ Authentication failed - check your LATE_API_KEY")
            return None
        except Exception as e:
            print(f"❌ Error fetching accounts: {str(e)}")
            return None

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        retry=retry_if_exception_type(httpx.HTTPStatusError)
    )
    def _create_post_with_retry(self, payload: Dict) -> Dict:
        """Create post via late.dev API with retry logic

        Args:
            payload: API request payload

        Returns:
            Dict with success status and post details

        Raises:
            httpx.HTTPStatusError: If all retries fail
        """
        try:
            response = self.late_client.post("/posts", json=payload)
            response.raise_for_status()

            data = response.json()
            post = data.get("post", {})

            # Extract platform-specific data
            platform_data = post.get("platforms", [{}])[0] if post.get("platforms") else {}

            return {
                "success": True,
                "post_id": post.get("_id"),
                "status": post.get("status"),
                "scheduled_for": post.get("scheduledFor"),
                "platform_post_url": platform_data.get("platformPostUrl"),
                "status_url": f"https://getlate.dev/dashboard/posts/{post.get('_id')}"
            }

        except httpx.HTTPStatusError as e:
            if e.response.status_code == 429:
                print("⚠️  Rate limit exceeded - waiting before retry...")
            elif e.response.status_code == 401:
                print("❌ Authentication failed - check your LATE_API_KEY")
                # Don't retry auth errors
                raise
            elif e.response.status_code == 400:
                # Bad request - don't retry
                error_data = e.response.json() if e.response.headers.get("content-type", "").startswith("application/json") else {}
                return {
                    "success": False,
                    "error": error_data.get("error", "Bad request"),
                    "details": error_data
                }
            else:
                print(f"❌ API error: {e.response.status_code}")
            # Re-raise for retry logic
            raise
        except httpx.TimeoutException:
            print("⚠️  Request timeout - retrying...")
            raise
        except Exception as e:
            return {
                "success": False,
                "error": f"Unexpected error: {str(e)}"
            }

    def _schedule_nostr(
        self,
        post_data: Dict,
        scheduled_at: datetime,
        immediate: bool
    ) -> Dict:
        """Schedule post to Nostr

        Args:
            post_data: Post content from ContentGenerator
            scheduled_at: When to post
            immediate: Post immediately if True

        Returns:
            Dict with scheduling result and post ID
        """
        # Convert to Nostr format
        nostr_result = self.nostr_publisher.publish_from_post_data(post_data)

        # Record in analytics if successful
        if nostr_result.get("success"):
            self.nostr_analytics.record_event(
                event_id=nostr_result.get("event_id", "unknown"),
                kind=1,  # Text note
                content=post_data.get("content", "")[:200],
                published_at=scheduled_at.isoformat() if scheduled_at else datetime.now(timezone.utc).isoformat(),
                platform="nostr",
                pillar=post_data.get("pillar", "")
            )

        # Save to scheduled database
        return {
            "success": nostr_result.get("success", False),
            "platform": "nostr",
            "post_id": nostr_result.get("event_id", ""),
            "scheduled_at": scheduled_at.isoformat() if scheduled_at else datetime.now(timezone.utc).isoformat(),
            "immediate": immediate,
            "message": nostr_result.get("message", "")
        }

    def _calculate_optimal_time(self, platform: str, immediate: bool = False) -> datetime:
        """Calculate optimal posting time based on cadence and history"""
        if immediate:
            return datetime.now(timezone.utc)

        # Get upcoming optimal slots
        cadence_config = self.cadence.get(platform, self.cadence["twitter"])
        now = datetime.now(timezone.utc)

        # Simple heuristic: pick next optimal time slot
        # In production, this would check existing scheduled posts
        optimal_times = cadence_config.get("optimal_times", [])

        # Try today's slots
        for time_str in optimal_times:
            hour, minute = map(int, time_str.split(":"))
            slot_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)

            if slot_time > now + timedelta(minutes=30):  # At least 30 min from now
                return slot_time

        # If no slots today, try tomorrow
        tomorrow = now + timedelta(days=1)
        tomorrow_slot = tomorrow.replace(hour=9, minute=0, second=0, microsecond=0)

        return tomorrow_slot

    def _schedule_twitter(
        self,
        post_data: Dict,
        scheduled_at: datetime,
        immediate: bool
    ) -> Dict:
        """Schedule post to Twitter/X via late.dev API

        Args:
            post_data: Post content from ContentGenerator
            scheduled_at: When to post
            immediate: Post immediately if True

        Returns:
            Dict with scheduling result and post ID
        """
        if not self.late_client:
            return self._placeholder_schedule("twitter", post_data, scheduled_at, immediate)

        try:
            # Get connected Twitter account
            account_id = self._get_platform_account("twitter")
            if not account_id:
                return {
                    "success": False,
                    "error": "No Twitter account connected. Please connect an account via late.dev dashboard.",
                    "platform": "twitter",
                    "note": "Run the connect_twitter_flow() method to link your account"
                }

            # Prepare API payload
            payload = {
                "content": post_data.get("content", ""),
                "platforms": [
                    {
                        "platform": "twitter",
                        "accountId": account_id
                    }
                ]
            }

            # Add scheduling time or publish immediately
            if immediate:
                payload["publishNow"] = True
            else:
                payload["scheduledFor"] = scheduled_at.isoformat()
                payload["timezone"] = "UTC"

            # Make API call with retry logic
            response = self._create_post_with_retry(payload)

            if response.get("success"):
                return {
                    "success": True,
                    "platform": "twitter",
                    "post_id": response.get("post_id"),
                    "scheduled_at": scheduled_at.isoformat(),
                    "immediate": immediate,
                    "status_url": response.get("status_url"),
                    "platform_post_url": response.get("platform_post_url")
                }
            else:
                return response

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to schedule Twitter post: {str(e)}",
                "platform": "twitter"
            }

    def _schedule_linkedin(
        self,
        post_data: Dict,
        scheduled_at: datetime,
        immediate: bool
    ) -> Dict:
        """Schedule post to LinkedIn via late.dev API

        Args:
            post_data: Post content from ContentGenerator
            scheduled_at: When to post
            immediate: Post immediately if True

        Returns:
            Dict with scheduling result and post ID
        """
        if not self.late_client:
            return self._placeholder_schedule("linkedin", post_data, scheduled_at, immediate)

        try:
            # Get connected LinkedIn account
            account_id = self._get_platform_account("linkedin")
            if not account_id:
                return {
                    "success": False,
                    "error": "No LinkedIn account connected. Please connect an account via late.dev dashboard.",
                    "platform": "linkedin",
                    "note": "Run the connect_linkedin_flow() method to link your account"
                }

            # Prepare API payload
            payload = {
                "content": post_data.get("content", ""),
                "platforms": [
                    {
                        "platform": "linkedin",
                        "accountId": account_id
                    }
                ]
            }

            # Add scheduling time or publish immediately
            if immediate:
                payload["publishNow"] = True
            else:
                payload["scheduledFor"] = scheduled_at.isoformat()
                payload["timezone"] = "UTC"

            # Make API call with retry logic
            response = self._create_post_with_retry(payload)

            if response.get("success"):
                return {
                    "success": True,
                    "platform": "linkedin",
                    "post_id": response.get("post_id"),
                    "scheduled_at": scheduled_at.isoformat(),
                    "immediate": immediate,
                    "status_url": response.get("status_url"),
                    "platform_post_url": response.get("platform_post_url")
                }
            else:
                return response

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to schedule LinkedIn post: {str(e)}",
                "platform": "linkedin"
            }

    def get_engagement_metrics(self, platform: str, post_id: str) -> Dict:
        """Retrieve engagement metrics for a post

        Note: Placeholder until MCP integration
        """
        # Placeholder implementation
        # Would use:
        # - Typefully: typefully.get_post_metrics
        # - late.dev: late.get_post_metrics
        # - Nostr: nostr_analytics.get_event_metrics

        return {
            "platform": platform,
            "post_id": post_id,
            "impressions": 0,
            "likes": 0,
            "shares": 0,
            "comments": 0,
            "engagement_rate": 0.0,
            "note": "MCP integration pending - using placeholder"
        }

    def get_scheduled_posts(self, platform: Optional[str] = None) -> List[Dict]:
        """Get all scheduled posts

        Args:
            platform: Filter by platform (optional)

        Returns:
            List of scheduled posts
        """
        posts = self.store.list_scheduled_records()

        if platform:
            posts = [p for p in posts if p.get("platform") == platform]

        return posts

    def _save_scheduled_post(
        self,
        post_data: Dict,
        platform: str,
        scheduled_at: datetime,
        platform_post_id: str,
        status: str
    ):
        """Save scheduled post to database"""
        post_id = f"{platform}_{platform_post_id}"

        self.store.save_scheduled_record({
            "post_id": post_id,
            "post_data": post_data,
            "platform": platform,
            "scheduled_at": scheduled_at.isoformat(),
            "platform_post_id": platform_post_id,
            "status": status,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    def cancel_post(self, post_id: str) -> Dict:
        """Cancel a scheduled post

        Note: Placeholder until MCP integration
        """
        record = self.store.get_scheduled_record(post_id)
        if record is None:
            return {
                "success": False,
                "error": f"Post {post_id} not found"
            }

        # Cancel on platform (placeholder)
        # Would use MCP to cancel
        record["status"] = "cancelled"
        record["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        self.store.save_scheduled_record(record)

        return {
            "success": True,
            "post_id": post_id,
            "status": "cancelled"
        }

    def get_connect_url(self, platform: str, profile_id: Optional[str] = None) -> Dict:
        """Get OAuth URL to connect a social media account

        Args:
            platform: Platform name (e.g., "twitter", "linkedin")
            profile_id: Optional profile ID to connect account to

        Returns:
            Dict with auth_url and instructions
        """
        if not self.late_client:
            return {
                "success": False,
                "error": "late.dev client not initialized. Set LATE_API_KEY environment variable."
            }

        try:
            # First, create a profile if none provided
            if not profile_id:
                profile_response = self.late_client.post(
                    "/profiles",
                    json={"name": "Draper Marketing Pipeline", "description": "Automated content posting"}
                )
                profile_response.raise_for_status()
                profile_data = profile_response.json()
                profile_id = profile_data.get("profile", {}).get("_id")

            # Get OAuth URL
            params = {"profileId": profile_id} if profile_id else {}
            response = self.late_client.get(f"/connect/{platform}", params=params)
            response.raise_for_status()

            data = response.json()
            auth_url = data.get("authUrl")

            return {
                "success": True,
                "auth_url": auth_url,
                "profile_id": profile_id,
                "instructions": f"Open this URL to connect your {platform} account: {auth_url}"
            }

        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to get connect URL: {str(e)}"
            }

    def check_post_status(self, post_id: str) -> Dict:
        """Check the status of a scheduled post

        Args:
            post_id: Post ID from late.dev

        Returns:
            Dict with post status and details
        """
        if not self.late_client:
            return {
                "success": False,
                "error": "late.dev client not initialized"
            }

        try:
            response = self.late_client.get(f"/posts/{post_id}")
            response.raise_for_status()

            data = response.json()
            post = data.get("post", {})

            # Extract platform URLs for published posts
            platform_urls = {}
            for platform in post.get("platforms", []):
                platform_urls[platform["platform"]] = platform.get("platformPostUrl")

            return {
                "success": True,
                "post_id": post.get("_id"),
                "status": post.get("status"),
                "scheduled_for": post.get("scheduledFor"),
                "platform_urls": platform_urls,
                "content": post.get("content")
            }

        except httpx.HTTPStatusError as e:
            return {
                "success": False,
                "error": f"API error: {e.response.status_code}"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"Failed to check post status: {str(e)}"
            }

    def list_connected_accounts(self) -> Dict:
        """List all connected social media accounts

        Returns:
            Dict with list of connected accounts
        """
        if not self.late_client:
            return {
                "success": False,
                "error": "late.dev client not initialized",
                "accounts": []
            }

        try:
            response = self.late_client.get("/accounts")
            response.raise_for_status()

            data = response.json()
            accounts = data.get("accounts", [])

            return {
                "success": True,
                "accounts": accounts,
                "count": len(accounts)
            }

        except Exception as e:
            return {
                "success": False,
                "error": str(e),
                "accounts": []
            }

    def __del__(self):
        """Clean up HTTP client on destruction"""
        if hasattr(self, 'late_client') and self.late_client:
            try:
                self.late_client.close()
            except:
                pass


def main():
    """CLI for orchestrator"""
    import argparse

    parser = argparse.ArgumentParser(description="Social media posting orchestrator")
    parser.add_argument("--list", choices=["scheduled", "accounts"], help="List scheduled posts or connected accounts")
    parser.add_argument("--cancel", help="Cancel a post by ID")
    parser.add_argument("--connect", help="Get OAuth URL to connect a platform (e.g., twitter, linkedin)")
    parser.add_argument("--status", help="Check status of a post by ID")
    parser.add_argument("--test-twitter", action="store_true", help="Test Twitter scheduling with placeholder content")
    parser.add_argument("--test-linkedin", action="store_true", help="Test LinkedIn scheduling with placeholder content")

    args = parser.parse_args()

    orchestrator = SocialOrchestrator()

    if args.list == "scheduled":
        posts = orchestrator.get_scheduled_posts()
        print(f"Scheduled posts: {len(posts)}")
        for post in posts:
            print(f"  - {post['platform_post_id']}: {post['platform']} at {post['scheduled_at']}")

    elif args.list == "accounts":
        result = orchestrator.list_connected_accounts()
        if result["success"]:
            print(f"Connected accounts: {result['count']}")
            for account in result["accounts"]:
                print(f"  - {account['platform']}: {account['_id']} ({account.get('username', 'N/A')})")
        else:
            print(f"Error: {result['error']}")

    elif args.connect:
        result = orchestrator.get_connect_url(args.connect)
        if result["success"]:
            print(result["instructions"])
            print(f"Profile ID: {result['profile_id']}")
        else:
            print(f"Error: {result['error']}")

    elif args.status:
        result = orchestrator.check_post_status(args.status)
        if result["success"]:
            print(f"Post Status: {result['status']}")
            print(f"Scheduled For: {result.get('scheduled_for', 'N/A')}")
            print("Platform URLs:")
            for platform, url in result.get('platform_urls', {}).items():
                print(f"  - {platform}: {url}")
        else:
            print(f"Error: {result['error']}")

    elif args.cancel:
        result = orchestrator.cancel_post(args.cancel)
        print(json.dumps(result, indent=2))

    elif args.test_twitter:
        from datetime import datetime, timedelta, timezone
        test_post = {
            "content": "🧪 Test post from Draper Marketing Pipeline",
            "pillar": "testing"
        }
        scheduled_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        result = orchestrator.schedule_to_twitter(test_post, scheduled_at=scheduled_time, immediate=False)
        print(json.dumps(result, indent=2))

    elif args.test_linkedin:
        from datetime import datetime, timedelta, timezone
        test_post = {
            "content": "🧪 Test post from Draper Marketing Pipeline\n\nTesting automated LinkedIn scheduling via late.dev API.",
            "pillar": "testing"
        }
        scheduled_time = datetime.now(timezone.utc) + timedelta(minutes=5)
        result = orchestrator.schedule_to_linkedin(test_post, scheduled_at=scheduled_time, immediate=False)
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
