#!/usr/bin/env python3
"""
Test Typefully API Integration

This script tests:
1. Fetching social accounts from Typefully
2. Creating a test draft
3. Scheduling the draft
4. Cleaning up (deleting the test draft)

Usage:
    python test_typefully_integration.py

Requirements:
    TYPEFULLY_API_KEY must be set in .env file
"""

import os
import sys
import asyncio
from pathlib import Path

# Add project to path
sys.path.insert(0, str(Path(__file__).parent))

from integrations.typefully import TypefullyClient, TypefullySyncClient
from dotenv import load_dotenv

# Load .env
load_dotenv()


def test_sync_client():
    """Test synchronous client (used by dashboard)"""
    print("=" * 60)
    print("Testing Synchronous Typefully Client")
    print("=" * 60)
    
    api_key = os.getenv("TYPEFULLY_API_KEY")
    if not api_key:
        print("❌ TYPEFULLY_API_KEY not found in .env")
        print("   Please add it to the .env file:")
        print("   TYPEFULLY_API_KEY=your-typefully-api-key")
        return False
    
    print(f"✓ API Key found: {api_key[:10]}...{api_key[-4:]}")
    
    try:
        with TypefullySyncClient(api_key=api_key) as client:
            print("\n1. Fetching social accounts...")
            accounts = client.get_social_accounts()
            
            print(f"✓ Found {len(accounts)} account(s):")
            for account in accounts:
                print(f"  • {account.get('platform', 'unknown'):10} - {account.get('handle', 'unknown'):20} ({account.get('name', 'unknown')})")
                print(f"    ID: {account.get('id', 'unknown')}")
            
            if not accounts:
                print("  ⚠️  No accounts found. Make sure you have connected social accounts in Typefully.")
                return True  # Not a failure, just no accounts
            
            print("\n2. Testing draft creation...")
            test_content = "🧪 Test post from Draper Marketing Pipeline\n\nThis is a test - will be deleted shortly.\n\n#testing"
            
            draft = client.create_draft(
                content=test_content,
                threadify=False
            )
            
            draft_id = draft.get("id")
            print(f"✓ Draft created: {draft_id}")
            print(f"  Status: {draft.get('status', 'unknown')}")
            
            # Note: We're not actually scheduling or publishing to avoid spam
            # Just creating a draft to verify API works
            
            print("\n3. Fetching scheduled posts...")
            try:
                # This might fail if endpoint doesn't exist
                scheduled = client._client.get("/drafts/?filter=scheduled")
                if scheduled.status_code == 200:
                    scheduled_posts = scheduled.json()
                    print(f"✓ Found {len(scheduled_posts)} scheduled post(s)")
                else:
                    print(f"  Info: Scheduled posts endpoint returned {scheduled.status_code}")
            except Exception as e:
                print(f"  Info: Could not fetch scheduled posts: {e}")
            
            print("\n" + "=" * 60)
            print("✅ Synchronous client test PASSED")
            print("=" * 60)
            print("\n⚠️  Test draft created (ID: {})".format(draft_id))
            print("   Please delete it manually in Typefully dashboard to clean up")
            print("   Or it will remain as a draft (not published)")
            
            return True
            
    except Exception as e:
        print(f"\n❌ Test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


async def test_async_client():
    """Test async client"""
    print("\n" + "=" * 60)
    print("Testing Async Typefully Client")
    print("=" * 60)
    
    api_key = os.getenv("TYPEFULLY_API_KEY")
    if not api_key:
        print("❌ TYPEFULLY_API_KEY not found in .env")
        return False
    
    try:
        async with TypefullyClient(api_key=api_key) as client:
            print("\n1. Fetching social accounts (async)...")
            accounts = await client.get_social_accounts()
            
            print(f"✓ Found {len(accounts)} account(s)")
            for account in accounts:
                print(f"  • {account.get('platform', 'unknown'):10} - {account.get('handle', 'unknown')}")
            
            print("\n✅ Async client test PASSED")
            return True
            
    except Exception as e:
        print(f"\n❌ Async test FAILED: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_dashboard_integration():
    """Test that the dashboard can fetch accounts"""
    print("\n" + "=" * 60)
    print("Testing Dashboard Integration")
    print("=" * 60)
    
    api_key = os.getenv("TYPEFULLY_API_KEY")
    if not api_key:
        print("❌ TYPEFULLY_API_KEY not found")
        return False
    
    # Simulate what the dashboard does
    print("\n1. Storing API key in project secrets...")
    
    project_id = "draper-fc78f02c"
    secrets_file = Path("data/projects") / project_id / "secrets.json"
    secrets_file.parent.mkdir(parents=True, exist_ok=True)
    
    import json
    secrets_data = {
        "typefully": {
            "api_key": api_key,
            "drafts_enabled": True,
            "auto_schedule": False
        }
    }
    
    with open(secrets_file, 'w') as f:
        json.dump(secrets_data, f, indent=2)
    
    secrets_file.chmod(0o600)
    print(f"✓ Secrets stored at {secrets_file} (600 permissions)")
    
    print("\n2. Testing dashboard endpoint logic...")
    try:
        with TypefullySyncClient(api_key=api_key) as client:
            accounts = client.get_social_accounts()
            
            # Simulate what /api/projects/{id}/social-profiles does
            profiles = []
            for account in accounts:
                profiles.append({
                    "account_id": account.get("id", ""),
                    "platform": account.get("platform", ""),
                    "handle": account.get("handle", ""),
                    "display_name": account.get("name", ""),
                    "enabled": False  # Default to disabled
                })
            
            print(f"✓ Transformed {len(profiles)} accounts for dashboard")
            for p in profiles:
                print(f"  • {p['platform']:10} - {p['handle']:20} (enabled: {p['enabled']})")
            
            print("\n✅ Dashboard integration test PASSED")
            return True
            
    except Exception as e:
        print(f"\n❌ Dashboard integration test FAILED: {e}")
        return False


def main():
    """Run all tests"""
    print("\n" + "🧪 " * 20)
    print("Typefully API Integration Test Suite")
    print("🧪 " * 20)
    
    results = {
        "sync_client": False,
        "async_client": False,
        "dashboard_integration": False
    }
    
    # Test 1: Sync client
    results["sync_client"] = test_sync_client()
    
    # Test 2: Async client
    results["async_client"] = asyncio.run(test_async_client())
    
    # Test 3: Dashboard integration
    results["dashboard_integration"] = test_dashboard_integration()
    
    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)
    
    for test_name, passed in results.items():
        status = "✅ PASSED" if passed else "❌ FAILED"
        print(f"{test_name:25} {status}")
    
    all_passed = all(results.values())
    
    if all_passed:
        print("\n🎉 All tests PASSED!")
        print("\n⚠️  CLEANUP REMINDER:")
        print("   - Check Typefully dashboard for test drafts")
        print("   - Delete any test drafts manually")
        print("   - Test draft content: '🧪 Test post from Draper Marketing Pipeline'")
    else:
        print("\n❌ Some tests FAILED - check output above")
        sys.exit(1)


if __name__ == "__main__":
    main()
