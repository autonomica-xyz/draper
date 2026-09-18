#!/bin/bash
# Setup script for publishing providers (Typefully and Late API)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PIPELINE_ROOT="$(dirname "$SCRIPT_DIR")"
ENV_FILE="$PIPELINE_ROOT/.env"

echo "🚀 Draper Publishing Providers Setup"
echo "=========================================="
echo ""
echo "This script will help you configure Typefully and/or Late API"
echo "for multi-platform content publishing."
echo ""

# Create .env if it doesn't exist
if [ ! -f "$ENV_FILE" ]; then
    touch "$ENV_FILE"
    echo "✅ Created .env file at $ENV_FILE"
fi

# Check existing configuration
TYPEFULLY_CONFIGURED=false
LATE_CONFIGURED=false

if grep -q "TYPEFULLY_API_KEY=" "$ENV_FILE" 2>/dev/null; then
    TYPEFULLY_CONFIGURED=true
fi

if grep -q "LATE_API_KEY=" "$ENV_FILE" 2>/dev/null; then
    LATE_CONFIGURED=true
fi

echo "📋 Current Configuration:"
echo "  • Typefully: $([ "$TYPEFULLY_CONFIGURED" = true ] && echo "✅ Configured" || echo "❌ Not configured")"
echo "  • Late API:  $([ "$LATE_CONFIGURED" = true ] && echo "✅ Configured" || echo "❌ Not configured")"
echo ""

# Typefully setup
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📝 Typefully (Twitter, LinkedIn, etc.)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Typefully supports:"
echo "  • Twitter/X"
echo "  • LinkedIn"
echo "  • Threads"
echo "  • Mastodon"
echo ""

if [ "$TYPEFULLY_CONFIGURED" = true ]; then
    read -p "Typefully is already configured. Reconfigure? (y/N): " RECONFIGURE
    if [ "$RECONFIGURE" != "y" ] && [ "$RECONFIGURE" != "Y" ]; then
        echo "⏭️  Skipping Typefully"
    else
        TYPEFULLY_CONFIGURED=false
    fi
fi

if [ "$TYPEFULLY_CONFIGURED" = false ]; then
    echo ""
    echo "Get your Typefully API key:"
    echo "  1. Go to: https://typefully.com/settings/api"
    echo "  2. Create a new API key"
    echo "  3. Copy the key (starts with 'tf_')"
    echo ""
    read -p "Enter Typefully API key (or press Enter to skip): " TYPEFULLY_KEY
    
    if [ -n "$TYPEFULLY_KEY" ]; then
        # Remove existing key if present
        sed -i '/TYPEFULLY_API_KEY=/d' "$ENV_FILE" 2>/dev/null || true
        echo "TYPEFULLY_API_KEY=$TYPEFULLY_KEY" >> "$ENV_FILE"
        echo "✅ Typefully API key saved"
    else
        echo "⏭️  Skipped Typefully setup"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🌐 Late API (Multi-platform)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Late API supports 13 platforms:"
echo "  • Instagram, TikTok, YouTube"
echo "  • LinkedIn, Twitter/X, Facebook"
echo "  • Pinterest, Threads, Bluesky"
echo "  • Snapchat, Google Business"
echo "  • Reddit, Telegram"
echo ""

if [ "$LATE_CONFIGURED" = true ]; then
    read -p "Late API is already configured. Reconfigure? (y/N): " RECONFIGURE
    if [ "$RECONFIGURE" != "y" ] && [ "$RECONFIGURE" != "Y" ]; then
        echo "⏭️  Skipping Late API"
    else
        LATE_CONFIGURED=false
    fi
fi

if [ "$LATE_CONFIGURED" = false ]; then
    echo ""
    echo "Get your Late API key:"
    echo "  1. Go to: https://app.getlate.dev/settings/api"
    echo "  2. Create a new API key"
    echo "  3. Copy the key"
    echo ""
    echo "Pricing: https://getlate.dev/pricing"
    echo "  • Free: 100 posts/month"
    echo "  • Starter: $29/mo (1,000 posts)"
    echo "  • Growth: $99/mo (10,000 posts)"
    echo ""
    read -p "Enter Late API key (or press Enter to skip): " LATE_KEY
    
    if [ -n "$LATE_KEY" ]; then
        # Remove existing key if present
        sed -i '/LATE_API_KEY=/d' "$ENV_FILE" 2>/dev/null || true
        echo "LATE_API_KEY=$LATE_KEY" >> "$ENV_FILE"
        echo "✅ Late API key saved"
    else
        echo "⏭️  Skipped Late API setup"
    fi
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅ Setup Complete!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# Check what's configured now
TYPEFULLY_CONFIGURED=false
LATE_CONFIGURED=false

if grep -q "TYPEFULLY_API_KEY=" "$ENV_FILE" 2>/dev/null; then
    TYPEFULLY_CONFIGURED=true
fi

if grep -q "LATE_API_KEY=" "$ENV_FILE" 2>/dev/null; then
    LATE_CONFIGURED=true
fi

echo "📡 Configured providers:"
if [ "$TYPEFULLY_CONFIGURED" = true ]; then
    echo "  ✅ Typefully"
fi
if [ "$LATE_CONFIGURED" = true ]; then
    echo "  ✅ Late API"
fi

if [ "$TYPEFULLY_CONFIGURED" = false ] && [ "$LATE_CONFIGURED" = false ]; then
    echo "  ⚠️  No providers configured"
    echo ""
    echo "You'll need at least one provider to publish content."
    echo "Run this script again when you have API keys."
else
    echo ""
    echo "🎉 Ready to publish!"
    echo ""
    echo "Next steps:"
    echo "  1. Restart the dashboard: python dashboard/unified_dashboard.py"
    echo "  2. Go to Integrations tab to test connections"
    echo "  3. Go to Profiles tab to enable social accounts"
    echo ""
fi

echo "Environment file: $ENV_FILE"
