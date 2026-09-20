#!/usr/bin/env python3
"""
Typefully API Client

Direct integration with Typefully API for scheduling posts to Twitter and LinkedIn.
Docs: https://support.typefully.com/en/articles/8718287-typefully-api

For MCP server integration, see: https://github.com/typefully/mcp-server-typefully
"""

import os
import httpx
from datetime import datetime
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum


class Platform(Enum):
    TWITTER = "twitter"
    LINKEDIN = "linkedin"


@dataclass
class Draft:
    """Typefully draft"""
    id: str
    content: str
    platform: Platform
    status: str  # draft, scheduled, published
    scheduled_at: Optional[datetime] = None
    published_at: Optional[datetime] = None
    thread_ids: Optional[List[str]] = None


class TypefullyClient:
    """
    Typefully API client for content scheduling
    
    Usage:
        client = TypefullyClient()  # Uses TYPEFULLY_API_KEY env var
        
        # Create and schedule a post
        draft = await client.create_draft(
            content="Hello world! 🚀",
            platform=Platform.TWITTER
        )
        await client.schedule_draft(draft.id, schedule_date="next-free-slot")
    """
    
    BASE_URL = "https://api.typefully.com/v2"
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize Typefully client
        
        Args:
            api_key: Typefully API key. If not provided, uses TYPEFULLY_API_KEY env var.
        """
        self.api_key = api_key or os.getenv("TYPEFULLY_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Typefully API key required. Set TYPEFULLY_API_KEY environment variable "
                "or pass api_key parameter. Get your key at: https://typefully.com/settings/api"
            )
        
        self._client = httpx.AsyncClient(
            base_url=self.BASE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "marketing-pipeline/1.0"
            },
            timeout=30.0
        )
    
    async def close(self):
        """Close the HTTP client"""
        await self._client.aclose()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
    
    async def create_draft(
        self,
        content: str,
        platform: Platform = Platform.TWITTER,
        social_set_id: Optional[str] = None,
        threadify: bool = False,
        share_on_linkedin: bool = False,
        auto_retweet_enabled: bool = False,
        auto_plug_enabled: bool = False
    ) -> Dict[str, Any]:
        """
        Create a new draft in Typefully
        
        Args:
            content: Post content (use \\n\\n\\n\\n for thread breaks)
            platform: Target platform (twitter or linkedin)
            social_set_id: Typefully social set ID (which account to post to)
                          Get this from Typefully with Development mode enabled
            threadify: Auto-split into thread
            share_on_linkedin: Cross-post to LinkedIn
            auto_retweet_enabled: Enable auto-retweet
            auto_plug_enabled: Enable auto-plug
        
        Returns:
            Draft data including id
        """
        payload = {
            "content": content,
            "threadify": threadify,
            "share-on-linkedin": share_on_linkedin or platform == Platform.LINKEDIN,
            "auto-retweet-enabled": auto_retweet_enabled,
            "auto-plug-enabled": auto_plug_enabled
        }
        
        # Add social set ID if specified (selects which account to post to)
        if social_set_id:
            payload["social-set-id"] = social_set_id
        
        response = await self._client.post("/drafts/", json=payload)
        response.raise_for_status()
        return response.json()
    
    async def schedule_draft(
        self,
        draft_id: str,
        schedule_date: str = "next-free-slot"
    ) -> Dict[str, Any]:
        """
        Schedule a draft for publication
        
        Args:
            draft_id: Draft ID from create_draft
            schedule_date: Either "next-free-slot" or ISO 8601 datetime
        
        Returns:
            Updated draft data
        """
        payload = {"schedule-date": schedule_date}
        
        response = await self._client.put(
            f"/drafts/{draft_id}/schedule/",
            json=payload
        )
        response.raise_for_status()
        return response.json()
    
    async def create_and_schedule(
        self,
        content: str,
        platform: Platform = Platform.TWITTER,
        social_set_id: Optional[str] = None,
        schedule_date: str = "next-free-slot",
        threadify: bool = False
    ) -> Dict[str, Any]:
        """
        Create a draft and schedule it in one call
        
        Args:
            content: Post content
            platform: Target platform
            social_set_id: Which account to post to (from Typefully)
            schedule_date: When to publish
            threadify: Auto-split into thread
        
        Returns:
            Scheduled draft data
        """
        draft = await self.create_draft(
            content=content,
            platform=platform,
            social_set_id=social_set_id,
            threadify=threadify,
            share_on_linkedin=platform == Platform.LINKEDIN
        )
        
        scheduled = await self.schedule_draft(
            draft_id=draft["id"],
            schedule_date=schedule_date
        )
        
        return scheduled
    
    async def get_scheduled_posts(self) -> List[Dict[str, Any]]:
        """
        Get all scheduled posts
        
        Returns:
            List of scheduled drafts
        """
        response = await self._client.get("/drafts/?filter=scheduled")
        response.raise_for_status()
        return response.json()
    
    async def get_recently_published(self, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Get recently published posts
        
        Args:
            limit: Max posts to return
        
        Returns:
            List of published posts
        """
        response = await self._client.get(f"/drafts/?filter=published&limit={limit}")
        response.raise_for_status()
        return response.json()
    
    async def get_social_accounts(self) -> List[Dict[str, Any]]:
        """
        Get connected social accounts
        
        Returns:
            List of social accounts with platform, handle, id
            Example: [
                {"id": "twitter_123", "platform": "twitter", "handle": "@username", "name": "Display Name"},
                {"id": "linkedin_456", "platform": "linkedin", "handle": "company-name", "name": "Company Name"}
            ]
        """
        try:
            # Try to get user profile which should include connected accounts
            response = await self._client.get("/me/")
            response.raise_for_status()
            data = response.json()
            
            # Parse accounts from response
            # The actual structure depends on Typefully API response
            accounts = data.get("accounts", [])
            
            return accounts
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                # Endpoint might not exist, return empty list
                return []
            raise


class TypefullySyncClient:
    """
    Synchronous wrapper for TypefullyClient
    
    For use in non-async contexts like CLI commands.
    """
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("TYPEFULLY_API_KEY")
        if not self.api_key:
            raise ValueError(
                "Typefully API key required. Set TYPEFULLY_API_KEY environment variable."
            )
        
        self._client = httpx.Client(
            base_url=TypefullyClient.BASE_URL,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "User-Agent": "marketing-pipeline/1.0"
            },
            timeout=30.0
        )
    
    def create_draft(self, content: str, social_set_id: Optional[str] = None, **kwargs) -> Dict[str, Any]:
        """Create a draft (sync)"""
        payload = {
            "content": content,
            "threadify": kwargs.get("threadify", False),
            "share-on-linkedin": kwargs.get("share_on_linkedin", False),
        }
        if social_set_id:
            payload["social-set-id"] = social_set_id
        
        response = self._client.post("/drafts/", json=payload)
        response.raise_for_status()
        return response.json()
    
    def schedule_draft(self, draft_id: str, schedule_date: str = "next-free-slot") -> Dict[str, Any]:
        """Schedule a draft (sync)"""
        payload = {"schedule-date": schedule_date}
        response = self._client.put(f"/drafts/{draft_id}/schedule/", json=payload)
        response.raise_for_status()
        return response.json()
    
    def create_and_schedule(
        self, 
        content: str, 
        social_set_id: Optional[str] = None,
        schedule_date: str = "next-free-slot", 
        **kwargs
    ) -> Dict[str, Any]:
        """Create and schedule in one call (sync)"""
        draft = self.create_draft(content, social_set_id=social_set_id, **kwargs)
        return self.schedule_draft(draft["id"], schedule_date)
    
    def get_social_accounts(self) -> List[Dict[str, Any]]:
        """Get connected social accounts (sync) - uses v2 social-sets endpoint"""
        try:
            response = self._client.get("/social-sets")
            response.raise_for_status()
            data = response.json()
            
            # Parse paginated response
            if isinstance(data, dict) and "results" in data:
                social_sets = data["results"]
            elif isinstance(data, list):
                if data and isinstance(data[0], dict) and "results" in data[0]:
                    social_sets = data[0]["results"]
                else:
                    social_sets = data
            else:
                social_sets = []
            
            # Transform to accounts format for compatibility
            accounts = []
            for ss in social_sets:
                accounts.append({
                    "id": str(ss.get("id")),
                    "social_set_id": ss.get("id"),
                    "platform": "twitter",
                    "handle": ss.get("username") or ss.get("name"),
                    "name": ss.get("name") or ss.get("username"),
                    "profile_image_url": ss.get("profile_image_url")
                })
            return accounts
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 404:
                return []
            raise
    
    def get_drafts_for_social_set(
        self,
        social_set_id: int,
        status: str = "",
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get drafts for a specific social set via v2 API.

        Args:
            social_set_id: Typefully social set ID
            status: Filter -- 'scheduled', 'published', 'draft', or '' for all
            limit: Max results (1-50)
        """
        try:
            params: Dict[str, Any] = {"limit": limit}
            if status:
                params["status"] = status
            response = self._client.get(
                f"/social-sets/{social_set_id}/drafts",
                params=params
            )
            response.raise_for_status()
            data = response.json()
            return data.get("results", []) if isinstance(data, dict) else data
        except Exception as e:
            print(f"Error fetching drafts for social set {social_set_id}: {e}")
            return []

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


# Convenience functions
def schedule_post(content: str, platform: str = "twitter", when: str = "next-free-slot") -> Dict[str, Any]:
    """
    Quick helper to schedule a post
    
    Args:
        content: Post content
        platform: "twitter" or "linkedin"
        when: "next-free-slot" or ISO datetime
    
    Returns:
        Scheduled draft data
    """
    with TypefullySyncClient() as client:
        return client.create_and_schedule(
            content=content,
            share_on_linkedin=platform == "linkedin",
            schedule_date=when
        )


if __name__ == "__main__":
    # Test the client
    import asyncio
    
    async def test():
        async with TypefullyClient() as client:
            # Create a test draft
            draft = await client.create_draft(
                content="Test post from draper pipeline! 🚀",
                platform=Platform.TWITTER
            )
            print(f"Created draft: {draft}")
    
    asyncio.run(test())
