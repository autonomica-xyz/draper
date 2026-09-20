#!/usr/bin/env python3
"""
Typefully Publishing Provider
Implements PublishingProvider for Typefully API v2
"""

import os
import time
import mimetypes
import requests
from pathlib import Path
from typing import Dict, List, Optional

from .publishing_provider import (
    PublishingProvider,
    SocialAccount,
    PublishRequest,
    PublishResult,
    PublishErrorCode,
)


class TypefullyProvider(PublishingProvider):
    """Typefully API v2 implementation"""

    BASE_URL = "https://api.typefully.com/v2"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("TYPEFULLY_API_KEY")
        self._social_sets_cache = None

    def get_name(self) -> str:
        return "typefully"

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _get_headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "User-Agent": "marketing-pipeline/1.0"
        }

    def _get_social_sets(self) -> List[Dict]:
        """Fetch social sets (groups of connected accounts)"""
        if self._social_sets_cache:
            return self._social_sets_cache

        try:
            response = requests.get(
                f"{self.BASE_URL}/social-sets",
                headers=self._get_headers(),
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            self._social_sets_cache = data.get("results", [])
            return self._social_sets_cache
        except Exception as e:
            print(f"Error fetching Typefully social sets: {e}")
            return []

    def get_accounts(self) -> List[SocialAccount]:
        """Fetch connected accounts from Typefully.
        Each social set can publish to twitter and linkedin."""
        accounts = []
        social_sets = self._get_social_sets()

        for social_set in social_sets:
            set_id = str(social_set.get("id"))
            set_name = social_set.get("name", "Unnamed")
            handle = social_set.get("username", "")

            # Each Typefully social set supports twitter and linkedin
            for platform in ("twitter", "linkedin"):
                accounts.append(SocialAccount(
                    account_id=f"typefully_{set_id}_{platform}",
                    platform=platform,
                    handle=handle,
                    display_name=f"{set_name} ({platform.title()})",
                    provider="typefully",
                    enabled=True
                ))

        return accounts

    def publish(self, request: PublishRequest) -> PublishResult:
        """
        Publish to Typefully via v2 API.

        Creates a draft on a social set with optional scheduling.
        account_id format: "typefully_{social_set_id}_{platform}"
        """
        # Extract social_set_id from account_id, or auto-discover
        account_id = request.account_id
        if not account_id or not account_id.startswith("typefully_"):
            accounts = self.get_accounts()
            for acct in accounts:
                if acct.platform == request.platform:
                    account_id = acct.account_id
                    break
            if not account_id or not account_id.startswith("typefully_"):
                return PublishResult(
                    success=False,
                    error=f"No Typefully account found for platform '{request.platform}'",
                    provider="typefully",
                    error_code=PublishErrorCode.ACCOUNT_NOT_FOUND,
                )

        parts = account_id.split("_")
        if len(parts) < 3:
            return PublishResult(
                success=False,
                error="Malformed account_id",
                provider="typefully",
                error_code=PublishErrorCode.INVALID_ACCOUNT,
            )

        social_set_id = int(parts[1])
        platform = parts[2] if len(parts) > 2 else request.platform

        # Map platform names to Typefully v2 platform keys
        platform_key = "x" if platform == "twitter" else platform

        # Build v2 payload: split threads into separate posts
        char_limit = 280 if platform == "twitter" else 3000
        posts = self._split_into_posts(request.content, request.content_type, char_limit)

        # Upload media files if provided
        if request.media_urls:
            media_ids = self._upload_media_files(social_set_id, request.media_urls)
            if media_ids and posts:
                posts[0]["media_ids"] = media_ids

        payload = {
            "platforms": {
                platform_key: {
                    "enabled": True,
                    "posts": posts
                }
            }
        }

        # Scheduling
        if request.scheduled_at:
            payload["publish_at"] = request.scheduled_at.isoformat()
        elif request.schedule_next_slot:
            payload["publish_at"] = "next-free-slot"

        try:
            response = requests.post(
                f"{self.BASE_URL}/social-sets/{social_set_id}/drafts",
                headers=self._get_headers(),
                json=payload,
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            draft_id = data.get("id")

            scheduled = bool(payload.get("publish_at"))

            return PublishResult(
                success=True,
                draft_id=str(draft_id) if draft_id else None,
                url=f"https://typefully.com/drafts/{draft_id}" if draft_id else None,
                provider="typefully",
                scheduled=scheduled
            )

        except requests.exceptions.HTTPError as e:
            return self._http_error_result(e)
        except Exception as e:
            return PublishResult(
                success=False,
                error=f"Typefully draft creation failed: {e}",
                provider="typefully",
                error_code=PublishErrorCode.PROVIDER_ERROR,
            )

    def _upload_media(self, social_set_id: int, file_path: str) -> Optional[str]:
        """Upload a media file to Typefully via presigned S3 URL.

        Args:
            social_set_id: The social set to upload for
            file_path: Local path or URL to the media file

        Returns:
            media_id string if successful, None otherwise
        """
        p = Path(file_path)
        filename = p.name
        content_type, _ = mimetypes.guess_type(file_path)
        content_type = content_type or "application/octet-stream"

        # Step 1: request presigned upload URL
        try:
            resp = requests.post(
                f"{self.BASE_URL}/social-sets/{social_set_id}/media/upload",
                headers=self._get_headers(),
                json={"filename": filename, "content_type": content_type},
                timeout=15
            )
            resp.raise_for_status()
            upload_data = resp.json()
        except Exception as e:
            print(f"Typefully media upload request failed: {e}")
            return None

        media_id = upload_data.get("media_id")
        upload_url = upload_data.get("upload_url")
        if not media_id or not upload_url:
            print(f"Typefully media upload: missing media_id or upload_url")
            return None

        # Step 2: PUT file contents to the presigned S3 URL
        try:
            with open(file_path, "rb") as f:
                file_bytes = f.read()

            put_resp = requests.put(
                upload_url,
                data=file_bytes,
                headers={"Content-Type": content_type},
                timeout=60
            )
            put_resp.raise_for_status()
        except Exception as e:
            print(f"Typefully S3 upload failed: {e}")
            return None

        # Step 3: poll for processing completion (up to 30s)
        for _ in range(15):
            try:
                status_resp = requests.get(
                    f"{self.BASE_URL}/social-sets/{social_set_id}/media/{media_id}",
                    headers=self._get_headers(),
                    timeout=10
                )
                if status_resp.status_code == 200:
                    status_data = status_resp.json()
                    if status_data.get("status") == "ready":
                        return media_id
            except Exception:
                pass
            time.sleep(2)

        # Return media_id anyway -- it may still be usable
        return media_id

    def _upload_media_files(self, social_set_id: int, media_urls: List[str]) -> List[str]:
        """Upload multiple media files, returning list of media_ids."""
        media_ids = []
        for url_or_path in media_urls:
            mid = self._upload_media(social_set_id, url_or_path)
            if mid:
                media_ids.append(mid)
        return media_ids

    @staticmethod
    def _split_into_posts(content: str, content_type: str = "",
                          char_limit: int = 280) -> List[Dict]:
        """Split content into posts that respect platform character limits.

        For threads, first splits on N/M markers (e.g. '1/7', '2/7'),
        then enforces char_limit on each resulting post.
        For single posts over the limit, splits into a thread.
        """
        import re

        content = content.strip()
        # Strip metadata prefixes like "Platform: twitter\nContent Type: thread\n\n"
        content = re.sub(r'^Platform:\s*\w+\nContent Type:\s*\w+\n\n', '', content)
        content = content.strip()

        if not content:
            return [{"text": ""}]

        # Phase 1: split threads on N/M markers
        raw_parts = [content]
        if content_type == "thread":
            parts = re.split(r'(?:\n\n|\A)\d+/\d+\s*\n', content)
            filtered = [p.strip() for p in parts if p.strip()]
            if len(filtered) > 1:
                raw_parts = filtered

        # Phase 2: enforce character limit on each part
        posts = []
        for text in raw_parts:
            if len(text) <= char_limit:
                posts.append({"text": text})
            else:
                posts.extend(
                    {"text": chunk} for chunk in
                    TypefullyProvider._break_to_limit(text, char_limit)
                )

        return posts if posts else [{"text": content[:char_limit]}]

    @staticmethod
    def _break_to_limit(text: str, limit: int) -> List[str]:
        """Break a single text into chunks that fit within the character limit.

        Tries to split at paragraph boundaries first, then sentence boundaries,
        then word boundaries as a last resort.
        """
        if len(text) <= limit:
            return [text]

        chunks = []
        remaining = text

        while remaining:
            remaining = remaining.strip()
            if len(remaining) <= limit:
                chunks.append(remaining)
                break

            # Try paragraph break (double newline)
            cut = TypefullyProvider._find_break(remaining, limit, '\n\n')
            if not cut:
                # Try single newline
                cut = TypefullyProvider._find_break(remaining, limit, '\n')
            if not cut:
                # Try sentence end (. or ! or ?)
                cut = TypefullyProvider._find_sentence_break(remaining, limit)
            if not cut:
                # Last resort: word boundary
                cut = remaining[:limit].rfind(' ')
                if cut <= 0:
                    cut = limit

            chunks.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()

        return [c for c in chunks if c]

    @staticmethod
    def _find_break(text: str, limit: int, delimiter: str) -> int:
        """Find the last occurrence of delimiter within limit."""
        idx = text[:limit].rfind(delimiter)
        return idx if idx > 0 else 0

    @staticmethod
    def _find_sentence_break(text: str, limit: int) -> int:
        """Find the last sentence-ending punctuation within limit."""
        import re
        # Look for '. ' or '! ' or '? ' or end-of-sentence followed by newline
        matches = list(re.finditer(r'[.!?](?:\s|$)', text[:limit]))
        if matches:
            last = matches[-1]
            return last.end()
        return 0

    def _http_error_result(self, e) -> PublishResult:
        """Build error result from HTTP error"""
        error_msg = f"Typefully API error: {e.response.status_code}"
        try:
            error_data = e.response.json()
            detail = (error_data.get('message')
                      or error_data.get('detail')
                      or error_data.get('error')
                      or str(error_data))
            error_msg += f" - {detail}"
        except Exception:
            error_msg += f" - {e.response.text[:200]}"
        error_code = PublishErrorCode.PROVIDER_ERROR
        status_code = getattr(getattr(e, "response", None), "status_code", None)
        if status_code == 401 or status_code == 403:
            error_code = PublishErrorCode.AUTH_FAILED
        elif status_code == 429:
            error_code = PublishErrorCode.RATE_LIMITED
        return PublishResult(
            success=False,
            error=error_msg,
            provider="typefully",
            error_code=error_code,
        )

    def get_analytics(self, account_id: Optional[str] = None) -> Dict:
        """
        Fetch analytics from Typefully.
        Returns aggregated stats across all social sets or for a specific account.
        """
        social_sets = self._get_social_sets()

        if not social_sets:
            return {"error": "No social sets found"}

        target_set_id = None
        if account_id and account_id.startswith("typefully_"):
            parts = account_id.split("_")
            if len(parts) >= 2:
                target_set_id = int(parts[1])

        all_posts = []

        for social_set in social_sets:
            set_id = social_set.get("id")

            if target_set_id and set_id != target_set_id:
                continue

            try:
                response = requests.get(
                    f"{self.BASE_URL}/social-sets/{set_id}/drafts",
                    headers=self._get_headers(),
                    params={"status": "published", "limit": 50},
                    timeout=10
                )
                response.raise_for_status()
                data = response.json()
                posts = data.get("results", [])
                all_posts.extend(posts)
            except Exception as e:
                print(f"Error fetching analytics for set {set_id}: {e}")

        total_posts = len(all_posts)
        total_impressions = 0
        total_likes = 0
        total_retweets = 0
        total_comments = 0

        for post in all_posts:
            stats = post.get("stats", {})
            total_impressions += stats.get("impressions", 0)
            total_likes += stats.get("likes", 0)
            total_retweets += stats.get("retweets", 0)
            total_comments += stats.get("comments", 0)

        total_engagement = total_likes + total_retweets + total_comments
        avg_engagement_rate = (
            (total_engagement / total_impressions * 100)
            if total_impressions > 0
            else 0
        )

        return {
            "provider": "typefully",
            "total_posts": total_posts,
            "total_impressions": total_impressions,
            "total_engagement": total_engagement,
            "avg_engagement_rate": round(avg_engagement_rate, 2),
            "posts": all_posts
        }
