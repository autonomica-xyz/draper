#!/usr/bin/env python3
"""
Publishing Provider Abstraction
Allows swapping between Typefully, Late API, or other platforms
"""

from abc import ABC, abstractmethod
from enum import Enum
from typing import Dict, List, Optional
from dataclasses import dataclass
from datetime import datetime


@dataclass
class SocialAccount:
    """Represents a connected social media account"""
    account_id: str
    platform: str  # "twitter", "linkedin", "instagram", etc.
    handle: str
    display_name: str
    provider: str  # "typefully", "late", etc.
    enabled: bool = True


@dataclass
class PublishRequest:
    """Request to publish content"""
    content: str
    platform: str
    account_id: Optional[str] = None
    content_type: str = ""  # "thread", "story_post", etc.
    scheduled_at: Optional[datetime] = None
    media_urls: List[str] = None
    as_draft: bool = True
    auto_publish: bool = False
    schedule_next_slot: bool = False
    # Origin context (used by nostr sign-now-publish-later to link the
    # signing request back to the review record).
    review_id: Optional[str] = None
    project_id: Optional[str] = None


class PublishStatus(str, Enum):
    """Stable result states for publishing operations."""

    SUCCEEDED = "succeeded"
    FAILED = "failed"


class PublishErrorCode(str, Enum):
    """Machine-readable publish failure categories."""

    NOT_CONFIGURED = "not_configured"
    INVALID_ACCOUNT = "invalid_account"
    ACCOUNT_NOT_FOUND = "account_not_found"
    PROVIDER_ERROR = "provider_error"
    RATE_LIMITED = "rate_limited"
    AUTH_FAILED = "auth_failed"
    SIGNING_REQUIRED = "signing_required"
    UNKNOWN = "unknown"


@dataclass
class PublishResult:
    """Result of publish operation"""
    success: bool
    post_id: Optional[str] = None
    draft_id: Optional[str] = None
    url: Optional[str] = None
    error: Optional[str] = None
    provider: str = "unknown"
    scheduled: bool = False
    status: Optional[PublishStatus] = None
    error_code: Optional[PublishErrorCode] = None

    def __post_init__(self) -> None:
        if self.status is None:
            self.status = PublishStatus.SUCCEEDED if self.success else PublishStatus.FAILED
        elif isinstance(self.status, str):
            self.status = PublishStatus(self.status)
        if self.error_code is not None and isinstance(self.error_code, str):
            self.error_code = PublishErrorCode(self.error_code)


class PublishingProvider(ABC):
    """Abstract base for publishing providers"""
    
    @abstractmethod
    def get_name(self) -> str:
        """Provider name (e.g., 'typefully', 'late')"""
        pass
    
    @abstractmethod
    def is_configured(self) -> bool:
        """Check if provider has valid credentials"""
        pass
    
    @abstractmethod
    def get_accounts(self) -> List[SocialAccount]:
        """Fetch connected social accounts"""
        pass
    
    @abstractmethod
    def publish(self, request: PublishRequest) -> PublishResult:
        """Publish content to a platform"""
        pass
    
    @abstractmethod
    def get_analytics(self, account_id: Optional[str] = None) -> Dict:
        """Fetch analytics data"""
        pass


class PublishingManager:
    """Manages multiple publishing providers"""
    
    def __init__(self):
        self.providers: Dict[str, PublishingProvider] = {}
        self._primary_provider: Optional[str] = None
    
    def register_provider(self, provider: PublishingProvider, primary: bool = False):
        """Register a publishing provider"""
        name = provider.get_name()
        self.providers[name] = provider
        
        if primary or not self._primary_provider:
            self._primary_provider = name
    
    def get_provider(self, name: Optional[str] = None) -> Optional[PublishingProvider]:
        """Get provider by name, or primary if not specified"""
        if name:
            return self.providers.get(name)
        
        if self._primary_provider:
            provider = self.providers.get(self._primary_provider)
            if provider and provider.is_configured():
                return provider
        
        # Return first configured provider
        for provider in self.providers.values():
            if provider.is_configured():
                return provider
        
        return None
    
    def get_all_accounts(self) -> List[SocialAccount]:
        """Get accounts from all configured providers"""
        accounts = []
        for provider in self.providers.values():
            if provider.is_configured():
                try:
                    accounts.extend(provider.get_accounts())
                except Exception as e:
                    print(f"⚠️  Error fetching accounts from {provider.get_name()}: {e}")
        return accounts
    
    def publish(self, request: PublishRequest, provider_name: Optional[str] = None) -> PublishResult:
        """Publish using specified or primary provider"""
        provider = self.get_provider(provider_name)
        
        if not provider:
            return PublishResult(
                success=False,
                error="No configured publishing provider available",
                error_code=PublishErrorCode.NOT_CONFIGURED,
            )
        
        if not provider.is_configured():
            return PublishResult(
                success=False,
                error=f"Provider {provider.get_name()} is not configured",
                provider=provider.get_name(),
                error_code=PublishErrorCode.NOT_CONFIGURED,
            )
        
        return provider.publish(request)
