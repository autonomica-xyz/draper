# Draper Marketing Pipeline

AI-powered autonomous marketing content generation and scheduling system with **multi-project support**.

Generate high-quality social media content using LLMs, review it through a web dashboard, and automatically schedule to Twitter/LinkedIn via Typefully.

## Features

### Core Features
- 🤖 **AI Content Generation** - Generate platform-optimized content using Claude, GPT-4, or other LLMs
- 📁 **Multi-Project Support** - Manage multiple brands/accounts with strict isolation
- 📊 **Web Dashboard** - Review, approve, and manage generated content at `http://localhost:8765`
- 📅 **Auto-Scheduling** - Push approved content to Typefully for automated posting
- 🔒 **Safety Guards** - Content tagged with project ID, prevents cross-account posting
- 🔧 **CLI & API** - Full programmatic control for automation

### 🆕 Marketing Knowledge Integration (v2.6)

Enhanced with Anthropic knowledge-work-plugins/marketing framework:

#### 🎣 Hook Formulas System
- **8 Hook Types**: statistic, contrarian, question, scenario, claim, story, value, curiosity
- **6 Headline Formulas**: Proven formulas for higher engagement
- **Platform-Specific**: Each hook type tailored to Twitter/LinkedIn

#### 📢 CTA Strategy
- **Platform-Specific CTAs**: Tailored call-to-action suggestions for each platform
- **Twitter**: "Drop a comment if you agree", "Save this for later"
- **LinkedIn**: "Share your thoughts in the comments", "Tag someone who needs to see this"
- **Email**: "Read the full story", "Claim your spot"
- **Blog**: "Read our complete guide to [topic]", "Subscribe for weekly insights"

#### 🎨 Brand Voice System
Comprehensive brand voice configuration for consistent messaging:
- **Personality Attributes**: 3-5 traits with examples (knowledgeable, authentic, technical but accessible)
- **Tone Spectrum**: Per-channel tone adaptation (twitter, linkedin, email, blog)
- **Messaging Pillars**: 3-5 core themes that define brand communication
- **Terminology Management**: Preferred and avoided terms
- **Style Rules**: Oxford comma, contractions, emoji usage, exclamation marks

#### 📝 7 Content Types
Extended from 2 to 7 content generation types:

1. **Twitter Thread** - 6-8 tweets with hooks, narrative, and CTA
2. **LinkedIn Post** - Professional posts with stories and insights
3. **Blog Post** - 1000-1500 words with SEO optimization
4. **Email Newsletter** - Subject lines, preview text, body, and CTA
5. **Landing Page** - Headline, value props, social proof, CTAs
6. **Press Release** - Journalistic style with dateline and boilerplate
7. **Case Study** - Customer success stories with metrics and results

#### 🔍 SEO Optimization
Built-in SEO features for blog posts:
- Primary keyword suggestion
- Keyword placement optimization
- Meta description generation
- H2/H3 structure recommendations
- Reading level guidance

See [`docs/content-plan-format.md`](docs/content-plan-format.md) and
[`examples/content_plan.simple.example.md`](examples/content_plan.simple.example.md) for the
structured planning inputs used by generation.

### Publishing Providers (v2.5)

#### 📡 Multi-Platform Publishing
- **Typefully** - Twitter/X, LinkedIn, Threads, Mastodon
- **Late API** - Instagram, TikTok, YouTube, Facebook, Pinterest, Bluesky, Reddit, Telegram, Snapchat, Google Business
- **Provider-agnostic architecture** - Use one or both simultaneously
- **Auto-detection** - Reads API keys from environment
- **Unified interface** - Same workflow regardless of provider

#### 📅 Visual Calendar
- Month/week/day/list views powered by FullCalendar
- Color-coded events by platform
- Drag-and-drop rescheduling
- Professional timeline view like LateWiz

#### 🎨 Modern UI
- LateWiz-inspired design
- Gradient buttons with smooth animations
- Improved typography and spacing
- Better form inputs with focus states
- Mobile-responsive layout

### Multi-Project Social Features (v2.0)

#### 🎯 Content Strategy Management
- Upload and edit markdown content plans per project
- In-browser markdown editor with preview mode
- Version tracking with last-updated timestamps
- Download strategies for backup
- Simple structured format reference: [`docs/content-plan-format.md`](docs/content-plan-format.md)
- Full example plan: [`examples/content_plan.simple.example.md`](examples/content_plan.simple.example.md)

#### 📱 Social Profiles Management
- Configure multiple social profiles per platform (e.g., @brand AND @founder on Twitter)
- Enable/disable profiles per project
- Support for Twitter, LinkedIn, and Nostr
- Map profiles to Typefully drafts

#### 📅 Posting Strategy Configuration
- Default posting strategy (frequency, times, platforms)
- Per-platform overrides (e.g., Twitter: 5/day, LinkedIn: 1/day)
- Visual time picker for optimal posting times
- Platform-specific content strategies

#### ⚙️ Integrations Dashboard
- Per-project Typefully API keys (secure storage in `secrets.json`)
- Test connection functionality
- Masked API key display for security
- AI generator selection per project

## Quick Start

### Installation

**Uses `uv` for fast dependency management.**

```bash
# Install uv if you don't have it
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone the repository
git clone https://github.com/your-org/draper.git
cd draper

# Create virtual environment and install dependencies
uv venv
uv pip install -e .

# Activate the environment
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate   # Windows
```

### Setup Publishing Providers

**Interactive setup script:**

```bash
./scripts/setup-providers.sh
```

This will guide you through:
1. Typefully API key setup (Twitter, LinkedIn, Threads, Mastodon)
2. Late API key setup (13 platforms including Instagram, TikTok, YouTube)

**Or manually configure `.env`:**

```bash
cp .env.example .env
```

Required settings in `.env`:

```bash
# Dashboard authentication (required outside explicit local development)
DRAPER_DASHBOARD_TOKEN=replace-with-openssl-rand-hex-32

# LLM Provider (at least one required)
ANTHROPIC_API_KEY=your-anthropic-api-key     # For Claude (recommended)
# OPENAI_API_KEY=your-openai-api-key         # Alternative

# Publishing Providers (at least one required)
TYPEFULLY_API_KEY=your-typefully-api-key     # For Twitter/LinkedIn via Typefully
# LATE_API_KEY=your-late-api-key             # For additional platforms via Late API

# Optional: Custom endpoint (for proxies like ZeroWidth)
# ANTHROPIC_BASE_URL=https://api.anthropic.com

# Optional: Model selection
# LLM_MODEL=claude-sonnet-4-20250514
```

### Start the Dashboard

```bash
# Option 1: Run directly
./run.sh dashboard

# Option 2: Via CLI
draper review --web --port 8765

# Option 3: Install as systemd service (see below)
```

**Dashboard URL:** http://localhost:8765

The dashboard requires authentication by default, including when bound to
localhost behind a reverse proxy. Set a strong admin token before starting it:

```bash
export DRAPER_DASHBOARD_TOKEN="$(openssl rand -hex 32)"
./run.sh dashboard
```

API clients can authenticate with `Authorization: Bearer $DRAPER_DASHBOARD_TOKEN`
or `X-API-Key: $DRAPER_DASHBOARD_TOKEN`. Browser users can sign in at `/login`.
For local-only development without auth, set `DRAPER_ALLOW_UNAUTHENTICATED_LOCAL=1`;
do not use that setting in production.

Project owners can create scoped project tokens through:

```bash
curl -X POST http://localhost:8765/api/projects/PROJECT_ID/access/tokens \
  -H "Authorization: Bearer $DRAPER_DASHBOARD_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"label":"Project A publisher","role":"publisher","mcp_enabled":false}'
```

Roles are `viewer`, `editor`, `publisher`, and `owner`. Scoped tokens only see
the projects listed on the token.

### Dashboard Tabs

The unified dashboard provides comprehensive project management:

- **🔄 Pipeline** - Review and approve generated content
- **🎯 Strategy** - Upload/edit markdown content plans
- **📱 Profiles** - Manage social media profiles and accounts
- **📅 Schedule** - Configure posting frequency and times
- **⚙️ Integrations** - Set up Typefully API and other integrations
- **📊 Analytics** - View performance metrics across platforms
- **📂 Past Posts** - Browse published content history
- **🦀 Nostr** - Direct publishing to Nostr protocol

## Multi-Project Setup

Each project has its own content queue, analytics, and Typefully social account configuration.

### Content Plan Format

Use the simple markdown contract for reliable planning and parsing:

- Format spec: [`docs/content-plan-format.md`](docs/content-plan-format.md)
- Example file: [`examples/content_plan.simple.example.md`](examples/content_plan.simple.example.md)

Use that format inside each project's `content_plan.md`.

### Create Projects

```bash
# Add projects for each brand/product
draper project add draper -d "Marketing automation startup"
draper project add acme -d "Confidential computing platform"
draper project add widgets -d "Prediction markets"

# List all projects
draper project list
```

### Configure Typefully Social Sets

Each project posts to different Twitter/LinkedIn accounts within your single Typefully account:

```bash
# 1. In Typefully: Settings → API → Enable Development mode
#    This shows social set IDs in the UI

# 2. Configure each project
draper project switch draper
draper project config --set twitter_social_set_id=ss_your_draper_twitter
draper project config --set linkedin_social_set_id=ss_your_draper_linkedin

draper project switch acme
draper project config --set twitter_social_set_id=ss_your_acme_twitter
draper project config --set linkedin_social_set_id=ss_your_acme_linkedin
```

### Project Configuration Options

```bash
# View current config
draper project config

# Content settings
draper project config --set pillars=educational,technical,news
draper project config --set tone=professional  # professional, casual, technical, friendly
draper project config --set posts_per_batch=10

# Platform settings  
draper project config --set platforms=twitter,linkedin
draper project config --set default_platform=twitter

# Scheduling
draper project config --set auto_schedule=true
draper project config --set schedule_times=09:00,14:00,18:00
```

## CLI Reference

### Project Commands

```bash
draper project list              # List all projects
draper project add <name>        # Create new project
draper project switch <name>     # Switch active project
draper project config            # View project config
draper project config --set K=V  # Update config
draper project delete <name> --confirm
```

### Content Commands

All content commands work within the current project context:

```bash
draper generate                  # Generate 5 posts (default)
draper generate -n 10            # Generate 10 posts
draper generate -p twitter       # Twitter only
draper generate -p linkedin      # LinkedIn only
draper generate -p both          # Both platforms (default)

draper status                    # Show pipeline status
draper review                    # CLI review (interactive)
draper review --web              # Start web dashboard
draper schedule                  # Schedule approved → Typefully
draper config                    # Show global config
```

## Web Dashboard

### Starting the Dashboard

```bash
# Foreground (for testing)
draper review --web --port 8765

# Background (production)
nohup python -m dashboard.unified_dashboard --run-server --port 8765 &
```

### Dashboard Features

- **Pipeline Tab** - View and approve/reject pending content
- **Analytics Tab** - Performance metrics and trends
- **Scheduled Tab** - View scheduled posts
- **Past Posts Tab** - History of published content

### Systemd Service (Production)

Install as a system service for automatic startup:

```bash
# Review and adjust User=, WorkingDirectory=, EnvironmentFile=, and ReadWritePaths=
sudo cp draper-dashboard.service /etc/systemd/system/

# Enable and start
sudo systemctl daemon-reload
sudo systemctl enable draper-dashboard
sudo systemctl start draper-dashboard

# Check status
sudo systemctl status draper-dashboard

# View logs
journalctl -u draper-dashboard -f
```

Service file location: `draper-dashboard.service`. See
[`docs/production.md`](docs/production.md) for production deployment, backup, and security
checklists.

## Workflow

### 1. Generate Content

```bash
draper project switch myproject
draper generate -n 5
```

Content is generated with AI and tagged with the project ID.

### 2. Review Content

**Web Dashboard:**
```bash
draper review --web
# Open http://localhost:8765
```

**CLI Review:**
```bash
draper review
# Interactive: (a)pprove, (r)eject, (s)kip, (q)uit
```

### 3. Schedule to Typefully

```bash
draper schedule
```

Approved content is sent to Typefully using the project's configured social set IDs.

## Safety Features

### Project Isolation

- Content tagged with `project_id` at generation
- Scheduling verifies content matches current project
- Wrong project content → **blocked with warning**
- Each project uses different Typefully social sets

### Example Safety Check

```
📁 Project: acme
📅 Scheduling 3 posts to Typefully...
   ✅ [twitter] How TEEs protect your data...
   ✅ [linkedin] Confidential computing 101...
   ⚠️  SKIPPED: Content belongs to different project
      Content project: draper
      Current project: acme
```

## Architecture

```
draper/
├── cli.py                    # CLI entry point
├── run.sh                    # Quick-start script
├── .env                      # Configuration (gitignored)
├── .env.example              # Config template
│
├── projects/                 # Multi-project management
│   └── manager.py            # Project CRUD, isolation
│
├── feedback/                 # Content review workflow
│   └── manager.py            # Approve/reject/schedule
│
├── generator/                # AI content generation
│   ├── llm_content_generator.py       # Main LiteLLM generator
│   ├── zai_content_generator.py       # ZAI GLM generator
│   └── automated_content_generator.py # Plan-driven orchestration
│
├── integrations/             # External services
│   └── typefully.py          # Typefully API client
│
├── dashboard/                # Web UI
│   ├── unified_dashboard.py  # FastAPI app
│   └── templates/            # Jinja2 templates
│
├── analytics/                # Performance tracking
│
└── data/                     # Local data (gitignored)
    ├── projects.json         # Project registry
    └── projects/             # Per-project data
        ├── draper-xxx/
        │   └── reviews.json
        └── acme-xxx/
            └── reviews.json
```

## API Usage

### Python API

```python
from projects import ProjectManager
from generator.llm_content_generator import LLMContentGenerator
from feedback import FeedbackManager
from integrations.typefully import TypefullySyncClient

# Setup
pm = ProjectManager()
project = pm.get_project_by_name("draper")
feedback = FeedbackManager(data_dir=pm.get_project_data_dir(project.project_id))

# Generate
generator = LLMContentGenerator()
posts = generator.generate_batch(count=5, platforms=["twitter"])

# Tag and save
for post in posts:
    post["project_id"] = project.project_id
    feedback.add_for_review(post)

# Schedule approved content
with TypefullySyncClient() as client:
    for item in feedback.get_approved():
        social_set_id = project.get_social_set_id(item["post_data"]["platform"])
        client.create_and_schedule(
            content=item["post_data"]["content"],
            social_set_id=social_set_id
        )
```

## Automation

### Cron-based Generation

```bash
# Edit crontab
crontab -e

# Generate content daily at 9am for each project
0 9 * * * cd /opt/draper && source .venv/bin/activate && python -m cli project switch draper && python -m cli generate -n 5
0 10 * * * cd /opt/draper && source .venv/bin/activate && python -m cli project switch acme && python -m cli generate -n 5
```

### Full Automation Script

```bash
#!/bin/bash
# daily-content.sh - Run daily for each project

cd /opt/draper
source .venv/bin/activate

for project in draper acme widgets; do
    echo "Processing $project..."
    python -m cli project switch "$project"
    python -m cli generate -n 5
    python -m cli schedule  # Auto-schedule if auto_schedule=true
done
```

## Development

```bash
# Install dev dependencies
uv pip install -e ".[dev]"

# Run tests
python -m pytest

# Lint
python -m ruff check .
python -m ruff format .

# Build package artifacts
python -m build
```

## File Structure

Each project has its own isolated data directory:

```
data/
├── projects.json                          # Global project registry
├── projects/
│   ├── draper-fc78f02c/
│   │   ├── content_plan.md               # 🎯 Uploaded content strategy
│   │   ├── settings.json                 # 📱📅 Profiles & posting strategy
│   │   ├── secrets.json                  # 🔒 API keys (600 permissions)
│   │   └── reviews.json                  # Content review queue
│   └── acme-a1b2c3d4/
│       ├── content_plan.md
│       ├── settings.json
│       ├── secrets.json
│       └── reviews.json
```

### File Descriptions

- **content_plan.md** - Markdown content strategy uploaded via dashboard (use [`docs/content-plan-format.md`](docs/content-plan-format.md))
- **settings.json** - Social profiles, posting strategy, and platform overrides
- **secrets.json** - Securely stored API keys (not committed to git)
- **reviews.json** - Content review queue with feedback history

### Security

- `secrets.json` files are automatically created with `600` permissions (owner read/write only)
- API keys are never logged or exposed in responses (masked display only)
- `.gitignore` includes `secrets.json` to prevent accidental commits

## Troubleshooting

### Dashboard won't start

```bash
# Check if port is in use
lsof -i :8765

# Kill existing process
pkill -f "unified_dashboard"

# Check logs
cat /tmp/draper-dashboard.log
```

### Generation fails

```bash
# Check API key
draper config

# Verify required variables are set without printing secret values
python - <<'PY'
import os
from dotenv import load_dotenv

load_dotenv()
for name in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "TYPEFULLY_API_KEY", "LATE_API_KEY"):
    print(f"{name}: {'set' if os.getenv(name) else 'missing'}")
PY
```

### Scheduling fails

```bash
# Check Typefully config without printing the key
python - <<'PY'
import os
from dotenv import load_dotenv

load_dotenv()
print("TYPEFULLY_API_KEY:", "set" if os.getenv("TYPEFULLY_API_KEY") else "missing")
PY

# Check project social sets
draper project config
```

## License

MIT License - see [LICENSE](LICENSE) for details.

---

Built with 🤖 by the Draper project
