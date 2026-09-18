# Publishing Providers

This directory contains the publishing provider abstraction layer that allows Draper to work with multiple social media scheduling APIs.

## Architecture

```
PublishingManager (Router)
    ├── TypefullyProvider (Twitter, LinkedIn, Threads, Mastodon)
    ├── LateProvider (13 platforms)
    └── [Future providers...]
```

## Supported Providers

### 1. Typefully (`typefully_provider.py`)

**Platforms:** Twitter/X, LinkedIn, Threads, Mastodon

**Features:**
- Draft creation
- Scheduled posting
- Analytics
- Thread support

**Setup:**
```bash
export TYPEFULLY_API_KEY="tf_..."
```

Get your key: https://typefully.com/settings/api

### 2. Late API (`late_provider.py`)

**Platforms:** Instagram, TikTok, YouTube, LinkedIn, Pinterest, Twitter/X, Facebook, Threads, Bluesky, Snapchat, Google Business, Reddit, Telegram

**Features:**
- Multi-platform posting
- Smart queue
- Media uploads (up to 5GB videos)
- Scheduled posting
- Analytics

**Setup:**
```bash
export LATE_API_KEY="late_..."
```

Get your key: https://app.getlate.dev/settings/api

**Pricing:**
- Free: 100 posts/month
- Starter: $29/mo (1,000 posts)
- Growth: $99/mo (10,000 posts)

## Quick Setup

Run the interactive setup script:

```bash
cd /opt/draper
./scripts/setup-providers.sh
```

## Usage in Dashboard

The dashboard automatically detects configured providers from environment variables:

1. **Start dashboard:**
   ```bash
   python -m dashboard.unified_dashboard --run-server --port 8765
   ```

2. **Configure in UI:**
   - Go to **Integrations** tab
   - Test connections
   - Configure provider preferences

3. **Enable accounts:**
   - Go to **Profiles** tab
   - Toggle accounts you want to use
   - Accounts sync automatically from providers

## Provider Selection

The `PublishingManager` automatically routes publish requests to the appropriate provider:

- **Primary provider:** Set during initialization (defaults to Typefully if configured)
- **Fallback:** Uses first available configured provider
- **Multi-provider:** Can use both simultaneously for different platforms

Example:
```python
# Typefully for Twitter
result = publishing_manager.publish(
    PublishRequest(
        content="Building in public!",
        platform="twitter",
        account_id="typefully_123_twitter"
    )
)

# Late API for Instagram
result = publishing_manager.publish(
    PublishRequest(
        content="Check out this product!",
        platform="instagram",
        account_id="late_456",
        media_urls=["https://..."]
    )
)
```

## Adding New Providers

To add a new provider:

1. **Create provider class:**
   ```python
   from integrations.publishing_provider import PublishingProvider
   
   class MyProvider(PublishingProvider):
       def get_name(self) -> str:
           return "myprovider"
       
       def is_configured(self) -> bool:
           return bool(os.getenv("MY_API_KEY"))
       
       # Implement other abstract methods...
   ```

2. **Register in dashboard:**
   ```python
   my_provider = MyProvider()
   self.publishing_manager.register_provider(my_provider)
   ```

3. **Update account ID format:**
   Use prefix pattern: `{provider}_{account_id}_{optional_platform}`
   Example: `myprovider_789_twitter`

## Account ID Format

Each provider uses a specific account ID format to ensure uniqueness:

- **Typefully:** `typefully_{social_set_id}_{platform}`
  - Example: `typefully_123_twitter`
  - Reason: Typefully uses social sets (groups of accounts)

- **Late API:** `late_{account_id}`
  - Example: `late_abc123`
  - Reason: Late has per-platform accounts

## Error Handling

All providers return standardized `PublishResult`:

```python
PublishResult(
    success=True/False,
    post_id="...",          # If published
    draft_id="...",         # If saved as draft
    url="...",              # Link to view/edit
    error="...",            # Error message if failed
    provider="typefully"    # Provider name
)
```

## Testing Connections

Test provider connectivity:

```bash
python -c "
from integrations.typefully_provider import TypefullyProvider
from integrations.late_provider import LateProvider

tf = TypefullyProvider()
print(f'Typefully: {\"✅ OK\" if tf.is_configured() else \"❌ Not configured\"}')

late = LateProvider()
print(f'Late API: {\"✅ OK\" if late.is_configured() else \"❌ Not configured\"}')
"
```

## Analytics

Fetch analytics from all providers:

```python
# Get unified analytics
analytics = publishing_manager.get_all_accounts()

for account in analytics:
    print(f"{account.platform} - {account.display_name}")
```

## Troubleshooting

### "No configured publishing provider available"

**Solution:** Set at least one API key:
```bash
export TYPEFULLY_API_KEY="tf_..."
# or
export LATE_API_KEY="late_..."
```

### "Typefully API error: 401"

**Solution:** Your API key is invalid or expired. Get a new one from https://typefully.com/settings/api

### "Late API error: 403"

**Solution:** Check your Late API subscription. Free tier has 100 posts/month limit.

### Accounts not showing in Profiles tab

**Solution:**
1. Check API keys are set correctly
2. Ensure accounts are connected in provider's dashboard (Typefully/Late)
3. Restart the Draper dashboard

## Best Practices

1. **Use both providers strategically:**
   - Typefully: Twitter, LinkedIn (better drafts and threads)
   - Late API: Instagram, TikTok, YouTube (broader platform support)

2. **Configure per-project:**
   - Different projects can use different social accounts
   - Profiles tab lets you enable/disable per project

3. **Test before auto-publish:**
   - Always use `as_draft=True` first
   - Review in provider's UI before publishing

4. **Monitor rate limits:**
   - Typefully: Check your plan limits
   - Late API: Free tier = 100 posts/month

## Security

**⚠️ IMPORTANT:** Never commit API keys to Git!

Your `.env` file should be in `.gitignore`:

```bash
# Check .gitignore includes .env
grep -q "^.env$" .gitignore || echo ".env" >> .gitignore
```

Store keys in:
- `.env` file (for local development)
- Environment variables (for production)
- Secret manager (for cloud deployments)

## Future Enhancements

Potential future providers:
- Buffer
- Hootsuite
- Direct API integrations (Twitter API v2, LinkedIn API)
- Nostr (already implemented separately)
- Bluesky direct
- Mastodon direct

## Support

**Typefully Support:** https://typefully.com/support
**Late API Docs:** https://docs.getlate.dev
**Draper Issues:** Create an issue in the repo
