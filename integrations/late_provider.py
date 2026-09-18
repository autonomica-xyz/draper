#!/usr/bin/env python3
"""
Late API Publishing Provider
Implements PublishingProvider for Late.dev (getlate.dev) - multi-platform scheduler
"""

import os
import requests
from typing import Dict, List, Optional

from .publishing_provider import (
    PublishingProvider,
    SocialAccount,
    PublishRequest,
    PublishResult,
    PublishErrorCode,
)


class LateProvider(PublishingProvider):
    """
    Late API implementation
    
    Late supports: Instagram, TikTok, YouTube, LinkedIn, Pinterest, X/Twitter,
    Facebook, Threads, Bluesky, Snapchat, Google Business, Reddit, Telegram
    """
    
    BASE_URL = "https://getlate.dev/api/v1"
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("LATE_API_KEY")
        self._accounts_cache = None
    
    def get_name(self) -> str:
        return "late"
    
    def is_configured(self) -> bool:
        return bool(self.api_key)
    
    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def get_accounts(self) -> List[SocialAccount]:
        """Fetch connected accounts from Late API"""
        if self._accounts_cache:
            return self._accounts_cache
        
        try:
            response = requests.get(
                f"{self.BASE_URL}/accounts",
                headers=self._get_headers(),
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            accounts = []
            for acc in data.get("accounts", []):
                platform = acc.get("platform", "").lower()
                account_id = acc.get("_id")  # MongoDB ObjectId
                username = acc.get("username", "")
                display_name = acc.get("displayName") or username
                is_connected = acc.get("isActive", False)
                
                # Map Late's platform names to our standard
                platform_map = {
                    "x": "twitter",
                    "twitter": "twitter",
                    "linkedin": "linkedin",
                    "instagram": "instagram",
                    "tiktok": "tiktok",
                    "youtube": "youtube",
                    "pinterest": "pinterest",
                    "facebook": "facebook",
                    "threads": "threads",
                    "bluesky": "bluesky",
                    "snapchat": "snapchat",
                    "google_business": "google_business",
                    "reddit": "reddit",
                    "telegram": "telegram"
                }
                
                mapped_platform = platform_map.get(platform, platform)
                
                accounts.append(SocialAccount(
                    account_id=f"late_{account_id}",
                    platform=mapped_platform,
                    handle=username,
                    display_name=display_name,
                    provider="late",
                    enabled=is_connected
                ))
            
            self._accounts_cache = accounts
            return accounts
            
        except Exception as e:
            print(f"❌ Error fetching Late accounts: {e}")
            return []
    
    def publish(self, request: PublishRequest) -> PublishResult:
        """
        Publish to Late API
        
        Late supports:
        - Immediate posting
        - Scheduled posting
        - Queue (smart scheduling)
        - Media uploads
        """
        # Extract Late account ID from our account_id format
        if not request.account_id or not request.account_id.startswith("late_"):
            return PublishResult(
                success=False,
                error="Invalid account_id for Late. Expected format: late_{account_id}",
                provider="late",
                error_code=PublishErrorCode.INVALID_ACCOUNT,
            )
        
        late_account_id = request.account_id.replace("late_", "")
        
        # Build post payload
        payload = {
            "accountId": late_account_id,
            "content": request.content,
        }
        
        # Handle scheduling
        if request.scheduled_at:
            payload["scheduledAt"] = request.scheduled_at.isoformat()
        elif not request.auto_publish:
            # Send to queue (Late's smart scheduling)
            payload["queue"] = True
        
        # Media handling
        if request.media_urls:
            # Late expects media as array of objects
            payload["media"] = [
                {"url": url} for url in request.media_urls
            ]
        
        # Draft mode - Late doesn't have explicit "draft" mode
        # Instead, we can schedule far in the future or use queue
        if request.as_draft and not request.scheduled_at:
            payload["queue"] = True
        
        try:
            response = requests.post(
                f"{self.BASE_URL}/posts",
                headers=self._get_headers(),
                json=payload,
                timeout=15
            )
            response.raise_for_status()
            
            data = response.json()
            post_id = data.get("id")
            status = data.get("status")
            
            return PublishResult(
                success=True,
                post_id=post_id,
                url=f"https://app.getlate.dev/posts/{post_id}",
                provider="late"
            )
            
        except requests.exceptions.HTTPError as e:
            error_msg = f"Late API error: {e.response.status_code}"
            try:
                error_data = e.response.json()
                error_msg += f" - {error_data.get('error', error_data.get('message', ''))}"
            except:
                pass
            
            return PublishResult(
                success=False,
                error=error_msg,
                provider="late",
                error_code=PublishErrorCode.RATE_LIMITED
                if e.response.status_code == 429
                else PublishErrorCode.AUTH_FAILED
                if e.response.status_code in (401, 403)
                else PublishErrorCode.PROVIDER_ERROR,
            )
        except Exception as e:
            return PublishResult(
                success=False,
                error=f"Late publish failed: {str(e)}",
                provider="late",
                error_code=PublishErrorCode.PROVIDER_ERROR,
            )
    
    def get_analytics(self, account_id: Optional[str] = None) -> Dict:
        """
        Fetch analytics from Late API
        
        Returns post performance metrics
        """
        try:
            params = {}
            
            # Filter by account if specified
            if account_id and account_id.startswith("late_"):
                late_account_id = account_id.replace("late_", "")
                params["accountId"] = late_account_id
            
            response = requests.get(
                f"{self.BASE_URL}/posts",
                headers=self._get_headers(),
                params=params,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            posts = data.get("posts", [])
            
            # Aggregate metrics
            total_posts = len(posts)
            total_impressions = 0
            total_likes = 0
            total_comments = 0
            total_shares = 0
            
            for post in posts:
                stats = post.get("metrics", {})
                total_impressions += stats.get("impressions", 0)
                total_likes += stats.get("likes", 0)
                total_comments += stats.get("comments", 0)
                total_shares += stats.get("shares", 0)
            
            total_engagement = total_likes + total_comments + total_shares
            avg_engagement_rate = (
                (total_engagement / total_impressions * 100)
                if total_impressions > 0
                else 0
            )
            
            return {
                "provider": "late",
                "total_posts": total_posts,
                "total_impressions": total_impressions,
                "total_engagement": total_engagement,
                "avg_engagement_rate": round(avg_engagement_rate, 2),
                "posts": posts
            }
            
        except Exception as e:
            print(f"❌ Error fetching Late analytics: {e}")
            return {
                "error": str(e),
                "provider": "late"
            }
    
    def upload_media(self, file_path: str) -> Optional[str]:
        """
        Upload media file to Late
        
        Returns: Media URL if successful, None otherwise
        """
        try:
            with open(file_path, "rb") as f:
                files = {"file": f}
                response = requests.post(
                    f"{self.BASE_URL}/media/upload",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    files=files,
                    timeout=30
                )
                response.raise_for_status()
                data = response.json()
                return data.get("url")
        except Exception as e:
            print(f"❌ Late media upload failed: {e}")
            return None
